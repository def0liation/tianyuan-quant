from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError

from sqlalchemy import select, update

from ..db.models_research import ResearchHypothesisDraftDB, ResearchLoopDB
from ..db.session import AsyncSessionLocal
from ..models.research import (
    ConfirmResearchHypothesisDraftRequest,
    CreateResearchIterationRequest,
    ResearchActionSelection,
    ResearchHypothesisDraft,
    ResearchHypothesisDraftRequest,
    ResearchHypothesisDraftResponse,
    ResearchIteration,
)
from .agent_runtime_store import get_llm_profile, get_runtime_config
from .llm_runner import (
    _call_profile_chat,
    _extract_content,
    _extract_finish_reason,
    _extract_json,
    _validate_profile,
)
from .research_store import research_loop_store


logger = logging.getLogger(__name__)


PROMPT_VERSION = "research_hypothesis_p6_v1"
ACTION_MODULES = {
    "factor": ["factor_engine", "technical_kline_analyst", "qiam"],
    "signal": ["signalops", "dvg_gate", "risk_firewall"],
    "risk_rule": ["risk_firewall", "kill_switch", "case_library"],
    "execution_rule": ["execution", "trade_micro", "signalops"],
    "data_quality_rule": ["data_reliability_engine", "guardrail_hub", "knowledge"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


class ResearchHypothesisStore:
    async def generate_draft(
        self,
        loop_id: str,
        request: ResearchHypothesisDraftRequest,
    ) -> Optional[ResearchHypothesisDraftResponse]:
        detail = await research_loop_store.get_loop_detail(loop_id)
        if detail is None:
            return None

        iteration = self._select_iteration(detail.iterations, detail.loop.current_iteration_id, request.iteration_id)
        if request.iteration_id and iteration is None:
            raise ValueError("Research iteration not found for loop")
        metrics = self._merge_metrics(iteration, request.context_metrics)
        action_selection = self.select_action_target(
            metrics,
            fallback_target=detail.loop.action_target,
        )
        drafts = self._rule_drafts(
            loop_title=detail.loop.title,
            objective=detail.loop.objective,
            iteration=iteration,
            selection=action_selection,
            max_drafts=request.max_drafts,
        )
        prompt_provenance = {
            "prompt_version": PROMPT_VERSION,
            "source": "RULE",
            "loop_id": loop_id,
            "iteration_id": iteration.iteration_id if iteration else None,
            "rule_id": action_selection.rule_id,
            "llm_requested": request.use_llm,
        }
        token_usage: Dict[str, Any] = {}
        llm_status = "NOT_REQUESTED"
        llm_error = ""

        if request.use_llm:
            llm_result = await self._generate_llm_drafts(
                request=request,
                loop_payload={
                    "loop": _model_to_dict(detail.loop),
                    "iteration": _model_to_dict(iteration) if iteration else None,
                    "metrics": metrics,
                    "action_selection": _model_to_dict(action_selection),
                    "rule_drafts": [_model_to_dict(draft) for draft in drafts],
                },
            )
            llm_status = llm_result["status"]
            llm_error = llm_result["error"]
            token_usage = llm_result["usage"]
            prompt_provenance = {**prompt_provenance, **llm_result["provenance"]}
            if llm_result["drafts"]:
                drafts = llm_result["drafts"][: request.max_drafts]

        response = ResearchHypothesisDraftResponse(
            draft_id=_generate_id("RHYP"),
            loop_id=loop_id,
            iteration_id=iteration.iteration_id if iteration else None,
            status="DRAFT_READY" if drafts else "NO_DRAFT",
            action_selection=action_selection,
            drafts=drafts,
            prompt_provenance=prompt_provenance,
            token_usage=token_usage,
            llm_status=llm_status,
            llm_error=llm_error,
            created_at=_now(),
        )
        await self._record_draft(loop_id, request, response)
        return response

    async def list_drafts(self, loop_id: str) -> Optional[list[ResearchHypothesisDraftResponse]]:
        detail = await research_loop_store.get_loop_detail(loop_id)
        if detail is None:
            return None
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ResearchHypothesisDraftDB)
                .where(ResearchHypothesisDraftDB.loop_id == loop_id)
                .order_by(ResearchHypothesisDraftDB.created_at.desc())
            )
            return [self._record_to_response(record) for record in result.scalars().all()]

    async def get_draft(self, draft_id: str) -> Optional[ResearchHypothesisDraftResponse]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ResearchHypothesisDraftDB).where(ResearchHypothesisDraftDB.draft_id == draft_id)
            )
            record = result.scalar_one_or_none()
            return self._record_to_response(record) if record else None

    async def confirm_draft(
        self,
        draft_id: str,
        request: ConfirmResearchHypothesisDraftRequest,
    ) -> Optional[ResearchIteration]:
        async with AsyncSessionLocal() as db:
            claim = await db.execute(
                update(ResearchHypothesisDraftDB)
                .where(ResearchHypothesisDraftDB.draft_id == draft_id)
                .where(ResearchHypothesisDraftDB.status == "DRAFT")
                .where(ResearchHypothesisDraftDB.confirmed_iteration_id.is_(None))
                .values(status="CONFIRMING", updated_at=_now())
            )
            await db.commit()
            if (claim.rowcount or 0) == 0:
                result = await db.execute(
                    select(ResearchHypothesisDraftDB).where(ResearchHypothesisDraftDB.draft_id == draft_id)
                )
                record = result.scalar_one_or_none()
                if not record:
                    return None
                if record.confirmed_iteration_id:
                    return await research_loop_store.get_iteration(record.confirmed_iteration_id)
                if (record.status or "").upper() == "CONFIRMING":
                    raise TimeoutError("Research hypothesis draft confirmation is already running.")
                raise ValueError(f"Research hypothesis draft cannot be confirmed from status {record.status}")

            result = await db.execute(
                select(ResearchHypothesisDraftDB).where(ResearchHypothesisDraftDB.draft_id == draft_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            drafts = [ResearchHypothesisDraft(**item) for item in (record.drafts_json or [])]
            if request.selected_index >= len(drafts):
                record.status = "DRAFT"
                record.updated_at = _now()
                await db.commit()
                raise ValueError("selected_index is out of range")
            selected = drafts[request.selected_index]
            loop_id = record.loop_id
            record_draft_id = record.draft_id
            action_selection = record.action_selection or {}
            prompt_provenance = record.prompt_provenance or {}
            token_usage = record.token_usage or {}

        try:
            iteration = await research_loop_store.create_iteration(
                loop_id,
                CreateResearchIterationRequest(
                    hypothesis=selected.hypothesis,
                    plan=selected.plan,
                    target_modules=selected.target_modules,
                    metrics={
                        "source_draft_id": record_draft_id,
                        "action_target": selected.action_target,
                        "action_selection": action_selection,
                        "prompt_provenance": prompt_provenance,
                        "token_usage": token_usage,
                        "hypothesis_draft_source": selected.source,
                        "confirmation_reviewer": request.reviewer,
                        "confirmation_note": request.note,
                        "auto_run_started": False,
                    },
                ),
            )
            if iteration is None:
                raise ValueError("research loop for draft no longer exists")
        except Exception:
            await self._reset_confirmation_status(draft_id)
            raise

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ResearchHypothesisDraftDB)
                .where(ResearchHypothesisDraftDB.draft_id == draft_id)
                .values(
                    status="CONFIRMED",
                    confirmed_iteration_id=iteration.iteration_id,
                    confirmed_at=_now(),
                    updated_at=_now(),
                )
            )
            await db.commit()
        return iteration

    def select_action_target(
        self,
        metrics: Dict[str, Any],
        fallback_target: str = "factor",
    ) -> ResearchActionSelection:
        warnings = " ".join(str(item).lower() for item in _as_list(metrics.get("quality_warnings")) + _as_list(metrics.get("warnings")))
        dvg_status = str(metrics.get("dvg_status") or metrics.get("dvg") or "").upper()
        quality_score = _metric_float(metrics, "quality_score", "evidence_quality", "coverage_score")
        data_coverage = _metric_float(metrics, "data_coverage", "source_coverage")
        missing_data_count = _metric_float(metrics, "missing_data_count", "missing_source_count")
        if (
            dvg_status in {"FAIL", "LOW", "MISSING", "PARTIAL", "BLOCKED"}
            or _lt(quality_score, 60)
            or _lt(data_coverage, 0.7)
            or _gt(missing_data_count, 0)
            or any(token in warnings for token in ("data", "dvg", "missing", "source", "coverage"))
        ):
            return ResearchActionSelection(
                target="data_quality_rule",
                rule_id="P6_DATA_QUALITY_BOTTLENECK",
                reason="DVG, evidence quality, or source coverage is the current bottleneck.",
                confidence=0.86,
                evidence=_evidence(metrics, ["dvg_status", "quality_score", "data_coverage", "missing_data_count", "quality_warnings"]),
            )

        max_drawdown = _metric_float(metrics, "max_drawdown", "drawdown", "drawdown_pct")
        false_positive_rate = _metric_float(metrics, "false_positive_rate", "false_positive_pct")
        risk_score = _metric_float(metrics, "risk_score", "risk_level_score")
        if _gt(max_drawdown, 0.08) or _gt(false_positive_rate, 0.25) or _gt(risk_score, 70):
            return ResearchActionSelection(
                target="risk_rule",
                rule_id="P6_RISK_RULE_BOTTLENECK",
                reason="Drawdown, false positives, or risk score point to risk rule refinement.",
                confidence=0.82,
                evidence=_evidence(metrics, ["max_drawdown", "false_positive_rate", "risk_score"]),
            )

        slippage = _metric_float(metrics, "slippage", "slippage_rate", "avg_slippage")
        reachability = _metric_float(metrics, "reachability", "execution_reachability", "fill_rate")
        execution_status = str(metrics.get("execution_status") or metrics.get("execution") or "").upper()
        if _gt(slippage, 0.01) or _lt(reachability, 0.8) or execution_status in {"BLOCKED", "LOW_REACH", "FAILED"}:
            return ResearchActionSelection(
                target="execution_rule",
                rule_id="P6_EXECUTION_BOTTLENECK",
                reason="Slippage or execution reachability is limiting the research result.",
                confidence=0.8,
                evidence=_evidence(metrics, ["slippage", "reachability", "fill_rate", "execution_status"]),
            )

        trigger_quality = _metric_float(metrics, "trigger_quality", "trigger_score")
        invalidation_quality = _metric_float(metrics, "invalidation_quality", "invalidation_score")
        signal_confidence = _metric_float(metrics, "signal_confidence", "signal_quality")
        if _lt(trigger_quality, 0.65) or _lt(invalidation_quality, 0.65) or _lt(signal_confidence, 0.6):
            return ResearchActionSelection(
                target="signal",
                rule_id="P6_SIGNAL_BOTTLENECK",
                reason="Signal trigger or invalidation quality is weak.",
                confidence=0.78,
                evidence=_evidence(metrics, ["trigger_quality", "invalidation_quality", "signal_confidence"]),
            )

        factor_stability = _metric_float(metrics, "factor_stability", "factor_stability_score")
        technical_quality = _metric_float(metrics, "technical_quality", "technical_score")
        factor_quality = _metric_float(metrics, "factor_quality", "factor_score")
        if _lt(factor_stability, 0.65) or _lt(technical_quality, 0.65) or _lt(factor_quality, 0.65):
            return ResearchActionSelection(
                target="factor",
                rule_id="P6_FACTOR_BOTTLENECK",
                reason="Factor stability or technical metric quality is weak.",
                confidence=0.76,
                evidence=_evidence(metrics, ["factor_stability", "technical_quality", "factor_quality"]),
            )

        target = fallback_target if fallback_target in ACTION_MODULES else "factor"
        return ResearchActionSelection(
            target=target,
            rule_id="P6_LOOP_TARGET_FALLBACK",
            reason="No stronger bottleneck was detected; continue with the loop action target.",
            confidence=0.58,
            evidence=_evidence(metrics, ["engine_verdict", "suggested_feedback_verdict", "confidence"]),
        )

    async def _generate_llm_drafts(
        self,
        request: ResearchHypothesisDraftRequest,
        loop_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        profile_id = request.llm_profile_id or get_runtime_config().default_llm_profile_id
        try:
            profile = get_llm_profile(profile_id)
        except KeyError as exc:
            return self._llm_result("SKIPPED", str(exc), profile_id=profile_id)

        validation_error = _validate_profile(profile)
        if validation_error:
            return self._llm_result(
                "SKIPPED",
                validation_error,
                profile_id=profile.id,
                provider=profile.provider,
                model=profile.model,
            )

        messages = self._llm_messages(loop_payload, request.max_drafts)
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(_call_profile_chat, profile, messages)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            return self._llm_result(
                "FAILED",
                f"LLM transport failed: {exc.__class__.__name__}",
                profile_id=profile.id,
                provider=profile.provider,
                model=profile.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            logger.warning("Research hypothesis LLM generation failed for profile %s: %s", profile.id, exc)
            return self._llm_result(
                "FAILED",
                "LLM hypothesis generation failed. Rule drafts are still available.",
                profile_id=profile.id,
                provider=profile.provider,
                model=profile.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        content = _extract_content(response)
        parsed = _extract_json(content)
        drafts = self._drafts_from_llm(parsed, loop_payload["action_selection"]["target"])
        return {
            "status": "COMPLETED" if drafts else "FAILED",
            "error": "" if drafts else "LLM response did not include valid draft hypotheses.",
            "drafts": drafts,
            "usage": response.get("usage", {}),
            "provenance": {
                "source": "LLM",
                "profile_id": profile.id,
                "provider": profile.provider,
                "model": profile.model,
                "finish_reason": _extract_finish_reason(response),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            },
        }

    def _llm_messages(self, payload: Dict[str, Any], max_drafts: int) -> list[dict[str, str]]:
        user_payload = {
            "task": "Generate draft research hypotheses only. Do not start a run or make a trade recommendation.",
            "max_drafts": max_drafts,
            "context": payload,
            "required_json": {
                "drafts": [
                    {
                        "hypothesis": "short falsifiable research hypothesis",
                        "plan": "human-reviewable experiment plan",
                        "rationale": "why this draft follows from the selected bottleneck",
                    }
                ]
            },
        }
        return [
            {
                "role": "system",
                "content": "You generate draft research hypotheses for a guarded stock-analysis research lab. Drafts require human confirmation and must not trigger execution.",
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
        ]

    def _drafts_from_llm(self, parsed: Any, target: str) -> list[ResearchHypothesisDraft]:
        if not isinstance(parsed, dict):
            return []
        raw_drafts = parsed.get("drafts")
        if not isinstance(raw_drafts, list):
            return []
        drafts: list[ResearchHypothesisDraft] = []
        for item in raw_drafts:
            if not isinstance(item, dict):
                continue
            hypothesis = str(item.get("hypothesis") or "").strip()
            if not hypothesis:
                continue
            drafts.append(
                ResearchHypothesisDraft(
                    hypothesis=hypothesis,
                    plan=str(item.get("plan") or "").strip(),
                    action_target=target,
                    target_modules=ACTION_MODULES.get(target, ACTION_MODULES["factor"]),
                    rationale=str(item.get("rationale") or "").strip(),
                    source="LLM",
                )
            )
        return drafts

    def _llm_result(
        self,
        status: str,
        error: str,
        profile_id: str = "",
        provider: str = "",
        model: str = "",
        latency_ms: int = 0,
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "error": error,
            "drafts": [],
            "usage": {},
            "provenance": {
                "source": "LLM",
                "profile_id": profile_id,
                "provider": provider,
                "model": model,
                "latency_ms": latency_ms,
            },
        }

    def _rule_drafts(
        self,
        loop_title: str,
        objective: str,
        iteration: Optional[ResearchIteration],
        selection: ResearchActionSelection,
        max_drafts: int,
    ) -> list[ResearchHypothesisDraft]:
        prior = iteration.hypothesis if iteration else objective
        templates = {
            "data_quality_rule": [
                (
                    "If missing data sources are gated before analysis, the research verdict quality will improve without increasing false positives.",
                    "Run the same hypothesis with required DVG/data-source coverage checks, then compare evidence quality, missing-data warnings, and final verdict stability.",
                ),
                (
                    "If low-quality evidence is blocked from feedback, accepted knowledge candidates will contain fewer unsupported lessons.",
                    "Materialize only after evidence quality reaches the configured threshold, then review rejected versus accepted knowledge candidates.",
                ),
            ],
            "risk_rule": [
                (
                    "If drawdown and false-positive caps are tightened before signal promotion, rejected iterations will fall without suppressing valid WAIT decisions.",
                    "Compare baseline and candidate runs on drawdown, false-positive rate, QIAM confidence, and risk firewall downgrade reasons.",
                ),
                (
                    "If risk-rule thresholds are conditioned on recent volatility, high-risk research loops will produce more actionable patch candidates.",
                    "Evaluate volatility-conditioned risk rules against case-library failures and sandbox evaluation pass rate.",
                ),
            ],
            "execution_rule": [
                (
                    "If execution reachability is required before signal qualification, simulated slippage regressions will decrease.",
                    "Compare execution node reachability, slippage, fill rate, and SignalOps paper-order outcomes before and after the rule change.",
                ),
                (
                    "If order sizing is constrained by available cash and board-lot reachability, execution failures will become reviewable instead of silent.",
                    "Run sandbox evaluation on candidate sizing constraints and review error-ledger entries for execution blockers.",
                ),
            ],
            "signal": [
                (
                    "If triggers and invalidation rules are scored separately, weak signals will stay in WATCH instead of becoming patch candidates.",
                    "Compare trigger quality, invalidation quality, signal confidence, and downstream verdict changes across recent runs.",
                ),
                (
                    "If signal promotion requires both trigger quality and DVG pass status, false positives will decrease.",
                    "Replay recent SignalOps cases with the combined gate and review false-positive rate plus accepted feedback count.",
                ),
            ],
            "factor": [
                (
                    "If factor stability is combined with technical confirmation, factor-driven iterations will produce more stable verdicts.",
                    "Compare factor stability, technical quality, MA confirmation, and verdict confidence before and after the candidate factor gate.",
                ),
                (
                    "If unstable factor slices are routed to WAIT until technical quality improves, patch-required feedback should decrease.",
                    "Review factor slices with low stability and compare patch-required rate against accepted iterations.",
                ),
            ],
        }
        target_templates = templates.get(selection.target, templates["factor"])
        drafts = []
        for hypothesis, plan in target_templates:
            drafts.append(
                ResearchHypothesisDraft(
                    hypothesis=f"{hypothesis} Context: {prior[:160]}",
                    plan=plan,
                    action_target=selection.target,
                    target_modules=ACTION_MODULES.get(selection.target, ACTION_MODULES["factor"]),
                    rationale=f"{selection.reason} Source loop: {loop_title}.",
                    source="RULE",
                )
            )
        return drafts[:max_drafts]

    def _select_iteration(
        self,
        iterations: list[ResearchIteration],
        current_iteration_id: Optional[str],
        requested_iteration_id: Optional[str],
    ) -> Optional[ResearchIteration]:
        if requested_iteration_id:
            return next((item for item in iterations if item.iteration_id == requested_iteration_id), None)
        if current_iteration_id:
            current = next((item for item in iterations if item.iteration_id == current_iteration_id), None)
            if current:
                return current
        return iterations[-1] if iterations else None

    def _merge_metrics(
        self,
        iteration: Optional[ResearchIteration],
        context_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        if iteration:
            metrics.update(_flatten_metric_payload(iteration.metrics or {}))
            metrics.update(iteration.metrics or {})
            metrics["iteration_verdict"] = iteration.verdict
            metrics["iteration_status"] = iteration.status
        if context_metrics:
            flattened = _flatten_metric_payload(context_metrics)
            metrics.update(flattened)
            metrics.update(context_metrics)
            _merge_list_metric(metrics, "quality_warnings", flattened.get("quality_warnings"))
            _merge_list_metric(metrics, "warnings", flattened.get("warnings"))
            _merge_list_metric(metrics, "blocking_reasons", flattened.get("blocking_reasons"))
        return metrics

    async def _reset_confirmation_status(self, draft_id: str) -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ResearchHypothesisDraftDB)
                .where(ResearchHypothesisDraftDB.draft_id == draft_id)
                .where(ResearchHypothesisDraftDB.status == "CONFIRMING")
                .values(status="DRAFT", updated_at=_now())
            )
            await db.commit()

    async def _record_draft(
        self,
        loop_id: str,
        request: ResearchHypothesisDraftRequest,
        response: ResearchHypothesisDraftResponse,
    ) -> None:
        async with AsyncSessionLocal() as db:
            record = ResearchHypothesisDraftDB(
                draft_id=response.draft_id,
                loop_id=loop_id,
                source_iteration_id=response.iteration_id,
                status="DRAFT",
                selected_action_target=response.action_selection.target,
                action_selection=_model_to_dict(response.action_selection),
                drafts_json=[_model_to_dict(draft) for draft in response.drafts],
                request_json=_model_to_dict(request),
                prompt_provenance=response.prompt_provenance,
                token_usage=response.token_usage,
                llm_status=response.llm_status,
                llm_error=response.llm_error,
                created_at=response.created_at,
                updated_at=response.created_at,
            )
            db.add(record)
            loop_result = await db.execute(select(ResearchLoopDB).where(ResearchLoopDB.loop_id == loop_id))
            loop = loop_result.scalar_one_or_none()
            if loop:
                loop.updated_at = response.created_at
            await db.commit()

    def _record_to_response(self, record: ResearchHypothesisDraftDB) -> ResearchHypothesisDraftResponse:
        return ResearchHypothesisDraftResponse(
            draft_id=record.draft_id,
            loop_id=record.loop_id,
            iteration_id=record.source_iteration_id,
            status=record.status or "DRAFT",
            action_selection=ResearchActionSelection(**(record.action_selection or {})),
            drafts=[ResearchHypothesisDraft(**item) for item in (record.drafts_json or [])],
            prompt_provenance=record.prompt_provenance or {},
            token_usage=record.token_usage or {},
            llm_status=record.llm_status or "NOT_REQUESTED",
            llm_error=record.llm_error or "",
            confirmation_required=record.status != "CONFIRMED",
            auto_run_started=False,
            confirmed_iteration_id=record.confirmed_iteration_id,
            created_at=record.created_at,
        )


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _flatten_metric_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    flattened: Dict[str, Any] = {}
    for key in ("baseline", "current", "metrics", "current_metrics"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            for nested_key, nested_value in nested.items():
                if nested_value not in (None, "", [], {}):
                    flattened[nested_key] = nested_value

    comparison = payload.get("comparison")
    if isinstance(comparison, list):
        comparison_warnings: list[Any] = []
        for row in comparison:
            if not isinstance(row, dict):
                continue
            row_key = str(row.get("key") or "").strip()
            if row_key and row_key not in flattened:
                for value_key in ("current", "delta", "baseline"):
                    value = row.get(value_key)
                    if value not in (None, "", [], {}):
                        flattened[row_key] = value
                        break
            warning = row.get("warning")
            if warning not in (None, "", [], {}):
                comparison_warnings.extend(_as_list(warning))
        if comparison_warnings:
            flattened["quality_warnings"] = comparison_warnings

    for key in ("quality_warnings", "warnings", "blocking_reasons"):
        if payload.get(key) not in (None, "", [], {}):
            _merge_list_metric(flattened, key, payload.get(key))
    return flattened


def _merge_list_metric(metrics: Dict[str, Any], key: str, value: Any) -> None:
    next_values = _as_list(value)
    if not next_values:
        return
    merged = []
    for item in _as_list(metrics.get(key)) + next_values:
        if item in (None, ""):
            continue
        text = str(item)
        if text not in merged:
            merged.append(text)
    metrics[key] = merged


def _model_to_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _metric_float(metrics: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = metrics.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, str):
            cleaned = value.strip().replace("%", "")
            try:
                number = float(cleaned)
            except ValueError:
                continue
            return number / 100 if "%" in value and abs(number) > 1 else number
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _lt(value: Optional[float], threshold: float) -> bool:
    return value is not None and value < threshold


def _gt(value: Optional[float], threshold: float) -> bool:
    return value is not None and value > threshold


def _evidence(metrics: Dict[str, Any], keys: list[str]) -> list[str]:
    evidence = []
    for key in keys:
        value = metrics.get(key)
        if value not in (None, "", [], {}):
            evidence.append(f"{key}={value}")
    return evidence


research_hypothesis_store = ResearchHypothesisStore()
