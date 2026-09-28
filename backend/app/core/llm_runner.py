from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models.agent_runtime import AgentDeployment, AgentLLMProfile, LLMConfigTestResult

logger = logging.getLogger(__name__)
from .agent_framework import load_agent_prompt
from .agent_runtime_store import get_agent_execution_config, record_llm_profile_test_result
from .llm_egress_policy import (
    LLMEgressBlockedError,
    assert_llm_egress_allowed,
    validate_llm_egress,
)


@dataclass
class LLMRunResult:
    status: str
    provider: str
    model: str
    profile_id: str
    content: str = ""
    parsed_json: Optional[Any] = None
    error: str = ""
    latency_ms: int = 0
    usage: Optional[Dict[str, Any]] = None
    finish_reason: str = ""

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "profileId": self.profile_id,
            "content": self.content,
            "parsedJson": self.parsed_json,
            "error": self.error,
            "latencyMs": self.latency_ms,
            "usage": self.usage or {},
            "finishReason": self.finish_reason,
        }


async def run_agent_llm(
    agent_id: str,
    run_data: Dict[str, Any],
    prior_outputs: Dict[str, Any],
) -> LLMRunResult:
    agent, profile = get_agent_execution_config(agent_id)
    validation_error = _validate_profile(profile)
    if validation_error:
        result = LLMRunResult(
            status="SKIPPED",
            provider=profile.provider,
            model=profile.model,
            profile_id=profile.id,
            error=validation_error,
        )
        _record_llm_run_health(agent_id, run_data, result, live_call=False)
        return result

    messages = _build_messages(agent, run_data, prior_outputs)
    started = time.perf_counter()
    try:
        response = await asyncio.to_thread(_call_profile_chat, profile, messages)
    except LLMEgressBlockedError as exc:
        result = LLMRunResult(
            status="SKIPPED",
            provider=profile.provider,
            model=profile.model,
            profile_id=profile.id,
            error=exc.decision.message,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        _record_llm_run_health(agent_id, run_data, result, live_call=False)
        return result
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        result = LLMRunResult(
            status="FAILED",
            provider=profile.provider,
            model=profile.model,
            profile_id=profile.id,
            error=_format_transport_error(exc),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        _record_llm_run_health(agent_id, run_data, result)
        return result
    except Exception as exc:  # Defensive: providers can fail with non-standard exceptions.
        logger.exception("LLM call failed for profile %s: %s", profile.id, exc)
        result = LLMRunResult(
            status="FAILED",
            provider=profile.provider,
            model=profile.model,
            profile_id=profile.id,
            error="An unexpected error occurred while calling the LLM. Please try again later.",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        _record_llm_run_health(agent_id, run_data, result)
        return result

    content = _extract_content(response)
    result = LLMRunResult(
        status="COMPLETED",
        provider=profile.provider,
        model=profile.model,
        profile_id=profile.id,
        content=content,
        parsed_json=_extract_json(content),
        latency_ms=int((time.perf_counter() - started) * 1000),
        usage=response.get("usage", {}),
        finish_reason=_extract_finish_reason(response),
    )
    _record_llm_run_health(agent_id, run_data, result)
    return result


def _record_llm_run_health(
    agent_id: str,
    run_data: Dict[str, Any],
    result: LLMRunResult,
    *,
    live_call: bool = True,
) -> None:
    if not result.profile_id:
        return

    health_status = "READY" if result.status == "COMPLETED" else result.status
    message = _llm_run_health_message(agent_id, result)
    details: Dict[str, Any] = {
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "usage": result.usage or {},
        "finish_reason": result.finish_reason,
        "agent_id": agent_id,
        "run_id": run_data.get("runId") or run_data.get("run_id") or "",
        "llm_run_status": result.status,
        "live_call": live_call,
    }
    if result.error:
        details["error"] = result.error

    try:
        record_llm_profile_test_result(
            result.profile_id,
            LLMConfigTestResult(
                profile_id=result.profile_id,
                status=health_status,
                message=message,
                details=details,
            ),
            live_call=live_call,
        )
    except Exception:
        logger.exception("Failed to record LLM profile health for %s", result.profile_id)


def _llm_run_health_message(agent_id: str, result: LLMRunResult) -> str:
    if result.status == "COMPLETED":
        return f"Live agent LLM call succeeded for {agent_id}."
    if result.status == "SKIPPED":
        return result.error or f"Live agent LLM call skipped for {agent_id}."
    return result.error or f"Live agent LLM call failed for {agent_id}."


def _validate_profile(profile: AgentLLMProfile) -> str:
    if not profile.enabled:
        return "LLM profile is disabled."
    if not profile.base_url:
        return "LLM profile base_url is missing."
    if not profile.model:
        return "LLM profile model is missing."
    if _requires_api_key(profile) and not profile.api_key:
        return "LLM profile api_key is missing."
    egress_decision = validate_llm_egress(profile)
    if not egress_decision.allowed:
        return egress_decision.message
    return ""


def _requires_api_key(profile: AgentLLMProfile) -> bool:
    base_url = profile.base_url.lower()
    if profile.provider == "local":
        return False
    return not (
        base_url.startswith("http://localhost")
        or base_url.startswith("http://127.0.0.1")
    )


def _build_messages(
    agent: AgentDeployment,
    run_data: Dict[str, Any],
    prior_outputs: Dict[str, Any],
) -> List[Dict[str, str]]:
    system_prompt = load_agent_prompt(agent.id)
    user_payload = {
        "agent_id": agent.id,
        "agent_name": agent.name,
        "node_type": agent.node_type,
        "system_prompt_ref": agent.system_prompt_ref,
        "run_context": _compact_run_context(run_data),
        "prior_agent_outputs": prior_outputs,
        "output_contract": _output_contract(agent),
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _compact_run_context(run_data: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "runId",
        "runMode",
        "environment",
        "stockCode",
        "stockName",
        "taskType",
        "userPosition",
        "dvg",
        "risk",
        "atrade",
        "market",
        "marketData",
        "marketTechnical",
        "technicalKline",
        "bottomResearch",
        "quantCore",
        "quantEngine",
        "factorSlicing",
        "qiam",
        "portfolio",
        "execution",
        "signalOps",
        "killSwitch",
        "orchestratorPlan",
        "finalContext",
    ]
    return {key: run_data.get(key) for key in keys if key in run_data}


def _output_contract(agent: AgentDeployment) -> Dict[str, Any]:
    if agent.id == "final_writer":
        return {
            "format": "json_preferred",
            "rule": "Only express upstream-allowed conclusions. Do not reopen forbidden paths. Explain how the conclusion was derived and expose data for human verification.",
            "schema": {
                "finalAction": "One upstream-allowed final action.",
                "humanConfirmationRequired": True,
                "sections": [
                    {
                        "title": "结论如何得出",
                        "content": "Explain the chain from DVG, risk, QIAM, portfolio, execution, and kill switch to finalAction.",
                        "riskLevel": "LOW|MEDIUM|HIGH",
                        "requiresConfirmation": True,
                    },
                    {
                        "title": "基本面解析",
                        "content": "Summarize available fundamental, macro, sector, factor, and missing fundamental data.",
                        "riskLevel": "LOW|MEDIUM|HIGH",
                        "requiresConfirmation": True,
                    },
                    {
                        "title": "技术面解析",
                        "content": "Summarize quote, liquidity, volatility, price-limit state, T+1, Level-2/depth availability, and execution constraints.",
                        "riskLevel": "LOW|MEDIUM|HIGH",
                        "requiresConfirmation": True,
                    },
                    {
                        "title": "数据核验清单",
                        "content": "List data source, timestamp, missing data, conflicts, audit id, and fields a human should verify.",
                        "riskLevel": "LOW|MEDIUM|HIGH",
                        "requiresConfirmation": True,
                    },
                ],
            },
        }
    return {
        "format": "strict_json",
        "rule": "Return one flat JSON object matching the node prompt schema. Use UNKNOWN/MISSING/NOT_AVAILABLE for uncertain fields.",
    }


def _call_profile_chat(
    profile: AgentLLMProfile,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    assert_llm_egress_allowed(profile)
    if profile.provider == "anthropic":
        return _call_anthropic_messages(profile, messages)
    return _call_openai_compatible_chat(profile, messages)


def _call_openai_compatible_chat(
    profile: AgentLLMProfile,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    endpoint = _chat_endpoint(profile.base_url)
    payload = {
        "model": profile.model,
        "messages": messages,
        "temperature": profile.temperature,
        "max_tokens": profile.max_tokens,
    }
    if _should_disable_thinking_for_probe(profile):
        payload["thinking"] = {"type": "disabled"}
    headers = {
        "Content-Type": "application/json",
        **profile.extra_headers,
    }
    if profile.api_key:
        headers["Authorization"] = f"Bearer {profile.api_key}"

    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=profile.timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _should_disable_thinking_for_probe(profile: AgentLLMProfile) -> bool:
    return bool(
        getattr(profile, "live_test_disable_thinking", False)
        and profile.provider == "deepseek"
        and profile.model.startswith("deepseek-v4-")
    )


def _call_anthropic_messages(
    profile: AgentLLMProfile,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    endpoint = _anthropic_endpoint(profile.base_url)
    system_prompt = "\n\n".join(
        message["content"]
        for message in messages
        if message.get("role") == "system"
    )
    anthropic_messages = [
        {
            "role": message["role"],
            "content": message["content"],
        }
        for message in messages
        if message.get("role") in {"user", "assistant"}
    ]
    payload = {
        "model": profile.model,
        "messages": anthropic_messages,
        "max_tokens": profile.max_tokens,
        "temperature": profile.temperature,
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "Content-Type": "application/json",
        "x-api-key": profile.api_key,
        "anthropic-version": profile.extra_headers.get("anthropic-version", "2023-06-01"),
        **{key: value for key, value in profile.extra_headers.items() if key != "anthropic-version"},
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=profile.timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _chat_endpoint(base_url: str) -> str:
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/chat/completions"):
        return clean_url
    return f"{clean_url}/chat/completions"


def _anthropic_endpoint(base_url: str) -> str:
    clean_url = base_url.rstrip("/")
    if clean_url.endswith("/messages"):
        return clean_url
    return f"{clean_url}/messages"


def _extract_content(response: Dict[str, Any]) -> str:
    anthropic_content = response.get("content")
    if isinstance(anthropic_content, list):
        return "".join(
            part.get("text", "")
            for part in anthropic_content
            if isinstance(part, dict) and part.get("type") == "text"
        )

    choices = response.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            )
    return str(first.get("text", ""))


def _extract_finish_reason(response: Dict[str, Any]) -> str:
    if response.get("stop_reason"):
        return str(response.get("stop_reason", ""))

    choices = response.get("choices") or []
    if not choices:
        return ""
    return str(choices[0].get("finish_reason", ""))


def _extract_json(content: str) -> Optional[Any]:
    if not content.strip():
        return None
    cleaned = _strip_code_fence(content.strip())
    for candidate in (cleaned, _slice_json_candidate(cleaned)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _strip_code_fence(content: str) -> str:
    if content.startswith("```"):
        lines = content.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return content


def _slice_json_candidate(content: str) -> str:
    object_start = content.find("{")
    object_end = content.rfind("}")
    array_start = content.find("[")
    array_end = content.rfind("]")

    candidates = []
    if object_start != -1 and object_end > object_start:
        candidates.append((object_start, object_end + 1))
    if array_start != -1 and array_end > array_start:
        candidates.append((array_start, array_end + 1))
    if not candidates:
        return ""

    start, end = sorted(candidates, key=lambda item: item[0])[0]
    return content[start:end]


def _format_transport_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        provider_message = _extract_provider_error_message(exc)
        guidance = _http_status_guidance(exc.code)
        logger.exception("HTTP transport error: %s", exc)
        if provider_message:
            return f"LLM service rejected the request (HTTP {exc.code}): {provider_message} {guidance}".strip()
        return f"LLM service rejected the request (HTTP {exc.code}). {guidance}".strip()
    logger.exception("Transport error: %s", exc)
    return "A network or transport error occurred. Please check your connection and try again."


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
