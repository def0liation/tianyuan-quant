import re
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..models.research import (
    CreateResearchIterationRequest,
    CreateResearchLoopRequest,
    ResearchEvidenceLink,
    ResearchIterationFeedbackRequest,
)


EXTERNAL_SOURCE_NAME = "rd-agent"
EXTERNAL_SOURCE_TYPE = "RD_AGENT_TRACE"
MASK = "***MASKED***"
MAX_TRACE_DEPTH = 12
MAX_TRACE_MAPPING_KEYS = 200
MAX_TRACE_LIST_ITEMS = 500
MAX_TRACE_TEXT_CHARS = 5_000
MAX_TRACE_ITERATIONS = 100
MAX_TRACE_EVIDENCE_PER_ITERATION = 50
MAX_TRACE_METRICS = 100

SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|access[_-]?token|auth[_-]?token|authorization|bearer|secret|password|passwd|pwd|token)",
    re.IGNORECASE,
)
OPENAI_KEY_PATTERN = re.compile(r"\bsk(?:-proj)?-[A-Za-z0-9_-]{12,}\b")
BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
SECRET_QUERY_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password)=)[^&\s]+"
)


class NormalizedResearchIterationImport(BaseModel):
    order: int
    create_request: CreateResearchIterationRequest
    feedback_request: ResearchIterationFeedbackRequest
    external_source: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class NormalizedResearchTrace(BaseModel):
    loop_create_request: CreateResearchLoopRequest
    iterations: list[NormalizedResearchIterationImport] = Field(default_factory=list)
    external_source: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


def normalize_rd_agent_trace(
    trace: Mapping[str, Any],
    *,
    source_id: str | None = None,
    imported_at: str | None = None,
) -> NormalizedResearchTrace:
    """Convert an external RD-Agent trace JSON object into Research Lab import payloads."""
    if not isinstance(trace, Mapping):
        raise TypeError("trace must be a mapping")

    _enforce_trace_budget(trace)
    safe_trace = mask_secrets(dict(trace))
    imported_at = imported_at or _now()
    trace_id = _first_text(safe_trace, "trace_id", "traceId", "id", "run_id", "runId") or source_id or "unknown"
    external_source = {
        "source": EXTERNAL_SOURCE_NAME,
        "source_type": EXTERNAL_SOURCE_TYPE,
        "source_id": trace_id,
        "imported_at": imported_at,
        "external": True,
    }

    loop_payload = _as_mapping(safe_trace.get("loop"))
    title = (
        _first_text(loop_payload, "title", "name")
        or _first_text(safe_trace, "title", "name", "experiment_name", "experimentName")
        or f"RD-Agent Trace {trace_id}"
    )
    objective = (
        _first_text(loop_payload, "objective", "goal", "task", "description")
        or _first_text(safe_trace, "objective", "goal", "task", "description")
        or "Imported RD-Agent research trace"
    )

    raw_iterations = _extract_iterations(safe_trace)
    warnings: list[str] = []
    if not raw_iterations:
        raw_iterations = [_fallback_iteration(safe_trace)]
        warnings.append("No explicit iterations found; created one iteration from top-level trace fields.")
    if len(raw_iterations) > MAX_TRACE_ITERATIONS:
        raise ValueError(f"RD-Agent trace import exceeds the {MAX_TRACE_ITERATIONS} iteration limit.")

    normalized_iterations = [
        _normalize_iteration(item, index=index, trace_id=trace_id, imported_at=imported_at)
        for index, item in enumerate(raw_iterations, start=1)
    ]

    first_iteration = normalized_iterations[0].create_request if normalized_iterations else None
    tags = _normalize_text_list(safe_trace.get("tags")) + _normalize_text_list(loop_payload.get("tags"))
    tags = _dedupe(["rd-agent", "external-import", *tags])
    target_modules = first_iteration.target_modules if first_iteration else []

    loop_request = CreateResearchLoopRequest(
        title=title,
        objective=objective,
        hypothesis=first_iteration.hypothesis if first_iteration else "",
        plan=first_iteration.plan if first_iteration else "",
        action_target=_action_target(safe_trace, loop_payload, raw_iterations[0] if raw_iterations else {}),
        owner=_first_text(safe_trace, "owner", "author", "created_by", "createdBy") or "rd-agent",
        tags=tags,
        target_modules=target_modules,
        linked_projects=[],
    )

    return NormalizedResearchTrace(
        loop_create_request=loop_request,
        iterations=normalized_iterations,
        external_source=external_source,
        warnings=warnings,
    )


