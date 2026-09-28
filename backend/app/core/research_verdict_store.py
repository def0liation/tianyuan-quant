from datetime import datetime, timezone
from typing import Any, Optional

from ..core.agent_runtime_store import load_persisted_runs
from . import analysis_lifecycle_service
from ..core.analysis_run_registry import get_run
from ..core.backtest_store import backtest_store
from ..core.case_library_store import case_library_store, knowledge_patch_store
from ..core.data_pipeline import summarize_run
from ..core.evaluation_store import evaluation_sandbox_store
from ..core.knowledge_store import list_knowledge_items
from ..core.research_store import research_loop_store
from ..models.research import (
    ResearchEvidenceLink,
    ResearchIterationFeedbackRequest,
    ResearchMetricComparisonRow,
    ResearchVerdictEvidence,
    ResearchVerdictInputs,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchVerdictStore:
    async def get_inputs(
        self,
        iteration_id: str,
        *,
        baseline_run_id: Optional[str] = None,
        candidate_run_id: Optional[str] = None,
    ) -> Optional[ResearchVerdictInputs]:
        iterations = await research_loop_store.list_iterations()
        iteration = next((item for item in iterations if item.iteration_id == iteration_id), None)
        if iteration is None:
            return None
        loop_detail = await research_loop_store.get_loop_detail(iteration.loop_id)
        action_target = loop_detail.loop.action_target if loop_detail else "factor"

        loop_iterations = sorted(
            [item for item in iterations if item.loop_id == iteration.loop_id],
            key=lambda item: item.order,
        )
        previous = next((item for item in reversed(loop_iterations) if item.order < iteration.order), None)
        metrics: dict[str, Any] = dict(iteration.metrics or {})
        artifact_links = metrics.get("artifact_links") if isinstance(metrics.get("artifact_links"), dict) else {}
        linked_case_id = iteration.linked_case_id or _as_optional_str(artifact_links.get("case_id"))
        linked_knowledge_item_id = iteration.linked_knowledge_item_id or _as_optional_str(artifact_links.get("knowledge_item_id"))
        linked_patch_id = iteration.linked_patch_id or _as_optional_str(artifact_links.get("patch_id"))
        evidence: list[ResearchVerdictEvidence] = []
        blocking_reasons: list[str] = []
        quality_warnings: list[str] = []
        comparison: list[ResearchMetricComparisonRow] = []
        baseline: dict[str, Any] = {}
        current: dict[str, Any] = {}
        thresholds = self._thresholds(action_target)
        metrics["action_target"] = action_target
        metrics["thresholds"] = thresholds

        effective_candidate_run_id = candidate_run_id or iteration.linked_run_id
        effective_baseline_run_id = (
            baseline_run_id
            or _as_optional_str(metrics.get("baseline_run_id"))
            or (previous.linked_run_id if previous else None)
        )
        effective_candidate_backtest_id = _as_optional_str(metrics.get("candidate_backtest_id")) or iteration.linked_backtest_id
        effective_baseline_backtest_id = (
            _as_optional_str(metrics.get("baseline_backtest_id"))
            or (previous.linked_backtest_id if previous else None)
        )
        if effective_candidate_backtest_id:
            metrics.setdefault("candidate_backtest_id", effective_candidate_backtest_id)
        if effective_baseline_backtest_id:
            metrics.setdefault("baseline_backtest_id", effective_baseline_backtest_id)

        if iteration.evidence_links:
            for link in iteration.evidence_links:
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type=link.source_type,
                        source_id=link.source_id,
                        label=link.label,
                        quality=link.quality,
                        reported_quality=link.reported_quality,
                        summary="Existing iteration evidence.",
                        created_at=link.created_at,
                    )
                )
                if (
                    link.quality
                    and link.quality.upper() not in {"HIGH", "PASS"}
                    and _should_warn_on_stored_evidence_link(
                        link,
                        effective_candidate_backtest_id=effective_candidate_backtest_id,
                        effective_baseline_backtest_id=effective_baseline_backtest_id,
                    )
                ):
                    quality_warnings.append(f"{link.source_type}:{link.source_id} quality={link.quality}")

        candidate_run = self._get_run(effective_candidate_run_id) if effective_candidate_run_id else None
        if effective_candidate_run_id and not candidate_run:
            blocking_reasons.append(f"Linked run not found: {effective_candidate_run_id}")
        if candidate_run:
            run_metrics, run_warnings = self._run_metrics(candidate_run)
            metrics.update(run_metrics)
            quality_warnings.extend(run_warnings)
            current = self._run_snapshot(candidate_run)
            evidence.append(self._run_evidence(candidate_run, run_metrics))
        elif not effective_candidate_run_id:
            blocking_reasons.append("No linked analysis run for this iteration.")

        if effective_baseline_run_id and effective_candidate_run_id and effective_baseline_run_id != effective_candidate_run_id:
            compare_result = self._safe_compare_runs(effective_baseline_run_id, effective_candidate_run_id)
            if compare_result:
                baseline = compare_result.get("leftRun") or {}
                current = compare_result.get("rightRun") or current
                comparison = self._comparison_rows(compare_result)
                metrics["changed_count"] = compare_result.get("changedCount", 0)
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type="RUN_COMPARE",
                        source_id=f"{effective_baseline_run_id}->{effective_candidate_run_id}",
                        label="Baseline vs current run compare",
                        quality="MEDIUM",
                        summary=compare_result.get("summary", ["Run compare generated."])[0],
                        metrics={"changed_count": compare_result.get("changedCount", 0)},
                        created_at=compare_result.get("generatedAt") or _now(),
                    )
                )
            else:
                quality_warnings.append("Run compare was unavailable for baseline/current ids.")
        elif effective_baseline_run_id:
            baseline_run = self._get_run(effective_baseline_run_id)
            if baseline_run:
                baseline = self._run_snapshot(baseline_run)

        candidate_backtest: Optional[dict[str, Any]] = None
        candidate_backtest_metrics: dict[str, Any] = {}
        if effective_candidate_backtest_id:
            candidate_backtest = await backtest_store.get_run(effective_candidate_backtest_id)
            if candidate_backtest:
                candidate_backtest_metrics = self._backtest_metrics(candidate_backtest)
                is_bottom_backtest = _is_bottom_research_backtest(candidate_backtest)
                if is_bottom_backtest:
                    backtest_quality = str(candidate_backtest_metrics.get("backtest_evidence_grade") or "SUPPORTING").upper()
                    backtest_warnings = []
                    metrics["bottom_research_backtest_id"] = effective_candidate_backtest_id
                    metrics["bottom_research_supporting_only"] = True
                    metrics["simulation_only"] = True
                    metrics["is_real_trade"] = False
                else:
                    backtest_quality, backtest_warnings = self._backtest_evidence_quality(candidate_backtest)
                metrics.update(candidate_backtest_metrics)
                quality_warnings.extend(backtest_warnings)
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type="BACKTEST",
                        source_id=effective_candidate_backtest_id,
                        label="Linked MFE/MAE Path Research backtest result" if is_bottom_backtest else "Linked candidate backtest result",
                        quality=backtest_quality,
                        summary=(
                            f"Backtest {candidate_backtest.get('status')} return={candidate_backtest_metrics.get('backtest_return_pct')} "
                            f"evidence={backtest_quality}"
                        ),
                        metrics=candidate_backtest_metrics,
                        created_at=candidate_backtest.get("updated_at") or _now(),
                    )
                )
            else:
                blocking_reasons.append(f"Linked backtest not found: {effective_candidate_backtest_id}")

        baseline_backtest: Optional[dict[str, Any]] = None
        baseline_backtest_metrics: dict[str, Any] = {}
        if effective_baseline_backtest_id and effective_baseline_backtest_id != effective_candidate_backtest_id:
            baseline_backtest = await backtest_store.get_run(effective_baseline_backtest_id)
            if baseline_backtest:
                baseline_backtest_metrics = self._backtest_metrics(baseline_backtest)
                baseline_quality, baseline_warnings = self._backtest_evidence_quality(baseline_backtest)
                metrics.update(_prefix_metrics(baseline_backtest_metrics, "baseline"))
                quality_warnings.extend(baseline_warnings)
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type="BASELINE_BACKTEST",
                        source_id=effective_baseline_backtest_id,
                        label="Linked baseline backtest result",
                        quality=baseline_quality,
                        summary=(
                            f"Baseline backtest {baseline_backtest.get('status')} "
                            f"return={baseline_backtest_metrics.get('backtest_return_pct')} evidence={baseline_quality}"
                        ),
                        metrics=baseline_backtest_metrics,
                        created_at=baseline_backtest.get("updated_at") or _now(),
                    )
                )
            else:
                blocking_reasons.append(f"Linked baseline backtest not found: {effective_baseline_backtest_id}")

        if baseline_backtest and candidate_backtest:
            backtest_compare_metrics = self._backtest_compare_metrics(
                baseline_backtest_metrics,
                candidate_backtest_metrics,
            )
            metrics.update(backtest_compare_metrics)
            comparison.extend(self._backtest_comparison_rows(backtest_compare_metrics))
            evidence.append(
                ResearchVerdictEvidence(
                    source_type="BACKTEST_COMPARE",
                    source_id=f"{effective_baseline_backtest_id}->{effective_candidate_backtest_id}",
                    label="Baseline vs candidate backtest compare",
                    quality="MEDIUM",
                    summary=f"Backtest comparison verdict={backtest_compare_metrics.get('backtest_comparison_verdict')}",
                    metrics=backtest_compare_metrics,
                    created_at=_now(),
                )
            )

        if linked_case_id:
            case = await case_library_store.get_case(linked_case_id)
            if case:
                case_metrics = self._case_metrics(case)
                metrics.update(case_metrics)
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type="CASE",
                        source_id=linked_case_id,
                        label="Linked case review",
                        quality="MEDIUM",
                        summary=case.get("review_note") or "Case review linked.",
                        metrics=case_metrics,
                        created_at=case.get("updated_at") or _now(),
                    )
                )
                if case.get("review_status") != "REVIEWED":
                    blocking_reasons.append("Linked case has not been reviewed.")
            else:
                blocking_reasons.append(f"Linked case not found: {linked_case_id}")

        if linked_knowledge_item_id:
            knowledge = self._get_knowledge(linked_knowledge_item_id)
            if knowledge:
                knowledge_metrics = self._knowledge_metrics(knowledge)
                metrics.update(knowledge_metrics)
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type="KNOWLEDGE",
                        source_id=linked_knowledge_item_id,
                        label="Linked knowledge candidate",
                        quality="MEDIUM",
                        summary=knowledge.review_note or knowledge.decision_impact or "Knowledge item linked.",
                        metrics=knowledge_metrics,
                        created_at=knowledge.updated_at or _now(),
                    )
                )
                if knowledge.status == "PENDING_REVIEW":
                    blocking_reasons.append("Linked knowledge item is still pending review.")
            else:
                blocking_reasons.append(f"Linked knowledge item not found: {linked_knowledge_item_id}")

        if linked_patch_id:
            patch = await self._get_patch(linked_patch_id)
            if patch:
                patch_metrics = self._patch_metrics(patch)
                metrics.update(patch_metrics)
                evidence.append(
                    ResearchVerdictEvidence(
                        source_type="PATCH",
                        source_id=linked_patch_id,
                        label="Linked knowledge patch",
                        quality="MEDIUM",
                        summary=patch.get("reason") or "Patch linked.",
                        metrics=patch_metrics,
                        created_at=patch.get("updated_at") or _now(),
                    )
                )
                latest_eval = await self._latest_evaluation(linked_patch_id)
                if latest_eval:
                    eval_metrics = self._evaluation_metrics(latest_eval)
                    metrics.update(eval_metrics)
                    evidence.append(
                        ResearchVerdictEvidence(
                            source_type="EVALUATION",
                            source_id=latest_eval["eval_id"],
                            label="Latest patch evaluation",
                            quality="MEDIUM",
                            summary=latest_eval.get("summary") or "Patch evaluation linked.",
                            metrics=eval_metrics,
                            created_at=latest_eval.get("updated_at") or _now(),
                        )
                    )
            else:
                blocking_reasons.append(f"Linked patch not found: {linked_patch_id}")

        if not evidence:
            blocking_reasons.append("No evidence links are available for verdict evaluation.")
        decision_evidence = _review_gate_verdict_evidence(_dedupe_evidence(evidence))
        if decision_evidence and all(_is_bottom_research_evidence(item) for item in decision_evidence):
            blocking_reasons.append(
                "MFE/MAE Path Research evidence is supporting_only and needs independent run, case, patch, or review-gated backtest evidence."
            )
            quality_warnings.append("mfe_mae_research_supporting_only")

        engine_verdict, suggested_feedback_verdict = self._decide(
            metrics, decision_evidence, blocking_reasons, quality_warnings, thresholds
        )
        confidence = self._confidence(metrics, decision_evidence, blocking_reasons)
        evidence = decision_evidence
        can_accept_feedback = suggested_feedback_verdict == "ACCEPTED" and not blocking_reasons

        return ResearchVerdictInputs(
            iteration_id=iteration.iteration_id,
            loop_id=iteration.loop_id,
            status=iteration.status,
            current_verdict=iteration.verdict,
            engine_verdict=engine_verdict,
            suggested_feedback_verdict=suggested_feedback_verdict,
            confidence=confidence,
            can_accept_feedback=can_accept_feedback,
            blocking_reasons=_dedupe(blocking_reasons),
            quality_warnings=_dedupe(quality_warnings),
            metrics=metrics,
            baseline=baseline,
            current=current,
            comparison=comparison,
            evidence=evidence,
            generated_at=_now(),
        )

    async def refresh_inputs(
        self,
        iteration_id: str,
        *,
        baseline_run_id: Optional[str] = None,
        candidate_run_id: Optional[str] = None,
    ) -> Optional[ResearchVerdictInputs]:
        inputs = await self.get_inputs(
            iteration_id,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        )
        if inputs is None:
            return None
        next_status = self._refresh_status(inputs.status, inputs.current_verdict)
        await research_loop_store.record_feedback(
            iteration_id,
            ResearchIterationFeedbackRequest(
                action="VERDICT_INPUTS_REFRESHED",
                verdict=inputs.current_verdict,
                status=next_status,
                note=f"Verdict engine={inputs.engine_verdict}; confidence={inputs.confidence}",
                metrics={
                    **inputs.metrics,
                    "engine_verdict": inputs.engine_verdict,
                    "suggested_feedback_verdict": inputs.suggested_feedback_verdict,
                    "confidence": inputs.confidence,
                    "blocking_reasons": inputs.blocking_reasons,
                    "quality_warnings": inputs.quality_warnings,
                    "comparison": [row.model_dump() for row in inputs.comparison],
                },
                evidence_links=[
                    ResearchEvidenceLink(
                        source_type=item.source_type,
                        source_id=item.source_id,
                        label=item.label,
                        quality=item.quality,
                        reported_quality=item.reported_quality,
                        created_at=item.created_at,
                    )
                    for item in inputs.evidence
                ],
            ),
        )
        return await self.get_inputs(
            iteration_id,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        )

    def _refresh_status(self, current_status: str, current_verdict: str) -> str:
        terminal = {"ACCEPTED", "REJECTED", "PATCH_REQUIRED"}
        if _upper(current_status) in terminal or _upper(current_verdict) in terminal:
            return current_status
        return "EVALUATED"

    def _get_run(self, run_id: Optional[str]) -> Optional[dict[str, Any]]:
        if not run_id:
            return None
        try:
            run = get_run(run_id)
            if run:
                return run
        except Exception:
            pass
        run = load_persisted_runs().get(run_id)
        return run if isinstance(run, dict) else None

    def _safe_compare_runs(self, left_id: str, right_id: str) -> Optional[dict[str, Any]]:
        try:
            return analysis_lifecycle_service.compare_runs(left_id, right_id)
        except Exception:
            return None

    async def _get_patch(self, patch_id: str) -> Optional[dict[str, Any]]:
        patches = await knowledge_patch_store.list_patches(limit=200)
        return next((item for item in patches if item.get("patch_id") == patch_id), None)

    def _get_knowledge(self, item_id: str) -> Optional[Any]:
        return next((item for item in list_knowledge_items() if item.item_id == item_id), None)

    async def _latest_evaluation(self, patch_id: str) -> Optional[dict[str, Any]]:
        evaluations = await evaluation_sandbox_store.list_evaluations(patch_id=patch_id, limit=1)
        return evaluations[0] if evaluations else None

    def _run_metrics(self, run: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        compressed = run.get("compressedSummary") or summarize_run(run).model_dump(mode="json")
        quality = compressed.get("quality") or {}
        dvg = run.get("dvg") or {}
        qiam = run.get("qiam") or {}
        kill_switch = run.get("killSwitch") or {}
        signalops = run.get("signalOps") or {}
        paper_trading = run.get("paperTrading") or {}
        bottom = _extract_mfe_mae_research(run)
        warnings = list(quality.get("issues") or [])
        warnings.extend(quality.get("missing_critical_fields") or [])
        if dvg.get("status") and dvg.get("status") != "PASS":
            warnings.append(f"dvg_status={dvg.get('status')}")
        if kill_switch.get("active"):
            warnings.append(f"kill_switch={kill_switch.get('level') or 'ACTIVE'}")
        if signalops.get("blockedReason"):
            warnings.append(f"signalops_blocked={signalops.get('blockedReason')}")
        if paper_trading.get("triggeredInvalidation"):
            warnings.append("paper_trading_triggered_invalidation")
        return (
            {
                "run_status": run.get("status"),
                "final_action": (run.get("finalWriter") or {}).get("finalAction") or run.get("finalAction"),
                "quality_score": quality.get("score"),
                "quality_level": quality.get("level"),
                "qiam_confidence": qiam.get("modelConfidenceFinal"),
                "dvg_status": dvg.get("status"),
                "kill_switch_active": kill_switch.get("active", False),
                "signalops_status": signalops.get("signalStatus"),
                "signalops_blocked_reason": signalops.get("blockedReason"),
                "paper_trading_status": paper_trading.get("status"),
                "paper_trading_simulated_profit": paper_trading.get("simulatedProfit"),
                "paper_trading_max_drawdown": paper_trading.get("maxDrawdown"),
                "paper_trading_triggered_invalidation": paper_trading.get("triggeredInvalidation"),
                "run_id": run.get("runId"),
                **_bottom_research_metrics(bottom),
            },
            [str(item) for item in warnings if str(item).strip()],
        )

    def _run_snapshot(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run.get("runId"),
            "status": run.get("status"),
            "final_action": (run.get("finalWriter") or {}).get("finalAction") or run.get("finalAction"),
            "data_mode": run.get("dataMode"),
            "updated_at": run.get("updatedAt"),
        }

    def _run_evidence(self, run: dict[str, Any], metrics: dict[str, Any]) -> ResearchVerdictEvidence:
        is_mfe_mae_only = _is_mfe_mae_research_run(run)
        return ResearchVerdictEvidence(
            source_type="MFE_MAE_RESEARCH_RUN" if is_mfe_mae_only else "RUN",
            source_id=str(run.get("runId") or ""),
            label="Linked MFE/MAE Path Research run" if is_mfe_mae_only else "Linked guarded analysis run",
            quality=str(metrics.get("quality_level") or "UNKNOWN"),
            summary=f"{run.get('status')} final_action={metrics.get('final_action')}",
            metrics=metrics,
            created_at=str(run.get("updatedAt") or run.get("createdAt") or _now()),
        )

    def _comparison_rows(self, compare_result: dict[str, Any]) -> list[ResearchMetricComparisonRow]:
        rows: list[ResearchMetricComparisonRow] = []
        for item in compare_result.get("diffs") or []:
            if not item.get("changed"):
                continue
            rows.append(
                ResearchMetricComparisonRow(
                    key=str(item.get("key") or ""),
                    label=str(item.get("label") or item.get("key") or ""),
                    baseline=item.get("left"),
                    current=item.get("right"),
                    warning=str(item.get("impact") or ""),
                )
            )
            if len(rows) >= 8:
                break
        return rows

    def _backtest_metrics(self, backtest: dict[str, Any]) -> dict[str, Any]:
        report = backtest.get("report") or {}
        comparison = backtest.get("comparison") or {}
        evidence_strength = _backtest_evidence_strength(report)
        sample_window = report.get("sampleWindow") if isinstance(report.get("sampleWindow"), dict) else {}
        statistical_confidence = report.get("statisticalConfidence") if isinstance(report.get("statisticalConfidence"), dict) else {}
        research_contract = _backtest_research_contract(report)
        benchmark = report.get("benchmark") if isinstance(report.get("benchmark"), dict) else {}
        has_evidence_strength = bool(evidence_strength)
        return {
            "backtest_status": backtest.get("status"),
            "backtest_run_id": _backtest_id(backtest),
            "backtest_return_pct": report.get("total_return_pct"),
            "backtest_hit_rate": report.get("hit_rate"),
            "backtest_max_drawdown_pct": report.get("max_drawdown_pct"),
            "backtest_comparison_verdict": comparison.get("verdict"),
            "backtest_return_delta": comparison.get("return_delta"),
            "backtest_drawdown_delta": comparison.get("drawdown_delta"),
            "backtest_data_source": report.get("data_source"),
            "backtest_signal_source": report.get("signal_source"),
            "backtest_evidence_grade": evidence_strength.get("grade") or "LOW",
            "backtest_can_support_research_verdict": (
                _evidence_all_truthy(evidence_strength, "canSupportResearchVerdict", "can_support_research_verdict")
                if has_evidence_strength
                else False
            ),
            "backtest_research_usage": evidence_strength.get("researchUsage") or ("supporting_only" if not has_evidence_strength else None),
            "backtest_review_conclusion": _backtest_review_conclusion(evidence_strength),
            "backtest_sample_window": sample_window,
            "backtest_statistical_confidence": statistical_confidence,
            "backtest_limitations": report.get("limitations") or evidence_strength.get("limitations") or [],
            "backtest_research_contract": research_contract,
            "backtest_benchmark_symbol": research_contract.get("benchmark_symbol") or benchmark.get("symbol"),
            "backtest_experiment_package_hash": research_contract.get("experiment_package_hash"),
            "backtest_walk_forward": research_contract.get("walk_forward") or {},
            "backtest_out_of_sample_start": research_contract.get("out_of_sample_start") or "",
            "backtest_out_of_sample_end": research_contract.get("out_of_sample_end") or "",
            "backtest_out_of_sample_configured": research_contract.get("out_of_sample_configured"),
        }

    def _backtest_compare_metrics(
        self,
        baseline_metrics: dict[str, Any],
        candidate_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        return_delta = round(
            _as_number(candidate_metrics.get("backtest_return_pct"))
            - _as_number(baseline_metrics.get("backtest_return_pct")),
            4,
        )
        drawdown_delta = round(
            _as_number(candidate_metrics.get("backtest_max_drawdown_pct"))
            - _as_number(baseline_metrics.get("backtest_max_drawdown_pct")),
            4,
        )
        hit_rate_delta = round(
            _as_number(candidate_metrics.get("backtest_hit_rate"))
            - _as_number(baseline_metrics.get("backtest_hit_rate")),
            4,
        )
        if return_delta < 0 or drawdown_delta > 0.01:
            verdict = "REGRESSED"
        elif return_delta > 0 and drawdown_delta <= 0:
            verdict = "IMPROVED"
        else:
            verdict = "NO_REGRESSION"
        return {
            "baseline_backtest_id": baseline_metrics.get("backtest_run_id"),
            "candidate_backtest_id": candidate_metrics.get("backtest_run_id"),
            "backtest_return_delta": return_delta,
            "backtest_drawdown_delta": drawdown_delta,
            "backtest_hit_rate_delta": hit_rate_delta,
            "backtest_comparison_verdict": verdict,
            "backtest_review_conclusion": candidate_metrics.get("backtest_review_conclusion"),
        }

    def _backtest_comparison_rows(self, compare_metrics: dict[str, Any]) -> list[ResearchMetricComparisonRow]:
        return [
            ResearchMetricComparisonRow(
                key="backtest_return_delta",
                label="Backtest return delta",
                delta=compare_metrics.get("backtest_return_delta"),
                quality=compare_metrics.get("backtest_comparison_verdict") or "",
            ),
            ResearchMetricComparisonRow(
                key="backtest_drawdown_delta",
                label="Backtest drawdown delta",
                delta=compare_metrics.get("backtest_drawdown_delta"),
                quality=compare_metrics.get("backtest_comparison_verdict") or "",
            ),
            ResearchMetricComparisonRow(
                key="backtest_hit_rate_delta",
                label="Backtest hit-rate delta",
                delta=compare_metrics.get("backtest_hit_rate_delta"),
                quality=compare_metrics.get("backtest_comparison_verdict") or "",
            ),
        ]

    def _backtest_evidence_quality(self, backtest: dict[str, Any]) -> tuple[str, list[str]]:
        status = str(backtest.get("status") or "").upper()
        report = backtest.get("report") or {}
        evidence_strength = _backtest_evidence_strength(report)
        grade = str(evidence_strength.get("grade") or "").upper()
        if not grade:
            grade = "LOW"
        can_support = _evidence_all_truthy(evidence_strength, "canSupportResearchVerdict", "can_support_research_verdict") if evidence_strength else False
        limitations = report.get("limitations") or evidence_strength.get("limitations") or []
        warnings: list[str] = []
        if not evidence_strength:
            warnings.append(
                f"BACKTEST:{_backtest_id(backtest)} quality={grade}; "
                "missing evidenceStrength review gate; supporting evidence only."
            )
        elif grade not in {"HIGH", "PASS"} or not can_support:
            warnings.append(
                f"BACKTEST:{_backtest_id(backtest)} quality={grade}; "
                "supporting evidence only until evidenceStrength.canSupportResearchVerdict is true."
            )
        for item in limitations[:5]:
            warnings.append(f"BACKTEST_LIMITATION:{item}")
        return grade, warnings

    def _case_metrics(self, case: dict[str, Any]) -> dict[str, Any]:
        return {
            "case_review_status": case.get("review_status"),
            "case_conclusion_correct": case.get("conclusion_correct"),
            "case_final_action_correct": case.get("final_action_correct"),
            "case_data_sufficiency": case.get("data_sufficiency"),
            "case_optimism_bias": case.get("optimism_bias"),
        }

    def _knowledge_metrics(self, knowledge: Any) -> dict[str, Any]:
        return {
            "knowledge_status": knowledge.status,
            "knowledge_category": knowledge.category,
            "knowledge_confidence": knowledge.confidence,
            "knowledge_version": knowledge.version,
        }

    def _patch_metrics(self, patch: dict[str, Any]) -> dict[str, Any]:
        return {
            "patch_status": patch.get("approval_status"),
            "patch_backtest_required": patch.get("backtest_required"),
        }

    def _evaluation_metrics(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        return {
            "evaluation_status": evaluation.get("status"),
            "evaluation_pass_rate": evaluation.get("pass_rate"),
            "evaluation_improvement_rate": evaluation.get("improvement_rate"),
            "evaluation_regressed_cases": evaluation.get("regressed_cases"),
            "evaluation_improved_cases": evaluation.get("improved_cases"),
            "evaluation_total_cases": evaluation.get("total_cases"),
        }

    def _decide(
        self,
        metrics: dict[str, Any],
        evidence: list[ResearchVerdictEvidence],
        blocking_reasons: list[str],
        quality_warnings: list[str],
        thresholds: dict[str, Any],
    ) -> tuple[str, str]:
        if metrics.get("run_status") == "FAILED":
            return "REJECT", "REJECTED"
        if metrics.get("kill_switch_active") or _upper(metrics.get("dvg_status")) in {"BLOCK", "FAIL", "ERROR"}:
            return "GUARDRAIL_BLOCKED", "PATCH_REQUIRED"
        if _upper(metrics.get("backtest_comparison_verdict")) == "REGRESSED" or _as_number(metrics.get("evaluation_regressed_cases")) > 0:
            return "REGRESSED", "PATCH_REQUIRED"
        if metrics.get("paper_trading_triggered_invalidation") is True:
            return "REGRESSED", "PATCH_REQUIRED"
        if metrics.get("case_conclusion_correct") is False or metrics.get("case_final_action_correct") is False:
            return "REJECT", "REJECTED"
        quality_score = _as_number(metrics.get("quality_score"))
        quality_level = _upper(metrics.get("quality_level"))
        min_quality = _as_number(thresholds.get("min_quality_score")) or 50
        min_qiam = _as_number(thresholds.get("min_qiam_confidence"))
        qiam_confidence = _as_number(metrics.get("qiam_confidence"))
        if blocking_reasons or quality_level == "LOW" or (quality_score and quality_score < min_quality):
            return "NEEDS_MORE_DATA", "PENDING"
        if min_qiam and qiam_confidence and qiam_confidence < min_qiam:
            return "NEEDS_MORE_DATA", "PENDING"
        if evidence and quality_level == "HIGH" and not quality_warnings:
            return "ACCEPT", "ACCEPTED"
        return "NEEDS_MORE_DATA", "PENDING"

    def _thresholds(self, action_target: str) -> dict[str, Any]:
        target = _upper(action_target)
        defaults = {
            "min_quality_score": 60,
            "min_qiam_confidence": 0.55,
            "max_regressed_cases": 0,
        }
        overrides = {
            "FACTOR": {"min_quality_score": 65, "min_qiam_confidence": 0.60},
            "MODEL": {"min_quality_score": 70, "min_qiam_confidence": 0.65},
            "SIGNAL": {"min_quality_score": 70, "min_qiam_confidence": 0.60},
            "RISK_RULE": {"min_quality_score": 75, "min_qiam_confidence": 0.65},
            "PORTFOLIO_RULE": {"min_quality_score": 75, "min_qiam_confidence": 0.65},
            "EXECUTION_RULE": {"min_quality_score": 75, "min_qiam_confidence": 0.60},
        }
        return {**defaults, **overrides.get(target, {})}

    def _confidence(
        self,
        metrics: dict[str, Any],
        evidence: list[ResearchVerdictEvidence],
        blocking_reasons: list[str],
    ) -> float:
        score = min(0.45, len(evidence) * 0.12)
        quality_score = _as_number(metrics.get("quality_score"))
        if quality_score:
            score += min(0.35, quality_score / 100 * 0.35)
        if metrics.get("evaluation_status") == "COMPLETED":
            score += 0.12
        if metrics.get("backtest_status") == "COMPLETED":
            score += 0.08
        score -= min(0.35, len(blocking_reasons) * 0.12)
        return round(max(0.0, min(1.0, score)), 2)


def _as_optional_str(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "pass", "ready"}:
        return True
    if text in {"false", "0", "no", "n", "fail", "failed", "low", "supporting_only"}:
        return False
    return False


def _evidence_all_truthy(evidence: dict[str, Any], *keys: str) -> bool:
    values = [_as_bool(evidence[key]) for key in keys if key in evidence]
    return bool(values) and all(values)


def _evidence_any_truthy(evidence: dict[str, Any], *keys: str) -> bool:
    return any(_as_bool(evidence[key]) for key in keys if key in evidence)


def _weakest_evidence_grade(*values: Any) -> str:
    rank = {
        "MISSING": 0,
        "UNKNOWN": 0,
        "LOW": 1,
        "SUPPORTING_ONLY": 1,
        "WEAK": 1,
        "WARN": 1,
        "REVIEW": 1,
        "REVIEW_ONLY": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "PASS": 3,
        "READY": 3,
        "STRONG": 3,
        "PRIMARY": 3,
        "PRIMARY_EVIDENCE": 3,
    }
    normalized = [str(value or "").strip().upper() for value in values if str(value or "").strip()]
    if not normalized:
        return ""
    weakest = min(normalized, key=lambda value: rank.get(value, 0))
    return weakest if weakest in {"MISSING", "UNKNOWN", "LOW", "MEDIUM", "HIGH", "PASS"} else (
        "HIGH" if rank.get(weakest, 0) >= 3 else "LOW"
    )


def _conservative_research_usage(*values: Any) -> str:
    normalized = [str(value or "").strip().lower() for value in values if str(value or "").strip()]
    if not normalized:
        return ""
    if "supporting_only" in normalized:
        return "supporting_only"
    return normalized[0]


def _backtest_evidence_strength(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    snake = report.get("evidence_strength") if isinstance(report.get("evidence_strength"), dict) else {}
    camel = report.get("evidenceStrength") if isinstance(report.get("evidenceStrength"), dict) else {}
    if not snake and not camel:
        return {}

    normalized = {**snake, **camel}
    grade = _weakest_evidence_grade(camel.get("grade"), snake.get("grade"))
    if grade:
        normalized["grade"] = grade

    usage = _conservative_research_usage(camel.get("researchUsage"), snake.get("research_usage"))
    if usage:
        normalized["researchUsage"] = usage
        normalized["research_usage"] = usage

    can_support = _evidence_all_truthy(
        {**camel, **snake},
        "canSupportResearchVerdict",
        "can_support_research_verdict",
    )
    normalized["canSupportResearchVerdict"] = can_support
    normalized["can_support_research_verdict"] = can_support

    weak_sample = _evidence_any_truthy({**camel, **snake}, "weakSample", "weak_sample")
    normalized["weakSample"] = weak_sample
    normalized["weak_sample"] = weak_sample
    return normalized


def _backtest_research_contract(report: dict[str, Any]) -> dict[str, Any]:
    contract = report.get("researchContract") if isinstance(report, dict) else {}
    if isinstance(contract, dict) and contract:
        return contract
    provenance = report.get("provenance") if isinstance(report, dict) else {}
    contract = provenance.get("researchContract") if isinstance(provenance, dict) else {}
    if isinstance(contract, dict) and contract:
        return contract
    benchmark = report.get("benchmark") if isinstance(report, dict) and isinstance(report.get("benchmark"), dict) else {}
    out_of_sample = (
        report.get("outOfSampleWindow")
        if isinstance(report, dict) and isinstance(report.get("outOfSampleWindow"), dict)
        else {}
    )
    return {
        "walk_forward": {},
        "out_of_sample_start": out_of_sample.get("startDate") or "",
        "out_of_sample_end": out_of_sample.get("endDate") or "",
        "out_of_sample_configured": bool(out_of_sample.get("configured")),
        "benchmark_symbol": benchmark.get("symbol") or "",
        "experiment_package_hash": (provenance or {}).get("experimentPackageHash")
        or (provenance or {}).get("parameterHash"),
    }


def _backtest_review_conclusion(evidence_strength: dict[str, Any]) -> str:
    can_support = _evidence_all_truthy(evidence_strength, "canSupportResearchVerdict", "can_support_research_verdict")
    usage = str(evidence_strength.get("researchUsage") or evidence_strength.get("research_usage") or "").strip().lower()
    weak_sample = _evidence_any_truthy(evidence_strength, "weakSample", "weak_sample")
    if can_support and usage != "supporting_only" and not weak_sample:
        return "REVIEW_GATE_READY"
    return "SUPPORTING_ONLY"


def _bottom_research_metrics(bottom: dict[str, Any]) -> dict[str, Any]:
    if not bottom:
        return {}
    diagnostics = bottom.get("modelDiagnostics") if isinstance(bottom.get("modelDiagnostics"), dict) else {}
    provenance = bottom.get("provenance") if isinstance(bottom.get("provenance"), dict) else {}
    bottom_model = diagnostics.get("bottomRepairModel") if isinstance(diagnostics.get("bottomRepairModel"), dict) else {}
    walk_forward = diagnostics.get("walkForward") if isinstance(diagnostics.get("walkForward"), dict) else {}
    bottom_walk = walk_forward.get("bottomRepair") if isinstance(walk_forward.get("bottomRepair"), dict) else {}
    if not bottom_walk:
        bottom_walk = bottom_model.get("walkForward") if isinstance(bottom_model.get("walkForward"), dict) else {}
    mfe_eval = diagnostics.get("mfeMaePathRiskEvaluation") if isinstance(diagnostics.get("mfeMaePathRiskEvaluation"), dict) else {}
    if not bottom_walk and mfe_eval:
        bottom_walk = {
            "rankIc": mfe_eval.get("rankIc"),
            "foldCount": len(mfe_eval.get("folds") or []),
            "quantileCoverage": mfe_eval.get("quantileCoverage"),
        }
    return {
        "mfe_mae_research_status": bottom.get("status"),
        "mfe_favorable_probability": bottom.get("mfeFavorableProbability", bottom.get("bottomRepairProbability")),
        "mae_breach_probability": bottom.get("maeBreachProbability", bottom.get("breakdownRiskProbability")),
        "mfe_mae_research_model_version": provenance.get("modelVersion") or diagnostics.get("modelVersion"),
        "mfe_mae_research_sample_count": diagnostics.get("sampleCount"),
        "mfe_mae_rank_ic": mfe_eval.get("rankIc"),
        "mfe_mae_research_fold_count": bottom_walk.get("foldCount"),
        "mfe_mae_research_evidence_grade": diagnostics.get("evidenceGrade"),
        "mfe_mae_research_supporting_only": True,
        "bottom_research_status": bottom.get("status"),
        "bottom_repair_probability": bottom.get("bottomRepairProbability"),
        "breakdown_risk_probability": bottom.get("breakdownRiskProbability"),
        "bottom_research_regime": bottom.get("regimeState"),
        "bottom_research_model_version": provenance.get("modelVersion") or diagnostics.get("modelVersion"),
        "bottom_research_sample_count": diagnostics.get("sampleCount"),
        "bottom_research_brier": bottom_walk.get("brier"),
        "bottom_research_pr_auc": bottom_walk.get("prAuc"),
        "bottom_research_fold_count": bottom_walk.get("foldCount"),
        "bottom_research_evidence_grade": diagnostics.get("evidenceGrade"),
        "bottom_research_supporting_only": True,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _extract_mfe_mae_research(run: dict[str, Any]) -> dict[str, Any]:
    if isinstance(run.get("mfeMaeResearch"), dict):
        return run["mfeMaeResearch"]
    if isinstance(run.get("bottomResearch"), dict):
        return run["bottomResearch"]
    quant_core = run.get("quantCore") if isinstance(run.get("quantCore"), dict) else {}
    if isinstance(quant_core.get("mfeMaeResearch"), dict):
        return quant_core["mfeMaeResearch"]
    if isinstance(quant_core.get("bottomResearch"), dict):
        return quant_core["bottomResearch"]
    return {}


def _is_mfe_mae_research_run(run: dict[str, Any]) -> bool:
    task_type = str(run.get("taskType") or run.get("task_type") or "").lower()
    if any(token in task_type for token in ("mfe_mae", "mfe/mae", "bottom_research", "path_research")):
        return True
    if not _extract_mfe_mae_research(run):
        return False
    final_action = _upper((run.get("finalWriter") or {}).get("finalAction") or run.get("finalAction"))
    qiam = run.get("qiam") if isinstance(run.get("qiam"), dict) else {}
    has_trade_permission = bool(qiam.get("finalBuySuitability") or qiam.get("modelConfidenceFinal"))
    return final_action in {"WAIT", "REVIEW_ONLY", ""} and not has_trade_permission


def _is_bottom_research_backtest(backtest: dict[str, Any]) -> bool:
    report = backtest.get("report") if isinstance(backtest.get("report"), dict) else {}
    parameters = backtest.get("parameters") if isinstance(backtest.get("parameters"), dict) else {}
    provenance = report.get("provenance") if isinstance(report.get("provenance"), dict) else {}
    contract = _backtest_research_contract(report)
    signal_source = report.get("signal_source") or parameters.get("signal_source")
    return (
        _upper(signal_source) in {"MFE_MAE_PATH_RESEARCH", "BOTTOM_RESEARCH"}
        or bool(provenance.get("mfeMaeResearchVersion"))
        or bool(provenance.get("bottomResearchVersion"))
        or bool(contract.get("mfeMaeResearchVersion"))
        or bool(contract.get("bottomResearchVersion"))
    )


def _is_bottom_research_evidence(evidence: ResearchVerdictEvidence) -> bool:
    source_type = _upper(evidence.source_type)
    if source_type in {"MFE_MAE_RESEARCH_RUN", "BOTTOM_RESEARCH_RUN"}:
        return True
    if source_type != "BACKTEST":
        return False
    return (
        _upper(evidence.metrics.get("backtest_signal_source")) in {"MFE_MAE_PATH_RESEARCH", "BOTTOM_RESEARCH"}
        or bool(evidence.metrics.get("mfe_mae_research_supporting_only"))
        or bool(evidence.metrics.get("bottom_research_supporting_only"))
        or "mfe/mae" in str(evidence.label or "").lower()
        or "bottom research" in str(evidence.label or "").lower()
    )


def _should_warn_on_stored_evidence_link(
    evidence: ResearchEvidenceLink,
    *,
    effective_candidate_backtest_id: Optional[str],
    effective_baseline_backtest_id: Optional[str],
) -> bool:
    source_type = _upper(evidence.source_type)
    if source_type in {"MFE_MAE_RESEARCH_RUN", "BOTTOM_RESEARCH_RUN"}:
        return False
    if source_type == "BACKTEST":
        label = str(evidence.label or "").lower()
        if "mfe/mae" in label or "bottom research" in label:
            return False
        source_id = _as_optional_str(evidence.source_id)
        hydrated_backtest_ids = {
            item for item in (effective_candidate_backtest_id, effective_baseline_backtest_id) if item
        }
        return source_id not in hydrated_backtest_ids
    return True


def _prefix_metrics(metrics: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def _backtest_id(backtest: dict[str, Any]) -> str:
    return str(backtest.get("run_id") or backtest.get("backtest_id") or backtest.get("id") or "<unknown>")


def _upper(value: Any) -> str:
    return str(value or "").upper()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _dedupe_evidence(values: list[ResearchVerdictEvidence]) -> list[ResearchVerdictEvidence]:
    merged: dict[str, ResearchVerdictEvidence] = {}
    for item in values:
        key = f"{item.source_type}:{item.source_id}"
        previous = merged.get(key)
        if previous and previous.reported_quality and not item.reported_quality:
            item = item.model_copy(update={"reported_quality": previous.reported_quality})
        merged[key] = item
    return list(merged.values())


def _review_gate_evidence_quality(value: Any) -> str:
    quality = _upper(value)
    if quality in {
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
    if quality in {"SUPPORTING_ONLY", "WARN", "REVIEW", "REVIEW_ONLY"}:
        return "LOW"
    if quality in {"FAIL", "FAILED", "BLOCKED"}:
        return "MISSING"
    if quality in {"MEDIUM", "LOW", "MISSING", "PENDING", "UNKNOWN"}:
        return quality
    return "UNKNOWN"


def _review_gate_verdict_evidence(values: list[ResearchVerdictEvidence]) -> list[ResearchVerdictEvidence]:
    result: list[ResearchVerdictEvidence] = []
    for item in values:
        quality = _review_gate_evidence_quality(item.quality)
        if item.quality == quality:
            result.append(item)
            continue
        data = item.model_dump()
        if not data.get("reported_quality"):
            data["reported_quality"] = item.reported_quality or item.quality
        data["quality"] = quality
        result.append(ResearchVerdictEvidence(**data))
    return result


research_verdict_store = ResearchVerdictStore()
