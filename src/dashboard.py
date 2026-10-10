from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any, Mapping

from src import database
from src.rules import evaluate_sensor_readings

logger = logging.getLogger("maintainai.dashboard")


def get_dashboard_summary() -> dict[str, Any]:
    with database.get_connection() as conn:
        equipment_count = conn.execute(
            "SELECT COUNT(*) AS total FROM equipment"
        ).fetchone()[0]
        issue_count = conn.execute(
            "SELECT COUNT(*) AS total FROM issues"
        ).fetchone()[0]
        draft_count = conn.execute(
            "SELECT COUNT(*) AS total FROM work_orders WHERE status = 'draft'"
        ).fetchone()[0]
        approved_count = conn.execute(
            "SELECT COUNT(*) AS total FROM work_orders WHERE status = 'approved'"
        ).fetchone()[0]
        recent = conn.execute(
            """
            SELECT a.event_type, a.created_at, i.description, i.equipment_id,
                   w.status, w.work_order_id
            FROM audit_events a
            LEFT JOIN issues i ON i.issue_id = a.issue_id
            LEFT JOIN work_orders w ON w.work_order_id = a.work_order_id
            ORDER BY a.created_at DESC, a.event_id DESC
            LIMIT 6
            """
        ).fetchall()
        equipment_health = conn.execute(
            """
            SELECT e.equipment_id, e.equipment_type,
                   (SELECT COUNT(*) FROM issues i
                    WHERE i.equipment_id = e.equipment_id) AS issue_count,
                   (SELECT MAX(i.created_at) FROM issues i
                    WHERE i.equipment_id = e.equipment_id) AS latest_issue,
                   (SELECT COUNT(*) FROM work_orders w
                    JOIN issues i ON i.issue_id = w.issue_id
                    WHERE i.equipment_id = e.equipment_id
                      AND w.status = 'draft') AS pending_work_orders,
                   (SELECT COUNT(*) FROM work_orders w
                    JOIN issues i ON i.issue_id = w.issue_id
                    WHERE i.equipment_id = e.equipment_id
                      AND w.status = 'approved') AS approved_work_orders,
                   (SELECT COUNT(*) FROM work_orders w
                    JOIN issues i ON i.issue_id = w.issue_id
                    WHERE i.equipment_id = e.equipment_id
                      AND w.status = 'rejected') AS rejected_work_orders,
                   (SELECT i.sensor_readings FROM issues i
                    WHERE i.equipment_id = e.equipment_id
                    ORDER BY i.created_at DESC, i.issue_id DESC
                    LIMIT 1) AS latest_sensor_readings
            FROM equipment e
            ORDER BY e.equipment_id
            """
        ).fetchall()
        sensor_history = conn.execute(
            """
            SELECT issue_id, equipment_id, created_at, sensor_readings
            FROM issues
            WHERE sensor_readings IS NOT NULL AND sensor_readings != '{}'
            ORDER BY created_at DESC, issue_id DESC
            LIMIT 100
            """
        ).fetchall()
        work_orders = conn.execute(
            """
            SELECT w.work_order_id, w.issue_id, w.status, w.draft_json,
                   w.created_at, w.reviewed_by, i.equipment_id,
                   i.description
            FROM work_orders w
            JOIN issues i ON i.issue_id = w.issue_id
            WHERE w.status = 'draft'
            ORDER BY w.created_at DESC, w.work_order_id DESC
            LIMIT 6
            """
        ).fetchall()

    trend_rows = []
    for row in reversed(sensor_history):
        try:
            readings = json.loads(row["sensor_readings"] or "{}")
        except json.JSONDecodeError:
            logger.warning(
                "Skipping invalid sensor JSON for issue %s",
                row["issue_id"],
            )
            continue
        if not isinstance(readings, dict):
            continue
        point = {"Timestamp": row["created_at"], "Issue": row["issue_id"]}
        for metric in (
            "vibration_mm_s",
            "bearing_temperature_c",
            "discharge_pressure_bar",
        ):
            value = readings.get(metric)
            if isinstance(value, dict):
                value = value.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            try:
                numeric_value = float(value)
            except (OverflowError, ValueError):
                continue
            if math.isfinite(numeric_value):
                point[metric] = numeric_value
        if len(point) > 2:
            trend_rows.append(point)

    return {
        "equipment_count": equipment_count,
        "issue_count": issue_count,
        "draft_count": draft_count,
        "approved_count": approved_count,
        "recent_activity": recent,
        "equipment_health": equipment_health,
        "sensor_report_count": len(sensor_history),
        "sensor_trends": trend_rows,
        "work_orders": work_orders,
        "snapshot_at": datetime.now().strftime("%b %d, %Y · %H:%M"),
    }


def equipment_health_state(item: Mapping[str, Any]) -> tuple[str, str, str]:
    try:
        readings = json.loads(item["latest_sensor_readings"] or "{}")
    except json.JSONDecodeError:
        logger.warning(
            "Invalid latest sensor JSON for equipment %s",
            item["equipment_id"],
        )
        return "Unknown", "status-unknown", "Latest sensor data is invalid"

    if not isinstance(readings, dict):
        return "Unknown", "status-unknown", "Latest sensor data is unavailable"

    sensor_metrics = {
        "vibration_mm_s",
        "bearing_temperature_c",
        "discharge_pressure_bar",
    }
    readings = {
        key: value for key, value in readings.items()
        if key in sensor_metrics
    }
    if not readings:
        return "Unknown", "status-unknown", "No sensor readings on the latest report"

    result = evaluate_sensor_readings(readings)
    if result["has_alerts"]:
        return (
            "Critical",
            "status-critical",
            "At least one reading exceeded an illustrative demo threshold",
        )
    if result["has_warnings"]:
        return (
            "Warning",
            "status-warning",
            "Readings are missing, invalid, conflicting or need verification",
        )
    return (
        "Normal",
        "status-normal",
        "Latest supplied readings are within illustrative demo thresholds",
    )