def mask_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if SECRET_KEY_PATTERN.search(text_key):
                masked[text_key] = MASK
            else:
                masked[text_key] = mask_secrets(item)
        return masked
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_secrets(item) for item in value)
    if isinstance(value, str):
        return _mask_secret_text(value)
    return value


def _normalize_iteration(
    raw: Any,
    *,
    index: int,
    trace_id: str,
    imported_at: str,
) -> NormalizedResearchIterationImport:
    item = _as_mapping(raw)
    metrics = _normalize_metrics(item)
    evidence_links = _normalize_evidence(item, index=index, trace_id=trace_id, imported_at=imported_at)

    linked_run_id = _first_text(item, "run_id", "runId", "analysis_run_id", "analysisRunId") or None
    linked_backtest_id = _first_text(item, "backtest_id", "backtestId") or None
    create_request = CreateResearchIterationRequest(
        hypothesis=_iteration_hypothesis(item, index),
        plan=_text_or_join(
            _first_present(item, "plan", "experiment_plan", "experimentPlan", "design", "implementation", "code_plan")
        ),
        target_modules=_target_modules(item),
        linked_run_id=linked_run_id,
        metrics=metrics,
    )
    feedback_request = ResearchIterationFeedbackRequest(
        action=_feedback_action(item),
        verdict=_feedback_verdict(item),
        note=_feedback_note(item),
        reviewer=EXTERNAL_SOURCE_NAME,
        status=_first_text(item, "status", "state") or None,
        linked_run_id=linked_run_id,
        linked_backtest_id=linked_backtest_id,
        linked_case_id=_first_text(item, "case_id", "caseId") or None,
        linked_knowledge_item_id=_first_text(item, "knowledge_item_id", "knowledgeItemId") or None,
        linked_patch_id=_first_text(item, "patch_id", "patchId") or None,
        metrics=metrics,
        evidence_links=evidence_links,
    )

    return NormalizedResearchIterationImport(
        order=index,
        create_request=create_request,
        feedback_request=feedback_request,
        external_source={
            "source": EXTERNAL_SOURCE_NAME,
            "source_type": EXTERNAL_SOURCE_TYPE,
            "source_id": trace_id,
            "external_iteration_id": _first_text(item, "iteration_id", "iterationId", "id") or str(index),
            "imported_at": imported_at,
        },
        raw=dict(item),
    )


def _extract_iterations(trace: Mapping[str, Any]) -> list[Any]:
    loop = _as_mapping(trace.get("loop"))
    for container in (trace, loop):
        for key in ("iterations", "iteration", "steps", "trace", "history", "rounds"):
            value = container.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, Mapping):
                return list(value.values())
    return []


def _fallback_iteration(trace: Mapping[str, Any]) -> dict[str, Any]:
    fallback = dict(trace)
    fallback.update({
        "hypothesis": _first_text(trace, "hypothesis", "idea", "proposal", "summary") or "Imported RD-Agent hypothesis",
        "plan": _first_present(trace, "plan", "experiment_plan", "implementation"),
        "metrics": _first_present(trace, "metrics", "metric", "scores", "results"),
        "evidence": _first_present(trace, "evidence", "artifacts", "logs"),
        "feedback": _first_present(trace, "feedback", "review", "analysis"),
    })
    return fallback


