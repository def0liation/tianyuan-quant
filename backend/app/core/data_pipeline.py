import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from ..models.data_pipeline import (
    CompressionOverview,
    DataFingerprint,
    DataQualityScore,
    KnowledgeDistillationGroup,
    RunCompressionSummary,
)
from ..models.knowledge import KnowledgeItem


DECISION_KEEP_FIELDS = [
    "runId",
    "auditId",
    "stockCode",
    "stockName",
    "taskType",
    "runMode",
    "status",
    "createdAt",
    "updatedAt",
    "dataSources",
    "dvg",
    "risk",
    "qiam",
    "killSwitch",
    "execution",
    "signalOps",
    "paperTrading",
    "finalWriter",
    "finalAction",
    "agentResults",
    "auditLog",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def fingerprint_payload(payload: dict[str, Any], namespace: str) -> DataFingerprint:
    canonical = _canonical_payload(payload)
    encoded = _stable_json(canonical).encode("utf-8")
    return DataFingerprint(
        namespace=namespace,
        fingerprint=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        canonical_keys=sorted(canonical.keys()),
        created_at=_now(),
    )


def score_run_quality(run_data: dict[str, Any]) -> DataQualityScore:
    issues: list[str] = []
    strengths: list[str] = []
    missing: list[str] = []
    score = 0

    for field in ("runId", "stockCode", "runMode", "status"):
        if run_data.get(field):
            score += 4
        else:
            missing.append(field)
    if _final_action(run_data):
        score += 4
    else:
        missing.append("finalAction")

    dvg = run_data.get("dvg") or {}
    if dvg.get("status"):
        score += 8
    else:
        missing.append("dvg.status")
    if dvg.get("dataReliability"):
        score += 7
    if dvg.get("status") == "PASS":
        score += 5
        strengths.append("dvg_passed")
    if dvg.get("criticalMissingData") or dvg.get("dataConflicts"):
        issues.append("dvg_has_missing_or_conflicting_data")

    qiam = run_data.get("qiam") or {}
    if qiam.get("finalBuySuitability"):
        score += 8
    else:
        missing.append("qiam.finalBuySuitability")
    if isinstance(qiam.get("modelConfidenceFinal"), (int, float)) and not isinstance(qiam.get("modelConfidenceFinal"), bool):
        score += 6
        if qiam["modelConfidenceFinal"] >= 0.75:
            strengths.append("qiam_high_confidence")
    if qiam.get("downgradeReasons") or qiam.get("missingData"):
        issues.append("qiam_downgraded_or_missing_data")

    data_sources = run_data.get("dataSources") or {}
    source_coverage = _source_coverage(data_sources)
    available, total = _source_coverage_numbers(source_coverage)
    if total:
        score += min(15, round(15 * available / total))
        if available == total:
            strengths.append("all_data_sources_ready")
        elif available == 0:
            issues.append("all_data_sources_mock_or_unavailable")
    else:
        issues.append("data_sources_not_reported")

    nodes = run_data.get("nodes") or []
    agent_results = run_data.get("agentResults") or []
    if nodes:
        score += 8
        strengths.append("agent_node_trace_present")
    else:
        missing.append("nodes")
    if agent_results:
        score += 7
    elif run_data.get("status") == "COMPLETED":
        issues.append("completed_run_without_agent_results")

    audit_log = run_data.get("auditLog") or []
    if audit_log:
        score += 7
        strengths.append("audit_log_present")
    else:
        issues.append("audit_log_missing")

    final_writer = run_data.get("finalWriter") or {}
    if final_writer.get("sections"):
        score += 8
    else:
        issues.append("final_writer_sections_missing")

    kill_switch = run_data.get("killSwitch") or {}
    if "active" in kill_switch or kill_switch.get("level"):
        score += 4
    else:
        missing.append("killSwitch")

    score = max(0, min(100, score))
    level = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    return DataQualityScore(
        score=score,
        level=level,
        issues=_dedupe(issues),
        strengths=_dedupe(strengths),
        source_coverage=source_coverage,
        missing_critical_fields=_dedupe(missing),
    )


def summarize_run(run_data: dict[str, Any]) -> RunCompressionSummary:
    canonical = _canonical_payload(run_data)
    quality = score_run_quality(run_data)
    fingerprint = fingerprint_payload(canonical, namespace="run_decision_v1")
    guardrails = _guardrail_summary(run_data)
    evidence = _evidence_summary(run_data)
    key_metrics = _key_metrics(run_data)
    agent_summary = _agent_summary(run_data)
    retention_action, retention_reason = _retention_policy(run_data, quality)
    serialized_summary = {
        "key_metrics": key_metrics,
        "guardrail_summary": guardrails,
        "evidence_summary": evidence,
        "agent_summary": agent_summary,
    }

    return RunCompressionSummary(
        run_id=run_data.get("runId", ""),
        symbol=run_data.get("stockCode", ""),
        stock_name=run_data.get("stockName", ""),
        status=run_data.get("status", ""),
        run_mode=run_data.get("runMode", ""),
        final_action=_final_action(run_data),
        data_fingerprint=fingerprint,
        quality=quality,
        keep_fields=list(canonical.keys()),
        key_metrics=key_metrics,
        decision_summary=_decision_summary(run_data, key_metrics),
        guardrail_summary=guardrails,
        evidence_summary=evidence,
        agent_summary=agent_summary,
        token_budget_estimate=max(1, round(len(_stable_json(serialized_summary)) / 4)),
        retention_action=retention_action,
        retention_reason=retention_reason,
        created_at=_now(),
        compression_persisted=is_run_compressed(run_data),
        artifact_path=compression_artifact_path(run_data.get("runId", "")),
        compressed_at=_compressed_at(run_data),
    )


def is_run_compressed(run_data: dict[str, Any]) -> bool:
    return isinstance(run_data.get("compressedSummary"), dict)


def compression_artifact_path(run_id: str) -> str | None:
    if not run_id:
        return None
    return f"backend/app/storage/runs/{run_id}.json#compressedSummary"


def persisted_compression_summary(run_data: dict[str, Any]) -> RunCompressionSummary | None:
    existing = run_data.get("compressedSummary")
    if not isinstance(existing, dict):
        return None

    payload = dict(existing)
    payload["compression_persisted"] = True
    payload["artifact_path"] = payload.get("artifact_path") or compression_artifact_path(run_data.get("runId", ""))
    payload["compressed_at"] = payload.get("compressed_at") or payload.get("created_at") or _compressed_at(run_data)
    return RunCompressionSummary(**payload)


def mark_summary_persisted(run_data: dict[str, Any], summary: RunCompressionSummary) -> RunCompressionSummary:
    compressed_at = _now()
    summary.compression_persisted = True
    summary.artifact_path = compression_artifact_path(run_data.get("runId", ""))
    summary.compressed_at = compressed_at
    run_data["compressedAt"] = compressed_at
    return summary


def compression_overview(runs: list[dict[str, Any]]) -> CompressionOverview:
    summaries = [summarize_run(run) for run in runs]
    actions: dict[str, int] = {}
    for summary in summaries:
        actions[summary.retention_action] = actions.get(summary.retention_action, 0) + 1

    return CompressionOverview(
        total_runs=len(runs),
        summarized_runs=len(summaries),
        average_quality_score=round(sum(item.quality.score for item in summaries) / len(summaries), 2) if summaries else 0,
        high_quality_count=sum(1 for item in summaries if item.quality.level == "HIGH"),
        medium_quality_count=sum(1 for item in summaries if item.quality.level == "MEDIUM"),
        low_quality_count=sum(1 for item in summaries if item.quality.level == "LOW"),
        retention_actions=actions,
        latest_run_id=max(runs, key=lambda item: item.get("updatedAt") or item.get("createdAt") or "").get("runId") if runs else None,
    )


def _compressed_at(run_data: dict[str, Any]) -> str | None:
    existing = run_data.get("compressedSummary")
    if isinstance(existing, dict):
        return existing.get("compressed_at") or existing.get("created_at") or run_data.get("compressedAt")
    return run_data.get("compressedAt")


def distill_knowledge_items(
    items: list[KnowledgeItem],
    *,
    min_group_size: int = 2,
) -> list[KnowledgeDistillationGroup]:
    buckets: dict[str, list[KnowledgeItem]] = {}
    for item in items:
        key = _knowledge_group_key(item)
        buckets.setdefault(key, []).append(item)

    groups: list[KnowledgeDistillationGroup] = []
    for key, grouped_items in buckets.items():
        if len(grouped_items) < min_group_size:
            continue
        sorted_items = sorted(grouped_items, key=lambda item: (item.version, item.updated_at), reverse=True)
        representative = sorted_items[0]
        shared_tags = _shared_tags(sorted_items)
        groups.append(
            KnowledgeDistillationGroup(
                group_id=f"KDG_{_fingerprint(key)[:12]}",
                category=representative.category,
                fingerprint=_fingerprint(
                    {
                        "category": representative.category,
                        "shared_tags": shared_tags,
                        "thesis": _normalize_text(representative.thesis)[:180],
                    }
                ),
                item_ids=[item.item_id for item in sorted_items],
                representative_item_id=representative.item_id,
                duplicate_count=len(sorted_items) - 1,
                shared_tags=shared_tags,
                suggested_action="MERGE_OR_ARCHIVE_DUPLICATES",
                reason="Items share category and normalized tags; keep the newest/highest-version item as representative.",
            )
        )

    return sorted(groups, key=lambda group: group.duplicate_count, reverse=True)


def _canonical_payload(run_data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: run_data.get(key)
        for key in DECISION_KEEP_FIELDS
        if key in run_data
    }


def _final_action(run_data: dict[str, Any]) -> str:
    final_writer = run_data.get("finalWriter") or {}
    return final_writer.get("finalAction") or run_data.get("finalAction") or "WAIT"


def _source_coverage(data_sources: dict[str, Any]) -> str:
    summary = data_sources.get("summary") if isinstance(data_sources, dict) else None
    if isinstance(summary, dict) and summary.get("availableRatio"):
        return str(summary["availableRatio"])
    sources = data_sources.get("sources") if isinstance(data_sources, dict) else None
    if isinstance(sources, dict):
        total = len(sources)
        available = sum(1 for source in sources.values() if source.get("available") or source.get("status") == "READY")
        return f"{available}/{total}"
    return "0/0"


def _source_coverage_numbers(value: str) -> tuple[int, int]:
    try:
        available, total = value.split("/", 1)
        return int(available), int(total)
    except (ValueError, TypeError):
        return 0, 0


def _key_metrics(run_data: dict[str, Any]) -> dict[str, Any]:
    dvg = run_data.get("dvg") or {}
    qiam = run_data.get("qiam") or {}
    signalops = run_data.get("signalOps") or {}
    kill_switch = run_data.get("killSwitch") or {}
    token_usage = run_data.get("tokenUsage") or {}
    totals = token_usage.get("totals") if isinstance(token_usage, dict) else {}
    return {
        "dvg_status": dvg.get("status"),
        "data_reliability": dvg.get("dataReliability"),
        "hallucination_risk_score": dvg.get("hallucinationRiskScore"),
        "qiam_final": qiam.get("finalBuySuitability"),
        "qiam_confidence": qiam.get("modelConfidenceFinal"),
        "signal_status": signalops.get("signalStatus"),
        "signal_blocked_reason": signalops.get("blockedReason"),
        "kill_switch_active": kill_switch.get("active"),
        "kill_switch_level": kill_switch.get("level"),
        "data_source_coverage": _source_coverage(run_data.get("dataSources") or {}),
        "token_total": totals.get("total_tokens") if isinstance(totals, dict) else None,
    }


def _decision_summary(run_data: dict[str, Any], key_metrics: dict[str, Any]) -> str:
    symbol = run_data.get("stockCode", "UNKNOWN")
    final_action = _final_action(run_data)
    return (
        f"{symbol} ended with {final_action}; "
        f"DVG={key_metrics.get('dvg_status')}, "
        f"QIAM={key_metrics.get('qiam_final')}, "
        f"SignalOps={key_metrics.get('signal_status')}, "
        f"KillSwitch={key_metrics.get('kill_switch_level') or 'NONE'}."
    )


def _guardrail_summary(run_data: dict[str, Any]) -> list[str]:
    dvg = run_data.get("dvg") or {}
    qiam = run_data.get("qiam") or {}
    execution = run_data.get("execution") or {}
    signalops = run_data.get("signalOps") or {}
    kill_switch = run_data.get("killSwitch") or {}
    chip_kb = run_data.get("chipKb") or {}
    values = [
        *_as_list(dvg.get("criticalMissingData")),
        *_as_list(dvg.get("dataConflicts")),
        *_as_list(qiam.get("downgradeReasons")),
        *_as_list(qiam.get("missingData")),
        *_as_list(execution.get("forbiddenActions")),
        *_as_list(chip_kb.get("coreMissingData")),
    ]
    if signalops.get("blockedReason"):
        values.append(f"SignalOps blocked: {signalops['blockedReason']}")
    if kill_switch.get("active"):
        values.append(f"KillSwitch active: {kill_switch.get('level', 'UNKNOWN')} {kill_switch.get('triggerRule', '')}".strip())
    return _dedupe([str(value) for value in values if str(value).strip()]) or ["No active guardrail exception."]


def _evidence_summary(run_data: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for node in run_data.get("nodes") or []:
        summary = node.get("outputSummary") or node.get("inputSummary")
        if summary:
            evidence.append(f"{node.get('id', 'node')}: {_truncate(str(summary), 180)}")

    final_writer = run_data.get("finalWriter") or {}
    for section in final_writer.get("sections") or []:
        title = section.get("title", "Final")
        content = section.get("content", "")
        if content:
            evidence.append(f"{title}: {_truncate(str(content), 220)}")

    for event in run_data.get("auditLog") or []:
        message = event.get("message")
        if message:
            evidence.append(f"audit:{event.get('node', 'system')}: {_truncate(str(message), 160)}")

    return _dedupe(evidence)[:12]


def _agent_summary(run_data: dict[str, Any]) -> dict[str, Any]:
    nodes = run_data.get("nodes") or []
    counts: dict[str, int] = {}
    skipped: list[str] = []
    blocked: list[str] = []
    for node in nodes:
        status = str(node.get("status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1
        if node.get("isSkipped"):
            skipped.append(str(node.get("id", "")))
        if node.get("isBlocked"):
            blocked.append(str(node.get("id", "")))

    return {
        "node_count": len(nodes),
        "status_counts": counts,
        "skipped_nodes": _dedupe(skipped),
        "blocked_nodes": _dedupe(blocked),
        "agent_result_count": len(run_data.get("agentResults") or []),
        "audit_event_count": len(run_data.get("auditLog") or []),
    }


def _retention_policy(run_data: dict[str, Any], quality: DataQualityScore) -> tuple[str, str]:
    if run_data.get("status") not in {"COMPLETED", "FAILED"}:
        return "KEEP_RAW_UNTIL_FINAL", "Run is not terminal yet."
    if quality.level == "HIGH":
        return "KEEP_RAW_AND_SUMMARY", "High-quality terminal run; useful for replay and future distillation."
    if quality.level == "MEDIUM":
        return "KEEP_SUMMARY_REVIEW_RAW", "Moderate quality; summary is usable but raw data should be reviewed before reuse."
    return "REVIEW_BEFORE_USE", "Low quality or missing critical fields; keep only as an exception sample until reviewed."


def _knowledge_group_key(item: KnowledgeItem) -> str:
    tags = [
        tag.lower()
        for tag in item.tags
        if tag and not tag.upper().startswith("RUN_") and tag.upper() not in {"STANDARD_MODE", "FAST_MODE", "DEEP_MODE"}
    ]
    if tags:
        return f"{item.category}|{'|'.join(sorted(set(tags))[:4])}"
    return f"{item.category}|{_normalize_text(item.title + ' ' + item.thesis)[:120]}"


def _shared_tags(items: list[KnowledgeItem]) -> list[str]:
    tag_sets = [set(tag.lower() for tag in item.tags) for item in items if item.tags]
    if not tag_sets:
        return []
    shared = set.intersection(*tag_sets)
    if shared:
        return sorted(shared)
    counts: dict[str, int] = {}
    for tag_set in tag_sets:
        for tag in tag_set:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(tag for tag, count in counts.items() if count >= 2)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        result.append(clean)
        seen.add(clean)
    return result


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"
