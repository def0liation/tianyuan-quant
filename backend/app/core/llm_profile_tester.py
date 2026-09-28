from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict
from urllib.error import HTTPError, URLError

from ..models.agent_runtime import LLMConfigTestResult

logger = logging.getLogger(__name__)
from .agent_runtime_store import (
    get_llm_profile,
    record_llm_profile_test_result,
    test_llm_profile,
)
from .llm_egress_policy import LLMEgressBlockedError
from .llm_runner import _call_profile_chat

LIVE_TEST_TIMEOUT_SECONDS = 15
LIVE_TEST_GRACE_SECONDS = 2
LIVE_TEST_MAX_RESPONSE_TOKENS = 16


async def test_llm_profile_connection(
    profile_id: str,
    live_call: bool = False,
    test_prompt: str | None = None,
) -> LLMConfigTestResult:
    field_result = test_llm_profile(profile_id)
    if not live_call or field_result.status != "CONFIGURED":
        record_llm_profile_test_result(profile_id, field_result, live_call=False)
        return field_result

    try:
        profile = get_llm_profile(profile_id)
    except KeyError:
        result = LLMConfigTestResult(
            profile_id=profile_id,
            status="NOT_FOUND",
            message="LLM profile does not exist.",
            details={"live_call": False},
        )
        record_llm_profile_test_result(profile_id, result, live_call=False)
        return result

    prompt = test_prompt or "Reply with exactly: OK"
    started = time.perf_counter()
    test_timeout_seconds = min(profile.timeout_seconds, LIVE_TEST_TIMEOUT_SECONDS)
    test_profile = profile.model_copy(
        update={
            "timeout_seconds": test_timeout_seconds,
            "max_tokens": min(profile.max_tokens, LIVE_TEST_MAX_RESPONSE_TOKENS),
            "live_test_disable_thinking": True,
        }
    )
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _call_profile_chat,
                test_profile,
                [
                    {
                        "role": "system",
                        "content": "You are a connection test endpoint. Keep the response short.",
                    },
                    {"role": "user", "content": prompt},
                ],
            ),
            timeout=test_timeout_seconds + LIVE_TEST_GRACE_SECONDS,
        )
    except LLMEgressBlockedError as exc:
        result = LLMConfigTestResult(
            profile_id=profile_id,
            status="BLOCKED",
            message=exc.decision.message,
            details={
                **exc.decision.to_public_dict(),
                "provider": profile.provider,
                "model": profile.model,
                "base_url": profile.base_url,
                "timeout_seconds": test_timeout_seconds,
                "live_call": False,
            },
        )
        record_llm_profile_test_result(profile_id, result, live_call=False)
        return result
    except TimeoutError:
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = LLMConfigTestResult(
            profile_id=profile_id,
            status="FAILED",
            message=f"Live LLM connection timed out after {test_timeout_seconds} seconds.",
            details={
                "error": "live_call_timeout",
                "provider": profile.provider,
                "model": profile.model,
                "base_url": profile.base_url,
                "latency_ms": latency_ms,
                "timeout_seconds": test_timeout_seconds,
                "live_call": True,
            },
        )
        record_llm_profile_test_result(profile_id, result, live_call=live_call)
        return result
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        logger.exception("Live LLM connection transport test failed for profile %s: %s", profile_id, exc)
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_message = _format_live_test_error(exc)
        result = LLMConfigTestResult(
            profile_id=profile_id,
            status="FAILED",
            message=error_message,
            details={
                "error": error_message,
                "error_type": type(exc).__name__,
                "provider": profile.provider,
                "model": profile.model,
                "base_url": profile.base_url,
                "latency_ms": latency_ms,
                "timeout_seconds": test_timeout_seconds,
                "live_call": True,
            },
        )
        record_llm_profile_test_result(profile_id, result, live_call=live_call)
        return result
    except Exception as exc:
        logger.exception("Live LLM connection test failed for profile %s: %s", profile_id, exc)
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = LLMConfigTestResult(
            profile_id=profile_id,
            status="FAILED",
            message="Live LLM connection failed.",
            details={
                "error": "An unexpected error occurred during the connection test. Please try again later.",
                "provider": profile.provider,
                "model": profile.model,
                "base_url": profile.base_url,
                "latency_ms": latency_ms,
                "timeout_seconds": test_timeout_seconds,
                "live_call": True,
            },
        )
        record_llm_profile_test_result(profile_id, result, live_call=live_call)
        return result

    latency_ms = int((time.perf_counter() - started) * 1000)
    result = LLMConfigTestResult(
        profile_id=profile_id,
        status="READY",
        message="Live LLM connection succeeded.",
        details={
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url,
            "latency_ms": latency_ms,
            "timeout_seconds": test_timeout_seconds,
            "usage": _safe_usage(response),
            "live_call": True,
        },
    )
    record_llm_profile_test_result(profile_id, result, live_call=live_call)
    return result


def _safe_usage(response: Dict[str, Any]) -> Dict[str, Any]:
    usage = response.get("usage")
    return usage if isinstance(usage, dict) else {}


def _format_live_test_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        provider_message = _extract_provider_error_message(exc)
        guidance = _http_status_guidance(exc.code)
        if provider_message:
            return f"LLM service rejected the test request (HTTP {exc.code}): {provider_message} {guidance}".strip()
        return f"LLM service rejected the test request (HTTP {exc.code}). {guidance}".strip()
    if isinstance(exc, json.JSONDecodeError):
        return "LLM service returned a non-JSON response. Check whether the Base URL is OpenAI-compatible."
    if isinstance(exc, URLError):
        reason = _sanitize_error_text(str(getattr(exc, "reason", "") or exc))
        return f"Network error while contacting the LLM service: {reason}"
    return "Network or transport error while contacting the LLM service. Check the Base URL and network access."


def _extract_provider_error_message(exc: HTTPError) -> str:
    try:
        raw_body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    if not raw_body:
        return ""
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return _sanitize_error_text(raw_body)

    for value in _provider_error_candidates(payload):
        if isinstance(value, str) and value.strip():
            return _sanitize_error_text(value)
    return ""


def _provider_error_candidates(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    candidates: list[Any] = []
    if isinstance(error, dict):
        candidates.extend([error.get("message"), error.get("code"), error.get("type")])
    elif isinstance(error, str):
        candidates.append(error)
    candidates.extend([payload.get("message"), payload.get("detail"), payload.get("code")])
    return candidates


def _http_status_guidance(status_code: int) -> str:
    if status_code in {401, 403}:
        return "Check the API Key, account quota, and provider permissions."
    if status_code == 404:
        return "Check the Base URL and model ID."
    if status_code == 429:
        return "The provider is rate limiting this key."
    if 400 <= status_code < 500:
        return "Check the model ID and OpenAI-compatible request format."
    if status_code >= 500:
        return "The provider returned a server error; retry later or switch profiles."
    return ""


def _sanitize_error_text(value: str) -> str:
    collapsed = " ".join(value.split())
    if not collapsed:
        return ""
    redacted = collapsed
    for marker in ("sk-", "Bearer "):
        index = redacted.find(marker)
        if index != -1:
            redacted = redacted[:index] + f"{marker}..."
    return redacted[:240]
