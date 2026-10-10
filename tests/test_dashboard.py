import importlib
import json

import pytest

import src.database as database
from src.dashboard import equipment_health_state, get_dashboard_summary


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setenv("MAINTAINAI_DB_PATH", str(tmp_path / "maintainai.db"))
    importlib.reload(database)
    database.init_db()
    return database


def test_dashboard_summary_handles_empty_database(isolated_db):
    summary = get_dashboard_summary()

    assert summary["equipment_count"] == 0
    assert summary["issue_count"] == 0
    assert summary["draft_count"] == 0
    assert summary["approved_count"] == 0
    assert summary["recent_activity"] == []
    assert summary["equipment_health"] == []
    assert summary["sensor_report_count"] == 0
    assert summary["sensor_trends"] == []
    assert summary["work_orders"] == []


def test_dashboard_summary_uses_saved_records_and_sensor_readings(isolated_db):
    isolated_db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = isolated_db.create_issue(
        "CP-101",
        "Unusual vibration during operation",
        sensor_readings={
            "vibration_mm_s": 3.0,
            "bearing_temperature_c": 55.0,
            "discharge_pressure_bar": 3.0,
        },
    )
    work_order_id = isolated_db.create_work_order(
        issue_id,
        {
            "summary": "Inspect the pump",
            "priority": "medium",
            "actions": ["Check alignment"],
        },
    )

    summary = get_dashboard_summary()

    assert summary["equipment_count"] == 1
    assert summary["issue_count"] == 1
    assert summary["draft_count"] == 1
    assert summary["approved_count"] == 0
    assert len(summary["recent_activity"]) == 2
    assert summary["equipment_health"][0]["equipment_id"] == "CP-101"
    assert summary["sensor_report_count"] == 1
    assert len(summary["sensor_trends"]) == 1
    trend = summary["sensor_trends"][0]
    assert trend["Timestamp"]
    assert trend["Issue"] == issue_id
    assert trend["vibration_mm_s"] == 3.0
    assert trend["bearing_temperature_c"] == 55.0
    assert trend["discharge_pressure_bar"] == 3.0
    assert summary["work_orders"][0]["work_order_id"] == work_order_id

    isolated_db.review_work_order(work_order_id, "approved", "Technician")
    approved_summary = get_dashboard_summary()
    assert approved_summary["draft_count"] == 0
    assert approved_summary["approved_count"] == 1
    assert approved_summary["work_orders"] == []


@pytest.mark.parametrize(
    ("readings", "expected_state"),
    [
        (
            {
                "vibration_mm_s": 3.0,
                "bearing_temperature_c": 55.0,
                "discharge_pressure_bar": 3.0,
            },
            "Normal",
        ),
        ({"vibration_mm_s": 5.2}, "Critical"),
        ({"vibration_mm_s": "invalid"}, "Warning"),
        ({}, "Unknown"),
    ],
)
def test_equipment_health_state_uses_sensor_rule_results(
    readings,
    expected_state,
):
    state, _, _ = equipment_health_state(
        {"equipment_id": "CP-101", "latest_sensor_readings": json.dumps(readings)}
    )

    assert state == expected_state


def test_dashboard_handles_malformed_saved_sensor_json(isolated_db, caplog):
    isolated_db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = isolated_db.create_issue("CP-101", "Issue")
    with isolated_db.get_connection() as conn:
        conn.execute(
            "UPDATE issues SET sensor_readings = ? WHERE issue_id = ?",
            ("not-json", issue_id),
        )

    summary = get_dashboard_summary()
    state, _, detail = equipment_health_state(summary["equipment_health"][0])

    assert summary["sensor_report_count"] == 1
    assert summary["sensor_trends"] == []
    assert state == "Unknown"
    assert detail == "Latest sensor data is invalid"
    assert "invalid sensor JSON" in caplog.text
