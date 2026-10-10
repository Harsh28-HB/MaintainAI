
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(
    os.getenv("MAINTAINAI_DB_PATH", str(PROJECT_ROOT / "data" / "maintainai.db"))
)


@contextmanager
def get_connection():
    """Open a database connection and always close it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    """Create the tables required for issue and work-order history."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS equipment (
                equipment_id TEXT PRIMARY KEY,
                equipment_type TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS issues (
                issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id TEXT NOT NULL,
                description TEXT NOT NULL,
                operating_events TEXT NOT NULL DEFAULT '[]',
                sensor_readings TEXT NOT NULL DEFAULT '{}',
                observations TEXT NOT NULL DEFAULT '[]',
                possible_causes TEXT NOT NULL DEFAULT '[]',
                confirmed_findings TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (equipment_id)
                    REFERENCES equipment(equipment_id)
            );

            CREATE TABLE IF NOT EXISTS work_orders (
                work_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER NOT NULL,
                draft_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN (
                        'draft', 'approved', 'rejected', 'completed'
                    )),
                technician_notes TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (issue_id) REFERENCES issues(issue_id)
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id INTEGER,
                work_order_id INTEGER,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (issue_id) REFERENCES issues(issue_id),
                FOREIGN KEY (work_order_id)
                    REFERENCES work_orders(work_order_id)
            );
        """)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def register_equipment(equipment_id: str, equipment_type: str) -> None:
    """Register equipment, rejecting conflicting type changes."""
    equipment_id = equipment_id.strip()
    equipment_type = equipment_type.strip()

    if not equipment_id or not equipment_type:
        raise ValueError("Equipment ID and type are required.")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT equipment_type FROM equipment WHERE equipment_id = ?",
            (equipment_id,),
        ).fetchone()

        if existing and existing["equipment_type"] != equipment_type:
            raise ValueError(
                "This equipment ID is already registered with another type."
            )

        conn.execute(
            """INSERT OR IGNORE INTO equipment
               (equipment_id, equipment_type) VALUES (?, ?)""",
            (equipment_id, equipment_type),
        )


def create_issue(
    equipment_id: str,
    description: str,
    operating_events: list[str] | None = None,
    sensor_readings: dict[str, Any] | None = None,
    observations: list[dict[str, Any]] | None = None,
    possible_causes: list[dict[str, Any]] | None = None,
    confirmed_findings: list[dict[str, Any]] | None = None,
) -> int:
    """Persist an issue and return its ID."""
    if not equipment_id.strip() or not description.strip():
        raise ValueError("Equipment ID and issue description are required.")

    with get_connection() as conn:
        equipment = conn.execute(
            "SELECT equipment_id FROM equipment WHERE equipment_id = ?",
            (equipment_id.strip(),),
        ).fetchone()

        if not equipment:
            raise ValueError("Register the equipment before reporting an issue.")

        cursor = conn.execute(
            """INSERT INTO issues (
                equipment_id, description, operating_events,
                sensor_readings, observations, possible_causes,
                confirmed_findings
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                equipment_id.strip(),
                description.strip(),
                _json_dump(operating_events or []),
                _json_dump(sensor_readings or {}),
                _json_dump(observations or []),
                _json_dump(possible_causes or []),
                _json_dump(confirmed_findings or []),
            ),
        )

        issue_id = cursor.lastrowid
        conn.execute(
            """INSERT INTO audit_events (issue_id, event_type, details)
               VALUES (?, 'issue_created', ?)""",
            (issue_id, _json_dump({"equipment_id": equipment_id.strip()})),
        )

        return int(issue_id)


def get_issue_history(equipment_id: str) -> list[dict[str, Any]]:
    """Return an equipment's reports, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM issues
               WHERE equipment_id = ?
               ORDER BY created_at DESC, issue_id DESC""",
            (equipment_id.strip(),),
        ).fetchall()

    results = []
    json_fields = (
        "operating_events", "sensor_readings", "observations",
        "possible_causes", "confirmed_findings",
    )

    for row in rows:
        item = dict(row)
        for field in json_fields:
            item[field] = json.loads(item[field])
        results.append(item)

    return results


