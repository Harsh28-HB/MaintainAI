import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from src import ai_service


CITATION = "pump_manual.md | Section M-01: Excessive Vibration | lines 6-12"
EVIDENCE = [{
    "citation": CITATION,
    "content": "Check mounting bolts and inspect alignment.",
}]


def test_config_reads_streamlit_secret_when_environment_is_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(
        ai_service,
        "_streamlit_secret",
        lambda name: "cloud-model" if name == "OPENAI_MODEL" else None,
    )

    assert ai_service._config_value("OPENAI_MODEL") == "cloud-model"


def test_environment_config_takes_precedence_over_streamlit_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    monkeypatch.setattr(
        ai_service,
        "_streamlit_secret",
        lambda name: "cloud-model",
    )

    assert ai_service._config_value("OPENAI_MODEL") == "environment-model"


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


class FakeBytesResponse(FakeResponse):
    def __init__(self, body: bytes) -> None:
        self.body = body


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


@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_analyze_issue_selects_hosted_provider_and_validates_output(
    monkeypatch,
    provider,
):
    monkeypatch.setattr(ai_service, "AI_PROVIDER", provider)
    monkeypatch.setattr(ai_service, "OPENAI_MODEL", "cloud-model")
    monkeypatch.setattr(
        ai_service,
        "_call_hosted_llm",
        lambda messages, selected_provider: json.dumps(valid_result()),
    )

    result = ai_service.analyze_issue({}, {}, EVIDENCE)

    assert result["ai_provider"] == provider
    assert result["ai_model"] == "cloud-model"
    assert result["draft_work_order"]["evidence_citations"] == [CITATION]
    assert result["review_status"] == "draft"


def test_hosted_provider_uses_configured_credentials_model_and_endpoint(
    monkeypatch,
):
    client_config = {}
    request_config = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            client_config.update(kwargs)
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create)
            )

        def create(self, **kwargs):
            request_config.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"result": "ok"}')
                    )
                ]
            )

    monkeypatch.setattr(ai_service, "OPENAI_API_KEY", "test-secret")
    monkeypatch.setattr(ai_service, "OPENAI_MODEL", "cloud-model")
    monkeypatch.setattr(
        ai_service,
        "OPENAI_BASE_URL",
        "https://provider.example/v1",
    )
    monkeypatch.setattr(ai_service, "OpenAI", FakeOpenAI)

    content = ai_service._call_hosted_llm(
        [{"role": "user", "content": "Analyze."}],
        "openai_compatible",
    )

    assert content == '{"result": "ok"}'
    assert client_config == {
        "api_key": "test-secret",
        "timeout": 30.0,
        "max_retries": 1,
        "base_url": "https://provider.example/v1",
    }
    assert request_config["model"] == "cloud-model"
    assert request_config["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("exception_name", "error_type", "expected_message"),
    [
        ("APITimeoutError", "timeout", "request timed out"),
        ("AuthenticationError", "authentication", "authentication failed"),
        ("RateLimitError", "rate_limit", "rate limit reached"),
        ("APIConnectionError", "connection", "Could not connect"),
        ("APIStatusError", "status", "HTTP 503"),
    ],
)
def test_hosted_provider_failures_are_actionable_and_sanitized(
    monkeypatch,
    exception_name,
    error_type,
    expected_message,
):
    if error_type == "status":
        class MockProviderError(Exception):
            status_code = 503
    else:
        class MockProviderError(Exception):
            pass

    class FailedOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create)
            )

        def create(self, **kwargs):
            raise MockProviderError("private-secret-value")

    monkeypatch.setattr(ai_service, "OPENAI_API_KEY", "configured-secret")
    monkeypatch.setattr(ai_service, "OPENAI_MODEL", "cloud-model")
    monkeypatch.setattr(ai_service, "OpenAI", FailedOpenAI)
    monkeypatch.setattr(ai_service, exception_name, MockProviderError)

    with pytest.raises(ai_service.AIServiceError) as error:
        ai_service._call_hosted_llm([], "openai")

    assert expected_message in str(error.value)
    assert "private-secret-value" not in str(error.value)
    assert "configured-secret" not in str(error.value)


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
        match="Could not connect to local Ollama",
    ):
        ai_service.analyze_issue({}, {}, EVIDENCE)


def test_ollama_chat_uses_configured_endpoint_schema_and_timeout(monkeypatch):
    content = json.dumps(valid_result())
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(content)

    monkeypatch.setattr(ai_service, "OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setattr(ai_service, "OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setattr(ai_service, "urlopen", fake_urlopen)

    response = ai_service._call_ollama([
        {"role": "user", "content": "Analyze this issue."}
    ])

    assert response == content
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == "http://localhost:11434/api/chat"
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    payload = json.loads(request.data)
    assert payload["model"] == "qwen2.5:3b"
    assert payload["stream"] is False
    assert payload["format"] == ai_service.OUTPUT_SCHEMA
    assert payload["messages"] == [
        {"role": "user", "content": "Analyze this issue."}
    ]
    assert payload["options"] == {"temperature": 0.1}
    assert timeout == ai_service.OLLAMA_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("request timed out"),
        URLError(TimeoutError("socket timed out")),
    ],
)
def test_ollama_timeout_has_distinct_actionable_error(monkeypatch, failure):
    def timed_out(request, timeout):
        raise failure

    monkeypatch.setattr(ai_service, "urlopen", timed_out)

    with pytest.raises(ai_service.AIServiceError, match="did not respond within"):
        ai_service._call_ollama([])


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "supports the requested JSON schema"),
        (404, "could not find model"),
        (503, "Ollama is unavailable"),
    ],
)
def test_ollama_http_errors_are_classified(monkeypatch, status, message):
    def rejected(request, timeout):
        raise HTTPError(
            request.full_url,
            status,
            "Ollama error response",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(ai_service, "urlopen", rejected)

    with pytest.raises(ai_service.AIServiceError, match=message):
        ai_service._call_ollama([])


def test_ollama_invalid_response_json_has_distinct_error(monkeypatch):
    monkeypatch.setattr(
        ai_service,
        "urlopen",
        lambda request, timeout: FakeBytesResponse(b"{invalid"),
    )

    with pytest.raises(ai_service.AIServiceError, match="returned invalid JSON"):
        ai_service._call_ollama([])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"[]", "invalid response envelope"),
        (b'{"message": {}}', "missing message.content"),
    ],
)
def test_ollama_invalid_response_envelope_is_actionable(
    monkeypatch,
    body,
    message,
):
    monkeypatch.setattr(
        ai_service,
        "urlopen",
        lambda request, timeout: FakeBytesResponse(body),
    )

    with pytest.raises(ai_service.AIServiceError, match=message):
        ai_service._call_ollama([])


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


def test_ollama_connection_error_does_not_echo_endpoint_host(monkeypatch):
    monkeypatch.setattr(ai_service, "OLLAMA_URL", "https://sensitive.invalid")

    def unavailable(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(ai_service, "urlopen", unavailable)

    with pytest.raises(ai_service.AIServiceError) as error:
        ai_service._call_ollama([])

    assert "sensitive.invalid" not in str(error.value)