def _iteration_hypothesis(item: Mapping[str, Any], index: int) -> str:
    return (
        _first_text(item, "hypothesis", "hypo", "proposal", "idea", "experiment", "summary", "title")
        or f"Imported RD-Agent iteration {index}"
    )


def _normalize_metrics(item: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _first_present(item, "metrics", "metric", "scores", "results", "result")
    if isinstance(metrics, Mapping):
        if len(metrics) > MAX_TRACE_METRICS:
            raise ValueError(f"RD-Agent trace metrics exceed the {MAX_TRACE_METRICS} item limit.")
        return dict(metrics)
    if isinstance(metrics, list):
        if len(metrics) > MAX_TRACE_METRICS:
            raise ValueError(f"RD-Agent trace metrics exceed the {MAX_TRACE_METRICS} item limit.")
        output: dict[str, Any] = {}
        for index, metric in enumerate(metrics, start=1):
            if isinstance(metric, Mapping):
                key = _first_text(metric, "key", "name", "metric") or f"metric_{index}"
                output[key] = metric.get("value", metric.get("current", dict(metric)))
            else:
                output[f"metric_{index}"] = metric
        return output
    if metrics not in (None, ""):
        return {"value": metrics}
    return {}


def _normalize_evidence(
    item: Mapping[str, Any],
    *,
    index: int,
    trace_id: str,
    imported_at: str,
) -> list[ResearchEvidenceLink]:
    evidence = _first_present(item, "evidence", "evidence_links", "evidenceLinks", "artifacts", "artifact", "logs")
    if evidence is None:
        return [
            ResearchEvidenceLink(
                source_type=EXTERNAL_SOURCE_TYPE,
                source_id=f"{trace_id}:iteration:{index}",
                label=f"RD-Agent iteration {index}",
                quality="UNKNOWN",
                created_at=imported_at,
            )
        ]
    items = evidence if isinstance(evidence, list) else [evidence]
    if len(items) > MAX_TRACE_EVIDENCE_PER_ITERATION:
        raise ValueError(
            f"RD-Agent trace evidence exceeds the {MAX_TRACE_EVIDENCE_PER_ITERATION} item limit per iteration."
        )
    links: list[ResearchEvidenceLink] = []
    for evidence_index, entry in enumerate(items, start=1):
        if isinstance(entry, Mapping):
            source_id = _first_text(entry, "source_id", "sourceId", "id", "path", "url", "uri")
            label = _first_text(entry, "label", "name", "title", "summary", "path", "url")
            quality = _first_text(entry, "quality", "confidence", "grade") or "UNKNOWN"
        else:
            source_id = str(entry)
            label = str(entry)
            quality = "UNKNOWN"
        links.append(
            ResearchEvidenceLink(
                source_type=EXTERNAL_SOURCE_TYPE,
                source_id=source_id or f"{trace_id}:iteration:{index}:evidence:{evidence_index}",
                label=label or f"RD-Agent evidence {evidence_index}",
                quality=str(quality).upper(),
                created_at=imported_at,
            )
        )
    return links


def _feedback_action(item: Mapping[str, Any]) -> str:
    text = _first_text(item, "feedback_action", "feedbackAction", "action")
    if text:
        return text.upper()
    verdict = _feedback_verdict(item)
    if verdict == "ACCEPTED":
        return "ACCEPT"
    if verdict == "REJECTED":
        return "REJECT"
    if verdict == "PATCH_REQUIRED":
        return "PATCH"
    return "REVIEW"


def _feedback_verdict(item: Mapping[str, Any]) -> str:
    text = _first_text(item, "verdict", "decision", "feedback_verdict", "feedbackVerdict")
    if not text:
        feedback = _as_mapping(item.get("feedback"))
        text = _first_text(feedback, "verdict", "decision", "status")
    normalized = (text or "PENDING").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "ACCEPT": "ACCEPTED",
        "PASS": "ACCEPTED",
        "PASSED": "ACCEPTED",
        "SUCCESS": "ACCEPTED",
        "REJECT": "REJECTED",
        "FAIL": "REJECTED",
        "FAILED": "REJECTED",
        "PATCH": "PATCH_REQUIRED",
        "NEEDS_PATCH": "PATCH_REQUIRED",
    }
    return aliases.get(normalized, normalized)