def _insert_work_order(
    conn: sqlite3.Connection,
    issue_id: int,
    draft: dict[str, Any],
) -> int:
    issue = conn.execute(
        "SELECT issue_id FROM issues WHERE issue_id = ?",
        (issue_id,),
    ).fetchone()
    if not issue:
        raise ValueError("Issue not found.")

    cursor = conn.execute(
        """INSERT INTO work_orders (issue_id, draft_json)
           VALUES (?, ?)""",
        (issue_id, _json_dump(draft)),
    )
    work_order_id = int(cursor.lastrowid)
    conn.execute(
        """INSERT INTO audit_events
           (issue_id, work_order_id, event_type, details)
           VALUES (?, ?, 'work_order_drafted', ?)""",
        (issue_id, work_order_id, _json_dump({"status": "draft"})),
    )
    return work_order_id


def create_work_order(issue_id: int, draft: dict[str, Any]) -> int:
    """Save a proposed work order. It is never approved automatically."""
    with get_connection() as conn:
        return _insert_work_order(conn, issue_id, draft)


def create_analysis_work_order_once(
    issue_id: int,
    draft: dict[str, Any],
) -> tuple[int, bool]:
    """Create one analysis-generated work order per issue, idempotently."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """SELECT work_order_id FROM work_orders
               WHERE issue_id = ?
               ORDER BY CASE WHEN status = 'draft' THEN 0 ELSE 1 END,
                        work_order_id DESC
               LIMIT 1""",
            (issue_id,),
        ).fetchone()
        if existing:
            return int(existing["work_order_id"]), False

        work_order_id = _insert_work_order(conn, issue_id, draft)
        return work_order_id, True


def review_work_order(
    work_order_id: int,
    decision: str,
    technician: str,
    notes: str = "",
) -> None:
    """Record an explicit technician approval or rejection."""
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected.")

    if not technician.strip():
        raise ValueError("Technician name is required.")

    with get_connection() as conn:
        order = conn.execute(
            "SELECT issue_id, status FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()

        if not order:
            raise ValueError("Work order not found.")

        if order["status"] != "draft":
            raise ValueError("Only draft work orders can be reviewed.")

        conn.execute(
            """UPDATE work_orders
               SET status = ?, technician_notes = ?, reviewed_by = ?,
                   reviewed_at = CURRENT_TIMESTAMP
               WHERE work_order_id = ? AND status = 'draft'""",
            (
                decision,
                notes.strip(),
                technician.strip(),
                work_order_id,
            ),
        )

        conn.execute(
            """INSERT INTO audit_events
               (issue_id, work_order_id, event_type, details)
               VALUES (?, ?, ?, ?)""",
            (
                order["issue_id"],
                work_order_id,
                f"work_order_{decision}",
                _json_dump({
                    "technician": technician.strip(),
                    "notes": notes.strip(),
                }),
            ),
        )


def get_work_orders(issue_id: int) -> list[dict[str, Any]]:
    """List work orders associated with an issue."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM work_orders
               WHERE issue_id = ?
               ORDER BY work_order_id DESC""",
            (issue_id,),
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["draft"] = json.loads(item.pop("draft_json"))
        results.append(item)

    return results

def update_work_order_draft(
    work_order_id: int,
    draft: dict[str, Any],
    technician: str,
) -> None:
    """Update a draft work order and record the edit."""
    if not technician.strip():
        raise ValueError("Technician name is required.")

    with get_connection() as conn:
        order = conn.execute(
            "SELECT issue_id, status FROM work_orders WHERE work_order_id = ?",
            (work_order_id,),
        ).fetchone()

        if not order:
            raise ValueError("Work order not found.")

        if order["status"] != "draft":
            raise ValueError("Only draft work orders can be edited.")

        conn.execute(
            """UPDATE work_orders
               SET draft_json = ?
               WHERE work_order_id = ? AND status = 'draft'""",
            (_json_dump(draft), work_order_id),
        )

        conn.execute(
            """INSERT INTO audit_events
               (issue_id, work_order_id, event_type, details)
               VALUES (?, ?, 'work_order_edited', ?)""",
            (
                order["issue_id"],
                work_order_id,
                _json_dump({"technician": technician.strip()}),
            ),
        )
