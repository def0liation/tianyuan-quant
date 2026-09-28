import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from ..core.agent_runtime_store import load_persisted_runs
from ..core.analysis_run_registry import get_run
from ..db.models_research import ResearchArtifactMaterializationDB
from ..db.session import AsyncSessionLocal
from ..models.case_library import CaseLibraryItem, ErrorLedgerItem, KnowledgePatchItem
from ..models.evaluation import EvaluationRunItem
from ..models.knowledge import CreateKnowledgeItemRequest, KnowledgeItem
from ..models.research import (
    ResearchArtifactMaterializeRequest,
    ResearchArtifactMaterializeResult,
    ResearchEvidenceLink,
    ResearchIteration,
    ResearchIterationFeedbackRequest,
    ResearchLoop,
)
from .case_library_store import case_library_store, error_ledger_store, knowledge_patch_store
from .evaluation_store import evaluation_sandbox_store
from .knowledge_store import create_knowledge_item, list_knowledge_items
from .research_store import research_loop_store
from .research_verdict_store import research_verdict_store


RESERVED_PATCH_CONTENT_KEYS = {
    "research_loop_id",
    "research_iteration_id",
    "engine_verdict",
    "feedback_verdict",
    "metrics",
    "evidence",
}
MATERIALIZATION_LEASE_TIMEOUT_SECONDS = 300
MATERIALIZATION_WAIT_TIMEOUT_SECONDS = 30
MATERIALIZATION_WAIT_INTERVAL_SECONDS = 0.05


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_like_legacy_mock_run(run_id: str, run: dict[str, Any]) -> bool:
    if str(run_id).startswith(("RUN_HISTORY_", "RUN_MOCK_")):
        return True
    if str(run.get("runId", "")).startswith(("RUN_HISTORY_", "RUN_MOCK_")):
        return True
    if str(run.get("auditId", "")).startswith(("AUD_RUN_MOCK", "AUD_MOCK")):
        return True
    final_writer = run.get("finalWriter") or {}
    if isinstance(final_writer, dict) and str(final_writer.get("auditId", "")).startswith("AUD_FW_MOCK"):
        return True
    for event in run.get("auditLog") or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("runId", "")).startswith("RUN_MOCK_"):
            return True
        if str(event.get("auditId", "")).startswith(("AUD_MOCK", "AUD_NORMAL", "AUD_DISCOUNT")):
            return True
    return False