def _feedback_note(item: Mapping[str, Any]) -> str:
    feedback = item.get("feedback")
    if isinstance(feedback, Mapping):
        return _text_or_join(_first_present(feedback, "note", "notes", "summary", "critique", "reason"))
    return _text_or_join(_first_present(item, "feedback", "review", "critique", "reason", "analysis"))


def _action_target(*items: Mapping[str, Any]) -> str:
    for item in items:
        target = _first_text(item, "action_target", "actionTarget", "target", "target_type", "targetType")
        if target:
            return target.strip().lower()
    return "factor"


def _target_modules(item: Mapping[str, Any]) -> list[str]:
    return _dedupe(
        [
            *_normalize_text_list(_first_present(item, "target_modules", "targetModules", "modules", "module")),
            *_normalize_text_list(_first_present(item, "files", "file_paths", "filePaths")),
        ]
    )


def _first_present(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _first_text(data: Mapping[str, Any], *keys: str) -> str:
    return _text_or_join(_first_present(data, *keys)).strip()


def _text_or_join(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return "; ".join(f"{key}: {_text_or_join(item)}" for key, item in value.items() if item not in (None, ""))
    if isinstance(value, list):
        return "\n".join(_text_or_join(item) for item in value if item not in (None, ""))
    return str(value)


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _enforce_trace_budget(value: Any, *, path: str = "trace", depth: int = 0, seen: set[int] | None = None) -> None:
    if depth > MAX_TRACE_DEPTH:
        raise ValueError(f"RD-Agent trace exceeds the {MAX_TRACE_DEPTH} nesting depth limit at {path}.")
    if seen is None:
        seen = set()
    if isinstance(value, (Mapping, list, tuple)):
        marker = id(value)
        if marker in seen:
            raise ValueError(f"RD-Agent trace contains a recursive value at {path}.")
        seen.add(marker)
    if isinstance(value, Mapping):
        if len(value) > MAX_TRACE_MAPPING_KEYS:
            raise ValueError(f"RD-Agent trace object at {path} exceeds the {MAX_TRACE_MAPPING_KEYS} key limit.")
        for key, item in value.items():
            text_key = str(key)
            if len(text_key) > MAX_TRACE_TEXT_CHARS:
                raise ValueError(f"RD-Agent trace key at {path} exceeds the {MAX_TRACE_TEXT_CHARS} character limit.")
            _enforce_trace_budget(item, path=f"{path}.{text_key}", depth=depth + 1, seen=seen)
    elif isinstance(value, (list, tuple)):
        if len(value) > MAX_TRACE_LIST_ITEMS:
            raise ValueError(f"RD-Agent trace list at {path} exceeds the {MAX_TRACE_LIST_ITEMS} item limit.")
        for index, item in enumerate(value):
            _enforce_trace_budget(item, path=f"{path}[{index}]", depth=depth + 1, seen=seen)
    elif isinstance(value, str) and len(value) > MAX_TRACE_TEXT_CHARS:
        raise ValueError(f"RD-Agent trace text at {path} exceeds the {MAX_TRACE_TEXT_CHARS} character limit.")


def _mask_secret_text(value: str) -> str:
    masked = OPENAI_KEY_PATTERN.sub(MASK, value)
    masked = BEARER_PATTERN.sub(lambda match: f"{match.group(1)}{MASK}", masked)
    return SECRET_QUERY_PATTERN.sub(lambda match: f"{match.group(1)}{MASK}", masked)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
