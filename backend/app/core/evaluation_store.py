import json
import logging
import uuid
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, desc

logger = logging.getLogger(__name__)

from ..db.session import AsyncSessionLocal
from ..db.models_case_library import (
    CaseLibraryDB,
    ReviewTagDB,
    ErrorLedgerEntryDB,
    KnowledgePatchDB,
    EvaluationRunDB,
    KnowledgeVersionDB,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


STRATEGY_METRIC_KEYS = (
    "win_rate",
    "max_drawdown",
    "misjudge_rate",
    "manual_review_pass_rate",
    "risk_trigger_rate",
)

REGRESSION_RULE_TERMS = (
    "loosen",
    "relax",
    "disable",
    "remove",
    "bypass",
    "weaken",
    "less_strict",
    "lower_guardrail",
)

VERSION_STATUSES = {"draft", "review", "active", "deprecated", "rolled_back"}
CASE_SET_QUALITY_POLICY_ID = "knowledge_regression_case_set_quality_v1"
REGRESSION_WAIVER_POLICY_ID = "knowledge_promotion_regression_waiver_v1"
KNOWLEDGE_IMPACT_POLICY_ID = "knowledge_post_publish_impact_summary_v1"
KNOWLEDGE_VERSION_APPROVAL_REF_TYPES = {
    "backtest",
    "evaluation",
    "regression_waiver",
    "verdict",
}
MIN_REPRESENTATIVE_CASES = 3
MIN_REPRESENTATIVE_SYMBOLS = 2
MIN_REGRESSION_WAIVER_REASON_LENGTH = 20


class EvaluationSandboxStore:
    async def run_evaluation(self, patch_id: str, force: bool = False) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            patch_result = await db.execute(
                select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id)
            )
            patch = patch_result.scalar_one_or_none()
            if not patch:
                raise KeyError(f"Patch not found: {patch_id}")

            if not force:
                existing_result = await db.execute(
                    select(EvaluationRunDB)
                    .where(EvaluationRunDB.patch_id == patch_id)
                    .where(EvaluationRunDB.status == "COMPLETED")
                    .order_by(desc(EvaluationRunDB.created_at))
                    .limit(1)
                )
                existing = existing_result.scalar_one_or_none()
                if existing:
                    return self._eval_to_dict(existing)

            eval_id = _generate_id("EVAL")
            eval_run = EvaluationRunDB(
                eval_id=eval_id,
                patch_id=patch_id,
                status="RUNNING",
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(eval_run)
            await db.commit()

            start_time = time.time()

            try:
                cases_result = await db.execute(
                    select(CaseLibraryDB).where(CaseLibraryDB.review_status == "REVIEWED")
                )
                cases = cases_result.scalars().all()

                total = len(cases) or 1
                passed = 0
                improved = 0
                regressed = 0
                unchanged = 0
                per_case = []

                for case in cases:
                    case_result = self._evaluate_single_case(case, patch)
                    per_case.append(case_result)

                    if case_result.get("verdict") == "PASS":
                        passed += 1
                    if case_result.get("improvement") == "IMPROVED":
                        improved += 1
                    elif case_result.get("improvement") == "REGRESSED":
                        regressed += 1
                    else:
                        unchanged += 1

                if not cases:
                    unchanged = 1

                pass_rate = round(passed / total, 2)
                improvement_rate = round(improved / total, 2)
                elapsed = int((time.time() - start_time) * 1000)

                summary = (
                    f"Evaluation for patch '{patch.title}': "
                    f"{total} case(s) tested, "
                    f"{passed}/{total} passed (pass_rate={pass_rate}), "
                    f"{improved} improved, {regressed} regressed, {unchanged} unchanged. "
                    f"Improvement rate: {improvement_rate}."
                )

                eval_run.status = "COMPLETED"
                eval_run.total_cases = total
                eval_run.passed_cases = passed
                eval_run.improved_cases = improved
                eval_run.regressed_cases = regressed
                eval_run.unchanged_cases = unchanged
                eval_run.pass_rate = pass_rate
                eval_run.improvement_rate = improvement_rate
                eval_run.elapsed_ms = elapsed
                eval_run.per_case_results = per_case
                eval_run.summary = summary
                eval_run.updated_at = _now()

                existing_backtest = patch.backtest_result or {}
                patch.backtest_result = {
                    **existing_backtest,
                    "eval_id": eval_id,
                    "passed": passed == total,
                    "pass_rate": pass_rate,
                    "improvement_rate": improvement_rate,
                    "cases_tested": total,
                    "improved": improved,
                    "regressed": regressed,
                }
                patch.updated_at = _now()

                await db.commit()
                await db.refresh(eval_run)
                return self._eval_to_dict(eval_run)

            except Exception as exc:
                logger.exception("Evaluation run failed for patch %s: %s", patch_id, exc)
                eval_run.status = "FAILED"
                eval_run.error = "An unexpected error occurred during evaluation. Please try again later."
                eval_run.updated_at = _now()
                await db.commit()
                await db.refresh(eval_run)
                return self._eval_to_dict(eval_run)

    def _evaluate_single_case(self, case: CaseLibraryDB, patch: KnowledgePatchDB) -> Dict[str, Any]:
        affected = patch.affected_modules or []
        case_tags = case.tags or []
        case_lessons = case.key_lessons or []

        verdict = "PASS"
        improvement = "UNCHANGED"
        notes = []

        patch_tag = patch.patch_content.get("tag_fix", "")
        if patch_tag and patch_tag in [t for t in case_tags]:
            improvement = "IMPROVED"
            notes.append(f"Patch tag_fix '{patch_tag}' matched case tags")

        patch_module = patch.patch_content.get("module_fix", "")
        if patch_module and patch_module in affected:
            if case.conclusion_correct is False:
                improvement = "IMPROVED"
                notes.append(f"Patch module_fix '{patch_module}' targets previously incorrect case")
            else:
                notes.append(f"Patch module_fix '{patch_module}' applied to correct case")

        patch_rule = patch.patch_content.get("rule_change", "")
        if patch_rule:
            if case.optimism_bias in ("MODERATE", "SEVERE"):
                improvement = "IMPROVED"
                notes.append(f"Rule change '{patch_rule}' addresses optimism bias case")
            elif case.data_sufficiency == "INSUFFICIENT":
                improvement = "IMPROVED"
                notes.append(f"Rule change '{patch_rule}' addresses data insufficiency case")

        if case.conclusion_correct is False:
            verdict = "REVIEW"

        regression_reasons = self._patch_regression_reasons(case, patch, case_tags, case_lessons)
        if regression_reasons:
            verdict = "FAIL"
            improvement = "REGRESSED"
            notes.extend(regression_reasons)

        if improvement == "UNCHANGED" and not notes:
            notes.append("Patch had no measurable impact on this case")

        return {
            "case_id": case.case_id,
            "symbol": case.symbol,
            "verdict": verdict,
            "improvement": improvement,
            "original_conclusion_correct": case.conclusion_correct,
            "notes": notes,
        }

    def _patch_regression_reasons(
        self,
        case: CaseLibraryDB,
        patch: KnowledgePatchDB,
        case_tags: List[str],
        case_lessons: List[str],
    ) -> List[str]:
        patch_content = patch.patch_content or {}
        reasons: List[str] = []
        case_markers = self._case_regression_markers(case, case_tags, case_lessons)

        explicit_regression_tags = self._tokens_from_patch(
            patch_content.get("regression_tags")
            or patch_content.get("regresses_tags")
            or patch_content.get("known_regression_tags")
        )
        matching_tags = sorted(case_markers.intersection(explicit_regression_tags))
        if matching_tags:
            reasons.append(f"Patch declares regression risk for case marker(s): {', '.join(matching_tags)}")

        if patch_content.get("regression_risk") is True or patch_content.get("expected_regression") is True:
            reasons.append("Patch explicitly marks this change as regression-prone")

        weakening_flags = [
            "weakens_data_sufficiency_gate",
            "relaxes_risk_gate",
            "allows_optimism_bias",
            "disable_human_review",
            "reduces_review_requirement",
        ]
        if any(bool(patch_content.get(flag)) for flag in weakening_flags) and case_markers:
            reasons.append("Patch weakens a guardrail that protects this reviewed case")

        rule_change = str(patch_content.get("rule_change") or "").lower()
        if rule_change and any(term in rule_change for term in REGRESSION_RULE_TERMS) and case_markers:
            reasons.append(f"Rule change '{patch_content.get('rule_change')}' weakens controls for this case")

        return reasons

    def _case_regression_markers(
        self,
        case: CaseLibraryDB,
        case_tags: List[str],
        case_lessons: List[str],
    ) -> set[str]:
        markers = {self._normalize_marker(item) for item in case_tags if str(item).strip()}
        lessons = " ".join(str(item) for item in case_lessons).lower()
        if case.conclusion_correct is False:
            markers.add("CONCLUSION_INCORRECT")
        if case.data_sufficiency == "INSUFFICIENT":
            markers.add("DATA_INSUFFICIENT")
        if case.optimism_bias in ("MODERATE", "SEVERE"):
            markers.add("OPTIMISM_BIAS")
            markers.add(f"OPTIMISM_BIAS_{case.optimism_bias}")
        if "regress" in lessons or "退化" in lessons:
            markers.add("REGRESSION_HISTORY")
        return {marker for marker in markers if marker}

    def _tokens_from_patch(self, value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            tokens: set[str] = set()
            for item in value:
                tokens.update(self._tokens_from_patch(item))
            return tokens
        return {
            self._normalize_marker(part)
            for part in str(value).replace(";", ",").split(",")
            if str(part).strip()
        }

    def _normalize_marker(self, value: Any) -> str:
        return str(value or "").strip().upper().replace(" ", "_").replace("-", "_")

    async def get_evaluation(self, eval_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(EvaluationRunDB).where(EvaluationRunDB.eval_id == eval_id)
            )
            record = result.scalar_one_or_none()
            return self._eval_to_dict(record) if record else None

    async def list_evaluations(self, patch_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(EvaluationRunDB)
            if patch_id:
                query = query.where(EvaluationRunDB.patch_id == patch_id)
            query = query.order_by(desc(EvaluationRunDB.created_at)).limit(limit)
            result = await db.execute(query)
            records = result.scalars().all()
            return [self._eval_to_dict(r) for r in records]

    def _evaluation_evidence_strength(self, record: EvaluationRunDB) -> str:
        status = str(record.status or "").upper()
        if status == "COMPLETED":
            if int(record.regressed_cases or 0) == 0 and int(record.total_cases or 0) > 0:
                return "MEDIUM"
            return "LOW"
        if status == "FAILED":
            return "MISSING"
        return "PENDING"

    def _eval_to_dict(self, record: EvaluationRunDB) -> Dict[str, Any]:
        return {
            "eval_id": record.eval_id,
            "patch_id": record.patch_id,
            "status": record.status,
            "total_cases": record.total_cases,
            "passed_cases": record.passed_cases,
            "improved_cases": record.improved_cases,
            "regressed_cases": record.regressed_cases,
            "unchanged_cases": record.unchanged_cases,
            "pass_rate": record.pass_rate,
            "improvement_rate": record.improvement_rate,
            "elapsed_ms": record.elapsed_ms,
            "per_case_results": record.per_case_results or [],
            "summary": record.summary,
            "strategy_experiment_report": None,
            "evidence_usage": "review_gate_only",
            "evidence_strength": self._evaluation_evidence_strength(record),
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "error": record.error,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def run_strategy_experiment(
        self,
        hypothesis: str,
        strategy_configs: List[Dict[str, Any]],
        sample_window: Optional[Dict[str, Any]] = None,
        patch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not hypothesis.strip():
            raise ValueError("Strategy experiment requires a hypothesis.")
        if len(strategy_configs) < 2:
            raise ValueError("Strategy experiment requires at least two strategy configs.")

        async with AsyncSessionLocal() as db:
            patch = None
            if patch_id:
                patch_result = await db.execute(
                    select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id)
                )
                patch = patch_result.scalar_one_or_none()
                if not patch:
                    raise KeyError(f"Patch not found: {patch_id}")

            cases_result = await db.execute(
                select(CaseLibraryDB).where(CaseLibraryDB.review_status == "REVIEWED")
            )
            cases = cases_result.scalars().all()

            report = self._build_strategy_experiment_report(
                hypothesis=hypothesis,
                strategy_configs=strategy_configs,
                cases=cases,
                sample_window=sample_window or {},
            )

            if patch:
                backtest_result = dict(patch.backtest_result or {})
                backtest_result["strategy_experiment_report"] = report
                backtest_result["strategy_experiment_id"] = report["experiment_id"]
                backtest_result["strategy_hypothesis"] = hypothesis
                patch.backtest_result = backtest_result
                patch.updated_at = _now()
                await db.commit()

            return report

    def _build_strategy_experiment_report(
        self,
        hypothesis: str,
        strategy_configs: List[Dict[str, Any]],
        cases: List[CaseLibraryDB],
        sample_window: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_window = self._normalize_sample_window(sample_window, cases)
        metrics_by_strategy: Dict[str, Dict[str, Any]] = {}
        scores: Dict[str, float] = {}

        for idx, config in enumerate(strategy_configs):
            config_id = str(config.get("config_id") or config.get("id") or f"strategy_{idx + 1}")
            metrics = self._strategy_metrics(config, cases, idx, normalized_window)
            metrics_by_strategy[config_id] = metrics
            scores[config_id] = self._score_strategy(metrics)

        baseline_id = next(iter(metrics_by_strategy.keys()))
        winner_id = max(scores, key=scores.get)
        comparisons = self._compare_strategy_metrics(metrics_by_strategy, baseline_id)
        winner_metrics = metrics_by_strategy[winner_id]

        return {
            "experiment_id": _generate_id("STREXP"),
            "hypothesis": hypothesis,
            "strategy_count": len(metrics_by_strategy),
            "baseline_config_id": baseline_id,
            "winner_config_id": winner_id,
            "sample_window": normalized_window,
            "metrics_by_strategy": metrics_by_strategy,
            "comparisons": comparisons,
            "summary": (
                f"Strategy experiment compared {len(metrics_by_strategy)} configs for hypothesis "
                f"'{hypothesis}'. Winner: {winner_id} "
                f"(win_rate={winner_metrics['win_rate']}, max_drawdown={winner_metrics['max_drawdown']})."
            ),
            "evidence_usage": "review_gate_only",
            "evidence_strength": "LOW",
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "created_at": _now(),
        }

    def _strategy_metrics(
        self,
        config: Dict[str, Any],
        cases: List[CaseLibraryDB],
        index: int,
        sample_window: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_cases = len(cases) or 1
        incorrect_cases = sum(1 for case in cases if case.conclusion_correct is False)
        reviewed_cases = sum(1 for case in cases if case.review_status == "REVIEWED")
        base_pass_rate = 1 - (incorrect_cases / total_cases)
        params = config.get("parameters") or {}
        strictness = self._coerce_float(
            params.get("strictness", params.get("risk_threshold", 0.5)),
            default=0.5,
        )

        win_rate = self._metric_from_config(
            config,
            ("win_rate", "hit_rate", "pass_rate"),
            default=max(0.0, min(1.0, base_pass_rate + (index * 0.03) + (strictness * 0.02))),
            as_rate=True,
        )
        max_drawdown = self._metric_from_config(
            config,
            ("max_drawdown", "max_drawdown_pct", "drawdown"),
            default=max(0.0, min(1.0, 0.12 - (strictness * 0.02) + (index * 0.01))),
            as_rate=True,
        )
        misjudge_rate = self._metric_from_config(
            config,
            ("misjudge_rate", "false_positive_rate", "error_rate"),
            default=max(0.0, min(1.0, (incorrect_cases / total_cases) - (strictness * 0.03))),
            as_rate=True,
        )
        manual_review_pass_rate = self._metric_from_config(
            config,
            ("manual_review_pass_rate", "review_pass_rate"),
            default=max(0.0, min(1.0, (reviewed_cases / total_cases) + (strictness * 0.02))),
            as_rate=True,
        )
        risk_trigger_rate = self._metric_from_config(
            config,
            ("risk_trigger_rate", "risk_fire_rate", "trigger_rate"),
            default=max(0.0, min(1.0, 0.15 - (strictness * 0.02) + (index * 0.005))),
            as_rate=True,
        )

        return {
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
            "misjudge_rate": misjudge_rate,
            "manual_review_pass_rate": manual_review_pass_rate,
            "risk_trigger_rate": risk_trigger_rate,
            "sample_window": sample_window,
        }

    def _normalize_sample_window(
        self,
        sample_window: Dict[str, Any],
        cases: List[CaseLibraryDB],
    ) -> Dict[str, Any]:
        case_dates = [case.created_at for case in cases if case.created_at]
        normalized = {
            "case_count": len(cases),
            "reviewed_case_count": len(cases),
            "start": min(case_dates) if case_dates else None,
            "end": max(case_dates) if case_dates else None,
        }
        normalized.update(sample_window or {})
        return normalized

    def _metric_from_config(
        self,
        config: Dict[str, Any],
        keys: tuple[str, ...],
        default: float,
        as_rate: bool,
    ) -> float:
        for source in self._metric_sources(config):
            for key in keys:
                if key in source:
                    value = self._coerce_float(source.get(key), default)
                    if as_rate:
                        value = abs(value)
                        if value > 1 and value <= 100:
                            value = value / 100
                        value = max(0.0, min(1.0, value))
                    return round(value, 4)
        return round(default, 4)

    def _metric_sources(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        sources: List[Dict[str, Any]] = []
        candidates = [
            config,
            config.get("metrics"),
            config.get("parameters"),
            config.get("backtest_result"),
            config.get("report"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict):
                sources.append(candidate)
                for nested_key in ("metrics", "report", "comparison", "summary"):
                    nested = candidate.get(nested_key)
                    if isinstance(nested, dict):
                        sources.append(nested)
        return sources

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _score_strategy(self, metrics: Dict[str, Any]) -> float:
        return round(
            self._coerce_float(metrics.get("win_rate"))
            + self._coerce_float(metrics.get("manual_review_pass_rate"))
            - self._coerce_float(metrics.get("max_drawdown"))
            - self._coerce_float(metrics.get("misjudge_rate"))
            - self._coerce_float(metrics.get("risk_trigger_rate")),
            4,
        )

    def _compare_strategy_metrics(
        self,
        metrics_by_strategy: Dict[str, Dict[str, Any]],
        baseline_id: str,
    ) -> List[Dict[str, Any]]:
        baseline = metrics_by_strategy[baseline_id]
        comparisons: List[Dict[str, Any]] = []
        for config_id, metrics in metrics_by_strategy.items():
            if config_id == baseline_id:
                continue
            row = {
                "config_id": config_id,
                "baseline_config_id": baseline_id,
            }
            for key in STRATEGY_METRIC_KEYS:
                row[f"{key}_delta"] = round(
                    self._coerce_float(metrics.get(key)) - self._coerce_float(baseline.get(key)),
                    4,
                )
            comparisons.append(row)
        return comparisons


class KnowledgeVersionStore:
    def _version_evidence_strength(
        self,
        *,
        status: str,
        regression: Optional[Dict[str, Any]],
        approval_record: Dict[str, Any],
        source: Dict[str, Any],
    ) -> str:
        normalized_status = self._normalize_version_status(status)
        if normalized_status == "draft":
            return "PENDING"

        refs = approval_record.get("evidence_refs")
        review_evidence_count = len(refs) if isinstance(refs, list) else 0
        source_count = sum(1 for value in source.values() if value)
        has_review_evidence = review_evidence_count > 0
        has_source_context = source_count > 0

        if not regression:
            return "LOW" if has_review_evidence or has_source_context else "PENDING"

        regression_status = str(regression.get("status") or "").upper()
        impact = regression.get("knowledge_impact") if isinstance(regression.get("knowledge_impact"), dict) else {}
        policy = (
            regression.get("case_set_quality_policy")
            if isinstance(regression.get("case_set_quality_policy"), dict)
            else {}
        )
        quality_warnings = regression.get("quality_warnings") or regression.get("warnings") or []
        impact_risk = str(impact.get("risk_level") or "").upper()

        if (
            regression_status in {"REGRESSION", "FAIL", "FAILED", "BLOCKED"}
            or impact_risk == "HIGH"
            or policy.get("blocking") is True
        ):
            return "LOW"
        if has_review_evidence and regression_status in {"PASS", "PASSED", "OK"} and not quality_warnings:
            return "MEDIUM"
        return "LOW"

    async def build_promotion_governance(
        self,
        patch_id: str,
        evidence: Optional[Dict[str, Any]] = None,
        reviewer: str = "human",
    ) -> Dict[str, Any]:
        evidence = evidence or {}
        nested_evidence = evidence.get("evidence") if isinstance(evidence.get("evidence"), dict) else {}

        def _evidence_value(*keys: str) -> Any:
            for key in keys:
                if evidence.get(key):
                    return evidence[key]
                if nested_evidence.get(key):
                    return nested_evidence[key]
            return None

        def _evidence_id(*keys: str) -> Optional[str]:
            value = _evidence_value(*keys)
            normalized = str(value or "").strip()
            return normalized or None

        async with AsyncSessionLocal() as db:
            patch_result = await db.execute(
                select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id)
            )
            patch = patch_result.scalar_one_or_none()
            if not patch:
                raise KeyError(f"Patch not found: {patch_id}")

            requested_case_id = _evidence_id("source_case_id", "case_id")
            patch_case_id = str(patch.source_case_id or "").strip() or None
            if patch_case_id and requested_case_id and requested_case_id != patch_case_id:
                raise ValueError(
                    "Promotion rejected: source_case_id must match the patch source_case_id "
                    f"({patch_case_id})."
                )

            source_case_id = patch_case_id or requested_case_id
            source_case = None
            if source_case_id:
                source_case_result = await db.execute(
                    select(CaseLibraryDB).where(CaseLibraryDB.case_id == source_case_id)
                )
                source_case = source_case_result.scalar_one_or_none()
                if not source_case:
                    raise ValueError(f"Promotion rejected: source case {source_case_id} was not found.")

            requested_run_id = _evidence_id("source_run_id", "run_id")
            case_run_id = str(source_case.run_id or "").strip() if source_case else None
            if case_run_id and requested_run_id and requested_run_id != case_run_id:
                raise ValueError(
                    "Promotion rejected: source_run_id must match the source case run_id "
                    f"({case_run_id})."
                )

            source_run_id = case_run_id or requested_run_id
            backtest_result = patch.backtest_result or {}
            evidence_refs: List[Dict[str, Any]] = []
            regression_waiver: Optional[Dict[str, Any]] = None

            backtest_id = _evidence_value("backtest_id", "backtest_run_id") or backtest_result.get("backtest_id") or backtest_result.get("run_id")
            if backtest_id or any(key in backtest_result for key in ("report", "comparison", "total_trades", "max_drawdown")):
                evidence_refs.append(
                    {
                        "source_type": "backtest",
                        "source_id": backtest_id or f"{patch_id}:backtest_result",
                        "summary": "Backtest evidence attached to knowledge patch.",
                    }
                )

            evaluation_id = _evidence_value("evaluation_id", "eval_id") or backtest_result.get("eval_id")
            if evaluation_id:
                eval_result = await db.execute(
                    select(EvaluationRunDB)
                    .where(EvaluationRunDB.eval_id == evaluation_id)
                    .where(EvaluationRunDB.patch_id == patch_id)
                )
                evaluation = eval_result.scalar_one_or_none()
                if not evaluation:
                    raise ValueError(f"Promotion rejected: evaluation evidence not found for patch {patch_id}.")
                if evaluation.status != "COMPLETED":
                    raise ValueError(f"Promotion rejected: evaluation evidence {evaluation_id} is not completed.")
                if int(evaluation.regressed_cases or 0) > 0:
                    regression_waiver = self._build_regression_waiver(
                        evidence=evidence,
                        nested_evidence=nested_evidence,
                        reviewer=reviewer,
                        evaluation=evaluation,
                    )
                    if regression_waiver is None:
                        raise ValueError(
                            f"Promotion rejected: evaluation evidence {evaluation_id} has "
                            f"{evaluation.regressed_cases} regressed case(s). Resolve regression before promotion "
                            "or provide an audited regression waiver with approval_id, approver_role=admin, and reason."
                        )
                evidence_refs.append(
                    {
                        "source_type": "evaluation",
                        "source_id": evaluation_id,
                        "summary": evaluation.summary,
                        "metrics": {
                            "pass_rate": evaluation.pass_rate,
                            "improvement_rate": evaluation.improvement_rate,
                            "regressed_cases": evaluation.regressed_cases,
                        },
                    }
                )
                if regression_waiver is not None:
                    evidence_refs.append(
                        {
                            "source_type": "regression_waiver",
                            "source_id": regression_waiver["approval_id"],
                            "summary": regression_waiver["reason"],
                            "metrics": {
                                "evaluation_id": evaluation_id,
                                "regressed_cases": evaluation.regressed_cases,
                            },
                        }
                    )

            verdict_id = _evidence_value("verdict_id") or backtest_result.get("verdict_id")
            verdict_value = _evidence_value("verdict") or backtest_result.get("verdict")
            if verdict_id or verdict_value:
                evidence_refs.append(
                    {
                        "source_type": "verdict",
                        "source_id": verdict_id or f"{patch_id}:verdict",
                        "summary": verdict_value or "Verdict evidence supplied for promotion.",
                    }
                )

            if not evidence_refs:
                raise ValueError(
                    "Promotion rejected: provide at least one evidence reference "
                    "(backtest_id, evaluation_id, or verdict_id) before promoting this patch."
                )

            approval_record = dict(evidence.get("approval_record") or {})
            approval_record.setdefault("reviewer", reviewer)
            approval_record.setdefault("approved_at", _now())
            approval_record["evidence_refs"] = self._merge_evidence_refs(
                None,
                evidence_refs,
            )
            if regression_waiver is not None:
                approval_record["regression_waiver"] = regression_waiver

            rollback_impact = dict(evidence.get("rollback_impact") or {})
            rollback_impact.setdefault("rollback_plan", patch.rollback_plan)
            rollback_impact.setdefault("affected_modules", patch.affected_modules or [])

            return {
                "source_run_id": source_run_id,
                "source_case_id": source_case_id,
                "source_patch_id": patch_id,
                "source_evaluation_id": evaluation_id,
                "source_verdict_id": verdict_id,
                "scope": evidence.get("scope") or "knowledge_patch_promotion",
                "risk_boundary": evidence.get("risk_boundary") or patch.risk_note or "Promotion is limited to the patch's affected modules.",
                "approval_record": approval_record,
                "rollback_impact": rollback_impact,
                "status": "active",
            }

    def _build_regression_waiver(
        self,
        *,
        evidence: Dict[str, Any],
        nested_evidence: Dict[str, Any],
        reviewer: str,
        evaluation: EvaluationRunDB,
    ) -> Optional[Dict[str, Any]]:
        waiver = evidence.get("regression_waiver")
        waiver = waiver if isinstance(waiver, dict) else {}
        requested = bool(
            evidence.get("allow_regression_override")
            or nested_evidence.get("allow_regression_override")
            or waiver.get("enabled")
            or waiver.get("approved")
        )
        if not requested:
            return None

        reason = str(
            evidence.get("regression_override_reason")
            or nested_evidence.get("regression_override_reason")
            or waiver.get("reason")
            or ""
        ).strip()
        approval_id = str(
            evidence.get("regression_override_approval_id")
            or nested_evidence.get("regression_override_approval_id")
            or waiver.get("approval_id")
            or ""
        ).strip()
        approver_role = str(
            evidence.get("regression_override_approver_role")
            or nested_evidence.get("regression_override_approver_role")
            or waiver.get("approver_role")
            or ""
        ).strip().lower()

        if not approval_id:
            raise ValueError("Promotion rejected: regression waiver requires approval_id.")
        if approver_role != "admin":
            raise ValueError("Promotion rejected: regression waiver requires approver_role=admin.")
        if len(reason) < MIN_REGRESSION_WAIVER_REASON_LENGTH:
            raise ValueError(
                "Promotion rejected: regression waiver reason must describe the bounded override "
                f"({MIN_REGRESSION_WAIVER_REASON_LENGTH}+ characters)."
            )

        return {
            "policy_id": REGRESSION_WAIVER_POLICY_ID,
            "status": "APPROVED",
            "approval_id": approval_id,
            "reason": reason,
            "approved_by": reviewer,
            "approver_role": approver_role,
            "approved_at": _now(),
            "evaluation_id": evaluation.eval_id,
            "regressed_cases": int(evaluation.regressed_cases or 0),
            "mode": "AUDITED_OVERRIDE",
        }

    async def create_version(
        self,
        description: str = "",
        source_patch_id: Optional[str] = None,
        created_by: str = "system",
        source_run_id: Optional[str] = None,
        source_case_id: Optional[str] = None,
        source_evaluation_id: Optional[str] = None,
        source_verdict_id: Optional[str] = None,
        scope: str = "knowledge_base",
        risk_boundary: str = "",
        approval_record: Optional[Dict[str, Any]] = None,
        rollback_impact: Optional[Dict[str, Any]] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            latest = await db.execute(
                select(func.max(KnowledgeVersionDB.version_number))
            )
            max_ver = latest.scalar() or 0
            next_ver = max_ver + 1

            active_patches_result = await db.execute(
                select(KnowledgePatchDB).where(KnowledgePatchDB.approval_status == "APPROVED")
            )
            active_patch_records = active_patches_result.scalars().all()
            active_patches = [p.patch_id for p in active_patch_records]

            active_rules: List[str] = []
            for p in active_patch_records:
                if p.patch_content:
                    rule_keys = [k for k in p.patch_content.keys() if k not in ("risk_note", "rollback_plan", "backtest_required")]
                    active_rules.extend(rule_keys)

            normalized_status = self._normalize_version_status(status)
            governance = self._build_governance_metadata(
                source_run_id=source_run_id,
                source_case_id=source_case_id,
                source_patch_id=source_patch_id,
                source_evaluation_id=source_evaluation_id,
                source_verdict_id=source_verdict_id,
                scope=scope,
                risk_boundary=risk_boundary,
                approval_record=approval_record or {},
                rollback_impact=rollback_impact or {},
                status=normalized_status,
            )

            patch_delta = {}
            if source_patch_id:
                patch_delta["source"] = source_patch_id
            patch_delta["governance"] = governance
            version_id = _generate_id("KBVER")
            regression_report = None
            if normalized_status in {"active", "review", "rolled_back"}:
                regression_report = await self._build_post_publish_regression_report(
                    db,
                    version_id=version_id,
                    version_number=next_ver,
                    active_patch_records=active_patch_records,
                    trigger="create_version",
                )
                governance["post_publish_regression"] = self._regression_summary(regression_report)
                patch_delta["governance"] = governance
                patch_delta["post_publish_regression"] = regression_report

            version = KnowledgeVersionDB(
                version_id=version_id,
                version_number=next_ver,
                version_label=f"v{next_ver}",
                snapshot={
                    "version": next_ver,
                    "patch_count": len(active_patches),
                    "timestamp": _now(),
                    "governance": governance,
                    "post_publish_regression": regression_report,
                },
                active_patches=active_patches,
                active_rules=active_rules,
                patch_delta=patch_delta,
                source_patch_id=source_patch_id,
                created_by=created_by,
                description=description or f"Knowledge base version {next_ver}",
                created_at=_now(),
            )
            db.add(version)
            await db.commit()
            await db.refresh(version)
            return self._version_to_dict(version)

    async def run_post_publish_regression(
        self,
        version_id: str,
        performed_by: str = "system",
    ) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            version_result = await db.execute(
                select(KnowledgeVersionDB).where(KnowledgeVersionDB.version_id == version_id)
            )
            version = version_result.scalar_one_or_none()
            if not version:
                raise KeyError(f"Version not found: {version_id}")

            snapshot = dict(version.snapshot or {})
            patch_delta = dict(version.patch_delta or {})
            governance = self._extract_governance(snapshot, patch_delta, version.source_patch_id)
            if governance.get("status") == "draft":
                raise ValueError("Draft versions cannot run post-publish regression")

            patch_ids = version.active_patches or []
            patch_records: List[KnowledgePatchDB] = []
            if patch_ids:
                patch_result = await db.execute(
                    select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id.in_(patch_ids))
                )
                patch_records = patch_result.scalars().all()

            report = await self._build_post_publish_regression_report(
                db,
                version_id=version.version_id,
                version_number=version.version_number,
                active_patch_records=patch_records,
                trigger="manual_rerun",
                performed_by=performed_by,
            )

            governance["post_publish_regression"] = self._regression_summary(report)
            snapshot["governance"] = governance
            snapshot["post_publish_regression"] = report
            patch_delta["governance"] = governance
            patch_delta["post_publish_regression"] = report
            version.snapshot = snapshot
            version.patch_delta = patch_delta
            await db.commit()
            await db.refresh(version)
            return self._version_to_dict(version)

    async def list_versions(self, limit: int = 20) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(KnowledgeVersionDB)
                .order_by(desc(KnowledgeVersionDB.version_number))
                .limit(limit)
            )
            records = result.scalars().all()
            return [self._version_to_dict(r) for r in records]

    async def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(KnowledgeVersionDB).where(KnowledgeVersionDB.version_id == version_id)
            )
            record = result.scalar_one_or_none()
            return self._version_to_dict(record) if record else None

    async def diff_versions(self, version_id_a: str, version_id_b: str) -> Dict[str, Any]:
        ver_a = await self.get_version(version_id_a)
        ver_b = await self.get_version(version_id_b)
        if not ver_a or not ver_b:
            raise KeyError("One or both versions not found")

        patches_a = set(ver_a.get("active_patches", []))
        patches_b = set(ver_b.get("active_patches", []))
        rules_a = set(ver_a.get("active_rules", []))
        rules_b = set(ver_b.get("active_rules", []))

        return {
            "version_a": {"id": ver_a["version_id"], "number": ver_a["version_number"]},
            "version_b": {"id": ver_b["version_id"], "number": ver_b["version_number"]},
            "patches_added": sorted(patches_b - patches_a),
            "patches_removed": sorted(patches_a - patches_b),
            "rules_added": sorted(rules_b - rules_a),
            "rules_removed": sorted(rules_a - rules_b),
            "patch_count_diff": len(patches_b) - len(patches_a),
        }

    async def rollback_to(
        self,
        version_id: str,
        performed_by: str = "human",
        approval_record: Optional[Dict[str, Any]] = None,
        rollback_impact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        target = await self.get_version(version_id)
        if not target:
            raise KeyError(f"Version not found: {version_id}")
        if target.get("status") == "draft":
            raise ValueError("Rollback rejected: draft versions cannot be rollback targets.")

        async with AsyncSessionLocal() as db:
            current_approved = await db.execute(
                select(KnowledgePatchDB).where(KnowledgePatchDB.approval_status == "APPROVED")
            )
            current_approved_records = current_approved.scalars().all()
            archived_patch_ids = [p.patch_id for p in current_approved_records]
            for p in current_approved_records:
                p.approval_status = "ARCHIVED"
                p.updated_at = _now()

            target_patches = target.get("active_patches", [])
            for patch_id in target_patches:
                patch_result = await db.execute(
                    select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id)
                )
                p = patch_result.scalar_one_or_none()
                if p:
                    p.approval_status = "APPROVED"
                    p.updated_at = _now()

            await db.commit()

            rollback_metadata = dict(rollback_impact or {})
            rollback_metadata["target_version_id"] = version_id
            rollback_metadata["target_version_number"] = target["version_number"]
            rollback_metadata["archived_patches"] = archived_patch_ids
            rollback_metadata["restored_patches"] = target_patches
            rollback_metadata["restored_patch_count"] = len(target_patches)

            approval_metadata = dict(approval_record or {})
            approval_metadata.pop("evidence_refs", None)
            approval_metadata["action"] = "ROLLBACK"
            approval_metadata["performed_by"] = performed_by
            approval_metadata["performed_at"] = _now()

            new_version = await self.create_version(
                description=f"Rollback to version {target['version_number']}",
                source_run_id=target.get("source_run_id"),
                source_case_id=target.get("source_case_id"),
                source_patch_id=target.get("source_patch_id"),
                source_evaluation_id=target.get("source_evaluation_id"),
                source_verdict_id=target.get("source_verdict_id"),
                scope=target.get("scope", "knowledge_base"),
                risk_boundary=target.get("risk_boundary", ""),
                approval_record=approval_metadata,
                rollback_impact=rollback_metadata,
                status="rolled_back",
                created_by=performed_by,
            )
            return {
                "rollback_target": target,
                "new_version": new_version,
                "restored_patches": len(target_patches),
            }

    def _merge_evidence_refs(
        self,
        existing_refs: Any,
        validated_refs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        candidates = list(existing_refs if isinstance(existing_refs, list) else []) + validated_refs
        for raw_ref in self._sanitize_approval_evidence_refs(candidates):
            source_type = str(raw_ref.get("source_type") or "").strip()
            source_id = str(raw_ref.get("source_id") or "").strip()
            key = (source_type, source_id)
            if key in seen:
                continue
            seen.add(key)
            refs.append(dict(raw_ref))
        return refs

    def _version_to_dict(self, record: KnowledgeVersionDB) -> Dict[str, Any]:
        snapshot = record.snapshot or {}
        patch_delta = record.patch_delta or {}
        snapshot_response = dict(snapshot)
        patch_delta_response = dict(patch_delta)
        self._apply_governance_approval_boundary(snapshot_response)
        self._apply_governance_approval_boundary(patch_delta_response)
        governance = self._extract_governance(snapshot, patch_delta, record.source_patch_id)
        source = governance.get("source", {})
        regression = (
            snapshot.get("post_publish_regression")
            or patch_delta.get("post_publish_regression")
            or governance.get("post_publish_regression")
        )
        if not isinstance(regression, dict) or not regression.get("report_id") or not regression.get("status"):
            regression = None
        else:
            regression = self._with_post_publish_regression_boundary(regression)
            regression_summary = self._regression_summary(regression)
            snapshot_response["post_publish_regression"] = regression
            patch_delta_response["post_publish_regression"] = regression
            snapshot_governance = dict(snapshot_response.get("governance") or {})
            patch_delta_governance = dict(patch_delta_response.get("governance") or {})
            governance = dict(governance)
            governance["post_publish_regression"] = regression_summary
            snapshot_governance["post_publish_regression"] = regression_summary
            patch_delta_governance["post_publish_regression"] = regression_summary
            snapshot_response["governance"] = snapshot_governance
            patch_delta_response["governance"] = patch_delta_governance
        approval_record = governance.get("approval_record", {})
        return {
            "version_id": record.version_id,
            "version_number": record.version_number,
            "version_label": record.version_label,
            "snapshot": snapshot_response,
            "active_patches": record.active_patches or [],
            "active_rules": record.active_rules or [],
            "patch_delta": patch_delta_response,
            "source_patch_id": source.get("patch_id") or record.source_patch_id,
            "source_run_id": source.get("run_id"),
            "source_case_id": source.get("case_id"),
            "source_evaluation_id": source.get("evaluation_id"),
            "source_verdict_id": source.get("verdict_id"),
            "scope": governance.get("scope", "knowledge_base"),
            "risk_boundary": governance.get("risk_boundary", ""),
            "approval_record": approval_record,
            "rollback_impact": governance.get("rollback_impact", {}),
            "post_publish_regression": regression,
            "status": governance.get("status", "active"),
            "evidence_usage": "review_gate_only",
            "evidence_strength": self._version_evidence_strength(
                status=governance.get("status", "active"),
                regression=regression,
                approval_record=approval_record if isinstance(approval_record, dict) else {},
                source=source,
            ),
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "created_by": record.created_by,
            "description": record.description,
            "created_at": record.created_at,
        }

    def _build_governance_metadata(
        self,
        source_run_id: Optional[str],
        source_case_id: Optional[str],
        source_patch_id: Optional[str],
        source_evaluation_id: Optional[str],
        source_verdict_id: Optional[str],
        scope: str,
        risk_boundary: str,
        approval_record: Dict[str, Any],
        rollback_impact: Dict[str, Any],
        status: str,
    ) -> Dict[str, Any]:
        return {
            "source": {
                "run_id": source_run_id,
                "case_id": source_case_id,
                "patch_id": source_patch_id,
                "evaluation_id": source_evaluation_id,
                "verdict_id": source_verdict_id,
            },
            "scope": scope or "knowledge_base",
            "risk_boundary": risk_boundary or "",
            "approval_record": approval_record or {},
            "rollback_impact": rollback_impact or {},
            "status": self._normalize_version_status(status),
        }

    def _extract_governance(
        self,
        snapshot: Dict[str, Any],
        patch_delta: Dict[str, Any],
        source_patch_id: Optional[str],
    ) -> Dict[str, Any]:
        governance: Dict[str, Any] = {}
        for source in (patch_delta.get("governance"), snapshot.get("governance")):
            if isinstance(source, dict):
                governance.update(source)

        source = dict(governance.get("source") or {})
        if source_patch_id and not source.get("patch_id"):
            source["patch_id"] = source_patch_id
        governance["source"] = source
        governance.setdefault("scope", "knowledge_base")
        governance.setdefault("risk_boundary", "")
        governance["approval_record"] = self._sanitize_approval_record(
            governance.get("approval_record")
        )
        governance.setdefault("rollback_impact", {})
        governance.setdefault("post_publish_regression", {})
        governance["status"] = self._normalize_version_status(governance.get("status", "active"))
        return governance

    def _apply_governance_approval_boundary(self, payload: Dict[str, Any]) -> None:
        governance = payload.get("governance")
        if not isinstance(governance, dict):
            return
        sanitized = dict(governance)
        sanitized["approval_record"] = self._sanitize_approval_record(
            sanitized.get("approval_record")
        )
        payload["governance"] = sanitized

    def _sanitize_approval_record(self, approval_record: Any) -> Dict[str, Any]:
        if not isinstance(approval_record, dict):
            return {}
        sanitized = dict(approval_record)
        evidence_refs = self._sanitize_approval_evidence_refs(sanitized.get("evidence_refs"))
        if evidence_refs:
            sanitized["evidence_refs"] = evidence_refs
        else:
            sanitized.pop("evidence_refs", None)
        return sanitized

    def _sanitize_approval_evidence_refs(self, raw_refs: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_refs, list):
            return []

        refs: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, dict):
                continue
            source_type = str(raw_ref.get("source_type") or raw_ref.get("type") or "").strip().lower()
            source_id = str(raw_ref.get("source_id") or raw_ref.get("id") or "").strip()
            if source_type not in KNOWLEDGE_VERSION_APPROVAL_REF_TYPES or not source_id:
                continue

            key = (source_type, source_id)
            if key in seen:
                continue
            seen.add(key)

            ref = dict(raw_ref)
            ref["source_type"] = source_type
            ref["source_id"] = source_id
            if "evidence_usage" in ref:
                ref["evidence_usage"] = "review_gate_only"
            if "evidence_strength" in ref:
                ref["evidence_strength"] = self._review_gate_evidence_strength(
                    ref.get("evidence_strength"),
                    default="LOW",
                )
            if "simulation_only" in ref:
                ref["simulation_only"] = True
            if "is_real_trade" in ref:
                ref["is_real_trade"] = False
            if "strong_conclusion_allowed" in ref:
                ref["strong_conclusion_allowed"] = False
            refs.append(ref)
        return refs

    def _normalize_version_status(self, status: Any) -> str:
        normalized = str(status or "active").lower()
        if normalized not in VERSION_STATUSES:
            return "draft"
        return normalized

    def _review_gate_evidence_strength(self, value: Any, default: str = "LOW") -> str:
        normalized = str(value or default or "").strip().upper()
        if normalized in {
            "HIGH",
            "STRONG",
            "PRIMARY",
            "PRIMARY_EVIDENCE",
            "PRIMARY_EVIDENCE_READY",
            "RESEARCH_GRADE",
            "PASS",
            "READY",
        }:
            return "MEDIUM"
        if normalized in {"MEDIUM", "LOW", "MISSING", "PENDING"}:
            return normalized
        if normalized in {"UNKNOWN", "SUPPORTING_ONLY", "REVIEW", "REVIEW_ONLY", "WARN"}:
            return "LOW"
        if normalized in {"FAIL", "FAILED", "BLOCKED"}:
            return "MISSING"
        return default

    def _with_post_publish_regression_boundary(self, report: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(report)
        normalized["evidence_usage"] = "review_gate_only"
        normalized["evidence_strength"] = self._review_gate_evidence_strength(
            normalized.get("evidence_strength"),
            default="LOW",
        )
        normalized["simulation_only"] = True
        normalized["is_real_trade"] = False
        normalized["strong_conclusion_allowed"] = False
        return normalized

    async def _build_post_publish_regression_report(
        self,
        db,
        *,
        version_id: str,
        version_number: int,
        active_patch_records: List[KnowledgePatchDB],
        trigger: str,
        performed_by: str = "system",
    ) -> Dict[str, Any]:
        cases_result = await db.execute(
            select(CaseLibraryDB)
            .where(CaseLibraryDB.review_status == "REVIEWED")
            .order_by(desc(CaseLibraryDB.updated_at))
            .limit(30)
        )
        cases = cases_result.scalars().all()
        patch_count = len(active_patch_records)
        case_count = len(cases)
        total_checks = patch_count * case_count
        per_patch: List[Dict[str, Any]] = []
        improved = 0
        regressed = 0
        unchanged = 0
        reviewed = 0
        affected_modules: set[str] = set()

        evaluator = EvaluationSandboxStore()
        for patch in active_patch_records:
            patch_improved = 0
            patch_regressed = 0
            patch_unchanged = 0
            patch_review = 0
            affected_modules.update(patch.affected_modules or [])
            sampled_cases = []
            for case in cases:
                result = evaluator._evaluate_single_case(case, patch)
                sampled_cases.append(
                    {
                        "case_id": result.get("case_id"),
                        "symbol": result.get("symbol"),
                        "verdict": result.get("verdict"),
                        "improvement": result.get("improvement"),
                    }
                )
                if result.get("verdict") == "REVIEW":
                    patch_review += 1
                    reviewed += 1
                if result.get("improvement") == "IMPROVED":
                    patch_improved += 1
                    improved += 1
                elif result.get("improvement") == "REGRESSED":
                    patch_regressed += 1
                    regressed += 1
                else:
                    patch_unchanged += 1
                    unchanged += 1
            per_patch.append(
                {
                    "patch_id": patch.patch_id,
                    "title": patch.title,
                    "affected_modules": patch.affected_modules or [],
                    "checked_cases": case_count,
                    "improved_cases": patch_improved,
                    "regressed_cases": patch_regressed,
                    "unchanged_cases": patch_unchanged,
                    "review_required_cases": patch_review,
                    "sampled_cases": sampled_cases[:10],
                }
            )

        denominator = total_checks or 1
        case_set_quality = self._build_case_set_quality(cases, sorted(affected_modules))
        case_set_quality_policy = self._build_case_set_quality_policy(case_set_quality)
        warnings: List[str] = []
        if not patch_count:
            warnings.append("no_active_patches")
        if not case_count:
            warnings.append("no_reviewed_cases")
        status = "PASS"
        if warnings:
            status = "WARN"
        elif regressed > 0:
            status = "REGRESSION"
        elif reviewed > 0:
            status = "REVIEW"
        knowledge_impact = self._build_knowledge_impact(
            status=status,
            affected_modules=sorted(affected_modules),
            patch_count=patch_count,
            case_count=case_count,
            total_checks=total_checks,
            improved=improved,
            regressed=regressed,
            reviewed=reviewed,
            warnings=warnings,
            case_set_quality=case_set_quality,
        )

        report = {
            "report_id": f"REG_{version_id}",
            "version_id": version_id,
            "version_number": version_number,
            "status": status,
            "trigger": trigger,
            "performed_by": performed_by,
            "generated_at": _now(),
            "representative_case_count": case_count,
            "active_patch_count": patch_count,
            "total_checks": total_checks,
            "improved_cases": improved,
            "regressed_cases": regressed,
            "unchanged_cases": unchanged,
            "review_required_cases": reviewed,
            "improvement_rate": round(improved / denominator, 4),
            "regression_rate": round(regressed / denominator, 4),
            "review_required_rate": round(reviewed / denominator, 4),
            "affected_modules": sorted(affected_modules),
            "warnings": warnings,
            "case_set_quality": case_set_quality,
            "case_set_quality_policy": case_set_quality_policy,
            "knowledge_impact": knowledge_impact,
            "evidence_usage": "review_gate_only",
            "evidence_strength": "LOW",
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "quality_warnings": case_set_quality.get("warnings", []),
            "per_patch": per_patch,
        }
        report["summary"] = (
            f"Post-publish regression for v{version_number}: "
            f"{patch_count} patch(es), {case_count} representative case(s), "
            f"improved={improved}, regressed={regressed}, review_required={reviewed}."
        )
        return report

    def _build_case_set_quality(
        self,
        cases: List[CaseLibraryDB],
        affected_modules: List[str],
    ) -> Dict[str, Any]:
        reviewed_case_count = len(cases)
        symbols = sorted({str(case.symbol or "").strip() for case in cases if str(case.symbol or "").strip()})
        incorrect_case_count = sum(1 for case in cases if case.conclusion_correct is False)
        insufficient_data_case_count = sum(1 for case in cases if case.data_sufficiency == "INSUFFICIENT")
        optimism_bias_case_count = sum(1 for case in cases if case.optimism_bias in ("MODERATE", "SEVERE"))
        affected = [str(module).strip() for module in affected_modules if str(module).strip()]
        module_corpus = [
            self._module_search_text(case)
            for case in cases
        ]
        covered_modules = [
            module
            for module in affected
            if any(self._normalize_module_marker(module) in corpus for corpus in module_corpus)
        ]
        missing_modules = [module for module in affected if module not in covered_modules]

        warnings: List[str] = []
        if reviewed_case_count == 0:
            warnings.append("no_reviewed_cases")
        elif reviewed_case_count < MIN_REPRESENTATIVE_CASES:
            warnings.append("low_representative_case_count")
        if reviewed_case_count > 0 and len(symbols) < MIN_REPRESENTATIVE_SYMBOLS:
            warnings.append("single_symbol_representative_cases")
        if reviewed_case_count > 0 and not (incorrect_case_count or insufficient_data_case_count or optimism_bias_case_count):
            warnings.append("no_failure_or_boundary_cases")
        if missing_modules:
            warnings.append(f"missing_affected_module_cases:{','.join(missing_modules[:5])}")

        if reviewed_case_count == 0:
            status = "EMPTY"
        elif warnings:
            status = "LOW_COVERAGE"
        else:
            status = "READY"

        return {
            "status": status,
            "reviewed_case_count": reviewed_case_count,
            "unique_symbol_count": len(symbols),
            "symbols": symbols[:10],
            "incorrect_case_count": incorrect_case_count,
            "insufficient_data_case_count": insufficient_data_case_count,
            "optimism_bias_case_count": optimism_bias_case_count,
            "affected_modules": affected,
            "covered_affected_modules": covered_modules,
            "missing_affected_modules": missing_modules,
            "warnings": warnings,
        }

    def _build_case_set_quality_policy(self, case_set_quality: Dict[str, Any]) -> Dict[str, Any]:
        quality_status = str(case_set_quality.get("status") or "UNKNOWN").upper()
        warnings = [
            str(item)
            for item in (case_set_quality.get("warnings") or [])
            if str(item).strip()
        ]
        if quality_status == "READY":
            action = "ALLOW"
            reason = "representative_case_set_ready"
        elif quality_status == "EMPTY":
            action = "WARN_ONLY"
            reason = "no_reviewed_cases_warn_only"
        else:
            action = "WARN_ONLY"
            reason = "low_coverage_warn_only"

        return {
            "policy_id": CASE_SET_QUALITY_POLICY_ID,
            "mode": "WARN_ONLY",
            "action": action,
            "blocking": False,
            "override_required": False,
            "minimum_reviewed_cases": MIN_REPRESENTATIVE_CASES,
            "minimum_unique_symbols": MIN_REPRESENTATIVE_SYMBOLS,
            "requires_failure_or_boundary_case": True,
            "requires_affected_module_coverage": True,
            "reason": reason,
            "warnings": warnings,
            "remediation": self._build_case_set_quality_remediation(case_set_quality, warnings),
        }

    def _build_case_set_quality_remediation(
        self,
        case_set_quality: Dict[str, Any],
        warnings: List[str],
    ) -> Dict[str, Any]:
        reviewed_cases = int(case_set_quality.get("reviewed_case_count") or 0)
        unique_symbols = int(case_set_quality.get("unique_symbol_count") or 0)
        failure_or_boundary_cases = int(case_set_quality.get("incorrect_case_count") or 0) + int(
            case_set_quality.get("insufficient_data_case_count") or 0
        ) + int(case_set_quality.get("optimism_bias_case_count") or 0)
        missing_modules = [
            str(module)
            for module in (case_set_quality.get("missing_affected_modules") or [])
            if str(module).strip()
        ]
        required_actions: List[str] = []
        next_actions: List[str] = []

        reviewed_delta = max(0, MIN_REPRESENTATIVE_CASES - reviewed_cases)
        symbol_delta = max(0, MIN_REPRESENTATIVE_SYMBOLS - unique_symbols)

        if "no_reviewed_cases" in warnings:
            required_actions.append("add_reviewed_cases")
            next_actions.append(f"Review at least {MIN_REPRESENTATIVE_CASES} representative cases before trusting regression rates.")
        elif reviewed_delta:
            required_actions.append("add_reviewed_cases")
            next_actions.append(f"Add {reviewed_delta} reviewed representative case(s) to reach the minimum case-set size.")

        if reviewed_cases > 0 and symbol_delta:
            required_actions.append("add_symbol_diversity")
            next_actions.append(f"Add reviewed cases from {symbol_delta} additional symbol(s) to reduce single-symbol bias.")

        if reviewed_cases > 0 and failure_or_boundary_cases == 0:
            required_actions.append("add_failure_or_boundary_case")
            next_actions.append("Add at least one incorrect, insufficient-data, or optimism-bias case to cover failure boundaries.")

        if missing_modules:
            required_actions.append("cover_affected_modules")
            next_actions.append(f"Add reviewed cases tagged for affected module(s): {', '.join(missing_modules[:5])}.")

        if not next_actions:
            next_actions.append("No representative-case remediation is required for the current warn-only policy.")

        return {
            "status": "ACTION_REQUIRED" if required_actions else "NOT_REQUIRED",
            "owner": "case_library_reviewer",
            "required_actions": required_actions,
            "next_actions": next_actions,
            "required_reviewed_case_delta": reviewed_delta,
            "required_unique_symbol_delta": symbol_delta if reviewed_cases > 0 else MIN_REPRESENTATIVE_SYMBOLS,
            "missing_affected_modules": missing_modules,
            "target_case_mix": {
                "minimum_reviewed_cases": MIN_REPRESENTATIVE_CASES,
                "minimum_unique_symbols": MIN_REPRESENTATIVE_SYMBOLS,
                "requires_failure_or_boundary_case": True,
                "requires_affected_module_coverage": True,
            },
        }

    def _build_knowledge_impact(
        self,
        *,
        status: str,
        affected_modules: List[str],
        patch_count: int,
        case_count: int,
        total_checks: int,
        improved: int,
        regressed: int,
        reviewed: int,
        warnings: List[str],
        case_set_quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        quality_warnings = [
            str(item)
            for item in (case_set_quality.get("warnings") or [])
            if str(item).strip()
        ]
        quality_status = str(case_set_quality.get("status") or "UNKNOWN").upper()

        if patch_count <= 0:
            impact_status = "NO_ACTIVE_PATCHES"
            risk_level = "MEDIUM"
            action = "add_reviewed_patch_before_trusting_impact"
            strongest_signal = "missing_patch"
        elif case_count <= 0:
            impact_status = "NO_REVIEWED_CASES"
            risk_level = "MEDIUM"
            action = "add_representative_cases_before_trusting_impact"
            strongest_signal = "missing_case_set"
        elif regressed > 0:
            impact_status = "REGRESSION_ATTENTION"
            risk_level = "HIGH"
            action = "review_regressions_before_policy_trust"
            strongest_signal = "regression"
        elif reviewed > 0:
            impact_status = "REVIEW_ATTENTION"
            risk_level = "MEDIUM"
            action = "review_uncertain_cases_before_policy_trust"
            strongest_signal = "review_required"
        elif warnings or quality_warnings or quality_status != "READY":
            impact_status = "COVERAGE_LIMITED"
            risk_level = "MEDIUM"
            action = "expand_representative_case_set"
            strongest_signal = "case_set_quality"
        elif improved > 0:
            impact_status = "IMPROVING"
            risk_level = "LOW"
            action = "monitor_post_publish_impact"
            strongest_signal = "improvement"
        else:
            impact_status = "NO_MEASURABLE_CHANGE"
            risk_level = "LOW"
            action = "monitor_post_publish_impact"
            strongest_signal = "unchanged"

        return {
            "policy_id": KNOWLEDGE_IMPACT_POLICY_ID,
            "mode": "OBSERVATION_ONLY",
            "status": impact_status,
            "source_status": status,
            "risk_level": risk_level,
            "action": action,
            "strongest_signal": strongest_signal,
            "requires_human_review": risk_level in {"HIGH", "MEDIUM"},
            "auto_blocks_promotion": False,
            "evidence_basis": "post_publish_regression_report",
            "affected_module_count": len(affected_modules),
            "top_affected_modules": affected_modules[:5],
            "active_patch_count": patch_count,
            "representative_case_count": case_count,
            "total_checks": total_checks,
            "improved_cases": improved,
            "regressed_cases": regressed,
            "review_required_cases": reviewed,
            "net_improvement_cases": improved - regressed,
        }

    def _module_search_text(self, case: CaseLibraryDB) -> str:
        parts: List[str] = []
        parts.extend(str(item) for item in (case.tags or []))
        parts.extend(str(item) for item in (case.key_lessons or []))
        parts.append(str(case.review_note or ""))
        parts.append(str(case.market_context or ""))
        return self._normalize_module_marker(" ".join(parts))

    def _normalize_module_marker(self, value: Any) -> str:
        return (
            str(value or "")
            .strip()
            .lower()
            .replace("_", "")
            .replace("-", "")
            .replace(" ", "")
        )

    def _regression_summary(self, report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not report:
            return {}
        bounded_report = self._with_post_publish_regression_boundary(report)
        return {
            "report_id": bounded_report.get("report_id"),
            "status": bounded_report.get("status"),
            "generated_at": bounded_report.get("generated_at"),
            "representative_case_count": bounded_report.get("representative_case_count", 0),
            "active_patch_count": bounded_report.get("active_patch_count", 0),
            "total_checks": bounded_report.get("total_checks", 0),
            "improved_cases": bounded_report.get("improved_cases", 0),
            "regressed_cases": bounded_report.get("regressed_cases", 0),
            "unchanged_cases": bounded_report.get("unchanged_cases", 0),
            "review_required_cases": bounded_report.get("review_required_cases", 0),
            "improvement_rate": bounded_report.get("improvement_rate", 0.0),
            "regression_rate": bounded_report.get("regression_rate", 0.0),
            "review_required_rate": bounded_report.get("review_required_rate", 0.0),
            "affected_modules": bounded_report.get("affected_modules", []),
            "warnings": bounded_report.get("warnings", []),
            "case_set_quality": bounded_report.get("case_set_quality", {}),
            "case_set_quality_policy": bounded_report.get("case_set_quality_policy", {}),
            "knowledge_impact": bounded_report.get("knowledge_impact", {}),
            "evidence_usage": bounded_report.get("evidence_usage", "review_gate_only"),
            "evidence_strength": bounded_report.get("evidence_strength", "LOW"),
            "simulation_only": bounded_report.get("simulation_only", True),
            "is_real_trade": bounded_report.get("is_real_trade", False),
            "strong_conclusion_allowed": bounded_report.get("strong_conclusion_allowed", False),
            "quality_warnings": bounded_report.get("quality_warnings", []),
            "summary": bounded_report.get("summary", ""),
        }


evaluation_sandbox_store = EvaluationSandboxStore()
knowledge_version_store = KnowledgeVersionStore()