class ResearchArtifactStore:
    def __init__(self) -> None:
        self._iteration_locks: dict[str, asyncio.Lock] = {}

    async def materialize_iteration_artifacts(
        self,
        iteration_id: str,
        request: ResearchArtifactMaterializeRequest,
    ) -> Optional[ResearchArtifactMaterializeResult]:
        async with self._lock_for_iteration(iteration_id):
            if await research_loop_store.get_iteration(iteration_id) is None:
                return None
            owner_token = await self._acquire_persistent_materialization_lease(iteration_id, request)
            try:
                result = await self._materialize_iteration_artifacts_locked(iteration_id, request)
            except Exception as exc:
                await self._finish_persistent_materialization_lease(
                    iteration_id,
                    owner_token,
                    "FAILED",
                    error=str(exc),
                )
                raise

            artifact_links = {}
            if result and isinstance(result.iteration.metrics.get("artifact_links"), dict):
                artifact_links = result.iteration.metrics["artifact_links"]
            await self._finish_persistent_materialization_lease(
                iteration_id,
                owner_token,
                "COMPLETED",
                artifact_links=artifact_links,
            )
            return result

    def _lock_for_iteration(self, iteration_id: str) -> asyncio.Lock:
        lock = self._iteration_locks.get(iteration_id)
        if lock is None:
            lock = asyncio.Lock()
            self._iteration_locks[iteration_id] = lock
        return lock

    async def _acquire_persistent_materialization_lease(
        self,
        iteration_id: str,
        request: ResearchArtifactMaterializeRequest,
    ) -> str:
        owner_token = uuid.uuid4().hex
        deadline = datetime.now(timezone.utc) + timedelta(seconds=MATERIALIZATION_WAIT_TIMEOUT_SECONDS)
        request_json = request.model_dump(mode="json")

        while True:
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            stale_before = (now_dt - timedelta(seconds=MATERIALIZATION_LEASE_TIMEOUT_SECONDS)).isoformat()

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    update(ResearchArtifactMaterializationDB)
                    .where(ResearchArtifactMaterializationDB.iteration_id == iteration_id)
                    .where(
                        or_(
                            ResearchArtifactMaterializationDB.status != "RUNNING",
                            ResearchArtifactMaterializationDB.updated_at < stale_before,
                        )
                    )
                    .values(
                        status="RUNNING",
                        owner_token=owner_token,
                        request_json=request_json,
                        error="",
                        started_at=now,
                        updated_at=now,
                        completed_at=None,
                    )
                )
                if result.rowcount:
                    await db.commit()
                    return owner_token

                existing = await db.execute(
                    select(ResearchArtifactMaterializationDB).where(
                        ResearchArtifactMaterializationDB.iteration_id == iteration_id
                    )
                )
                if existing.scalar_one_or_none() is None:
                    db.add(
                        ResearchArtifactMaterializationDB(
                            iteration_id=iteration_id,
                            status="RUNNING",
                            owner_token=owner_token,
                            request_json=request_json,
                            artifact_links={},
                            error="",
                            started_at=now,
                            updated_at=now,
                        )
                    )
                    try:
                        await db.commit()
                        return owner_token
                    except IntegrityError:
                        await db.rollback()

            if datetime.now(timezone.utc) >= deadline:
                raise TimeoutError(f"Research artifact materialization is already running for {iteration_id}")
            await asyncio.sleep(MATERIALIZATION_WAIT_INTERVAL_SECONDS)

    async def _finish_persistent_materialization_lease(
        self,
        iteration_id: str,
        owner_token: str,
        status: str,
        *,
        artifact_links: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        now = _now()
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ResearchArtifactMaterializationDB)
                .where(ResearchArtifactMaterializationDB.iteration_id == iteration_id)
                .where(ResearchArtifactMaterializationDB.owner_token == owner_token)
                .values(
                    status=status,
                    owner_token="",
                    artifact_links=artifact_links or {},
                    error=error,
                    updated_at=now,
                    completed_at=now,
                )
            )
            await db.commit()

    async def _materialize_iteration_artifacts_locked(
        self,
        iteration_id: str,
        request: ResearchArtifactMaterializeRequest,
    ) -> Optional[ResearchArtifactMaterializeResult]:
        iteration = await research_loop_store.get_iteration(iteration_id)
        if iteration is None:
            return None
        detail = await research_loop_store.get_loop_detail(iteration.loop_id)
        loop = detail.loop if detail else None
        verdict_inputs = await research_verdict_store.get_inputs(iteration_id)
        warnings: list[str] = []

        metrics = dict(iteration.metrics or {})
        artifact_links = dict(metrics.get("artifact_links") if isinstance(metrics.get("artifact_links"), dict) else {})
        original_artifact_links = dict(artifact_links)

        run_data = self._get_run(iteration.linked_run_id)
        if not run_data and self._requires_canonical_run(request):
            warning = (
                "linked_run_missing_or_legacy_artifacts_blocked"
                if iteration.linked_run_id
                else "linked_run_required_artifacts_blocked"
            )
            warnings.append(warning)
            return ResearchArtifactMaterializeResult(
                iteration=iteration,
                provenance_chain=self._provenance_chain(iteration, artifact_links),
                warnings=warnings,
            )
        run_data = run_data or self._fallback_run(iteration, loop)

        case_model: CaseLibraryItem | None = None
        knowledge_model: KnowledgeItem | None = None
        error_model: ErrorLedgerItem | None = None
        patch_model: KnowledgePatchItem | None = None
        evaluation_model: EvaluationRunItem | None = None

        if request.create_case:
            case_model = await self._materialize_case(iteration, loop, run_data, request, warnings)
            if case_model:
                artifact_links["case_id"] = case_model.case_id

        if request.create_knowledge_item:
            knowledge_model = self._materialize_knowledge(iteration, loop, run_data, verdict_inputs, request, warnings)
            if knowledge_model:
                artifact_links["knowledge_item_id"] = knowledge_model.item_id

        if request.create_error_entry and self._should_create_error(iteration, verdict_inputs, request):
            error_model = await self._materialize_error(iteration, loop, run_data, verdict_inputs, artifact_links, request, warnings)
            if error_model:
                artifact_links["error_entry_id"] = error_model.entry_id

        should_create_patch = self._should_create_patch(iteration, verdict_inputs, request)
        existing_patch_id = iteration.linked_patch_id or artifact_links.get("patch_id")
        if request.create_patch and should_create_patch:
            patch_model = await self._materialize_patch(iteration, loop, verdict_inputs, artifact_links, request, warnings)
            if patch_model:
                artifact_links["patch_id"] = patch_model.patch_id
        elif request.create_patch and existing_patch_id and not request.force:
            patch_model = await self._get_patch(str(existing_patch_id))
            if patch_model:
                artifact_links["patch_id"] = patch_model.patch_id
            else:
                warnings.append("linked_patch_missing_verdict_not_actionable")
        elif request.create_patch and request.patch_content:
            warnings.append("patch_skipped_verdict_not_actionable")

        if request.run_evaluation:
            patch_id = patch_model.patch_id if patch_model else iteration.linked_patch_id or artifact_links.get("patch_id")
            if patch_id:
                evaluation = await evaluation_sandbox_store.run_evaluation(patch_id, force=request.force)
                evaluation_model = EvaluationRunItem(**evaluation)
                artifact_links["evaluation_id"] = evaluation_model.eval_id
            else:
                warnings.append("evaluation_skipped_no_patch")

        feedback_metrics = {
            "artifact_links": artifact_links,
            "materialized_at": _now(),
        }
        evidence_links = self._artifact_evidence_links(
            case_model=case_model,
            knowledge_model=knowledge_model,
            error_model=error_model,
            patch_model=patch_model,
            evaluation_model=evaluation_model,
        )
        links_changed = artifact_links != original_artifact_links
        missing_evidence = self._has_missing_evidence_links(iteration, evidence_links)
        should_record_feedback = request.force or links_changed or missing_evidence
        if should_record_feedback:
            updated_iteration = await research_loop_store.record_feedback(
                iteration.iteration_id,
                ResearchIterationFeedbackRequest(
                    action="MATERIALIZE_ARTIFACTS",
                    verdict=iteration.verdict,
                    status=iteration.status,
                    note=request.note or "Research Lab P5 artifacts materialized.",
                    reviewer=request.reviewer,
                    linked_run_id=iteration.linked_run_id,
                    linked_case_id=case_model.case_id if case_model else iteration.linked_case_id,
                    linked_knowledge_item_id=knowledge_model.item_id if knowledge_model else iteration.linked_knowledge_item_id,
                    linked_patch_id=patch_model.patch_id if patch_model else iteration.linked_patch_id,
                    metrics=feedback_metrics,
                    evidence_links=evidence_links,
                ),
            )
        else:
            updated_iteration = iteration

        return ResearchArtifactMaterializeResult(
            iteration=updated_iteration or iteration,
            case=case_model,
            knowledge_item=knowledge_model,
            error_entry=error_model,
            patch=patch_model,
            evaluation=evaluation_model,
            provenance_chain=self._provenance_chain(updated_iteration or iteration, artifact_links),
            warnings=warnings,
        )

    async def _materialize_case(
        self,
        iteration: ResearchIteration,
        loop: ResearchLoop | None,
        run_data: dict[str, Any],
        request: ResearchArtifactMaterializeRequest,
        warnings: list[str],
    ) -> CaseLibraryItem | None:
        if iteration.linked_case_id and not request.force:
            existing = await case_library_store.get_case(iteration.linked_case_id)
            if existing:
                return CaseLibraryItem(**existing)
            warnings.append("linked_case_missing_recreating")

        if not request.force:
            existing = await case_library_store.find_case_by_tag(f"iteration:{iteration.iteration_id}")
            if existing:
                return CaseLibraryItem(**existing)

        case_record = await case_library_store.create_case(run_data, reviewer=request.reviewer)
        case_data = case_library_store._case_to_dict(case_record)
        tags = _dedupe([
            *(case_data.get("tags") or []),
            "research_lab",
            f"loop:{iteration.loop_id}",
            f"iteration:{iteration.iteration_id}",
            *(iteration.target_modules or []),
        ])
        reviewed = await case_library_store.update_case_review(
            case_data["case_id"],
            {
                "key_lessons": _dedupe([iteration.hypothesis, request.note]),
                "market_context": f"Research loop: {loop.title if loop else iteration.loop_id}",
                "tags": tags,
                "reviewer": request.reviewer,
                "review_note": request.note or "Created from Research Lab iteration.",
                "review_status": "PENDING",
            },
        )
        return CaseLibraryItem(**(reviewed or case_data))

    def _materialize_knowledge(
        self,
        iteration: ResearchIteration,
        loop: ResearchLoop | None,
        run_data: dict[str, Any],
        verdict_inputs: Any,
        request: ResearchArtifactMaterializeRequest,
        warnings: list[str],
    ) -> KnowledgeItem | None:
        if iteration.linked_knowledge_item_id and not request.force:
            existing = self._find_knowledge(iteration.linked_knowledge_item_id, iteration.iteration_id)
            if existing:
                return existing
            warnings.append("linked_knowledge_missing_recreating")

        if not request.force:
            existing = self._find_knowledge(None, iteration.iteration_id)
            if existing:
                return existing

        evidence = [
            f"Research loop={iteration.loop_id}, iteration={iteration.iteration_id}.",
            f"Hypothesis: {iteration.hypothesis}",
            f"Verdict: {iteration.verdict}.",
        ]
        if iteration.linked_run_id:
            evidence.append(f"Linked run: {iteration.linked_run_id}.")
        if verdict_inputs:
            evidence.extend([
                f"Engine verdict={verdict_inputs.engine_verdict}, confidence={round(verdict_inputs.confidence, 3)}.",
                *[
                    f"{item.source_type}:{item.source_id} quality={item.quality}; {item.summary}"
                    for item in verdict_inputs.evidence[:5]
                ],
            ])

        item = create_knowledge_item(
            CreateKnowledgeItemRequest(
                category="RESEARCH_FEEDBACK",
                source_run_id=iteration.linked_run_id,
                source_audit_id=run_data.get("auditId") or run_data.get("audit_id"),
                title=f"{run_data.get('stockCode', 'RESEARCH')} research learning candidate",
                thesis=iteration.hypothesis,
                evidence=_dedupe(evidence),
                decision_impact="Use only after human review; preserve Research Lab provenance before changing guardrails or prompts.",
                guardrail_notes=_dedupe([
                    *(verdict_inputs.blocking_reasons if verdict_inputs else []),
                    *(verdict_inputs.quality_warnings if verdict_inputs else []),
                ]) or ["No blocking guardrail warning captured during materialization."],
                tags=_dedupe([
                    "research_lab",
                    f"loop:{iteration.loop_id}",
                    f"iteration:{iteration.iteration_id}",
                    str(run_data.get("stockCode") or "UNKNOWN"),
                    iteration.verdict,
                    *(iteration.target_modules or []),
                ]),
                confidence=self._knowledge_confidence(verdict_inputs),
            )
        )
        return item

    async def _materialize_error(
        self,
        iteration: ResearchIteration,
        loop: ResearchLoop | None,
        run_data: dict[str, Any],
        verdict_inputs: Any,
        artifact_links: dict[str, Any],
        request: ResearchArtifactMaterializeRequest,
        warnings: list[str],
    ) -> ErrorLedgerItem | None:
        existing_id = artifact_links.get("error_entry_id")
        if existing_id and not request.force:
            existing = await self._get_error_entry(str(existing_id))
            if existing:
                return existing
            warnings.append("linked_error_entry_missing_recreating")

        if not request.force:
            existing = await error_ledger_store.find_entry_by_research_iteration(iteration.iteration_id)
            if existing:
                return ErrorLedgerItem(**existing)

        engine_verdict = verdict_inputs.engine_verdict if verdict_inputs else iteration.verdict
        reasons = _dedupe([
            request.note,
            *(verdict_inputs.blocking_reasons if verdict_inputs else []),
            *(verdict_inputs.quality_warnings if verdict_inputs else []),
            iteration.hypothesis,
        ])
        entry = await error_ledger_store.create_entry(
            run_data,
            {
                "node": ",".join(iteration.target_modules[:3]) if iteration.target_modules else "research_lab",
                "error_type": f"RESEARCH_{engine_verdict}",
                "error_reason": "; ".join(reasons[:4]),
                "repeated_count": 1,
                "patch_required": True,
                "attribution": {
                    "source": "research_lab",
                    "loop_id": iteration.loop_id,
                    "iteration_id": iteration.iteration_id,
                    "loop_title": loop.title if loop else "",
                    "linked_run_id": iteration.linked_run_id,
                    "engine_verdict": engine_verdict,
                },
            },
        )
        return ErrorLedgerItem(**error_ledger_store._entry_to_dict(entry))

    async def _materialize_patch(
        self,
        iteration: ResearchIteration,
        loop: ResearchLoop | None,
        verdict_inputs: Any,
        artifact_links: dict[str, Any],
        request: ResearchArtifactMaterializeRequest,
        warnings: list[str],
    ) -> KnowledgePatchItem | None:
        patch_id = iteration.linked_patch_id or artifact_links.get("patch_id")
        if patch_id and not request.force:
            existing = await self._get_patch(str(patch_id))
            if existing:
                return existing
            warnings.append("linked_patch_missing_recreating")

        if not request.force:
            existing = await knowledge_patch_store.find_patch_by_research_iteration(iteration.iteration_id)
            if existing:
                return KnowledgePatchItem(**existing)

        engine_verdict = verdict_inputs.engine_verdict if verdict_inputs else iteration.verdict
        user_patch_content = dict(request.patch_content or {})
        ignored_keys = sorted(set(user_patch_content) & RESERVED_PATCH_CONTENT_KEYS)
        for key in ignored_keys:
            user_patch_content.pop(key, None)
        if ignored_keys:
            warnings.append(f"patch_content_reserved_keys_ignored:{','.join(ignored_keys)}")
        patch_content = {
            **user_patch_content,
            "research_loop_id": iteration.loop_id,
            "research_iteration_id": iteration.iteration_id,
            "engine_verdict": engine_verdict,
            "feedback_verdict": iteration.verdict,
            "metrics": verdict_inputs.metrics if verdict_inputs else iteration.metrics,
            "evidence": [item.model_dump() for item in verdict_inputs.evidence] if verdict_inputs else [],
        }
        patch = await knowledge_patch_store.create_patch(
            title=f"Research patch: {iteration.hypothesis[:120]}",
            reason=request.note or self._patch_reason(iteration, verdict_inputs),
            affected_modules=iteration.target_modules or ([loop.action_target] if loop else []),
            patch_content=patch_content,
            source_error_id=artifact_links.get("error_entry_id"),
            source_case_id=artifact_links.get("case_id") or iteration.linked_case_id,
        )
        return KnowledgePatchItem(**knowledge_patch_store._patch_to_dict(patch))

    def _should_create_error(self, iteration: ResearchIteration, verdict_inputs: Any, request: ResearchArtifactMaterializeRequest) -> bool:
        if request.force:
            return True
        verdicts = {
            str(iteration.verdict or "").upper(),
            str(verdict_inputs.engine_verdict if verdict_inputs else "").upper(),
            str(verdict_inputs.suggested_feedback_verdict if verdict_inputs else "").upper(),
        }
        return bool(verdicts & {"REJECTED", "REJECT", "REGRESSED", "PATCH_REQUIRED", "GUARDRAIL_BLOCKED"})

    def _should_create_patch(self, iteration: ResearchIteration, verdict_inputs: Any, request: ResearchArtifactMaterializeRequest) -> bool:
        if request.force:
            return True
        verdicts = {
            str(iteration.verdict or "").upper(),
            str(verdict_inputs.engine_verdict if verdict_inputs else "").upper(),
            str(verdict_inputs.suggested_feedback_verdict if verdict_inputs else "").upper(),
        }
        return bool(verdicts & {"ACCEPTED", "ACCEPT", "REGRESSED", "PATCH_REQUIRED", "GUARDRAIL_BLOCKED"})

    def _knowledge_confidence(self, verdict_inputs: Any) -> str:
        if not verdict_inputs:
            return "MEDIUM"
        if verdict_inputs.confidence >= 0.45:
            return "MEDIUM"
        return "LOW"

    def _patch_reason(self, iteration: ResearchIteration, verdict_inputs: Any) -> str:
        if verdict_inputs:
            reasons = _dedupe([*verdict_inputs.blocking_reasons, *verdict_inputs.quality_warnings])
            if reasons:
                return "; ".join(reasons[:3])
            return f"Research verdict {verdict_inputs.engine_verdict} requires a patch candidate."
        return f"Research iteration verdict {iteration.verdict} requires a patch candidate."

    def _requires_canonical_run(self, request: ResearchArtifactMaterializeRequest) -> bool:
        return any(
            [
                request.create_case,
                request.create_knowledge_item,
                request.create_error_entry,
                request.create_patch,
                request.run_evaluation,
            ]
        )

    def _find_knowledge(self, item_id: str | None, iteration_id: str) -> KnowledgeItem | None:
        for item in list_knowledge_items():
            if item_id and item.item_id == item_id:
                return item
            if f"iteration:{iteration_id}" in item.tags:
                return item
        return None

    async def _get_error_entry(self, entry_id: str) -> ErrorLedgerItem | None:
        existing = await error_ledger_store.get_entry(entry_id)
        return ErrorLedgerItem(**existing) if existing else None

    async def _get_patch(self, patch_id: str) -> KnowledgePatchItem | None:
        existing = await knowledge_patch_store.get_patch(patch_id)
        return KnowledgePatchItem(**existing) if existing else None

    def _has_missing_evidence_links(
        self,
        iteration: ResearchIteration,
        evidence_links: list[ResearchEvidenceLink],
    ) -> bool:
        existing = {
            (item.source_type.upper(), item.source_id)
            for item in iteration.evidence_links
        }
        return any((item.source_type.upper(), item.source_id) not in existing for item in evidence_links)

    def _artifact_evidence_links(
        self,
        *,
        case_model: CaseLibraryItem | None,
        knowledge_model: KnowledgeItem | None,
        error_model: ErrorLedgerItem | None,
        patch_model: KnowledgePatchItem | None,
        evaluation_model: EvaluationRunItem | None,
    ) -> list[ResearchEvidenceLink]:
        links: list[ResearchEvidenceLink] = []
        if case_model:
            links.append(_evidence_link("CASE", case_model.case_id, "Materialized case", "MEDIUM"))
        if knowledge_model:
            links.append(_evidence_link("KNOWLEDGE", knowledge_model.item_id, "Materialized knowledge candidate", knowledge_model.confidence))
        if error_model:
            links.append(_evidence_link("ERROR_LEDGER", error_model.entry_id, "Materialized error ledger entry", "MEDIUM"))
        if patch_model:
            links.append(_evidence_link("PATCH", patch_model.patch_id, "Materialized patch candidate", "MEDIUM"))
        if evaluation_model:
            links.append(_evidence_link("EVALUATION", evaluation_model.eval_id, "Materialized patch evaluation", "MEDIUM"))
        return links

    def _provenance_chain(self, iteration: ResearchIteration, artifact_links: dict[str, Any]) -> list[str]:
        chain = [f"loop:{iteration.loop_id}", f"iteration:{iteration.iteration_id}"]
        if iteration.linked_run_id:
            chain.append(f"run:{iteration.linked_run_id}")
        for key in ("case_id", "knowledge_item_id", "error_entry_id", "patch_id", "evaluation_id"):
            value = artifact_links.get(key)
            if value:
                chain.append(f"{key}:{value}")
        return chain

    def _get_run(self, run_id: Optional[str]) -> Optional[dict[str, Any]]:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return None
        try:
            run = get_run(normalized_run_id)
            if run:
                return run
        except Exception:
            pass
        run = load_persisted_runs().get(normalized_run_id)
        if not isinstance(run, dict):
            return None
        if _looks_like_legacy_mock_run(normalized_run_id, run):
            return None
        return run

    def _fallback_run(self, iteration: ResearchIteration, loop: ResearchLoop | None) -> dict[str, Any]:
        return {
            "runId": iteration.linked_run_id or iteration.iteration_id,
            "auditId": f"AUD_{iteration.iteration_id}",
            "stockCode": "RESEARCH",
            "stockName": loop.title if loop else "Research Lab",
            "taskType": loop.action_target if loop else "research",
            "runMode": "RESEARCH_LAB",
            "finalAction": iteration.verdict or "PENDING",
        }


