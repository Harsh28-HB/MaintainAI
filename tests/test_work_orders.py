import importlib

import pytest

from src import ai_service
import src.database as database
from src.rules import evaluate_sensor_readings
from src.work_order_drafts import draft_from_analysis, draft_from_issue


def setup_db(monkeypatch, tmp_path):
    db_path = tmp_path / "maintainai.db"
    monkeypatch.setenv("MAINTAINAI_DB_PATH", str(db_path))
    importlib.reload(database)
    database.init_db()
    return database


def test_equipment_registration_and_issue_creation(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)

    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue(
        "CP-101",
        "Unusual vibration during operation",
        operating_events=["Vibration noticed after startup"],
        sensor_readings={"vibration_mm_s": 5.2},
        observations=[{"text": "Vibration reading reported as 5.2 mm/s", "citations": []}],
    )

    assert issue_id > 0
    history = db.get_issue_history("CP-101")
    assert len(history) == 1
    assert history[0]["description"] == "Unusual vibration during operation"
    assert history[0]["sensor_readings"]["vibration_mm_s"] == 5.2


def test_issue_history_persists(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)

    db.register_equipment("CP-101", "Centrifugal Pump")
    db.create_issue("CP-101", "First issue")
    db.create_issue("CP-101", "Second issue")

    history = db.get_issue_history("CP-101")
    assert [item["description"] for item in history] == ["Second issue", "First issue"]


