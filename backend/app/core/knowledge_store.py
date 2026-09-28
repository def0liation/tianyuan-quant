import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.knowledge import (
    CreateKnowledgeItemRequest,
    KnowledgeItem,
    KnowledgeSummary,
    ReviewKnowledgeItemRequest,
)


STORAGE_FILE = Path(__file__).resolve().parents[1] / "storage" / "knowledge_iterations.json"

ACTIVE_STATUS = "ACTIVE"
PENDING_STATUS = "PENDING_REVIEW"
REJECTED_STATUS = "REJECTED"
ARCHIVED_STATUS = "ARCHIVED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _default_state() -> dict[str, Any]:
    return {"items": [], "updated_at": _now()}


def _load_state() -> dict[str, Any]:
    if not STORAGE_FILE.exists():
        state = _default_state()
        _save_state(state)
        return state

    with STORAGE_FILE.open("r", encoding="utf-8") as file:
        state = json.load(file)

    if "items" not in state:
        state["items"] = []
    if "updated_at" not in state:
        state["updated_at"] = _now()
    return state


def _save_state(state: dict[str, Any]) -> None:
    STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    with STORAGE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2, ensure_ascii=False)


def _items_from_state(state: dict[str, Any]) -> list[KnowledgeItem]:
    items = [KnowledgeItem(**item) for item in state.get("items", [])]
    for item in items:
        _apply_knowledge_boundaries(item)
    return items


def list_knowledge_items(
    status: str | None = None,
    category: str | None = None,
) -> list[KnowledgeItem]:
    items = _items_from_state(_load_state())
    if status:
        items = [item for item in items if item.status == status]
    if category:
        items = [item for item in items if item.category == category]
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def get_knowledge_summary() -> KnowledgeSummary:
    state = _load_state()
    items = _items_from_state(state)
    categories: dict[str, int] = {}
    for item in items:
        categories[item.category] = categories.get(item.category, 0) + 1

    return KnowledgeSummary(
        total=len(items),
        active_count=sum(1 for item in items if item.status == ACTIVE_STATUS),
        pending_count=sum(1 for item in items if item.status == PENDING_STATUS),
        rejected_count=sum(1 for item in items if item.status == REJECTED_STATUS),
        archived_count=sum(1 for item in items if item.status == ARCHIVED_STATUS),
        latest_version=max((item.version for item in items if item.status == ACTIVE_STATUS), default=0),
        categories=categories,
        updated_at=state.get("updated_at", _now()),
    )


def get_active_knowledge_context(limit: int = 8) -> list[dict[str, Any]]:
    active_items = [
        item
        for item in list_knowledge_items(status=ACTIVE_STATUS)
        if item.version > 0
    ]
    return [
        {
            "itemId": item.item_id,
            "version": item.version,
            "category": item.category,
            "title": item.title,
            "thesis": item.thesis,
            "decisionImpact": item.decision_impact,
            "tags": item.tags,
            "confidence": item.confidence,
            "evidenceUsage": item.evidence_usage,
            "evidenceStrength": item.evidence_strength,
            "simulationOnly": item.simulation_only,
            "isRealTrade": item.is_real_trade,
            "strongConclusionAllowed": item.strong_conclusion_allowed,
        }
        for item in sorted(active_items, key=lambda item: item.version, reverse=True)[:limit]
    ]


def create_knowledge_item(
    request: CreateKnowledgeItemRequest,
    *,
    source_run_verified: bool = False,
) -> KnowledgeItem:
    state = _load_state()
    item = KnowledgeItem(
        item_id=f"KB_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        category=request.category.strip() or "RUN_REVIEW",
        source_run_id=request.source_run_id,
        source_audit_id=request.source_audit_id,
        source_run_verified=bool(source_run_verified and request.source_run_id),
        title=request.title.strip(),
        thesis=request.thesis.strip(),
        evidence=[entry.strip() for entry in request.evidence if entry.strip()],
        decision_impact=request.decision_impact.strip(),
        guardrail_notes=[entry.strip() for entry in request.guardrail_notes if entry.strip()],
        tags=[entry.strip() for entry in request.tags if entry.strip()],
        confidence=_supporting_confidence(request.confidence),
        evidence_usage="supporting_only",
        evidence_strength=_knowledge_evidence_strength(
            evidence=[entry.strip() for entry in request.evidence if entry.strip()],
            guardrail_notes=[entry.strip() for entry in request.guardrail_notes if entry.strip()],
            status=PENDING_STATUS,
            source_run_id=request.source_run_id,
            source_run_verified=source_run_verified,
        ),
        simulation_only=True,
        is_real_trade=False,
        strong_conclusion_allowed=False,
        created_at=_now(),
        updated_at=_now(),
    )
    if not item.title:
        raise ValueError("title is required")
    if not item.thesis:
        raise ValueError("thesis is required")

    state["items"].append(_dump(item))
    _save_state(state)
    return item