def _evidence_link(source_type: str, source_id: str, label: str, quality: str) -> ResearchEvidenceLink:
    raw_quality = str(quality or "").strip().upper()
    review_quality = _review_gate_quality(raw_quality)
    reported_quality = raw_quality if raw_quality and raw_quality != review_quality else None
    return ResearchEvidenceLink(
        source_type=source_type,
        source_id=source_id,
        label=label,
        quality=review_quality,
        reported_quality=reported_quality,
        created_at=_now(),
    )


def _review_gate_quality(quality: str) -> str:
    normalized = str(quality or "").upper()
    if normalized in {
        "HIGH",
        "PASS",
        "READY",
        "STRONG",
        "PRIMARY",
        "PRIMARY_EVIDENCE",
        "PRIMARY_EVIDENCE_READY",
        "RESEARCH_GRADE",
    }:
        return "MEDIUM"
    if normalized in {"SUPPORTING_ONLY", "WARN", "REVIEW", "REVIEW_ONLY"}:
        return "LOW"
    if normalized in {"FAIL", "FAILED", "BLOCKED"}:
        return "MISSING"
    if normalized in {"MEDIUM", "LOW", "MISSING", "PENDING", "UNKNOWN"}:
        return normalized
    return "UNKNOWN"


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


research_artifact_store = ResearchArtifactStore()
