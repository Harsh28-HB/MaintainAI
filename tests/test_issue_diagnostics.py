import logging
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import ai_service, database
from src.issue_diagnostics import report_issue_workflow_error
from src.rules import evaluate_sensor_readings


def test_submission_error_handler_logs_safe_diagnostics_and_displays_error(
    caplog,
):
    displayed = []
    caplog.set_level(logging.WARNING, logger="maintainai.app")
    issue_description = "Confidential bearing vibration details"
    api_key = "private-provider-key"
    error = RuntimeError(
        "Could not connect to local Ollama; "
        f"issue={issue_description}; credential={api_key}"
    )

    report_issue_workflow_error(
        error,
        "ollama",
        (issue_description, api_key),
        displayed.append,
    )

    assert displayed == [
        "Could not connect to local Ollama; issue=[redacted]; "
        "credential=[redacted]"
    ]
    assert "provider=ollama" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "Could not connect to local Ollama" in caplog.text
    assert issue_description not in caplog.text
    assert api_key not in caplog.text


def test_submission_error_handler_keeps_user_message_when_no_secrets_present():
    displayed = []

    report_issue_workflow_error(
        RuntimeError("Model qwen2.5:3b is unavailable"),
        "ollama",
        (),
        displayed.append,
    )

    assert displayed == ["Model qwen2.5:3b is unavailable"]


def test_streamlit_issue_submission_displays_sanitized_ai_failure(
    monkeypatch,
    tmp_path,
):
    issue_description = "Private report text for diagnostic redaction"
    api_key = "private-test-key"
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "issue-submission.db")
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(ai_service, "OPENAI_API_KEY", api_key)

    def fail_ollama(_messages):
        raise ai_service.AIServiceError(
            f"Could not connect to local Ollama: {issue_description}; {api_key}"
        )

    monkeypatch.setattr(ai_service, "_call_ollama", fail_ollama)

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.radio[0].set_value("🛠️ Report an Issue").run()
    app.text_input[0].set_value("TEST-101")
    app.text_area[0].set_value(issue_description)
    app.button[0].click().run()

    displayed_errors = [element.value for element in app.error]
    assert any(
        "Could not connect to local Ollama" in message
        and "[redacted]" in message
        for message in displayed_errors
    )
    assert not app.exception
    assert issue_description not in " ".join(displayed_errors)
    assert api_key not in " ".join(displayed_errors)


def test_streamlit_demo_submission_discloses_mode_and_saves_guidance(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "demo-submission.db")
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.radio[0].set_value("🛠️ Report an Issue").run()
    app.text_input[0].set_value("DEMO-101")
    app.text_area[0].set_value(
        "Centrifugal pump unusual vibration during operation"
    )
    app.button[0].click().run()

    notice = "Demo Mode: deterministic guidance only. No generative AI is used."
    assert any(notice in element.value for element in app.info)
    assert any("demo guidance prepared" in element.value for element in app.success)
    assert app.session_state["last_analysis"]["ai_provider"] == "demo"
    assert app.session_state["last_analysis"]["ai_generated"] is False
    assert database.get_work_orders(app.session_state["last_issue_id"]) == []
    assert not app.exception


def test_analysis_results_lists_sensor_gaps_work_order_status_and_safety_limit(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "analysis-results.db")
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")
    database.init_db()
    database.register_equipment("DEMO-102", "Centrifugal Pump")

    readings = {"vibration_mm_s": "invalid"}
    sensor_results = evaluate_sensor_readings(readings)
    issue = {
        "equipment_id": "DEMO-102",
        "equipment_type": "Centrifugal Pump",
        "description": "Unusual vibration",
        "sensor_readings": readings,
    }
    issue_id = database.create_issue(
        "DEMO-102",
        issue["description"],
        sensor_readings=readings,
    )
    analysis = ai_service.analyze_issue(issue, sensor_results, [])
    database.create_work_order(
        issue_id,
        {
            "summary": "Technician review of reported equipment issue",
            "priority": "requires_review",
            "actions": ["Have a qualified technician review the issue."],
            "evidence_citations": [],
        },
    )

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["current_page"] = "Analysis Results"
    app.session_state["last_issue_id"] = issue_id
    app.session_state["last_issue"] = issue
    app.session_state["last_analysis"] = analysis
    app.session_state["last_analysis_issue_id"] = issue_id
    app.session_state["last_sensor_results"] = sensor_results
    app.session_state["last_evidence"] = []
    app.run()

    assert not app.exception
    headings = [item.value for item in app.subheader]
    assert "Issue analysis and available evidence" in headings
    assert "Sensor validation and missing readings" in headings
    assert "Recommended next action" in headings
    assert "Work-order status and required human review" in headings
    assert "Safety limitation" in headings

    warnings = " ".join(item.value for item in app.warning)
    assert "vibration_mm_s" in warnings
    assert "Invalid measurement" in warnings
    assert "bearing_temperature_c" in warnings
    assert "discharge_pressure_bar" in warnings
    assert "Operational safety not established" in warnings
    markdown = " ".join(item.value for item in app.markdown)
    assert "Pending Review" in markdown
    assert "No generative AI is used." in " ".join(
        item.value for item in app.info
    )


