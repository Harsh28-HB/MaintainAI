
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
import streamlit as st
from openai import (
    APIError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from streamlit.errors import StreamlitSecretNotFoundError

from src.retrieval import format_evidence

load_dotenv()

logger = logging.getLogger("maintainai.ai")

_OPERATIONAL_SAFETY_CLAIM = re.compile(
    r"\b(?:safe|unsafe)\b[^.!?\n]{0,80}\b"
    r"(?:equipment|machine|pump|motor|compressor|operate|operation|"
    r"operating|run|running)\b"
    r"|\b(?:equipment|machine|pump|motor|compressor|operate|operation|"
    r"operating|run|running)\b[^.!?\n]{0,80}\b(?:safe|unsafe)\b",
    re.IGNORECASE,
)
_OPERATIONAL_CLEARANCE_CLAIM = re.compile(
    r"\b(?:can|may|should|could|will|is able to|are able to)\s+"
    r"(?:safely\s+)?(?:continue|resume|keep)\s+"
    r"(?:normal\s+)?(?:operation|operating|running|to operate|to run)\b"
    r"|\b(?:operation|operation of (?:the )?"
    r"(?:equipment|machine|pump|motor|compressor))\s+"
    r"(?:can|may|should|could|will)\s+continue\b"
    r"|\b(?:can|may|should|could|will)\s+(?:be\s+)?"
    r"(?:operated|run|used)\s+(?:normally|as usual|safely)\b",
    re.IGNORECASE,
)


def _streamlit_secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except (StreamlitSecretNotFoundError, KeyError):
        return None
    return str(value).strip() if value is not None else None


def _config_value(name: str, default: str = "") -> str:
    streamlit_value = _streamlit_secret(name)
    if streamlit_value:
        return streamlit_value

    environment_value = os.getenv(name, "").strip()
    if environment_value:
        return environment_value
    return default


AI_PROVIDER = _config_value("AI_PROVIDER", "ollama").lower()
OLLAMA_URL = _config_value(
    "OLLAMA_URL", "http://localhost:11434"
).rstrip("/")
OLLAMA_MODEL = _config_value("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT_SECONDS = 120
OPENAI_API_KEY = _config_value("OPENAI_API_KEY")
OPENAI_MODEL = _config_value("OPENAI_MODEL")
OPENAI_BASE_URL = _config_value("OPENAI_BASE_URL").rstrip("/")

DEMO_MODE_NOTICE = (
    "Demo Mode: deterministic guidance only. No generative AI is used."
)


class AIServiceError(Exception):
    """Raised when AI analysis cannot safely complete."""


SYSTEM_PROMPT = """
You are MaintainAI, an equipment maintenance support assistant.

Return exactly one JSON object matching the supplied JSON schema.
Observations and possible causes are separate; causes are never confirmed
findings. Follow-up questions require question and reason. Inspection steps
require action, reason, and citations. The draft work order requires summary,
priority, actions, and evidence_citations. Include evidence_limitations as a
list of strings, even when the list is empty.

Use only exact citation strings from retrieved manual evidence. Never invent
citations, thresholds, or findings. If evidence does not support a claim, say
so and use an empty citations list. Recommendations are advisory and
preliminary. Do not claim or imply that equipment or operation is safe or
unsafe; this application has no verified equipment-specific rule for
establishing operational safety. For missing, invalid, or conflicting sensor
readings, identify each affected measurement and recommend obtaining and
verifying it with qualified technician review. Approval of a work order is
not permission to operate equipment. The work order is always a draft and
must never be approved automatically. Return JSON only.
"""

PRIORITIES = {
    "routine", "medium", "high", "urgent", "requires_review"
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "observations",
        "possible_causes",
        "follow_up_questions",
        "inspection_steps",
        "proposed_priority",
        "priority_rationale",
        "draft_work_order",
        "evidence_limitations",
    ],
    "properties": {
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "citations"],
                "properties": {
                    "text": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "possible_causes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "citations"],
                "properties": {
                    "text": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "follow_up_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question", "reason"],
                "properties": {
                    "question": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "inspection_steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "reason", "citations"],
                "properties": {
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "proposed_priority": {
            "type": "string",
            "enum": sorted(PRIORITIES),
        },
        "priority_rationale": {"type": "string"},
        "draft_work_order": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "summary", "priority", "actions", "evidence_citations"
            ],
            "properties": {
                "summary": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": sorted(PRIORITIES),
                },
                "actions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "evidence_citations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "evidence_limitations": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


class _RetryableOutputError(Exception):
    """Raised when a model response can be corrected with one retry."""


def _require_string(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise _RetryableOutputError(f"{field} must be a string.")


def _require_string_list(value: Any, field: str) -> None:
    if not isinstance(value, list):
        raise _RetryableOutputError(f"{field} must be a list.")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise _RetryableOutputError(
                f"{field}[{index}] must be a string."
            )


def _contains_unsupported_operational_safety_claim(value: Any) -> bool:
    if isinstance(value, str):
        return bool(
            _OPERATIONAL_SAFETY_CLAIM.search(value)
            or _OPERATIONAL_CLEARANCE_CLAIM.search(value)
        )
    if isinstance(value, dict):
        return any(
            _contains_unsupported_operational_safety_claim(item)
            for item in value.values()
        )
    if isinstance(value, list):
        return any(
            _contains_unsupported_operational_safety_claim(item)
            for item in value
        )
    return False


def _validate_result(
    result: Any,
    allowed_citations: set[str],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise _RetryableOutputError("The response must be a JSON object.")

    required_keys = set(OUTPUT_SCHEMA["required"])
    missing_keys = required_keys - set(result)
    unexpected_keys = set(result) - required_keys
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise _RetryableOutputError(
            f"Missing required fields: {missing}."
        )
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise _RetryableOutputError(
            f"Unexpected fields: {unexpected}."
        )

    def validate_records(
        records: Any,
        field: str,
        required: tuple[str, ...],
        string_fields: tuple[str, ...],
    ) -> None:
        if not isinstance(records, list):
            raise _RetryableOutputError(f"{field} must be a list.")
        for index, record in enumerate(records):
            record_field = f"{field}[{index}]"
            if not isinstance(record, dict):
                raise _RetryableOutputError(
                    f"{record_field} must be an object."
                )
            missing = set(required) - set(record)
            if missing:
                names = ", ".join(
                    f"{record_field}.{name}" for name in sorted(missing)
                )
                raise _RetryableOutputError(
                    f"Missing required fields: {names}."
                )
            unexpected = set(record) - set(required)
            if unexpected:
                names = ", ".join(
                    f"{record_field}.{name}"
                    for name in sorted(unexpected)
                )
                raise _RetryableOutputError(
                    f"Unexpected fields: {names}."
                )
            for name in string_fields:
                _require_string(record[name], f"{record_field}.{name}")
            if "citations" in required:
                validate_citations(
                    record["citations"],
                    f"{record_field}.citations",
                    allowed_citations,
                )

    def validate_citations(
        value: Any,
        field: str,
        citations: set[str],
    ) -> None:
        if not isinstance(value, list):
            raise _RetryableOutputError(f"{field} must be a list.")
        if any(not isinstance(item, str) for item in value):
            raise _RetryableOutputError(
                f"{field} must contain only strings."
            )
        if any(item not in citations for item in value):
            logger.warning(
                "AI output rejected for unsupported citations in %s",
                field,
            )
            raise AIServiceError(
                f"{field} contains a citation that was not retrieved."
            )

    validate_records(
        result["observations"],
        "observations",
        ("text", "citations"),
        ("text",),
    )
    validate_records(
        result["possible_causes"],
        "possible_causes",
        ("text", "citations"),
        ("text",),
    )
    validate_records(
        result["follow_up_questions"],
        "follow_up_questions",
        ("question", "reason"),
        ("question", "reason"),
    )
    validate_records(
        result["inspection_steps"],
        "inspection_steps",
        ("action", "reason", "citations"),
        ("action", "reason"),
    )

    if result["proposed_priority"] not in PRIORITIES:
        raise _RetryableOutputError(
            "proposed_priority must be one of: "
            + ", ".join(sorted(PRIORITIES))
            + "."
        )
    _require_string(result["priority_rationale"], "priority_rationale")
    _require_string_list(result["evidence_limitations"], "evidence_limitations")

    draft = result["draft_work_order"]
    if not isinstance(draft, dict):
        raise _RetryableOutputError("draft_work_order must be an object.")
    draft_required = {
        "summary", "priority", "actions", "evidence_citations"
    }
    draft_missing = draft_required - set(draft)
    if draft_missing:
        fields = ", ".join(
            f"draft_work_order.{name}" for name in sorted(draft_missing)
        )
        raise _RetryableOutputError(
            f"Missing required fields: {fields}."
        )
    draft_unexpected = set(draft) - draft_required
    if draft_unexpected:
        fields = ", ".join(
            f"draft_work_order.{name}"
            for name in sorted(draft_unexpected)
        )
        raise _RetryableOutputError(
            f"Unexpected fields: {fields}."
        )
    _require_string(draft["summary"], "draft_work_order.summary")
    if draft["priority"] not in PRIORITIES:
        raise _RetryableOutputError(
            "draft_work_order.priority must be one of: "
            + ", ".join(sorted(PRIORITIES))
            + "."
        )
    _require_string_list(draft["actions"], "draft_work_order.actions")
    validate_citations(
        draft["evidence_citations"],
        "draft_work_order.evidence_citations",
        allowed_citations,
    )
    if _contains_unsupported_operational_safety_claim(result):
        logger.warning(
            "AI output rejected for unsupported equipment-operation safety claim"
        )
        raise AIServiceError(
            "AI output made an unsupported equipment-operation safety claim. "
            "The analysis was not accepted."
        )
    return result


def _call_ollama(messages: list[dict[str, str]]) -> str:
    request_body = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "messages": messages,
        "options": {"temperature": 0.1},
    }
    request = Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            api_response = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        logger.error("Ollama returned HTTP status %s", exc.code)
        if exc.code == 404:
            raise AIServiceError(
                f"Ollama could not find model '{OLLAMA_MODEL}'. "
                "Pull the model and verify OLLAMA_MODEL."
            ) from exc
        if exc.code == 400:
            raise AIServiceError(
                "Ollama rejected the chat request (HTTP 400). Verify the "
                "configured model supports the requested JSON schema."
            ) from exc
        if exc.code >= 500:
            raise AIServiceError(
                f"Ollama is unavailable while handling the chat request "
                f"(HTTP {exc.code}). Check the local Ollama service."
            ) from exc
        raise AIServiceError(
            f"Ollama rejected the chat request (HTTP {exc.code})."
        ) from exc
    except (URLError, TimeoutError) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, TimeoutError):
            logger.warning(
                "Ollama request timed out after %s seconds",
                OLLAMA_TIMEOUT_SECONDS,
            )
            raise AIServiceError(
                f"Ollama did not respond within {OLLAMA_TIMEOUT_SECONDS} "
                "seconds. The model may still be loading; check Ollama and "
                "retry the analysis."
            ) from exc
        logger.error("Local AI connection failed: %s", type(exc).__name__)
        raise AIServiceError(
            "Could not connect to local Ollama. Verify OLLAMA_URL and "
            f"confirm model '{OLLAMA_MODEL}' is available."
        ) from exc
    except OSError as exc:
        logger.error("Ollama transport failed: %s", type(exc).__name__)
        raise AIServiceError(
            "The connection to local Ollama was interrupted. Check the "
            "service and retry the analysis."
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error("Ollama returned an invalid JSON response envelope")
        raise AIServiceError(
            "Ollama returned invalid JSON instead of a chat response. "
            "Check the local service and retry."
        ) from exc

    if not isinstance(api_response, dict):
        raise AIServiceError(
            "Ollama /api/chat returned an invalid response envelope. "
            "Check the local service version and retry."
        )
    message = api_response.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        logger.error("Ollama /api/chat response is missing message.content")
        raise AIServiceError(
            "Ollama /api/chat response is missing message.content. "
            "Check the local service version and retry."
        )
    return content


def _call_hosted_llm(messages: list[dict[str, str]], provider: str) -> str:
    if provider not in {"openai", "openai_compatible"}:
        raise AIServiceError(f"Unsupported hosted AI provider '{provider}'.")

    api_key = OPENAI_API_KEY
    if not api_key:
        raise AIServiceError(
            "Hosted AI is configured but OPENAI_API_KEY is missing. "
            "Set the API key in the environment before enabling it."
        )

    model = OPENAI_MODEL
    if not model:
        raise AIServiceError(
            "Hosted AI is configured but OPENAI_MODEL is missing. "
            "Set the model name in the environment before enabling it."
        )

    try:
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": 30.0,
            "max_retries": 1,
        }
        if OPENAI_BASE_URL:
            client_kwargs["base_url"] = OPENAI_BASE_URL
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=messages,
        )
    except APITimeoutError as exc:
        logger.warning("Hosted AI request timed out for provider %s", provider)
        raise AIServiceError(
            "Hosted AI request timed out. Retry the analysis or check provider "
            "availability."
        ) from exc
    except AuthenticationError as exc:
        logger.error("Hosted AI authentication failed for provider %s", provider)
        raise AIServiceError(
            "Hosted AI authentication failed. Verify OPENAI_API_KEY in the "
            "environment or Streamlit secrets."
        ) from exc
    except RateLimitError as exc:
        logger.warning("Hosted AI rate limit reached for provider %s", provider)
        raise AIServiceError(
            "Hosted AI rate limit reached. Retry later or check the provider "
            "quota."
        ) from exc
    except APIConnectionError as exc:
        logger.error("Hosted AI connection failed for provider %s", provider)
        raise AIServiceError(
            "Could not connect to the hosted AI provider. Check network access "
            "and OPENAI_BASE_URL."
        ) from exc
    except APIStatusError as exc:
        logger.error(
            "Hosted AI provider %s returned HTTP status %s",
            provider,
            exc.status_code,
        )
        raise AIServiceError(
            f"Hosted AI provider returned HTTP {exc.status_code}."
        ) from exc
    except APIError as exc:
        logger.error(
            "Hosted AI SDK error for provider %s: %s",
            provider,
            type(exc).__name__,
        )
        raise AIServiceError(
            "Hosted AI request failed. Check provider configuration and retry."
        ) from exc

    choices = getattr(response, "choices", None)
    if not choices:
        raise AIServiceError("Hosted AI returned no completion choices.")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)

    if not isinstance(content, str) or not content.strip():
        raise AIServiceError("Hosted AI returned an empty response.")
    return content


def _build_demo_analysis(
    issue: dict[str, Any],
    sensor_results: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed_evidence = format_evidence(evidence)
    observations = []
    description = str(issue.get("description", "")).strip()
    if description:
        observations.append({
            "text": f"Reported issue: {description}",
            "citations": [],
        })

    for result in sensor_results.get("results", []):
        if result.get("status") in {
            "threshold_exceeded",
            "missing",
            "invalid",
            "conflicting",
            "within_threshold",
        }:
            observations.append({
                "text": (
                    "Deterministic sensor check: "
                    f"{result.get('message', 'The configured threshold was exceeded.')}"
                ),
                "citations": [],
            })

    if allowed_evidence:
        inspection_steps = [{
            "action": (
                "Have a qualified technician review the cited manual "
                "passage before inspection."
            ),
            "reason": (
                "Review the retrieved manual passages listed in the evidence "
                "section before inspection."
            ),
            "citations": [item["citation"] for item in allowed_evidence],
        }]
        actions = [inspection_steps[0]["action"]]
        evidence_limitations = [
            "This deterministic demo does not infer or diagnose equipment failures."
        ]
        cited_evidence = [item["citation"] for item in allowed_evidence]
    else:
        inspection_steps = [{
            "action": (
                "Have a qualified technician assess the reported condition "
                "using approved site procedures."
            ),
            "reason": (
                "No relevant manual evidence was retrieved; do not treat "
                "this demo guidance as a substitute for the approved procedure."
            ),
            "citations": [],
        }]
        actions = [inspection_steps[0]["action"]]
        evidence_limitations = [
            "No relevant manual evidence was retrieved; no manual citations "
            "are available. Guidance is limited to the reported issue and "
            "deterministic sensor checks.",
            "This deterministic demo does not infer or diagnose equipment failures.",
        ]
        cited_evidence = []

    rationale = (
        "Demo mode does not assign operational urgency. A qualified "
        "technician must assess the issue and determine priority."
    )
    return {
        "observations": observations,
        "possible_causes": [],
        "follow_up_questions": [
            {
                "question": "When was the issue first observed, and has it changed?",
                "reason": (
                    "A technician should establish timing and trend from "
                    "verified operating history."
                ),
            },
            {
                "question": (
                    "Have applicable site safety and isolation procedures "
                    "been followed?"
                ),
                "reason": "Inspection must follow approved site procedures.",
            },
        ],
        "inspection_steps": inspection_steps,
        "proposed_priority": "requires_review",
        "priority_rationale": rationale,
        "draft_work_order": {
            "summary": "Technician review of reported equipment issue",
            "priority": "requires_review",
            "actions": actions,
            "evidence_citations": cited_evidence,
        },
        "evidence_limitations": evidence_limitations,
    }


def analyze_issue(
    issue: dict[str, Any],
    sensor_results: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze an equipment issue using the configured AI provider."""
    selected_provider = AI_PROVIDER
    logger.info("AI provider selected: %s", selected_provider)
    if not evidence and selected_provider != "demo":
        raise AIServiceError(
            "No relevant manual evidence was retrieved. "
            "AI analysis was not generated."
        )

    allowed_evidence = format_evidence(evidence)
    allowed_citations = {
        item["citation"] for item in allowed_evidence
    }

    if selected_provider == "demo":
        result = _build_demo_analysis(issue, sensor_results, allowed_evidence)
        validated_result = _validate_result(result, allowed_citations)
        validated_result["review_status"] = "draft"
        validated_result["ai_generated"] = False
        validated_result["ai_provider"] = "demo"
        validated_result["ai_model"] = None
        return validated_result

    payload = {
        "issue": issue,
        "deterministic_sensor_checks": sensor_results,
        "retrieved_manual_evidence": allowed_evidence,
    }

    user_message = json.dumps(
        payload, ensure_ascii=False, allow_nan=False
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    if selected_provider == "ollama":
        call_model = _call_ollama
        provider_name = "ollama"
        provider_model = OLLAMA_MODEL
    elif selected_provider in {"openai", "openai_compatible"}:
        call_model = lambda request_messages: _call_hosted_llm(request_messages, selected_provider)
        provider_name = selected_provider
        provider_model = OPENAI_MODEL
    else:
        raise AIServiceError(
            "Unsupported AI_PROVIDER value. Use 'ollama', 'openai', or "
            "'openai_compatible'."
        )

    for attempt in range(2):
        attempt_messages = list(messages)
        if attempt == 1:
            attempt_messages.append({
                "role": "user",
                "content": (
                    "Your previous response failed validation: "
                    f"{validation_error} Return a complete corrected JSON "
                    "object matching the required schema. Use only the "
                    "retrieved evidence and exact supplied citations."
                ),
            })

        try:
            content = call_model(attempt_messages)
        except AIServiceError:
            raise

        if not content.strip():
            output_error = _RetryableOutputError(
                "AI returned empty message.content."
            )
        else:
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                output_error = _RetryableOutputError(
                    "AI response is not valid JSON."
                )
            else:
                try:
                    validated_result = _validate_result(
                        result, allowed_citations
                    )
                except _RetryableOutputError as exc:
                    output_error = exc
                else:
                    validated_result["review_status"] = "draft"
                    validated_result["ai_generated"] = True
                    validated_result["ai_provider"] = provider_name
                    validated_result["ai_model"] = provider_model
                    logger.info(
                        "AI analysis completed and validated using %s",
                        provider_name,
                    )
                    return validated_result

        logger.warning(
            "AI output validation failed on attempt %s/2: %s",
            attempt + 1,
            output_error,
        )
        if attempt == 1:
            raise AIServiceError(
                "AI returned invalid output after one retry: "
                + str(output_error)
            ) from output_error
        validation_error = str(output_error)

    raise AssertionError("The bounded AI retry loop ended unexpectedly.")
