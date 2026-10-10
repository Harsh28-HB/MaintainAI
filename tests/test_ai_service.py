import json
from urllib.error import URLError

import pytest

from src import ai_service


CITATION = "pump_manual.md | Section M-01: Excessive Vibration | lines 6-12"
EVIDENCE = [{
    "citation": CITATION,
    "content": "Check mounting bolts and inspect alignment.",
}]


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.body = json.dumps({
            "model": "qwen2.5:3b",
            "message": {"content": content},
        }).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body


def valid_result() -> dict:
    return {
        "observations": [
            {"text": "Vibration was reported.", "citations": [CITATION]}
        ],
        "possible_causes": [
            {"text": "Misalignment is possible.", "citations": [CITATION]}
        ],
        "follow_up_questions": [
            {"question": "When did it begin?", "reason": "Establish timing."}
        ],
        "inspection_steps": [
            {
                "action": "Check mounting bolts.",
                "reason": "The manual identifies this inspection.",
                "citations": [CITATION],
            }
        ],
        "proposed_priority": "requires_review",
        "priority_rationale": "The evidence is insufficient to set urgency.",
        "draft_work_order": {
            "summary": "Inspect reported pump vibration.",
            "priority": "requires_review",
            "actions": ["Check mounting bolts."],
            "evidence_citations": [CITATION],
        },
        "evidence_limitations": ["No equipment-specific limit was supplied."],
    }


def run_with_responses(monkeypatch, responses: list[str]):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(ai_service, "urlopen", fake_urlopen)
    result = ai_service.analyze_issue(
        {"description": "Unusual vibration"},
        {"has_alerts": True},
        EVIDENCE,
    )
    return result, calls


def test_missing_required_field_is_reported_after_one_retry(monkeypatch):
    missing_field_result = valid_result()
    del missing_field_result["evidence_limitations"]
    content = json.dumps(missing_field_result)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(content)

    monkeypatch.setattr(ai_service, "urlopen", fake_urlopen)

    with pytest.raises(ai_service.AIServiceError) as error:
        ai_service.analyze_issue({}, {}, EVIDENCE)

    assert "evidence_limitations" in str(error.value)
    assert len(calls) == 2
    retry_messages = json.loads(calls[1].data)["messages"]
    assert "Missing required fields: evidence_limitations" in (
        retry_messages[-1]["content"]
    )


def test_malformed_json_gets_one_retry_using_json_schema(monkeypatch):
    result, calls = run_with_responses(
        monkeypatch,
        ["not-json", json.dumps(valid_result())],
    )

    assert result["ai_provider"] == "ollama"
    assert result["review_status"] == "draft"
    assert len(calls) == 2
    for request in calls:
        assert json.loads(request.data)["format"] == ai_service.OUTPUT_SCHEMA


@pytest.mark.parametrize(
    "field_path",
    ["proposed_priority", "draft_work_order.priority"],
)
def test_invalid_priority_is_rejected_with_field_name(
    monkeypatch,
    field_path,
):
    invalid_result = valid_result()
    if field_path == "proposed_priority":
        invalid_result["proposed_priority"] = "critical"
    else:
        invalid_result["draft_work_order"]["priority"] = "critical"
    content = json.dumps(invalid_result)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(content)

    monkeypatch.setattr(ai_service, "urlopen", fake_urlopen)

    with pytest.raises(ai_service.AIServiceError) as error:
        ai_service.analyze_issue({}, {}, EVIDENCE)

    assert field_path in str(error.value)
    assert len(calls) == 2


def test_unsupported_citation_is_rejected_without_retry(monkeypatch):
    invalid_result = valid_result()
    invalid_result["possible_causes"][0]["citations"] = [
        "invented manual citation"
    ]
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(json.dumps(invalid_result))

    monkeypatch.setattr(ai_service, "urlopen", fake_urlopen)

    with pytest.raises(ai_service.AIServiceError, match="not retrieved"):
        ai_service.analyze_issue({}, {}, EVIDENCE)

    assert len(calls) == 1


def test_invalid_field_type_is_reported_after_one_retry(monkeypatch):
    invalid_result = valid_result()
    invalid_result["observations"] = "not-a-list"
    content = json.dumps(invalid_result)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse(content)

    monkeypatch.setattr(ai_service, "urlopen", fake_urlopen)

    with pytest.raises(ai_service.AIServiceError) as error:
        ai_service.analyze_issue({}, {}, EVIDENCE)

    assert "observations must be a list" in str(error.value)
    assert len(calls) == 2


def test_ollama_connection_failure_is_actionable(monkeypatch):
    def unavailable(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(ai_service, "urlopen", unavailable)

    with pytest.raises(
        ai_service.AIServiceError,
        match="Cannot connect to local Ollama",
    ):
        ai_service.analyze_issue({}, {}, EVIDENCE)


def test_ollama_connection_error_does_not_disclose_endpoint_credentials(
    monkeypatch,
):
    monkeypatch.setattr(
        ai_service,
        "OLLAMA_URL",
        "https://private-user:private-password@example.test",
    )

    def unavailable(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(ai_service, "urlopen", unavailable)

    with pytest.raises(ai_service.AIServiceError) as error:
        ai_service._call_ollama([])

    assert "private-user" not in str(error.value)
    assert "private-password" not in str(error.value)
    assert "example.test" not in str(error.value)