@pytest.mark.parametrize("has_saved_analysis", [True, False])
def test_work_orders_page_creates_and_displays_draft_for_saved_issue(
    monkeypatch,
    tmp_path,
    has_saved_analysis,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "work-orders-page.db")
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")
    database.init_db()
    database.register_equipment("DEMO-103", "Centrifugal Pump")
    issue_id = database.create_issue(
        "DEMO-103",
        "Unusual vibration after startup",
        sensor_readings={"vibration_mm_s": "invalid"},
    )
    issue = database.get_issue(issue_id)
    sensor_results = evaluate_sensor_readings(issue["sensor_readings"])
    analysis = ai_service.analyze_issue(issue, sensor_results, [])

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["current_page"] = "Work Orders"
    app.session_state["last_issue_id"] = issue_id
    if has_saved_analysis:
        app.session_state["last_analysis"] = analysis
        app.session_state["last_analysis_issue_id"] = issue_id
    app.run()

    assert not app.exception
    assert app.selectbox[0].value == issue_id
    assert any(
        "No work order exists for this saved issue yet." in item.value
        for item in app.info
    )
    assert any(
        button.label == "Create Work Order Draft"
        for button in app.button
    )
    next(button for button in app.button if button.label == "Create Work Order Draft").click().run()

    orders = database.get_work_orders(issue_id)
    assert len(orders) == 1
    assert orders[0]["issue_id"] == issue_id
    assert orders[0]["status"] == "draft"
    assert orders[0]["reviewed_by"] is None
    if has_saved_analysis:
        assert orders[0]["draft"] == {
            "summary": analysis["draft_work_order"]["summary"],
            "priority": analysis["draft_work_order"]["priority"],
            "actions": analysis["draft_work_order"]["actions"],
            "evidence_citations": analysis["draft_work_order"]["evidence_citations"],
        }
    else:
        assert orders[0]["draft"]["priority"] == "requires_review"
        assert orders[0]["draft"]["evidence_citations"] == []
        assert "review" in orders[0]["draft"]["actions"][0].lower()
    assert any(
        f"Work order #{orders[0]['work_order_id']} was saved" in item.value
        for item in app.success
    )
    assert not any(
        "No work order exists for this saved issue yet." in item.value
        for item in app.info
    )
    assert any(
        f"Work order #{orders[0]['work_order_id']}"
        == expander.label
        for expander in app.expander
    )
    assert not app.exception

    refreshed_app = AppTest.from_file(str(app_path), default_timeout=30)
    refreshed_app.session_state["current_page"] = "Work Orders"
    refreshed_app.session_state["work_orders_issue_id"] = issue_id
    refreshed_app.run()
    assert not refreshed_app.exception
    assert refreshed_app.selectbox[0].value == issue_id
    assert not any(
        "No work order exists for this saved issue yet." in item.value
        for item in refreshed_app.info
    )
    assert any(
        expander.label == f"Work order #{orders[0]['work_order_id']}"
        for expander in refreshed_app.expander
    )
    persisted_orders = database.get_work_orders(issue_id)
    assert len(persisted_orders) == 1
    assert persisted_orders[0]["issue_id"] == issue_id
    assert persisted_orders[0]["work_order_id"] == orders[0]["work_order_id"]