def review_knowledge_item(item_id: str, request: ReviewKnowledgeItemRequest) -> KnowledgeItem:
    state = _load_state()
    items = _items_from_state(state)
    item = next((entry for entry in items if entry.item_id == item_id), None)
    if item is None:
        raise KeyError(f"Unknown knowledge item: {item_id}")

    action = request.action.upper()
    if action not in {"APPROVE", "REJECT", "ARCHIVE"}:
        raise ValueError("action must be APPROVE, REJECT, or ARCHIVE")

    if action == "APPROVE":
        item.status = ACTIVE_STATUS
        item.version = max((entry.version for entry in items), default=0) + 1
    elif action == "REJECT":
        item.status = REJECTED_STATUS
    else:
        item.status = ARCHIVED_STATUS

    item.reviewed_at = _now()
    item.updated_at = item.reviewed_at
    item.reviewer = request.reviewer
    item.review_note = request.note
    item.evidence_usage = "supporting_only"
    item.evidence_strength = _knowledge_evidence_strength(
        evidence=item.evidence,
        guardrail_notes=item.guardrail_notes,
        status=item.status,
        source_run_id=item.source_run_id,
        source_run_verified=item.source_run_verified,
    )
    item.simulation_only = True
    item.is_real_trade = False
    item.strong_conclusion_allowed = False

    state["items"] = [_dump(item if entry.item_id == item_id else entry) for entry in items]
    _save_state(state)
    return item


def create_learning_candidate_from_run(
    run_data: dict[str, Any],
    *,
    force: bool = False,
) -> KnowledgeItem:
    state = _load_state()
    items = _items_from_state(state)
    run_id = run_data.get("runId", "")
    if run_id and not force:
        existing = next(
            (
                item
                for item in items
                if item.source_run_id == run_id
                and item.status in {PENDING_STATUS, ACTIVE_STATUS}
            ),
            None,
        )
        if existing:
            return existing

    item = _candidate_from_run(run_data)
    items.append(item)
    state["items"] = [_dump(entry) for entry in items]
    _save_state(state)
    return item


def _candidate_from_run(run_data: dict[str, Any]) -> KnowledgeItem:
    run_id = run_data.get("runId", "")
    audit_id = run_data.get("auditId") or run_data.get("audit_id")
    symbol = run_data.get("stockCode", "UNKNOWN")
    run_mode = run_data.get("runMode", "UNKNOWN")
    task_type = run_data.get("taskType", "UNKNOWN")
    final_writer = run_data.get("finalWriter") or {}
    final_action = final_writer.get("finalAction") or run_data.get("finalAction", "WAIT")
    dvg = run_data.get("dvg") or {}
    qiam = run_data.get("qiam") or {}
    signalops = run_data.get("signalOps") or {}
    kill_switch = run_data.get("killSwitch") or {}
    execution = run_data.get("execution") or {}
    chip_kb = run_data.get("chipKb") or {}

    category = _candidate_category(final_action, dvg, kill_switch, signalops)
    confidence = _candidate_confidence(qiam, dvg)
    evidence = [
        f"Run {run_id or 'UNKNOWN'}: {symbol}, task={task_type}, mode={run_mode}.",
        f"Final action={final_action}, final writer mode={final_writer.get('mode', 'UNKNOWN')}.",
        f"DVG status={dvg.get('status', 'UNKNOWN')}, reliability={dvg.get('dataReliability', 'UNKNOWN')}, hallucination risk={dvg.get('hallucinationRiskScore', 'UNKNOWN')}.",
        f"QIAM final={qiam.get('finalBuySuitability', 'UNKNOWN')}, confidence={qiam.get('modelConfidenceFinal', 'UNKNOWN')}.",
        f"SignalOps status={signalops.get('signalStatus', 'UNKNOWN')}, blocked={signalops.get('blockedReason') or 'none'}.",
        f"KillSwitch active={kill_switch.get('active', False)}, level={kill_switch.get('level', 'NONE')}.",
    ]

    guardrail_notes = _compact_notes(
        [
            *_as_list(dvg.get("criticalMissingData")),
            *_as_list(dvg.get("dataConflicts")),
            *_as_list(qiam.get("downgradeReasons")),
            *_as_list(qiam.get("missingData")),
            *_as_list(execution.get("forbiddenActions")),
            *_as_list(chip_kb.get("coreMissingData")),
        ]
    )
    if not guardrail_notes:
        guardrail_notes = ["No guardrail exception captured in this run."]

    title = f"{symbol} {final_action} learning candidate"
    thesis = (
        f"When {symbol} produced final_action={final_action} under {run_mode}, "
        f"DVG={dvg.get('status', 'UNKNOWN')} and QIAM={qiam.get('finalBuySuitability', 'UNKNOWN')} "
        "should be reviewed as a reusable decision sample before it affects future prompts."
    )
    decision_impact = (
        f"Use as a {category} reference for future similar runs; keep human review required "
        "before changing guardrail thresholds or trading permissions."
    )

    return KnowledgeItem(
        item_id=f"KB_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        status=PENDING_STATUS,
        category=category,
        source_run_id=run_id or None,
        source_audit_id=audit_id,
        source_run_verified=bool(run_id),
        title=title,
        thesis=thesis,
        evidence=evidence,
        decision_impact=decision_impact,
        guardrail_notes=guardrail_notes,
        tags=_compact_notes(
            [
                str(symbol),
                str(run_mode),
                str(final_action),
                str(dvg.get("status", "DVG_UNKNOWN")),
                str(signalops.get("signalStatus", "SIGNAL_UNKNOWN")),
                category,
            ]
        ),
        confidence=confidence,
        evidence_usage="supporting_only",
        evidence_strength=_knowledge_evidence_strength(
            evidence=evidence,
            guardrail_notes=guardrail_notes,
            status=PENDING_STATUS,
            source_run_id=run_id or None,
            source_run_verified=bool(run_id),
        ),
        simulation_only=True,
        is_real_trade=False,
        strong_conclusion_allowed=False,
        created_at=_now(),
        updated_at=_now(),
    )