def test_saved_issue_can_be_loaded_with_sensor_data_and_equipment_type(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue(
        "CP-101",
        "Unusual vibration",
        operating_events=["Observed after startup"],
        sensor_readings={"vibration_mm_s": 5.2},
    )

    issue = db.get_issue(issue_id)

    assert issue is not None
    assert issue["equipment_type"] == "Centrifugal Pump"
    assert issue["description"] == "Unusual vibration"
    assert issue["operating_events"] == ["Observed after startup"]
    assert issue["sensor_readings"] == {"vibration_mm_s": 5.2}


def test_new_work_order_starts_as_draft(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")

    work_order_id = db.create_work_order(
        issue_id,
        {"summary": "Inspect pump", "priority": "requires_review", "actions": ["Check bolts"]},
    )

    orders = db.get_work_orders(issue_id)
    assert len(orders) == 1
    assert orders[0]["work_order_id"] == work_order_id
    assert orders[0]["status"] == "draft"
    assert orders[0]["draft"]["actions"] == ["Check bolts"]


def test_create_work_order_once_is_persistent_idempotent_and_reviewable(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Unusual vibration")
    draft = draft_from_issue(db.get_issue(issue_id))

    work_order_id, created = db.create_work_order_once(issue_id, draft)
    repeated_id, repeated_created = db.create_work_order_once(issue_id, draft)

    assert created is True
    assert repeated_created is False
    assert repeated_id == work_order_id
    assert len(db.get_work_orders(issue_id)) == 1

    reloaded = setup_db(monkeypatch, tmp_path)
    order = reloaded.get_work_orders(issue_id)[0]
    assert order["work_order_id"] == work_order_id
    assert order["issue_id"] == issue_id
    assert order["status"] == "draft"
    assert order["reviewed_by"] is None
    assert order["draft"]["priority"] == "requires_review"

    reloaded.review_work_order(work_order_id, "approved", "Technician A")
    approved_order = reloaded.get_work_orders(issue_id)[0]
    assert approved_order["status"] == "approved"
    assert approved_order["reviewed_by"] == "Technician A"


def test_work_order_read_deduplicates_repeated_but_preserves_distinct_actions(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Unusual vibration")
    work_order_id = db.create_work_order(
        issue_id,
        {
            "summary": "Review issue",
            "priority": "requires_review",
            "actions": [
                "Review the cited manual passage.",
                "Inspect the mounting bolts.",
                "Review the cited manual passage.",
            ],
        },
    )

    order = db.get_work_orders(issue_id)[0]

    assert order["work_order_id"] == work_order_id
    assert order["draft"]["actions"] == [
        "Review the cited manual passage.",
        "Inspect the mounting bolts.",
    ]


def test_technician_can_approve_and_reject_drafts(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")
    work_order_id = db.create_work_order(issue_id, {"summary": "Inspect pump", "priority": "medium", "actions": ["Check alignment"]})

    db.review_work_order(work_order_id, "approved", "Alice", "Looks fine.")
    order = db.get_work_orders(issue_id)[0]
    assert order["status"] == "approved"
    assert order["reviewed_by"] == "Alice"
    assert order["technician_notes"] == "Looks fine."

    with pytest.raises(ValueError, match="Only draft work orders can be reviewed"):
        db.review_work_order(work_order_id, "rejected", "Bob", "Already approved")


def test_missing_technician_and_invalid_decision_are_rejected(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")
    work_order_id = db.create_work_order(issue_id, {"summary": "Inspect pump", "priority": "medium", "actions": ["Check alignment"]})

    with pytest.raises(ValueError, match="Technician name is required"):
        db.review_work_order(work_order_id, "approved", "   ")

    with pytest.raises(ValueError, match="Decision must be approved or rejected"):
        db.review_work_order(work_order_id, "pending", "Alice")


def test_rejecting_a_draft_preserves_status_and_audit(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")
    work_order_id = db.create_work_order(issue_id, {"summary": "Inspect pump", "priority": "medium", "actions": ["Check alignment"]})

    db.review_work_order(work_order_id, "rejected", "Dana", "Not safe for dispatch.")
    order = db.get_work_orders(issue_id)[0]
    assert order["status"] == "rejected"
    assert order["reviewed_by"] == "Dana"

    with pytest.raises(ValueError, match="Only draft work orders can be reviewed"):
        db.review_work_order(work_order_id, "approved", "Chris")

    with db.get_connection() as conn:
        audit_rows = conn.execute(
            "SELECT event_type, details FROM audit_events WHERE work_order_id = ? ORDER BY event_id",
            (work_order_id,),
        ).fetchall()

    assert any(row["event_type"] == "work_order_rejected" for row in audit_rows)
    assert any("Dana" in row["details"] for row in audit_rows)


def test_editing_saved_draft_preserves_status_and_records_event(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")
    work_order_id = db.create_work_order(issue_id, {"summary": "Inspect pump", "priority": "medium", "actions": ["Check alignment"]})

    db.update_work_order_draft(
        work_order_id,
        {"summary": "Inspect pump and bearings", "priority": "high", "actions": ["Check alignment", "Inspect bearings"]},
        "Technician B",
    )

    order = db.get_work_orders(issue_id)[0]
    assert order["status"] == "draft"
    assert order["draft"]["summary"] == "Inspect pump and bearings"
    assert order["draft"]["priority"] == "high"

    with db.get_connection() as conn:
        audit_rows = conn.execute(
            "SELECT event_type, details FROM audit_events WHERE work_order_id = ? ORDER BY event_id",
            (work_order_id,),
        ).fetchall()

    assert any(row["event_type"] == "work_order_edited" for row in audit_rows)
    assert any("Technician B" in row["details"] for row in audit_rows)


def test_approved_or_rejected_orders_cannot_be_edited(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")
    approved_order_id = db.create_work_order(issue_id, {"summary": "Inspect pump", "priority": "medium", "actions": ["Check alignment"]})
    db.review_work_order(approved_order_id, "approved", "Alice", "Looks fine.")

    with pytest.raises(ValueError, match="Only draft work orders can be edited"):
        db.update_work_order_draft(approved_order_id, {"summary": "Changed"}, "Alice")

    rejected_order_id = db.create_work_order(issue_id, {"summary": "Inspect motor", "priority": "medium", "actions": ["Check mounting"]})
    db.review_work_order(rejected_order_id, "rejected", "Bob", "Rejecting for safety.")
    with pytest.raises(ValueError, match="Only draft work orders can be edited"):
        db.update_work_order_draft(rejected_order_id, {"summary": "Changed"}, "Bob")


def test_work_order_actions_and_decisions_persist_across_connections(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Issue")
    work_order_id = db.create_work_order(
        issue_id,
        {"summary": "Inspect pump", "priority": "requires_review", "actions": ["Check bolts", "Inspect alignment"]},
    )

    db.review_work_order(work_order_id, "approved", "Eve", "Approved after review.")

    reloaded = setup_db(monkeypatch, tmp_path)
    orders = reloaded.get_work_orders(issue_id)
    assert orders[0]["status"] == "approved"
    assert orders[0]["draft"]["actions"] == ["Check bolts", "Inspect alignment"]
    assert orders[0]["reviewed_by"] == "Eve"
    assert orders[0]["technician_notes"] == "Approved after review."


def test_invalid_issue_and_work_order_ids_produce_clear_errors(monkeypatch, tmp_path):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")

    with pytest.raises(ValueError, match="Issue not found"):
        db.create_work_order(999, {"summary": "Inspect pump", "priority": "medium", "actions": ["Check alignment"]})

    with pytest.raises(ValueError, match="Work order not found"):
        db.review_work_order(999, "approved", "Alice")

    with pytest.raises(ValueError, match="Work order not found"):
        db.update_work_order_draft(999, {"summary": "Updated"}, "Alice")

    with pytest.raises(ValueError, match="Register the equipment before reporting an issue"):
        db.create_issue("CP-999", "Issue from missing equipment")


def test_analysis_work_order_is_linked_to_issue_and_starts_as_draft(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Unusual vibration")
    analysis = {
        "ai_generated": True,
        "proposed_priority": "high",
        "inspection_steps": [
            {
                "action": "Inspect mounting bolts.",
                "reason": "Manual guidance.",
                "citations": ["pump_manual.md | Section Vibration | lines 1-4"],
            }
        ],
        "draft_work_order": {
            "summary": "Inspect pump vibration.",
            "priority": "high",
            "actions": ["Inspect mounting bolts."],
            "evidence_citations": [
                "pump_manual.md | Section Vibration | lines 1-4"
            ],
        },
    }

    work_order_id, created = db.create_analysis_work_order_once(
        issue_id,
        draft_from_analysis(analysis),
    )

    assert created is True
    order = db.get_work_orders(issue_id)[0]
    assert order["work_order_id"] == work_order_id
    assert order["issue_id"] == issue_id
    assert order["status"] == "draft"
    assert order["draft"] == {
        "summary": "Inspect pump vibration.",
        "priority": "high",
        "actions": ["Inspect mounting bolts."],
        "evidence_citations": [
            "pump_manual.md | Section Vibration | lines 1-4"
        ],
    }


def test_demo_guidance_can_only_create_a_pending_review_work_order(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Unusual vibration")

    analysis = ai_service.analyze_issue(
        {"description": "Unusual vibration"},
        evaluate_sensor_readings({}),
        [],
    )
    assert analysis["ai_provider"] == "demo"
    assert analysis["ai_generated"] is False
    assert analysis["review_status"] == "draft"

    work_order_id, created = db.create_analysis_work_order_once(
        issue_id,
        draft_from_analysis(analysis),
    )

    order = db.get_work_orders(issue_id)[0]
    assert created is True
    assert order["work_order_id"] == work_order_id
    assert order["status"] == "draft"
    assert order["reviewed_by"] is None


def test_repeated_analysis_work_order_creation_does_not_duplicate(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)
    db.register_equipment("CP-101", "Centrifugal Pump")
    issue_id = db.create_issue("CP-101", "Unusual vibration")
    draft = {
        "summary": "Inspect pump vibration.",
        "priority": "requires_review",
        "actions": ["Inspect mounting bolts."],
        "evidence_citations": [],
    }

    first_id, first_created = db.create_analysis_work_order_once(issue_id, draft)
    second_id, second_created = db.create_analysis_work_order_once(issue_id, draft)

    assert first_created is True
    assert second_created is False
    assert second_id == first_id
    assert len(db.get_work_orders(issue_id)) == 1
    with db.get_connection() as conn:
        audit_count = conn.execute(
            """SELECT COUNT(*) FROM audit_events
               WHERE work_order_id = ? AND event_type = 'work_order_drafted'""",
            (first_id,),
        ).fetchone()[0]
    assert audit_count == 1


def test_analysis_work_order_rejects_missing_issue_and_invalid_analysis(
    monkeypatch,
    tmp_path,
):
    db = setup_db(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="Issue not found"):
        db.create_analysis_work_order_once(
            999,
            {
                "summary": "Inspect pump",
                "priority": "medium",
                "actions": ["Inspect"],
                "evidence_citations": [],
            },
        )

    with pytest.raises(ValueError, match="valid AI analysis"):
        draft_from_analysis(None)

    with pytest.raises(ValueError, match="validated AI analysis"):
        draft_from_analysis({
            "draft_work_order": {
                "summary": "Inspect pump",
                "priority": "medium",
                "actions": ["Inspect"],
                "evidence_citations": [],
            }
        })

    with pytest.raises(ValueError, match="priority is invalid"):
        draft_from_analysis({
            "ai_generated": True,
            "draft_work_order": {
                "summary": "Inspect pump",
                "priority": "critical",
                "actions": ["Inspect"],
                "evidence_citations": [],
            }
        })


def test_analysis_draft_uses_inspection_action_and_analysis_priority():
    draft = draft_from_analysis({
        "ai_generated": True,
        "proposed_priority": "medium",
        "inspection_steps": [{"action": "Check alignment."}],
        "draft_work_order": {
            "summary": "Inspect pump.",
            "actions": [],
            "evidence_citations": [],
        },
    })

    assert draft["priority"] == "medium"
    assert draft["actions"] == ["Check alignment."]


def test_deterministic_demo_guidance_can_create_technician_review_draft():
    draft = draft_from_analysis({
        "ai_provider": "demo",
        "ai_generated": False,
        "proposed_priority": "requires_review",
        "draft_work_order": {
            "summary": "Technician review of reported equipment issue",
            "priority": "requires_review",
            "actions": ["Review cited manual passage."],
            "evidence_citations": ["manual.md | Section A | lines 1-2"],
        },
    })

    assert draft["priority"] == "requires_review"
    assert draft["actions"] == ["Review cited manual passage."]
    assert draft["evidence_citations"] == ["manual.md | Section A | lines 1-2"]


def test_unlabelled_non_ai_guidance_cannot_create_work_order_draft():
    with pytest.raises(ValueError, match="validated AI analysis"):
        draft_from_analysis({
            "ai_generated": False,
            "draft_work_order": {
                "summary": "Unverified",
                "priority": "requires_review",
                "actions": ["Inspect."],
                "evidence_citations": [],
            },
        })