def test_work_orders_selector_filters_issue_and_creates_for_selected_issue(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "issue-filter.db")
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")
    database.init_db()
    database.register_equipment("DEMO-104", "Centrifugal Pump")
    created_issues = [
        database.create_issue("DEMO-104", f"Issue {index}")
        for index in range(1, 14)
    ]
    issue_11 = created_issues[10]
    issue_13 = created_issues[12]
    issue_13_order_id = database.create_work_order(
        issue_13,
        {
            "summary": "Work for issue 13",
            "priority": "requires_review",
            "actions": ["Review issue 13."],
        },
    )

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["current_page"] = "Work Orders"
    app.session_state["last_issue_id"] = issue_13
    app.session_state["work_orders_issue_id"] = issue_13
    app.run()

    assert [expander.label for expander in app.expander] == [
        f"Work order #{issue_13_order_id}"
    ]
    app.selectbox[0].set_value(issue_11).run()

    assert app.selectbox[0].value == issue_11
    assert not app.expander
    assert any(
        button.label == "Create Work Order Draft"
        for button in app.button
    )

    next(
        button
        for button in app.button
        if button.label == "Create Work Order Draft"
    ).click().run()

    issue_11_orders = database.get_work_orders(issue_11)
    issue_13_orders = database.get_work_orders(issue_13)
    assert len(issue_11_orders) == 1
    assert issue_11_orders[0]["issue_id"] == issue_11
    assert issue_11_orders[0]["status"] == "draft"
    assert len(issue_13_orders) == 1
    assert issue_13_orders[0]["work_order_id"] == issue_13_order_id
    assert [expander.label for expander in app.expander] == [
        f"Work order #{issue_11_orders[0]['work_order_id']}"
    ]
    assert not app.exception


def test_work_orders_do_not_use_analysis_from_a_different_issue(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "stale-analysis.db")
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")
    database.init_db()
    database.register_equipment("DEMO-106", "Centrifugal Pump")
    source_issue_id = database.create_issue("DEMO-106", "Source issue")
    selected_issue_id = database.create_issue("DEMO-106", "Selected issue")
    stale_analysis = {
        "ai_provider": "demo",
        "ai_generated": False,
        "draft_work_order": {
            "summary": "Guidance from another issue",
            "priority": "requires_review",
            "actions": ["Source-issue-only action"],
            "evidence_citations": [],
        },
    }

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["current_page"] = "Work Orders"
    app.session_state["last_issue_id"] = source_issue_id
    app.session_state["last_analysis_issue_id"] = source_issue_id
    app.session_state["last_analysis"] = stale_analysis
    app.session_state["work_orders_issue_id"] = selected_issue_id
    app.run()

    assert app.selectbox[0].value == selected_issue_id
    next(
        button for button in app.button
        if button.label == "Create Work Order Draft"
    ).click().run()

    order = database.get_work_orders(selected_issue_id)[0]
    assert order["issue_id"] == selected_issue_id
    assert order["status"] == "draft"
    assert order["draft"]["summary"] == (
        "Technician review of reported issue"
    )
    assert "Source-issue-only action" not in order["draft"]["actions"]
    assert not app.exception


@pytest.mark.parametrize("reading", ["nan", "inf", "-inf", "1e999"])
def test_non_finite_sensor_input_is_saved_and_flagged_invalid(
    monkeypatch,
    tmp_path,
    reading,
):
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / f"non-finite-{reading.replace('-', 'negative-')}.db",
    )
    monkeypatch.setattr(ai_service, "AI_PROVIDER", "demo")

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    app.radio[0].set_value("🛠️ Report an Issue").run()
    app.text_input[0].set_value("DEMO-NONFINITE")
    app.text_area[0].set_value("Unusual vibration")
    app.text_input[1].set_value(reading)
    app.button[0].click().run()

    issue_id = app.session_state["last_issue_id"]
    saved_issue = database.get_issue(issue_id)
    assert saved_issue["sensor_readings"]["vibration_mm_s"] == reading
    result = evaluate_sensor_readings(saved_issue["sensor_readings"])
    assert result["results"][0]["status"] == "invalid"
    assert app.session_state["last_analysis_issue_id"] == issue_id
    assert not app.exception


def test_approved_status_is_distinct_from_priority_and_actions_are_unique(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "status-rendering.db")
    database.init_db()
    database.register_equipment("DEMO-105", "Centrifugal Pump")
    issue_id = database.create_issue("DEMO-105", "Reported vibration")
    instruction = (
        "Have a qualified technician review the cited manual passage "
        "before inspection."
    )
    work_order_id = database.create_work_order(
        issue_id,
        {
            "summary": "Technician review",
            "priority": "requires_review",
            "actions": [instruction, instruction, instruction],
        },
    )
    database.review_work_order(work_order_id, "approved", "Technician A")

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["current_page"] = "Work Orders"
    app.session_state["last_issue_id"] = issue_id
    app.session_state["work_orders_issue_id"] = issue_id
    app.run()

    assert not app.exception
    assert [expander.label for expander in app.expander] == [
        f"Work order #{work_order_id}"
    ]
    rendered = "\n".join(item.value for item in app.markdown)
    assert rendered.count("Approved for maintenance work") == 1
    assert "Priority: Requires Review" in rendered
    assert "Pending Review" not in rendered
    assert rendered.count(instruction) == 1
    assert any(
        "does not authorize equipment operation" in item.value
        for item in app.markdown
    )