def _knowledge_evidence_strength(
    *,
    evidence: list[str],
    guardrail_notes: list[str],
    status: str,
    source_run_id: str | None,
    source_run_verified: bool = False,
) -> str:
    if not evidence:
        return "MISSING"
    if status == PENDING_STATUS:
        return "PENDING"
    if status in {REJECTED_STATUS, ARCHIVED_STATUS}:
        return "LOW"
    if status == ACTIVE_STATUS and guardrail_notes and source_run_id and source_run_verified:
        return "MEDIUM"
    return "LOW"


def _apply_knowledge_boundaries(item: KnowledgeItem) -> KnowledgeItem:
    item.confidence = _supporting_confidence(item.confidence)
    item.evidence_usage = "supporting_only"
    item.evidence_strength = _knowledge_evidence_strength(
        evidence=item.evidence,
        guardrail_notes=item.guardrail_notes,
        status=item.status,
        source_run_id=item.source_run_id,
        source_run_verified=item.source_run_verified,
    )
    item.simulation_only = True
    item.is_real_trade = False
    item.strong_conclusion_allowed = False
    return item


def _candidate_category(
    final_action: str,
    dvg: dict[str, Any],
    kill_switch: dict[str, Any],
    signalops: dict[str, Any],
) -> str:
    if kill_switch.get("active") or kill_switch.get("level") in {"HARD", "COMPLIANCE"}:
        return "RISK_GUARDRAIL"
    if dvg.get("status") not in {None, "", "PASS"}:
        return "DVG_DATA_GATE"
    if signalops.get("blockedReason"):
        return "SIGNALOPS_BLOCK"
    if final_action in {"BUY_CANDIDATE", "ADD_CANDIDATE", "QUALIFIED"}:
        return "POSITIVE_SIGNAL"
    if final_action in {"WAIT", "REVIEW_ONLY", "HOLD"}:
        return "DEFENSIVE_REVIEW"
    return "RUN_REVIEW"


def _candidate_confidence(qiam: dict[str, Any], dvg: dict[str, Any]) -> str:
    confidence = qiam.get("modelConfidenceFinal")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        if confidence >= 0.75 and dvg.get("status") == "PASS":
            return "MEDIUM"
        if confidence >= 0.5:
            return "MEDIUM"
    return "LOW"


def _supporting_confidence(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return "MEDIUM" if normalized in {"HIGH", "MEDIUM"} else "LOW"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _compact_notes(values: list[str]) -> list[str]:
    seen: set[str] = set()
    notes: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        notes.append(clean)
        seen.add(clean)
    return notes
