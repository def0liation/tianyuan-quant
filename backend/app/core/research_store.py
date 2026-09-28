import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import desc, func, select

from ..db.models_research import (
    ResearchEvidenceLinkDB,
    ResearchFeedbackEventDB,
    ResearchIterationDB,
    ResearchLoopDB,
)
from ..db.session import AsyncSessionLocal
from ..core.agent_runtime_store import load_persisted_runs
from ..core.analysis_run_registry import get_run, iter_runs
from ..core.backtest_store import MFE_MAE_RESEARCH_SOURCE, backtest_store
from ..core.bottom_research import normalize_bottom_research_config
from ..core.evaluation_store import evaluation_sandbox_store
from ..core.signalops_store import signalops_store
from ..models.research import (
    ArchiveResearchLoopRequest,
    AttachResearchBacktestRequest,
    AttachResearchRunRequest,
    CreateNextResearchIterationRequest,
    CreateResearchIterationRequest,
    CreateResearchLoopRequest,
    CreateSampleResearchLoopRequest,
    CreateSampleResearchLoopResponse,
    ResearchEvidenceLink,
    ResearchFeedbackEvent,
    ResearchIteration,
    ResearchIterationFeedbackRequest,
    ResearchLoop,
    ResearchLoopDetail,
    ResearchSummary,
    ResearchWorkflowState,
    ResearchWorkflowStep,
    UpdateResearchIterationRequest,
    UpdateResearchLoopRequest,
)


LINKED_RUN_REJECTED_WARNING = "linked_run_id_missing_or_legacy_ignored"
LINKED_BACKTEST_REJECTED_WARNING = "linked_backtest_id_missing_ignored"
LEGACY_METRICS_EVIDENCE_REFS_WARNING = (
    "metrics.evidence_refs are compatibility-only; attach first-class evidence_links before verdict review."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


class ResearchLoopStore:
    async def get_summary(self) -> ResearchSummary:
        async with AsyncSessionLocal() as db:
            total_loops = await db.execute(select(func.count()).select_from(ResearchLoopDB))
            active_loops = await db.execute(
                select(func.count()).select_from(ResearchLoopDB).where(ResearchLoopDB.status == "ACTIVE")
            )
            paused_loops = await db.execute(
                select(func.count()).select_from(ResearchLoopDB).where(ResearchLoopDB.status == "PAUSED")
            )
            completed_loops = await db.execute(
                select(func.count()).select_from(ResearchLoopDB).where(ResearchLoopDB.status == "COMPLETED")
            )
            total_iterations = await db.execute(select(func.count()).select_from(ResearchIterationDB))
            pending_iterations = await db.execute(
                select(func.count()).select_from(ResearchIterationDB).where(ResearchIterationDB.verdict == "PENDING")
            )
            accepted_iterations = await db.execute(
                select(func.count()).select_from(ResearchIterationDB).where(ResearchIterationDB.verdict == "ACCEPTED")
            )
            rejected_iterations = await db.execute(
                select(func.count()).select_from(ResearchIterationDB).where(ResearchIterationDB.verdict == "REJECTED")
            )
            patch_required_iterations = await db.execute(
                select(func.count()).select_from(ResearchIterationDB).where(ResearchIterationDB.verdict == "PATCH_REQUIRED")
            )
            loops = await db.execute(select(ResearchLoopDB))
            linked_project_keys = {
                f"{item.get('project')}:{item.get('module')}:{item.get('path')}"
                for loop in loops.scalars().all()
                for item in (loop.linked_projects or [])
            }

            return ResearchSummary(
                total_loops=total_loops.scalar() or 0,
                active_loops=active_loops.scalar() or 0,
                paused_loops=paused_loops.scalar() or 0,
                completed_loops=completed_loops.scalar() or 0,
                total_iterations=total_iterations.scalar() or 0,
                pending_iterations=pending_iterations.scalar() or 0,
                accepted_iterations=accepted_iterations.scalar() or 0,
                rejected_iterations=rejected_iterations.scalar() or 0,
                patch_required_iterations=patch_required_iterations.scalar() or 0,
                linked_project_count=len(linked_project_keys),
                updated_at=_now(),
            )

    async def list_loops(self, status: Optional[str] = None) -> list[ResearchLoop]:
        async with AsyncSessionLocal() as db:
            query = select(ResearchLoopDB)
            if status:
                query = query.where(ResearchLoopDB.status == status)
            query = query.order_by(desc(ResearchLoopDB.updated_at))
            result = await db.execute(query)
            records = result.scalars().all()
            return [await self._loop_to_model(record) for record in records]

    async def get_loop_detail(self, loop_id: str) -> Optional[ResearchLoopDetail]:
        async with AsyncSessionLocal() as db:
            loop_result = await db.execute(select(ResearchLoopDB).where(ResearchLoopDB.loop_id == loop_id))
            loop = loop_result.scalar_one_or_none()
            if not loop:
                return None
            iteration_result = await db.execute(
                select(ResearchIterationDB)
                .where(ResearchIterationDB.loop_id == loop_id)
                .order_by(ResearchIterationDB.iteration_number)
            )
            loop_model = await self._loop_to_model(loop)
            iterations = [self._iteration_to_model(record) for record in iteration_result.scalars().all()]
            return ResearchLoopDetail(
                loop=loop_model,
                iterations=iterations,
                workflow_state=await self._build_workflow_state(loop_model, iterations),
            )

    async def list_iterations(self, loop_id: Optional[str] = None) -> list[ResearchIteration]:
        async with AsyncSessionLocal() as db:
            query = select(ResearchIterationDB)
            if loop_id:
                query = query.where(ResearchIterationDB.loop_id == loop_id)
            query = query.order_by(ResearchIterationDB.loop_id, ResearchIterationDB.iteration_number)
            result = await db.execute(query)
            return [self._iteration_to_model(record) for record in result.scalars().all()]

    async def get_iteration(self, iteration_id: str) -> Optional[ResearchIteration]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ResearchIterationDB).where(ResearchIterationDB.iteration_id == iteration_id)
            )
            record = result.scalar_one_or_none()
            return self._iteration_to_model(record) if record else None

    async def create_loop(self, request: CreateResearchLoopRequest) -> ResearchLoopDetail:
        title = request.title.strip()
        objective = request.objective.strip()
        if not title:
            raise ValueError("title is required")
        if not objective:
            raise ValueError("objective is required")

        async with AsyncSessionLocal() as db:
            now = _now()
            loop = ResearchLoopDB(
                loop_id=_generate_id("RLOOP"),
                title=title,
                objective=objective,
                status="ACTIVE",
                action_target=request.action_target.strip() or "factor",
                owner=request.owner.strip() or "human",
                tags=[tag.strip() for tag in request.tags if tag.strip()],
                linked_projects=[_model_to_dict(item) for item in request.linked_projects],
                source="super",
                created_at=now,
                updated_at=now,
            )
            db.add(loop)
            await db.flush()

            if request.hypothesis.strip():
                iteration = self._build_iteration_record(
                    loop.loop_id,
                    1,
                    CreateResearchIterationRequest(
                        hypothesis=request.hypothesis,
                        plan=request.plan,
                        target_modules=request.target_modules,
                    ),
                )
                db.add(iteration)
                loop.current_iteration_id = iteration.iteration_id

            await db.commit()

        detail = await self.get_loop_detail(loop.loop_id)
        if detail is None:
            raise RuntimeError("Research loop was not persisted")
        return detail

    async def update_loop(
        self,
        loop_id: str,
        request: UpdateResearchLoopRequest,
    ) -> Optional[ResearchLoopDetail]:
        updates = _model_update_dict(request)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ResearchLoopDB).where(ResearchLoopDB.loop_id == loop_id))
            loop = result.scalar_one_or_none()
            if not loop:
                return None

            if "title" in updates and updates["title"] is not None:
                title = str(updates["title"]).strip()
                if not title:
                    raise ValueError("title is required")
                loop.title = title
            if "objective" in updates and updates["objective"] is not None:
                objective = str(updates["objective"]).strip()
                if not objective:
                    raise ValueError("objective is required")
                loop.objective = objective
            if "status" in updates and updates["status"] is not None:
                loop.status = str(updates["status"]).strip().upper() or loop.status
                if loop.status in {"COMPLETED", "ARCHIVED"}:
                    loop.completed_at = _now()
            if "action_target" in updates and updates["action_target"] is not None:
                loop.action_target = str(updates["action_target"]).strip() or loop.action_target
            if "owner" in updates and updates["owner"] is not None:
                loop.owner = str(updates["owner"]).strip() or loop.owner
            if "tags" in updates:
                loop.tags = [str(tag).strip() for tag in (updates["tags"] or []) if str(tag).strip()]
            if "linked_projects" in updates:
                loop.linked_projects = [
                    _model_to_dict(item) for item in (updates["linked_projects"] or [])
                ]
            loop.updated_at = _now()
            await db.commit()

        return await self.get_loop_detail(loop_id)

    async def archive_loop(
        self,
        loop_id: str,
        request: ArchiveResearchLoopRequest,
    ) -> Optional[ResearchLoopDetail]:
        detail = await self.update_loop(loop_id, UpdateResearchLoopRequest(status="ARCHIVED"))
        if detail is None:
            return None
        if detail.loop.current_iteration_id:
            await self.record_feedback(
                detail.loop.current_iteration_id,
                ResearchIterationFeedbackRequest(
                    action="ARCHIVE_LOOP",
                    verdict="PENDING",
                    status="ARCHIVED",
                    note=request.note or "Research loop archived.",
                    reviewer=request.reviewer,
                ),
            )
            refreshed = await self.get_loop_detail(loop_id)
            return refreshed or detail
        return detail

    async def create_iteration(
        self,
        loop_id: str,
        request: CreateResearchIterationRequest,
    ) -> Optional[ResearchIteration]:
        if not request.hypothesis.strip():
            raise ValueError("hypothesis is required")

        async with AsyncSessionLocal() as db:
            loop_result = await db.execute(select(ResearchLoopDB).where(ResearchLoopDB.loop_id == loop_id))
            loop = loop_result.scalar_one_or_none()
            if not loop:
                return None
            max_order = await db.execute(
                select(func.max(ResearchIterationDB.iteration_number)).where(ResearchIterationDB.loop_id == loop_id)
            )
            next_order = (max_order.scalar() or 0) + 1
            iteration = self._build_iteration_record(loop_id, next_order, request)
            db.add(iteration)
            loop.current_iteration_id = iteration.iteration_id
            loop.updated_at = iteration.updated_at
            await db.commit()
            await db.refresh(iteration)
            return self._iteration_to_model(iteration)

    async def update_iteration(
        self,
        iteration_id: str,
        request: UpdateResearchIterationRequest,
    ) -> Optional[ResearchIteration]:
        updates = _model_update_dict(request)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ResearchIterationDB).where(ResearchIterationDB.iteration_id == iteration_id))
            iteration = result.scalar_one_or_none()
            if not iteration:
                return None

            if "status" in updates and updates["status"] is not None:
                iteration.status = str(updates["status"]).strip().upper() or iteration.status
            if "hypothesis" in updates and updates["hypothesis"] is not None:
                hypothesis = str(updates["hypothesis"]).strip()
                if not hypothesis:
                    raise ValueError("hypothesis is required")
                iteration.hypothesis = hypothesis
            if "plan" in updates:
                iteration.plan = "" if updates["plan"] is None else str(updates["plan"]).strip()
            if "target_modules" in updates:
                iteration.target_modules = [
                    str(module).strip() for module in (updates["target_modules"] or []) if str(module).strip()
                ]
            if "linked_run_id" in updates:
                linked_run_id = self._normalize_linked_run_id(updates["linked_run_id"])
                if str(updates["linked_run_id"] or "").strip() and not linked_run_id:
                    iteration.metrics = self._metrics_with_warning(
                        iteration.metrics,
                        LINKED_RUN_REJECTED_WARNING,
                    )
                iteration.linked_run_id = linked_run_id
            if "linked_backtest_id" in updates:
                linked_backtest_id = await self._normalize_linked_backtest_id(updates["linked_backtest_id"])
                if str(updates["linked_backtest_id"] or "").strip() and not linked_backtest_id:
                    iteration.metrics = self._metrics_with_warning(
                        iteration.metrics,
                        LINKED_BACKTEST_REJECTED_WARNING,
                    )
                iteration.linked_backtest_id = linked_backtest_id
            for field in [
                "linked_case_id",
                "linked_knowledge_item_id",
                "linked_patch_id",
            ]:
                if field in updates:
                    setattr(iteration, field, updates[field])
            if "metrics" in updates:
                iteration.metrics = (
                    {}
                    if updates["metrics"] is None
                    else {**(iteration.metrics or {}), **(updates["metrics"] or {})}
                )
            if "verdict" in updates and updates["verdict"] is not None:
                iteration.verdict = str(updates["verdict"]).strip().upper() or iteration.verdict
            iteration.updated_at = _now()
            if iteration.status in {"ACCEPTED", "REJECTED", "PATCH_REQUIRED", "ARCHIVED"}:
                iteration.completed_at = iteration.completed_at or iteration.updated_at

            loop_result = await db.execute(select(ResearchLoopDB).where(ResearchLoopDB.loop_id == iteration.loop_id))
            loop = loop_result.scalar_one_or_none()
            if loop:
                loop.current_iteration_id = iteration.iteration_id
                loop.updated_at = iteration.updated_at

            await db.commit()
            await db.refresh(iteration)
            return self._iteration_to_model(iteration)

    async def attach_run(
        self,
        iteration_id: str,
        request: AttachResearchRunRequest,
    ) -> Optional[ResearchIteration]:
        run_id = request.run_id.strip()
        if not run_id:
            raise ValueError("run_id is required")
        evidence_links = request.evidence_links or [
            ResearchEvidenceLink(
                source_type="RUN",
                source_id=run_id,
                label="Attached analysis run",
                quality="UNKNOWN",
                created_at=_now(),
            )
        ]
        return await self.record_feedback(
            iteration_id,
            ResearchIterationFeedbackRequest(
                action="ATTACH_RUN",
                verdict="PENDING",
                status=request.status,
                note=request.note or f"Attached analysis run {run_id}.",
                reviewer=request.reviewer,
                linked_run_id=run_id,
                metrics=request.metrics,
                evidence_links=evidence_links,
            ),
        )

    async def attach_backtest(
        self,
        iteration_id: str,
        request: AttachResearchBacktestRequest,
    ) -> Optional[ResearchIteration]:
        backtest_run_id = request.backtest_run_id.strip()
        if not backtest_run_id:
            raise ValueError("backtest_run_id is required")
        backtest_role = _backtest_role(request.metrics.get("backtest_role") or request.role)
        backtest_run = await backtest_store.get_run(backtest_run_id)
        backtest_report = (backtest_run or {}).get("report") or {}
        evidence_strength = _backtest_evidence_payload(backtest_report)
        evidence_quality = _backtest_evidence_strength(backtest_report) if backtest_run else "UNKNOWN"
        reported_quality = _backtest_reported_evidence_quality(evidence_strength, evidence_quality)
        review_conclusion = _backtest_review_conclusion(evidence_strength, request.review_conclusion)
        evidence_links = request.evidence_links or [
            ResearchEvidenceLink(
                source_type="BACKTEST",
                source_id=backtest_run_id,
                label=f"Attached {backtest_role} backtest result",
                quality=evidence_quality,
                reported_quality=reported_quality,
                created_at=_now(),
            )
        ]
        metrics = {
            **(request.metrics or {}),
            "backtest_role": backtest_role,
            "backtest_run_id": backtest_run_id,
            f"{backtest_role}_backtest_id": backtest_run_id,
            f"{backtest_role}_backtest_review_conclusion": review_conclusion,
        }
        if backtest_run:
            metrics.update(
                {
                    f"{backtest_role}_backtest_evidence_strength": evidence_strength,
                    "backtest_evidence_strength": evidence_strength,
                    "backtest_review_conclusion": review_conclusion,
                    "backtest_supporting_only": review_conclusion == "SUPPORTING_ONLY",
                }
            )
        return await self.record_feedback(
            iteration_id,
            ResearchIterationFeedbackRequest(
                action="ATTACH_BACKTEST",
                verdict="PENDING",
                status=request.status,
                note=request.note or f"Attached backtest result {backtest_run_id}.",
                reviewer=request.reviewer,
                linked_backtest_id=backtest_run_id,
                metrics=metrics,
                evidence_links=evidence_links,
            ),
        )

    async def attach_signalops_evidence(
        self,
        iteration_id: str,
        signal_id: str,
        *,
        reviewer: str = "human",
        note: str = "",
    ) -> Optional[ResearchIteration]:
        normalized_signal_id = signal_id.strip()
        if not normalized_signal_id:
            raise ValueError("signal_id is required")
        detail = await signalops_store.get_signal_detail(normalized_signal_id)
        if not detail:
            raise ValueError("SignalOps signal not found")

        from .auto_paper_trading import auto_paper_trading_store

        status = auto_paper_trading_store.get_status()
        signal = _metric_mapping(detail.get("signal"))
        transitions = detail.get("transitions") if isinstance(detail.get("transitions"), list) else []
        reviews = detail.get("reviews") if isinstance(detail.get("reviews"), list) else []
        tick = _signalops_tick_for_signal(normalized_signal_id, _metric_mapping(status.get("last_tick_result")))
        decision_card = _first_mapping(
            tick.get("decision_card"),
            _metric_mapping(tick.get("decision")).get("decision_card"),
        )
        module_evidence = _metric_mapping(tick.get("module_evidence"))
        portfolio_snapshot = _metric_mapping(tick.get("portfolio_snapshot"))
        symbol = str(signal.get("symbol") or tick.get("symbol") or "").strip()
        tick_at = str(tick.get("updated_at") or status.get("last_tick_at") or signal.get("updated_at") or _now())
        evidence_quality = _signalops_evidence_quality(signal, tick, transitions, reviews)
        evidence_links = [
            ResearchEvidenceLink(
                source_type="SIGNALOPS",
                source_id=normalized_signal_id,
                label=f"SignalOps lifecycle evidence {symbol or normalized_signal_id}",
                quality=evidence_quality,
                created_at=str(signal.get("updated_at") or tick_at),
            ),
            ResearchEvidenceLink(
                source_type="SIGNALOPS_TICK",
                source_id=f"{normalized_signal_id}:{tick_at}",
                label=f"SignalOps tick evidence {symbol or normalized_signal_id}",
                quality=evidence_quality,
                created_at=tick_at,
            ),
        ]
        metrics = {
            "signalops_signal_id": normalized_signal_id,
            "signalops_symbol": symbol,
            "signalops_status": str(signal.get("status") or ""),
            "signalops_latest_run_id": str(signal.get("latest_run_id") or signal.get("source_run_id") or ""),
            "signalops_tick_status": str(tick.get("status") or "MISSING"),
            "signalops_tick_message": str(tick.get("message") or ""),
            "signalops_tick_updated_at": tick_at,
            "signalops_tick_evidence_available": bool(tick),
            "signalops_decision_action": str(decision_card.get("action") or ""),
            "signalops_decision_reason": str(decision_card.get("reason") or decision_card.get("action_reason") or ""),
            "signalops_module_evidence_version": str(module_evidence.get("version") or ""),
            "signalops_portfolio_snapshot_id": str(
                portfolio_snapshot.get("snapshot_id")
                or portfolio_snapshot.get("portfolio_snapshot_id")
                or ""
            ),
            "signalops_review_count": len(reviews),
            "signalops_transition_count": len(transitions),
            "signalops_evidence_quality": evidence_quality,
            "signalops_evidence_usage": "supporting_only",
            "signalops_supporting_only": True,
            "simulation_only": True,
            "is_real_trade": False,
        }
        return await self.record_feedback(
            iteration_id,
            ResearchIterationFeedbackRequest(
                action="ATTACH_SIGNALOPS_EVIDENCE",
                verdict="PENDING",
                status="SIGNALOPS_EVIDENCE_ATTACHED",
                note=note or f"Attached SignalOps tick evidence from {normalized_signal_id}.",
                reviewer=reviewer,
                metrics=metrics,
                evidence_links=evidence_links,
            ),
        )

    async def close_bottom_research_backtest(
        self,
        iteration_id: str,
        *,
        run_id: Optional[str] = None,
        run_data: Optional[dict[str, Any]] = None,
        force_new: bool = False,
        reviewer: str = "system",
    ) -> Optional[ResearchIteration]:
        iteration = await self.get_iteration(iteration_id)
        if iteration is None:
            return None

        requested_run_id = str(run_id or (run_data or {}).get("runId") or iteration.linked_run_id or "").strip()
        run = run_data if isinstance(run_data, dict) and run_data.get("runId") else None
        if run is None and requested_run_id:
            run = self._run_by_id(requested_run_id)
        if not run:
            return None

        actual_run_id = str(run.get("runId") or requested_run_id).strip()
        if not self._run_matches_iteration(iteration, run):
            return await self._record_bottom_research_backtest_warning(
                iteration,
                actual_run_id,
                "run_not_linked_to_research_iteration",
                reviewer=reviewer,
            )

        bottom = (
            run.get("mfeMaeResearch")
            if isinstance(run.get("mfeMaeResearch"), dict)
            else run.get("bottomResearch")
            if isinstance(run.get("bottomResearch"), dict)
            else {}
        )
        bottom_status = str(bottom.get("status") or "").strip().upper()
        if bottom_status not in {"PASS", "WARN"}:
            return await self._record_bottom_research_backtest_warning(
                iteration,
                actual_run_id,
                f"mfe_mae_research_status_not_usable:{bottom_status or 'MISSING'}",
                reviewer=reviewer,
            )

        provenance = bottom.get("provenance") if isinstance(bottom.get("provenance"), dict) else {}
        start_date = str(provenance.get("firstTradeDate") or "").strip()
        end_date = str(provenance.get("lastTradeDate") or "").strip()
        if not start_date or not end_date:
            return await self._record_bottom_research_backtest_warning(
                iteration,
                actual_run_id,
                "mfe_mae_research_backtest_window_missing",
                reviewer=reviewer,
            )

        symbol = str(run.get("stockCode") or run.get("symbol") or "").strip()
        if not symbol:
            return await self._record_bottom_research_backtest_warning(
                iteration,
                actual_run_id,
                "mfe_mae_research_symbol_missing",
                reviewer=reviewer,
            )

        bottom_config = normalize_bottom_research_config(
            run.get("bottomResearchConfig")
            if isinstance(run.get("bottomResearchConfig"), dict)
            else bottom.get("config") if isinstance(bottom.get("config"), dict) else None,
            symbol=symbol,
        )
        parameters = {
            "signal_source": MFE_MAE_RESEARCH_SOURCE,
            "data_source": "AUTO",
            "bottom_research_config": bottom_config,
            "source_run_id": actual_run_id,
            "research_iteration_id": iteration.iteration_id,
            "simulation_only": True,
            "is_real_trade": False,
        }
        try:
            backtest_run = await backtest_store.create_run(
                symbol=symbol,
                stock_name=str(run.get("stockName") or ""),
                start_date=start_date,
                end_date=end_date,
                scenario_label="MFE/MAE Path Research auto evidence",
                parameters=parameters,
                reuse_existing=True,
                force_new=force_new,
            )
        except Exception as exc:
            return await self._record_bottom_research_backtest_warning(
                iteration,
                actual_run_id,
                "mfe_mae_research_backtest_error",
                detail=str(exc),
                reviewer=reviewer,
            )

        backtest_id = str(backtest_run.get("run_id") or "").strip()
        if not backtest_id:
            return await self._record_bottom_research_backtest_warning(
                iteration,
                actual_run_id,
                "mfe_mae_research_backtest_id_missing",
                reviewer=reviewer,
            )

        metrics = _bottom_research_iteration_metrics(
            bottom=bottom,
            backtest_run=backtest_run,
            run_id=actual_run_id,
            start_date=start_date,
            end_date=end_date,
        )
        backtest_report = (backtest_run.get("report") or {})
        backtest_evidence_payload = _backtest_evidence_payload(backtest_report)
        backtest_quality = _backtest_evidence_strength(backtest_report)
        evidence_links = [
            ResearchEvidenceLink(
                source_type="MFE_MAE_RESEARCH_RUN",
                source_id=actual_run_id,
                label="MFE/MAE Path Research analysis output",
                quality=_bottom_research_evidence_quality(bottom),
                created_at=_now(),
            ),
            ResearchEvidenceLink(
                source_type="BACKTEST",
                source_id=backtest_id,
                label="MFE/MAE Path Research automatic backtest",
                quality=backtest_quality,
                reported_quality=_backtest_reported_evidence_quality(backtest_evidence_payload, backtest_quality),
                created_at=str(backtest_run.get("updated_at") or _now()),
            ),
        ]
        return await self.record_feedback(
            iteration.iteration_id,
            ResearchIterationFeedbackRequest(
                action="MFE_MAE_RESEARCH_BACKTEST_LINKED",
                verdict=iteration.verdict or "PENDING",
                status=iteration.status,
                note=f"Linked MFE/MAE Path Research run {actual_run_id} to backtest {backtest_id}.",
                reviewer=reviewer or "system",
                linked_run_id=actual_run_id,
                linked_backtest_id=backtest_id,
                metrics=metrics,
                evidence_links=evidence_links,
            ),
        )

    async def _record_bottom_research_backtest_warning(
        self,
        iteration: ResearchIteration,
        run_id: str,
        warning: str,
        *,
        detail: str = "",
        reviewer: str = "system",
    ) -> Optional[ResearchIteration]:
        warnings = _dedupe([
            *_strings_from_metric(iteration.metrics.get("warnings")),
            warning,
        ])
        metrics: dict[str, Any] = {
            "bottom_research_backtest_warning": warning,
            "mfe_mae_research_backtest_warning": warning,
            "bottom_research_run_id": run_id or None,
            "mfe_mae_research_run_id": run_id or None,
            "bottom_research_supporting_only": True,
            "mfe_mae_research_supporting_only": True,
            "simulation_only": True,
            "is_real_trade": False,
            "warnings": warnings,
        }
        if detail:
            metrics["bottom_research_backtest_error"] = detail
            metrics["mfe_mae_research_backtest_error"] = detail
        return await self.record_feedback(
            iteration.iteration_id,
            ResearchIterationFeedbackRequest(
                action="MFE_MAE_RESEARCH_BACKTEST_SKIPPED",
                verdict=iteration.verdict or "PENDING",
                status=iteration.status,
                note=f"MFE/MAE Path Research backtest skipped: {warning}.",
                reviewer=reviewer or "system",
                linked_run_id=run_id or iteration.linked_run_id,
                metrics=metrics,
            ),
        )

    async def create_next_iteration(
        self,
        parent_iteration_id: str,
        request: CreateNextResearchIterationRequest,
    ) -> Optional[ResearchIteration]:
        parent = await self.get_iteration(parent_iteration_id)
        if not parent:
            return None
        hypothesis = (
            (request.hypothesis or "").strip()
            or str(parent.metrics.get("next_hypothesis") or "").strip()
            or f"Follow-up iteration after {parent_iteration_id}"
        )
        target_modules = request.target_modules or parent.target_modules
        next_iteration = await self.create_iteration(
            parent.loop_id,
            CreateResearchIterationRequest(
                hypothesis=hypothesis,
                plan=request.plan or parent.plan,
                target_modules=target_modules,
                metrics={
                    **request.metrics,
                    "parent_iteration_id": parent_iteration_id,
                    "source_action": "NEXT_ITERATION",
                    "created_from_feedback": True,
                },
            ),
        )
        if next_iteration:
            await self.record_feedback(
                parent_iteration_id,
                ResearchIterationFeedbackRequest(
                    action="NEXT_ITERATION_CREATED",
                    verdict=parent.verdict,
                    status="NEXT_ITERATION_READY",
                    note=request.note or f"Created next iteration {next_iteration.iteration_id}.",
                    reviewer=request.reviewer,
                    metrics={"next_iteration_id": next_iteration.iteration_id},
                ),
            )
        return next_iteration

    async def create_sample_loop_from_latest_run(
        self,
        request: Optional[CreateSampleResearchLoopRequest] = None,
    ) -> CreateSampleResearchLoopResponse:
        request = request or CreateSampleResearchLoopRequest()
        missing_reasons: list[str] = []
        context: dict[str, Any] = {
            "requested_run_id": request.run_id,
            "requested_symbol": request.symbol,
            "force_backtest": request.force_backtest,
        }
        run = self._completed_or_stale_run_by_id(request.run_id) if request.run_id else self._latest_completed_or_stale_run(symbol=request.symbol)
        if not run:
            if request.run_id:
                missing_reasons.append(f"Analysis run {request.run_id} is not completed/stale or is not available.")
            else:
                missing_reasons.append("No completed or stale analysis run is available to seed a research loop.")
            return CreateSampleResearchLoopResponse(created=False, missing_reasons=missing_reasons, context=context)

        run_id = str(run.get("runId") or "")
        symbol = str(run.get("stockCode") or run.get("symbol") or request.symbol or "").strip()
        stock_name = str(run.get("stockName") or run.get("name") or "").strip()
        run_status = str(run.get("status") or "").upper()
        portfolio = run.get("portfolio") if isinstance(run.get("portfolio"), dict) else {}
        portfolio_snapshot = run.get("portfolioSnapshot") if isinstance(run.get("portfolioSnapshot"), dict) else {}
        portfolio_snapshot_id = str(
            portfolio_snapshot.get("snapshotId")
            or portfolio_snapshot.get("snapshot_id")
            or portfolio.get("snapshotId")
            or portfolio.get("snapshot_id")
            or ""
        ).strip()
        portfolio_coverage = str(portfolio.get("portfolioCoverage") or "").strip()
        portfolio_positions = (
            portfolio_snapshot.get("positions")
            if isinstance(portfolio_snapshot.get("positions"), list)
            else portfolio.get("holdings") if isinstance(portfolio.get("holdings"), list)
            else []
        )
        if not symbol:
            missing_reasons.append(f"Latest analysis run {run_id or '<unknown>'} has no stockCode/symbol.")
            context.update({"analysis_run_id": run_id, "analysis_run_status": run_status})
            return CreateSampleResearchLoopResponse(created=False, missing_reasons=missing_reasons, context=context)
        if not portfolio_snapshot_id:
            missing_reasons.append(
                "Seed analysis run has no imported holdings snapshot; portfolio evidence remains user-input or template context."
            )

        signalops_signal = None
        try:
            signalops_signal = await signalops_store.upsert_from_run(run)
        except Exception as exc:
            missing_reasons.append(f"SignalOps evidence could not be materialized from run {run_id}: {exc}")

        signalops_records = await signalops_store.list_signals(symbol=symbol, limit=5)
        if not signalops_records:
            missing_reasons.append(f"No SignalOps lifecycle evidence found for {symbol}.")

        backtest_run = None
        backtest_created = False
        end_date = _run_date(run).strftime("%Y-%m-%d")
        start_date = (_run_date(run) - timedelta(days=90)).strftime("%Y-%m-%d")
        try:
            backtest_run = await backtest_store.create_run(
                symbol=symbol,
                stock_name=stock_name,
                start_date=start_date,
                end_date=end_date,
                scenario_label="Research sample loop",
                parameters={
                    "data_source": "MOCK",
                    "signal_source": "SIGNALOPS",
                    "signal_date": end_date,
                    "slippage_bps": 10,
                    "commission_bps": 3,
                    "stamp_tax_bps": 5,
                    "sample_loop": True,
                    "source_run_id": run_id,
                },
                reuse_existing=not request.force_backtest,
                force_new=request.force_backtest,
            )
            backtest_created = not bool((backtest_run.get("parameters") or {}).get("dedupe_reused"))
        except Exception as exc:
            missing_reasons.append(f"Backtest sample could not be created for {symbol}: {exc}")

        backtest_report = (backtest_run or {}).get("report") or {}
        backtest_strength = _backtest_evidence_strength(backtest_report)
        backtest_evidence_payload = _backtest_evidence_payload(backtest_report)
        backtest_review_conclusion = _backtest_review_conclusion(backtest_evidence_payload, "")
        if not backtest_run:
            missing_reasons.append("No backtest result is linked to this sample loop.")
        elif backtest_strength != "HIGH":
            missing_reasons.append(
                f"Backtest evidence strength is {backtest_strength}; keep it as supporting evidence until sample size, data source, and out-of-sample checks improve."
            )
        if str(backtest_report.get("data_source") or "").upper() in {"MOCK", "MOCK_FALLBACK"}:
            missing_reasons.append("Backtest uses mock or fallback market data.")
        if int(backtest_report.get("signal_source_count") or 0) <= 0:
            missing_reasons.append("Backtest has no SignalOps signals in the selected sample window.")
        if run_status == "STALE":
            missing_reasons.append(f"Seed analysis run {run_id} is STALE and is audit context only.")

        detail = await self.create_loop(
            CreateResearchLoopRequest(
                title=f"Sample research loop: {symbol}",
                objective=(
                    "Validate the latest analysis run with SignalOps lifecycle evidence, "
                    "a reproducible backtest report, and explicit evidence-strength limits."
                ),
                hypothesis=(
                    f"{symbol} analysis run {run_id} can become a research iteration only after "
                    "run evidence, SignalOps state, and backtest metadata are reviewed together."
                ),
                plan=(
                    "1. Review the linked analysis run and SignalOps lifecycle. "
                    "2. Inspect backtest sampleWindow, tradingCost, slippage, benchmark, and evidenceStrength. "
                    "3. Treat weak samples as supporting context, not as acceptance evidence."
                ),
                action_target="signal",
                owner=request.reviewer or "human",
                tags=[
                    "sample-loop",
                    "from-latest-run",
                    "signalops",
                    "backtest-evidence",
                    *(["weak-evidence"] if backtest_strength != "HIGH" else []),
                ],
                target_modules=["signalops", "backtest", "research_verdict", "market_data"],
                linked_projects=[
                    {
                        "project": "super",
                        "module": "research_lab",
                        "path": "frontend/src/components/research/ResearchLoopsPage.tsx",
                        "expected_version": "current",
                        "sync_status": "LINKED",
                        "note": "Sample loop generated from latest local run.",
                    }
                ],
            )
        )
        iteration = detail.iterations[0] if detail.iterations else None
        if iteration:
            run_quality = _run_evidence_quality(run)
            run_review_quality = _review_gate_evidence_quality(run_quality)
            evidence_links = [
                ResearchEvidenceLink(
                    source_type="RUN",
                    source_id=run_id,
                    label="Latest completed/stale analysis run",
                    quality=run_review_quality,
                    reported_quality=run_quality if run_quality != run_review_quality else None,
                    created_at=str(run.get("updatedAt") or run.get("createdAt") or _now()),
                )
            ]
            latest_signal = signalops_signal or (signalops_records[0] if signalops_records else None)
            if portfolio_snapshot_id:
                portfolio_quality = "HIGH" if portfolio_coverage == "HOLDINGS_CONNECTED" else "MEDIUM"
                portfolio_review_quality = _review_gate_evidence_quality(portfolio_quality)
                evidence_links.append(
                    ResearchEvidenceLink(
                        source_type="PORTFOLIO_SNAPSHOT",
                        source_id=portfolio_snapshot_id,
                        label="Imported holdings snapshot",
                        quality=portfolio_review_quality,
                        reported_quality=portfolio_quality if portfolio_quality != portfolio_review_quality else None,
                        created_at=str(
                            portfolio_snapshot.get("updatedAt")
                            or portfolio_snapshot.get("importedAt")
                            or portfolio_snapshot.get("createdAt")
                            or _now()
                        ),
                    )
                )
            if latest_signal:
                evidence_links.append(
                    ResearchEvidenceLink(
                        source_type="SIGNALOPS",
                        source_id=str(latest_signal.get("signal_id") or ""),
                        label="SignalOps lifecycle evidence",
                        quality="MEDIUM" if latest_signal.get("status") else "UNKNOWN",
                        created_at=str(latest_signal.get("updated_at") or latest_signal.get("created_at") or _now()),
                    )
                )
            if backtest_run:
                evidence_links.append(
                    ResearchEvidenceLink(
                        source_type="BACKTEST",
                        source_id=str(backtest_run.get("run_id") or ""),
                        label=f"Candidate backtest report ({backtest_review_conclusion.lower()})",
                        quality=backtest_strength,
                        reported_quality=_backtest_reported_evidence_quality(backtest_evidence_payload, backtest_strength),
                        created_at=str(backtest_run.get("updated_at") or _now()),
                    )
                )
            await self.record_feedback(
                iteration.iteration_id,
                ResearchIterationFeedbackRequest(
                    action="CREATE_SAMPLE_LOOP_FROM_LATEST_RUN",
                    verdict="PATCH_REQUIRED",
                    status="PATCH_REQUIRED",
                    note=(
                        "Sample loop seeded from latest local analysis run and reproducible backtest metadata; "
                        "weak/supporting evidence requires patch and evaluation review before any promotion."
                    ),
                    reviewer=request.reviewer or "human",
                    linked_run_id=run_id,
                    linked_backtest_id=str(backtest_run.get("run_id")) if backtest_run else None,
                    metrics={
                        "sample_loop": True,
                        "sample_evidence_usage": "supporting_only",
                        "analysis_run_id": run_id,
                        "analysis_run_status": run_status,
                        "analysis_run_updated_at": run.get("updatedAt") or run.get("createdAt"),
                        "symbol": symbol,
                        "stock_name": stock_name,
                        "portfolio_snapshot_id": portfolio_snapshot_id or None,
                        "portfolio_coverage": portfolio_coverage or None,
                        "portfolio_position_count": len(portfolio_positions),
                        "signalops_signal_ids": [
                            item.get("signal_id") for item in signalops_records if item.get("signal_id")
                        ],
                        "backtest_created": backtest_created,
                        "backtest_run_id": backtest_run.get("run_id") if backtest_run else None,
                        "candidate_backtest_id": backtest_run.get("run_id") if backtest_run else None,
                        "baseline_backtest_id": None,
                        "backtest_review_conclusion": backtest_review_conclusion,
                        "candidate_backtest_review_conclusion": backtest_review_conclusion,
                        "backtest_supporting_only": backtest_review_conclusion == "SUPPORTING_ONLY",
                        "backtest_evidence_strength": backtest_evidence_payload,
                        "candidate_backtest_evidence_strength": backtest_evidence_payload,
                        "backtest_sample_window": backtest_report.get("sampleWindow") or {},
                        "backtest_statistical_confidence": backtest_report.get("statisticalConfidence") or {},
                        "backtest_limitations": backtest_report.get("limitations") or [],
                        "missing_reasons": _dedupe(missing_reasons),
                        "quality_warnings": _dedupe(missing_reasons),
                    },
                    evidence_links=evidence_links,
                ),
            )

        refreshed = await self.get_loop_detail(detail.loop.loop_id)
        context.update(
            {
                "analysis_run_id": run_id,
                "analysis_run_status": run_status,
                "symbol": symbol,
                "stock_name": stock_name,
                "portfolio_snapshot_id": portfolio_snapshot_id or None,
                "portfolio_coverage": portfolio_coverage or None,
                "portfolio_position_count": len(portfolio_positions),
                "signalops_signal_ids": [item.get("signal_id") for item in signalops_records if item.get("signal_id")],
                "backtest_run_id": backtest_run.get("run_id") if backtest_run else None,
                "candidate_backtest_id": backtest_run.get("run_id") if backtest_run else None,
                "baseline_backtest_id": None,
                "backtest_review_conclusion": backtest_review_conclusion,
                "backtest_created": backtest_created,
                "backtest_evidence_strength": backtest_evidence_payload,
            }
        )
        return CreateSampleResearchLoopResponse(
            created=True,
            detail=refreshed or detail,
            missing_reasons=_dedupe(missing_reasons),
            context=context,
        )

    async def record_feedback(
        self,
        iteration_id: str,
        request: ResearchIterationFeedbackRequest,
    ) -> Optional[ResearchIteration]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ResearchIterationDB).where(ResearchIterationDB.iteration_id == iteration_id)
            )
            iteration = result.scalar_one_or_none()
            if not iteration:
                return None

            now = _now()
            event = ResearchFeedbackEvent(
                event_id=_generate_id("RFB"),
                action=request.action.strip().upper() or "REVIEW",
                verdict=request.verdict.strip().upper() or "PENDING",
                note=request.note.strip(),
                reviewer=request.reviewer.strip() or "human",
                created_at=now,
            )
            feedback_events = list(iteration.feedback_events or [])
            feedback_events.append(_model_to_dict(event))
            iteration.feedback_events = feedback_events
            iteration.verdict = event.verdict
            iteration.status = request.status.strip().upper() if request.status else self._status_from_verdict(event.verdict)
            metrics_update = dict(request.metrics or {})
            if request.linked_run_id is not None:
                linked_run_id = self._normalize_linked_run_id(request.linked_run_id)
                if linked_run_id:
                    iteration.linked_run_id = linked_run_id
                elif not str(request.linked_run_id or "").strip():
                    iteration.linked_run_id = None
                else:
                    metrics_update = self._metrics_with_warning(
                        {**(iteration.metrics or {}), **metrics_update},
                        LINKED_RUN_REJECTED_WARNING,
                    )
            if request.linked_backtest_id is not None:
                linked_backtest_id = await self._normalize_linked_backtest_id(request.linked_backtest_id)
                if linked_backtest_id:
                    iteration.linked_backtest_id = linked_backtest_id
                elif not str(request.linked_backtest_id or "").strip():
                    iteration.linked_backtest_id = None
                else:
                    metrics_update = self._metrics_with_warning(
                        {**(iteration.metrics or {}), **metrics_update},
                        LINKED_BACKTEST_REJECTED_WARNING,
                    )
            iteration.linked_case_id = request.linked_case_id or iteration.linked_case_id
            iteration.linked_knowledge_item_id = request.linked_knowledge_item_id or iteration.linked_knowledge_item_id
            iteration.linked_patch_id = request.linked_patch_id or iteration.linked_patch_id
            evidence_links, rejected_run_evidence, rejected_backtest_evidence = await self._normalize_evidence_links(request.evidence_links)
            if rejected_run_evidence:
                metrics_update = self._metrics_with_warning(
                    {**(iteration.metrics or {}), **metrics_update},
                    LINKED_RUN_REJECTED_WARNING,
                )
            if rejected_backtest_evidence:
                metrics_update = self._metrics_with_warning(
                    {**(iteration.metrics or {}), **metrics_update},
                    LINKED_BACKTEST_REJECTED_WARNING,
                )
            if request.override_blocking_reasons:
                metrics_update["verdict_gate_override"] = True
                metrics_update["verdict_gate_override_reason"] = request.override_reason.strip()
            iteration.metrics = {**(iteration.metrics or {}), **metrics_update}
            if evidence_links:
                iteration.evidence_links = _merge_evidence_links(
                    iteration.evidence_links or [],
                    [_review_gate_evidence_payload(item) for item in evidence_links],
                )
            await self._persist_first_class_feedback(db, iteration, event, request, evidence_links)
            iteration.updated_at = now
            if iteration.status in {"ACCEPTED", "REJECTED", "PATCH_REQUIRED", "ARCHIVED"}:
                iteration.completed_at = now

            loop_result = await db.execute(select(ResearchLoopDB).where(ResearchLoopDB.loop_id == iteration.loop_id))
            loop = loop_result.scalar_one_or_none()
            if loop:
                loop.current_iteration_id = iteration.iteration_id
                loop.updated_at = now

            await db.commit()
            await db.refresh(iteration)
            return self._iteration_to_model(iteration)

    async def _persist_first_class_feedback(
        self,
        db,
        iteration: ResearchIterationDB,
        event: ResearchFeedbackEvent,
        request: ResearchIterationFeedbackRequest,
        evidence_links: list[ResearchEvidenceLink],
    ) -> None:
        db.add(
            ResearchFeedbackEventDB(
                feedback_id=event.event_id,
                loop_id=iteration.loop_id,
                iteration_id=iteration.iteration_id,
                action=event.action,
                verdict=event.verdict,
                note=event.note,
                reviewer=event.reviewer,
                observations_json=[event.note] if event.note else [],
                knowledge_item_id=request.linked_knowledge_item_id,
                patch_id=request.linked_patch_id,
                audit_id=str(request.metrics.get("audit_id") or "") or None,
                created_at=event.created_at,
            )
        )
        for evidence in evidence_links:
            payload = _review_gate_evidence_payload(evidence)
            quality = str(payload.get("quality") or "UNKNOWN").strip().upper() or "UNKNOWN"
            source_type = evidence.source_type.strip().upper() or "UNKNOWN"
            source_id = evidence.source_id.strip()
            if not source_id:
                continue
            existing_link = (
                await db.execute(
                    select(ResearchEvidenceLinkDB).where(
                        ResearchEvidenceLinkDB.iteration_id == iteration.iteration_id,
                        ResearchEvidenceLinkDB.source_type == source_type,
                        ResearchEvidenceLinkDB.source_id == source_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_link:
                previous_summary = existing_link.summary_json if isinstance(existing_link.summary_json, dict) else {}
                previous_reported_quality = previous_summary.get("reportedQuality") or previous_summary.get("reported_quality")
                if previous_reported_quality and not (payload.get("reportedQuality") or payload.get("reported_quality")):
                    payload["reportedQuality"] = previous_reported_quality
                    payload["reported_quality"] = previous_reported_quality
                existing_link.label = evidence.label.strip()
                existing_link.quality = quality
                existing_link.summary_json = payload
                existing_link.created_at = evidence.created_at or existing_link.created_at
                continue
            db.add(
                ResearchEvidenceLinkDB(
                    link_id=_generate_id("REV"),
                    loop_id=iteration.loop_id,
                    iteration_id=iteration.iteration_id,
                    source_type=source_type,
                    source_id=source_id,
                    label=evidence.label.strip(),
                    quality=quality,
                    summary_json=payload,
                    created_at=evidence.created_at,
                )
            )

    async def _build_workflow_state(
        self,
        loop: ResearchLoop,
        iterations: list[ResearchIteration],
    ) -> ResearchWorkflowState:
        current = self._current_iteration(loop, iterations)
        if current is None:
            blocking_reasons = ["No research iteration exists for this loop."]
            maturity = self._maturity_profile("no_iteration", blocking_reasons)
            return ResearchWorkflowState(
                maturity_score=0,
                maturity_level=maturity["level"],
                maturity_label=maturity["label"],
                maturity_reasons=maturity["reasons"],
                stage="no_iteration",
                next_action="create_iteration",
                next_action_label="Create first iteration",
                blocking_reasons=blocking_reasons,
                steps=[
                    self._workflow_step(
                        key="iteration",
                        label="Iteration",
                        status="WAIT",
                        detail="Create an iteration before attaching research evidence.",
                        source="research_loop",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No research iteration exists for this loop."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="portfolio",
                        label="Portfolio Snapshot",
                        status="WAIT",
                        detail="Create an iteration before attaching a holdings snapshot.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="run",
                        label="Run",
                        status="WAIT",
                        detail="Create an iteration before attaching an analysis run.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="backtest",
                        label="Backtest",
                        status="WAIT",
                        detail="Create an iteration before attaching a backtest.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="backtest_quality",
                        label="Backtest Quality",
                        status="WAIT",
                        detail="Link a backtest before quality review.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="evidence",
                        label="Evidence Review",
                        status="WAIT",
                        detail="Create an iteration before reviewing evidence.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="artifacts",
                        label="Artifacts",
                        status="WAIT",
                        detail="Create an iteration before materializing artifacts.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="evaluation",
                        label="Evaluation",
                        status="WAIT",
                        detail="Create an iteration before evaluation.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="knowledge_version",
                        label="Knowledge Version",
                        status="WAIT",
                        detail="Create an iteration before knowledge promotion.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                    self._workflow_step(
                        key="feedback",
                        label="Feedback",
                        status="WAIT",
                        detail="Create an iteration before feedback.",
                        source="workflow_state",
                        source_timestamp=loop.updated_at,
                        evidence_strength="MISSING",
                        missing_items=["No current research iteration."],
                        next_action="create_iteration",
                        next_action_label="Create first iteration",
                    ),
                ],
                evidence_strength="MISSING",
            )

        metrics = current.metrics or {}
        artifact_links = metrics.get("artifact_links") if isinstance(metrics.get("artifact_links"), dict) else {}
        legacy_metrics_evidence_refs = metrics.get("evidence_refs") if isinstance(metrics.get("evidence_refs"), list) else []
        run_id, run_source, rejected_run_refs = self._workflow_run_ref(current, artifact_links)
        invalid_run_reason = (
            "Linked analysis run is missing or legacy; attach a canonical analysis run."
            if rejected_run_refs
            else ""
        )
        backtest_id, backtest_source, rejected_backtest_refs = await self._workflow_backtest_ref(current, artifact_links)
        invalid_backtest_reason = (
            "Linked backtest is missing; attach a persisted backtest run."
            if rejected_backtest_refs
            else ""
        )
        evidence_links, rejected_evidence_link_blockers = self._reviewable_workflow_evidence_links(
            current,
            run_id,
            backtest_id,
        )
        evidence_review_blockers = [
            *rejected_evidence_link_blockers,
            *(
                [LEGACY_METRICS_EVIDENCE_REFS_WARNING]
                if legacy_metrics_evidence_refs and not evidence_links
                else []
            ),
        ]
        case_id = current.linked_case_id or _first_text(artifact_links, "case_id")
        knowledge_id = (
            current.linked_knowledge_item_id
            or _first_text(artifact_links, "knowledge_item_id", "knowledge_id")
        )
        patch_id = current.linked_patch_id or _first_text(artifact_links, "patch_id")
        (
            evaluation_id,
            evaluation_source,
            rejected_evaluation_refs,
            evaluation_strength,
        ) = await self._workflow_evaluation_ref(
            artifact_links,
            patch_id,
        )
        invalid_evaluation_reason = (
            "Linked patch evaluation is missing or incomplete."
            if rejected_evaluation_refs
            else ""
        )
        portfolio_snapshot_id = (
            _first_text(artifact_links, "portfolio_snapshot_id", "portfolioSnapshotId")
            or _first_text(metrics, "portfolio_snapshot_id", "portfolioSnapshotId")
        )
        knowledge_version_id = (
            _first_text(artifact_links, "knowledge_version_id", "knowledgeVersionId", "version_id")
            or _first_text(metrics, "knowledge_version_id", "knowledgeVersionId", "version_id")
        )
        knowledge_version_status = str(
            _first_text(artifact_links, "knowledge_version_status", "knowledgeVersionStatus", "version_status")
            or _first_text(metrics, "knowledge_version_status", "knowledgeVersionStatus", "version_status")
            or ""
        ).strip().upper()
        knowledge_version_review_only = bool(
            knowledge_version_id
            and knowledge_version_status != "ACTIVE"
        )
        knowledge_version_ready = bool(knowledge_version_id and not knowledge_version_review_only)
        knowledge_version_review_reason = (
            "Knowledge version status is missing and cannot activate feedback acceptance."
            if knowledge_version_review_only and not knowledge_version_status
            else f"Knowledge version is {knowledge_version_status.lower()} and cannot activate feedback acceptance."
            if knowledge_version_review_only
            else ""
        )
        knowledge_version_step_status = "PASS"
        knowledge_version_step_detail = "Knowledge version promoted."
        knowledge_version_step_missing: list[str] = []
        knowledge_version_step_next_action = ""
        knowledge_version_step_next_action_label = ""
        if knowledge_version_review_only:
            knowledge_version_step_status = "WARN"
            knowledge_version_step_detail = knowledge_version_review_reason
            knowledge_version_step_missing = [knowledge_version_review_reason]
            knowledge_version_step_next_action = "review_knowledge_version"
            knowledge_version_step_next_action_label = "Review knowledge version"
        elif not knowledge_version_id:
            knowledge_version_step_status = "WAIT" if evaluation_id else "BLOCKED"
            knowledge_version_step_detail = (
                "Promote a knowledge version after evaluation."
                if evaluation_id
                else "Evaluate a patch before knowledge promotion."
            )
            knowledge_version_step_missing = (
                ["No promoted knowledge version for the current iteration."]
                if evaluation_id
                else ["No linked patch evaluation for the current iteration."]
            )
            knowledge_version_step_next_action = "promote_knowledge_version"
            knowledge_version_step_next_action_label = "Promote knowledge version"

        metrics_blockers = _strings_from_metric(metrics.get("blocking_reasons"))
        quality_warnings = _strings_from_metric(metrics.get("quality_warnings")) + _strings_from_metric(metrics.get("warnings"))
        research_quality_blockers = _research_quality_blockers(metrics, portfolio_snapshot_id, backtest_id, evaluation_id, knowledge_version_id)
        evidence_blockers = [
            *metrics_blockers,
            *quality_warnings,
            *research_quality_blockers,
            *evidence_review_blockers,
        ]
        verdict_status = str(current.verdict or "").upper()
        status = str(current.status or "").upper()
        can_accept = _truthy_metric(metrics.get("can_accept_feedback"))
        feedback_acceptance_ready = bool(
            can_accept
            and not metrics_blockers
            and not quality_warnings
            and not research_quality_blockers
            and not evidence_review_blockers
            and knowledge_version_ready
        )
        feedback_step_missing: list[str] = []
        if verdict_status != "ACCEPTED" and not feedback_acceptance_ready:
            feedback_step_missing = (
                [knowledge_version_review_reason]
                if knowledge_version_review_only
                else ["Feedback acceptance is not ready."]
            )
        if verdict_status == "ACCEPTED":
            feedback_step_next_action = "create_next_iteration"
            feedback_step_next_action_label = "Create next iteration"
            feedback_evidence_strength = "MEDIUM"
        elif feedback_acceptance_ready:
            feedback_step_next_action = "accept_feedback"
            feedback_step_next_action_label = "Accept feedback"
            feedback_evidence_strength = "MEDIUM"
        elif knowledge_version_review_only:
            feedback_step_next_action = "review_knowledge_version"
            feedback_step_next_action_label = "Review knowledge version"
            feedback_evidence_strength = "MISSING"
        else:
            feedback_step_next_action = "send_to_feedback"
            feedback_step_next_action_label = "Send to feedback"
            feedback_evidence_strength = "MISSING"
        portfolio_meta = self._source_meta_for_ref(
            current,
            portfolio_snapshot_id,
            ["PORTFOLIO_SNAPSHOT"],
            "metrics.portfolio_snapshot_id",
        )
        run_meta = self._source_meta_for_ref(
            current,
            run_id,
            ["RUN"],
            run_source or "workflow_state",
        )
        backtest_meta = self._source_meta_for_ref(
            current,
            backtest_id,
            ["BACKTEST"],
            backtest_source or "workflow_state",
        )
        case_meta = self._source_meta_for_ref(
            current,
            case_id,
            ["CASE", "SIM_CASE"],
            "research_iteration.linked_case_id" if current.linked_case_id and current.linked_case_id == case_id else "metrics.artifact_links",
        )
        knowledge_meta = self._source_meta_for_ref(
            current,
            knowledge_id,
            ["KNOWLEDGE"],
            "research_iteration.linked_knowledge_item_id"
            if current.linked_knowledge_item_id and current.linked_knowledge_item_id == knowledge_id
            else "metrics.artifact_links",
        )
        patch_meta = self._source_meta_for_ref(
            current,
            patch_id,
            ["PATCH"],
            "research_iteration.linked_patch_id" if current.linked_patch_id and current.linked_patch_id == patch_id else "metrics.artifact_links",
        )
        evaluation_meta = self._source_meta_for_ref(
            current,
            evaluation_id,
            ["EVALUATION"],
            evaluation_source or "metrics.artifact_links",
            evaluation_strength or "MEDIUM",
        )
        knowledge_version_meta = self._source_meta_for_ref(
            current,
            knowledge_version_id,
            ["KNOWLEDGE_VERSION"],
            "metrics.artifact_links",
        )
        latest_evidence_timestamp = max(
            [link.created_at for link in evidence_links if str(link.created_at or "").strip()],
            default=current.updated_at if legacy_metrics_evidence_refs else "",
        )
        evidence_strength = (
            "LOW"
            if evidence_blockers
            else (
                _workflow_min_review_strength(*(str(link.quality or "UNKNOWN") for link in evidence_links))
                if evidence_links
                else "MISSING"
            )
        )
        backtest_evidence = _metric_mapping(
            metrics.get("candidate_backtest_evidence_strength")
            or metrics.get("backtest_evidence_strength")
        )
        backtest_evidence_grade = str(backtest_evidence.get("grade") or "").strip().upper()
        backtest_quality_strength = (
            _workflow_review_strength(backtest_evidence_grade)
            if backtest_evidence_grade
            else (
                "MISSING"
                if not backtest_id
                else ("LOW" if _backtest_quality_has_blockers(research_quality_blockers) else "MEDIUM")
            )
        )
        artifact_missing = self._missing_artifact_reasons(case_id, knowledge_id, patch_id)
        artifact_strength = "MEDIUM" if not artifact_missing else ("MEDIUM" if case_id or knowledge_id or patch_id else "MISSING")
        feedback_timestamp = max(
            [event.created_at for event in (current.feedback_events or []) if str(event.created_at or "").strip()],
            default=current.updated_at,
        )

        steps = [
            self._workflow_step(
                key="iteration",
                label="Iteration",
                status="PASS",
                ref_id=current.iteration_id,
                detail=f"Current iteration #{current.order}: {status or 'DRAFT'}",
                source="research_iteration",
                source_timestamp=current.updated_at,
                evidence_strength="MEDIUM",
            ),
            self._workflow_step(
                key="portfolio",
                label="Portfolio Snapshot",
                status="PASS" if portfolio_snapshot_id else "BLOCKED",
                ref_id=portfolio_snapshot_id,
                detail="Imported holdings snapshot linked." if portfolio_snapshot_id else "No imported holdings snapshot is linked.",
                source=portfolio_meta["source"],
                source_timestamp=portfolio_meta["source_timestamp"],
                evidence_strength=portfolio_meta["evidence_strength"],
                missing_items=[] if portfolio_snapshot_id else ["No imported holdings snapshot is linked."],
                next_action="" if portfolio_snapshot_id else "attach_portfolio_snapshot",
                next_action_label="" if portfolio_snapshot_id else "Attach portfolio snapshot",
            ),
            self._workflow_step(
                key="run",
                label="Run",
                status="PASS" if run_id else "WAIT",
                ref_id=run_id,
                detail="Analysis run linked." if run_id else (invalid_run_reason or "No linked analysis run."),
                source=run_meta["source"],
                source_timestamp=run_meta["source_timestamp"],
                evidence_strength=run_meta["evidence_strength"],
                missing_items=[] if run_id else [invalid_run_reason or "No linked analysis run for the current iteration."],
                next_action="" if run_id else "attach_or_create_run",
                next_action_label="" if run_id else "Attach or create run",
            ),
            self._workflow_step(
                key="backtest",
                label="Backtest",
                status="PASS" if backtest_id else "WAIT",
                ref_id=backtest_id,
                detail="Backtest linked." if backtest_id else (invalid_backtest_reason or "No linked backtest."),
                source=backtest_meta["source"],
                source_timestamp=backtest_meta["source_timestamp"],
                evidence_strength=backtest_meta["evidence_strength"],
                missing_items=[] if backtest_id else [invalid_backtest_reason or "No linked backtest for the current iteration."],
                next_action="" if backtest_id else "attach_or_create_backtest",
                next_action_label="" if backtest_id else "Attach or create backtest",
            ),
            self._workflow_step(
                key="backtest_quality",
                label="Backtest Quality",
                status="WARN" if _backtest_quality_has_blockers(research_quality_blockers) else ("PASS" if backtest_id else "WAIT"),
                detail=_join_detail(research_quality_blockers) or ("Backtest evidence can support research review." if backtest_id else "Link a backtest before quality review."),
                source="metrics.backtest_evidence_strength" if backtest_evidence else "workflow_state",
                source_timestamp=current.updated_at,
                evidence_strength=backtest_quality_strength,
                missing_items=research_quality_blockers if research_quality_blockers else ([] if backtest_id else ["No linked backtest for the current iteration."]),
                next_action="" if backtest_id and not research_quality_blockers else "review_evidence",
                next_action_label="" if backtest_id and not research_quality_blockers else "Review evidence",
            ),
            self._workflow_step(
                key="evidence",
                label="Evidence Review",
                status="WARN" if evidence_blockers else ("PASS" if evidence_links else "WAIT"),
                detail=_join_detail(evidence_blockers)
                or ("Evidence links available." if evidence_links else "Verdict evidence has not been reviewed."),
                source="research_iteration.evidence_links" if evidence_links else ("metrics.evidence_refs" if legacy_metrics_evidence_refs else "workflow_state"),
                source_timestamp=latest_evidence_timestamp,
                evidence_strength=evidence_strength,
                missing_items=evidence_blockers
                if evidence_blockers
                else ([] if evidence_links else ["Verdict evidence has not been reviewed."]),
                next_action="review_evidence",
                next_action_label="Review evidence",
            ),
            self._workflow_step(
                key="artifacts",
                label="Artifacts",
                status="PASS" if case_id and knowledge_id and patch_id else ("WARN" if case_id or knowledge_id or patch_id else "WAIT"),
                ref_id=patch_id or knowledge_id or case_id,
                detail=self._artifact_detail(case_id, knowledge_id, patch_id),
                source=patch_meta["source"] if patch_id else (knowledge_meta["source"] if knowledge_id else case_meta["source"]),
                source_timestamp=patch_meta["source_timestamp"] if patch_id else (knowledge_meta["source_timestamp"] if knowledge_id else case_meta["source_timestamp"]),
                evidence_strength=artifact_strength,
                missing_items=artifact_missing,
                next_action="" if not artifact_missing else "materialize_artifacts",
                next_action_label="" if not artifact_missing else "Materialize artifacts",
            ),
            self._workflow_step(
                key="evaluation",
                label="Evaluation",
                status="PASS" if evaluation_id else ("WAIT" if patch_id else "BLOCKED"),
                ref_id=evaluation_id,
                detail="Patch evaluation linked."
                if evaluation_id
                else (invalid_evaluation_reason or ("Evaluate the linked patch." if patch_id else "Create a patch before evaluation.")),
                source=evaluation_meta["source"],
                source_timestamp=evaluation_meta["source_timestamp"],
                evidence_strength=evaluation_meta["evidence_strength"],
                missing_items=[] if evaluation_id else ([invalid_evaluation_reason] if invalid_evaluation_reason else (["No linked patch evaluation for the current iteration."] if patch_id else ["No linked patch candidate."])),
                next_action="" if evaluation_id else "evaluate_patch",
                next_action_label="" if evaluation_id else "Evaluate patch",
            ),
            self._workflow_step(
                key="knowledge_version",
                label="Knowledge Version",
                status=knowledge_version_step_status,
                ref_id=knowledge_version_id,
                detail=knowledge_version_step_detail,
                source=knowledge_version_meta["source"],
                source_timestamp=knowledge_version_meta["source_timestamp"],
                evidence_strength=knowledge_version_meta["evidence_strength"],
                missing_items=knowledge_version_step_missing,
                next_action=knowledge_version_step_next_action,
                next_action_label=knowledge_version_step_next_action_label,
            ),
            self._workflow_step(
                key="feedback",
                label="Feedback",
                status="PASS" if verdict_status == "ACCEPTED" else ("READY" if feedback_acceptance_ready else "WAIT"),
                detail=(
                    "Accepted by feedback."
                    if verdict_status == "ACCEPTED"
                    else ("Ready for acceptance feedback." if feedback_acceptance_ready else "Feedback acceptance is not ready.")
                ),
                source="research_iteration.feedback_events" if current.feedback_events else "research_iteration.metrics",
                source_timestamp=feedback_timestamp,
                evidence_strength=feedback_evidence_strength,
                missing_items=feedback_step_missing,
                next_action=feedback_step_next_action,
                next_action_label=feedback_step_next_action_label,
            ),
        ]

        blocking_reasons: list[str] = []
        next_action = "review_evidence"
        next_action_label = "Review evidence"
        stage = "evidence_review"

        if not run_id:
            stage = "missing_run"
            next_action = "attach_or_create_run"
            next_action_label = "Attach or create run"
            blocking_reasons.append(invalid_run_reason or "No linked analysis run for the current iteration.")
        elif not portfolio_snapshot_id:
            stage = "missing_portfolio_snapshot"
            next_action = "attach_portfolio_snapshot"
            next_action_label = "Attach portfolio snapshot"
            blocking_reasons.append("No imported holdings snapshot is linked to the current iteration.")
        elif not backtest_id:
            stage = "missing_backtest"
            next_action = "attach_or_create_backtest"
            next_action_label = "Attach or create backtest"
            blocking_reasons.append(invalid_backtest_reason or "No linked backtest for the current iteration.")
        elif evidence_blockers:
            stage = "needs_evidence_review"
            next_action = "review_evidence"
            next_action_label = "Review evidence"
            blocking_reasons.extend(evidence_blockers)
        elif not (case_id and knowledge_id and patch_id):
            stage = "missing_artifacts"
            next_action = "materialize_artifacts"
            next_action_label = "Materialize artifacts"
            blocking_reasons.extend(self._missing_artifact_reasons(case_id, knowledge_id, patch_id))
        elif not evaluation_id:
            stage = "missing_evaluation"
            next_action = "evaluate_patch"
            next_action_label = "Evaluate patch"
            blocking_reasons.append(invalid_evaluation_reason or "No linked patch evaluation for the current iteration.")
        elif not knowledge_version_id:
            stage = "missing_knowledge_version"
            next_action = "promote_knowledge_version"
            next_action_label = "Promote knowledge version"
            blocking_reasons.append("No promoted knowledge version for the current iteration.")
        elif knowledge_version_review_only:
            stage = "review_knowledge_version"
            next_action = "review_knowledge_version"
            next_action_label = "Review knowledge version"
            blocking_reasons.append(knowledge_version_review_reason)
        elif verdict_status == "ACCEPTED":
            stage = "accepted"
            next_action = "create_next_iteration"
            next_action_label = "Create next iteration"
        elif can_accept:
            stage = "feedback_ready"
            next_action = "accept_feedback"
            next_action_label = "Accept feedback"
        else:
            stage = "needs_feedback_decision"
            next_action = "send_to_feedback"
            next_action_label = "Send to feedback"

        blocking_reasons = _dedupe(blocking_reasons)
        maturity = self._maturity_profile(stage, blocking_reasons)
        return ResearchWorkflowState(
            maturity_score=self._maturity_score(steps),
            maturity_level=maturity["level"],
            maturity_label=maturity["label"],
            maturity_reasons=maturity["reasons"],
            stage=stage,
            next_action=next_action,
            next_action_label=next_action_label,
            blocking_reasons=blocking_reasons,
            steps=steps,
            evidence_strength=_workflow_min_review_strength(*(step.evidence_strength for step in steps)),
        )

    def _current_iteration(
        self,
        loop: ResearchLoop,
        iterations: list[ResearchIteration],
    ) -> Optional[ResearchIteration]:
        if not iterations:
            return None
        if loop.current_iteration_id:
            current = next((item for item in iterations if item.iteration_id == loop.current_iteration_id), None)
            if current:
                return current
        return sorted(iterations, key=lambda item: item.order)[-1]

    def _first_evidence_ref(self, iteration: ResearchIteration, source_type: str) -> Optional[str]:
        desired = source_type.upper()
        for link in iteration.evidence_links or []:
            if str(link.source_type or "").upper() == desired and link.source_id:
                return link.source_id
        return None

    def _evidence_link_for_ref(
        self,
        iteration: ResearchIteration,
        source_types: list[str],
        ref_id: Optional[str],
    ) -> Optional[ResearchEvidenceLink]:
        desired = {item.upper() for item in source_types}
        for link in iteration.evidence_links or []:
            source_type = str(link.source_type or "").upper()
            source_id = str(link.source_id or "").strip()
            if source_type in desired and source_id and (not ref_id or source_id == ref_id):
                return link
        return None

    def _source_meta_for_ref(
        self,
        iteration: ResearchIteration,
        ref_id: Optional[str],
        source_types: list[str],
        fallback_source: str,
        fallback_strength: str = "MEDIUM",
    ) -> dict[str, str]:
        link = self._evidence_link_for_ref(iteration, source_types, ref_id) if ref_id else None
        if link:
            return {
                "source": f"evidence_links.{str(link.source_type or '').upper()}",
                "source_timestamp": link.created_at,
                "evidence_strength": _workflow_min_review_strength(
                    str(link.quality or fallback_strength or "UNKNOWN"),
                    str(fallback_strength or "MEDIUM"),
                ),
            }
        if ref_id:
            return {
                "source": fallback_source,
                "source_timestamp": iteration.updated_at,
                "evidence_strength": _workflow_review_strength(str(fallback_strength or "MEDIUM")),
            }
        return {
            "source": fallback_source,
            "source_timestamp": iteration.updated_at,
            "evidence_strength": "MISSING",
        }

    def _workflow_run_ref(
        self,
        iteration: ResearchIteration,
        artifact_links: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        candidates = [
            ("research_iteration.linked_run_id", iteration.linked_run_id),
            (
                "metrics.artifact_links",
                _first_text(artifact_links, "run_id", "analysis_run_id", "candidate_run_id"),
            ),
            ("evidence_links.RUN", self._first_evidence_ref(iteration, "RUN")),
        ]
        rejected: list[str] = []
        for source, candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            linked_run_id = self._normalize_linked_run_id(text)
            if linked_run_id:
                return linked_run_id, source, rejected
            rejected.append(f"{source}:{text}")
        source = rejected[0].split(":", 1)[0] if rejected else ""
        return None, source, rejected

    async def _workflow_backtest_ref(
        self,
        iteration: ResearchIteration,
        artifact_links: dict[str, Any],
    ) -> tuple[Optional[str], str, list[str]]:
        candidates = [
            ("research_iteration.linked_backtest_id", iteration.linked_backtest_id),
            ("metrics.artifact_links", _first_text(artifact_links, "backtest_id", "backtest_run_id")),
            ("evidence_links.BACKTEST", self._first_evidence_ref(iteration, "BACKTEST")),
        ]
        rejected: list[str] = []
        for source, candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            linked_backtest_id = await self._normalize_linked_backtest_id(text)
            if linked_backtest_id:
                return linked_backtest_id, source, rejected
            rejected.append(f"{source}:{text}")
        source = rejected[0].split(":", 1)[0] if rejected else ""
        return None, source, rejected

    async def _workflow_evaluation_ref(
        self,
        artifact_links: dict[str, Any],
        patch_id: Optional[str],
    ) -> tuple[Optional[str], str, list[str], str]:
        candidates = [
            ("metrics.artifact_links", _first_text(artifact_links, "evaluation_id", "eval_id")),
        ]
        rejected: list[str] = []
        expected_patch_id = str(patch_id or "").strip()
        for source, candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            try:
                evaluation = await evaluation_sandbox_store.get_evaluation(text)
            except Exception:
                evaluation = None
            actual_eval_id = str((evaluation or {}).get("eval_id") or "").strip()
            actual_patch_id = str((evaluation or {}).get("patch_id") or "").strip()
            status = str((evaluation or {}).get("status") or "").strip().upper()
            if (
                actual_eval_id == text
                and status == "COMPLETED"
                and (not expected_patch_id or actual_patch_id == expected_patch_id)
            ):
                strength = str((evaluation or {}).get("evidence_strength") or "").strip().upper()
                return actual_eval_id, source, rejected, strength
            rejected.append(f"{source}:{text}")
        source = rejected[0].split(":", 1)[0] if rejected else ""
        return None, source, rejected, ""

    def _reviewable_workflow_evidence_links(
        self,
        iteration: ResearchIteration,
        run_id: Optional[str],
        backtest_id: Optional[str],
    ) -> tuple[list[ResearchEvidenceLink], list[str]]:
        reviewable: list[ResearchEvidenceLink] = []
        blockers: list[str] = []
        for link in iteration.evidence_links or []:
            source_type = str(link.source_type or "").strip().upper()
            source_id = str(link.source_id or "").strip()
            if source_type == "RUN" and (not run_id or source_id != run_id):
                blockers.append("Linked analysis run is missing or legacy; attach a canonical analysis run.")
                continue
            if source_type == "BACKTEST" and (not backtest_id or source_id != backtest_id):
                blockers.append("Linked backtest is missing; attach a persisted backtest run.")
                continue
            reviewable.append(link)
        return reviewable, _dedupe(blockers)

    def _workflow_step(
        self,
        *,
        key: str,
        label: str,
        status: str = "WAIT",
        ref_id: Optional[str] = None,
        detail: str = "",
        source: str = "",
        source_timestamp: str = "",
        evidence_strength: str = "",
        missing_items: Optional[list[str]] = None,
        next_action: str = "",
        next_action_label: str = "",
    ) -> ResearchWorkflowStep:
        status_value = str(status or "WAIT").upper()
        normalized_missing = _dedupe(missing_items or [])
        strength = str(evidence_strength or "").strip().upper()
        if not strength:
            strength = _workflow_strength_from_status(status_value, normalized_missing)
        strength = _workflow_review_strength(strength)
        action = next_action
        action_label = next_action_label
        if not action:
            action, action_label = _workflow_step_default_action(status_value, bool(normalized_missing))
        return ResearchWorkflowStep(
            key=key,
            label=label,
            status=status_value,
            ref_id=ref_id,
            detail=detail,
            source=source,
            source_timestamp=source_timestamp,
            evidence_strength=strength,
            missing_items=normalized_missing,
            next_action=action,
            next_action_label=action_label,
        )

    def _artifact_detail(
        self,
        case_id: Optional[str],
        knowledge_id: Optional[str],
        patch_id: Optional[str],
    ) -> str:
        missing = self._missing_artifact_reasons(case_id, knowledge_id, patch_id)
        if missing:
            return "; ".join(missing)
        return "Case, knowledge candidate, and patch are linked."

    def _missing_artifact_reasons(
        self,
        case_id: Optional[str],
        knowledge_id: Optional[str],
        patch_id: Optional[str],
    ) -> list[str]:
        reasons: list[str] = []
        if not case_id:
            reasons.append("No linked research case.")
        if not knowledge_id:
            reasons.append("No linked knowledge item.")
        if not patch_id:
            reasons.append("No linked patch candidate.")
        return reasons

    def _maturity_score(self, steps: list[ResearchWorkflowStep]) -> int:
        weights = {
            "PASS": 1.0,
            "READY": 0.85,
            "WARN": 0.55,
            "WAIT": 0.0,
            "BLOCKED": 0.0,
        }
        if not steps:
            return 0
        score = sum(weights.get(step.status.upper(), 0.0) for step in steps) / len(steps)
        return max(0, min(100, round(score * 100)))

    def _maturity_profile(self, stage: str, blocking_reasons: list[str]) -> dict[str, list[str] | str]:
        stage_key = str(stage or "").strip().lower()
        profile = {
            "no_iteration": (
                "missing_data",
                "Missing data",
                "Create a research iteration before collecting evidence.",
            ),
            "missing_run": (
                "missing_data",
                "Missing data",
                "Attach an analysis run before judging research readiness.",
            ),
            "missing_portfolio_snapshot": (
                "missing_data",
                "Missing data",
                "Attach a portfolio snapshot before judging research readiness.",
            ),
            "missing_backtest": (
                "missing_sample",
                "Missing sample",
                "Attach a backtest sample before evaluation or knowledge promotion.",
            ),
            "needs_evidence_review": (
                "missing_sample",
                "Missing sample or weak evidence",
                "Review weak, supporting-only, fallback, or low-coverage evidence before promotion.",
            ),
            "missing_artifacts": (
                "materialization_ready",
                "Ready to materialize artifacts",
                "Materialize case, knowledge, and patch artifacts before evaluation.",
            ),
            "missing_evaluation": (
                "evaluation_ready",
                "Ready for evaluation",
                "Evaluate the linked patch before publishing a knowledge version.",
            ),
            "missing_knowledge_version": (
                "knowledge_ready",
                "Ready to publish knowledge version",
                "Promote a knowledge version after successful evaluation.",
            ),
            "review_knowledge_version": (
                "knowledge_ready",
                "Knowledge version needs review",
                "Review the staged knowledge version before feedback acceptance.",
            ),
            "feedback_ready": (
                "feedback_ready",
                "Ready for feedback acceptance",
                "Accept feedback or create the next iteration after reviewer decision.",
            ),
            "needs_feedback_decision": (
                "feedback_ready",
                "Ready for feedback decision",
                "Send the reviewed evidence to feedback before closing the loop.",
            ),
            "accepted": (
                "accepted",
                "Accepted",
                "Create the next iteration when more research is needed.",
            ),
        }.get(
            stage_key,
            (
                "review_needed",
                "Review needed",
                "Review workflow state and blocking reasons before continuing.",
            ),
        )
        reasons = _dedupe(blocking_reasons) or [profile[2]]
        return {"level": profile[0], "label": profile[1], "reasons": reasons}

    async def _loop_to_model(self, record: ResearchLoopDB) -> ResearchLoop:
        async with AsyncSessionLocal() as db:
            count_result = await db.execute(
                select(func.count())
                .select_from(ResearchIterationDB)
                .where(ResearchIterationDB.loop_id == record.loop_id)
            )
            iteration_count = count_result.scalar() or 0
        return ResearchLoop(
            loop_id=record.loop_id,
            title=record.title,
            objective=record.objective,
            status=record.status,
            action_target=record.action_target,
            owner=record.owner,
            tags=record.tags or [],
            linked_projects=record.linked_projects or [],
            source=record.source,
            current_iteration_id=record.current_iteration_id,
            iteration_count=iteration_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _iteration_to_model(self, record: ResearchIterationDB) -> ResearchIteration:
        return ResearchIteration(
            iteration_id=record.iteration_id,
            loop_id=record.loop_id,
            order=record.iteration_number,
            status=record.status,
            hypothesis=record.hypothesis,
            plan=record.plan,
            target_modules=record.target_modules or [],
            linked_run_id=self._normalize_linked_run_id(record.linked_run_id),
            linked_backtest_id=record.linked_backtest_id,
            linked_case_id=record.linked_case_id,
            linked_knowledge_item_id=record.linked_knowledge_item_id,
            linked_patch_id=record.linked_patch_id,
            metrics=record.metrics or {},
            evidence_links=[_review_gate_evidence_payload(item) for item in (record.evidence_links or [])],
            feedback_events=record.feedback_events or [],
            verdict=record.verdict,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _build_iteration_record(
        self,
        loop_id: str,
        order: int,
        request: CreateResearchIterationRequest,
    ) -> ResearchIterationDB:
        now = _now()
        linked_run_id = self._normalize_linked_run_id(request.linked_run_id)
        metrics = dict(request.metrics or {})
        if str(request.linked_run_id or "").strip() and not linked_run_id:
            metrics = self._metrics_with_warning(metrics, LINKED_RUN_REJECTED_WARNING)
        return ResearchIterationDB(
            iteration_id=_generate_id("RITER"),
            loop_id=loop_id,
            iteration_number=order,
            status="DRAFT",
            hypothesis=request.hypothesis.strip(),
            plan=request.plan.strip(),
            target_modules=[module.strip() for module in request.target_modules if module.strip()],
            linked_run_id=linked_run_id,
            metrics=metrics,
            created_at=now,
            updated_at=now,
        )

    def _status_from_verdict(self, verdict: str) -> str:
        if verdict == "ACCEPTED":
            return "ACCEPTED"
        if verdict in {"REJECTED", "PATCH_REQUIRED"}:
            return verdict
        return "REVIEWED"

    def _latest_completed_or_stale_run(self, symbol: Optional[str] = None) -> Optional[dict[str, Any]]:
        desired_symbol = str(symbol or "").strip()
        candidates: dict[str, dict[str, Any]] = {}
        try:
            for _run_id, run in iter_runs():
                if isinstance(run, dict) and run.get("runId"):
                    candidates[str(run.get("runId"))] = run
        except Exception:
            pass

        for run_id, run in load_persisted_runs().items():
            if _looks_like_legacy_mock_run(run_id, run):
                continue
            if isinstance(run, dict) and run.get("runId"):
                candidates.setdefault(str(run.get("runId")), run)

        eligible = []
        for run in candidates.values():
            status = str(run.get("status") or "").upper()
            run_symbol = str(run.get("stockCode") or run.get("symbol") or "").strip()
            if status not in {"COMPLETED", "STALE"}:
                continue
            if desired_symbol and run_symbol != desired_symbol:
                continue
            eligible.append(run)
        if not eligible:
            return None
        return sorted(eligible, key=_run_sort_key, reverse=True)[0]

    def _completed_or_stale_run_by_id(self, run_id: Optional[str]) -> Optional[dict[str, Any]]:
        desired_run_id = str(run_id or "").strip()
        if not desired_run_id:
            return None
        candidates: dict[str, dict[str, Any]] = {}
        try:
            run = get_run(desired_run_id)
            if isinstance(run, dict) and run.get("runId"):
                candidates[desired_run_id] = run
        except Exception:
            pass

        persisted = load_persisted_runs().get(desired_run_id)
        if (
            isinstance(persisted, dict)
            and persisted.get("runId")
            and not _looks_like_legacy_mock_run(desired_run_id, persisted)
        ):
            candidates.setdefault(desired_run_id, persisted)

        run = candidates.get(desired_run_id)
        if not run:
            return None
        status = str(run.get("status") or "").upper()
        if status not in {"COMPLETED", "STALE"}:
            return None
        return run

    def _run_by_id(self, run_id: Optional[str]) -> Optional[dict[str, Any]]:
        desired_run_id = str(run_id or "").strip()
        if not desired_run_id:
            return None
        try:
            run = get_run(desired_run_id)
            if isinstance(run, dict) and run.get("runId"):
                return run
        except Exception:
            pass
        persisted = load_persisted_runs().get(desired_run_id)
        if (
            isinstance(persisted, dict)
            and persisted.get("runId")
            and not _looks_like_legacy_mock_run(desired_run_id, persisted)
        ):
            return persisted
        return None

    def _normalize_linked_run_id(self, run_id: Optional[str]) -> Optional[str]:
        desired_run_id = str(run_id or "").strip()
        if not desired_run_id:
            return None
        run = self._run_by_id(desired_run_id)
        actual_run_id = str((run or {}).get("runId") or "").strip()
        if actual_run_id != desired_run_id:
            return None
        return actual_run_id

    async def _normalize_linked_backtest_id(self, backtest_id: Optional[str]) -> Optional[str]:
        desired_backtest_id = str(backtest_id or "").strip()
        if not desired_backtest_id:
            return None
        try:
            backtest_run = await backtest_store.get_run(desired_backtest_id)
        except Exception:
            return None
        actual_backtest_id = str((backtest_run or {}).get("run_id") or "").strip()
        if actual_backtest_id != desired_backtest_id:
            return None
        return actual_backtest_id

    async def _normalize_evidence_links(
        self,
        evidence_links: list[ResearchEvidenceLink],
    ) -> tuple[list[ResearchEvidenceLink], bool, bool]:
        normalized: list[ResearchEvidenceLink] = []
        rejected_run = False
        rejected_backtest = False
        for evidence in evidence_links or []:
            source_type = str(evidence.source_type or "").strip().upper()
            source_id = str(evidence.source_id or "").strip()
            if source_type == "RUN":
                linked_run_id = self._normalize_linked_run_id(source_id)
                if not linked_run_id:
                    rejected_run = True
                    continue
                payload = _model_to_dict(evidence)
                payload["source_type"] = "RUN"
                payload["source_id"] = linked_run_id
                normalized.append(ResearchEvidenceLink(**payload))
                continue
            if source_type == "BACKTEST":
                linked_backtest_id = await self._normalize_linked_backtest_id(source_id)
                payload = _model_to_dict(evidence)
                payload["source_type"] = "BACKTEST"
                if linked_backtest_id:
                    payload["source_id"] = linked_backtest_id
                else:
                    rejected_backtest = True
                normalized.append(ResearchEvidenceLink(**payload))
                continue
            normalized.append(evidence)
        return normalized, rejected_run, rejected_backtest

    def _metrics_with_warning(self, metrics: Optional[dict[str, Any]], warning: str) -> dict[str, Any]:
        updated = dict(metrics or {})
        updated["warnings"] = _dedupe([
            *_strings_from_metric(updated.get("warnings")),
            warning,
        ])
        return updated

    def _run_matches_iteration(self, iteration: ResearchIteration, run: dict[str, Any]) -> bool:
        run_id = str(run.get("runId") or "").strip()
        rd_research = run.get("rdResearch") if isinstance(run.get("rdResearch"), dict) else {}
        rd_iteration_id = str(rd_research.get("iterationId") or "").strip()
        if rd_iteration_id:
            return rd_iteration_id == iteration.iteration_id
        return bool(run_id and iteration.linked_run_id and run_id == iteration.linked_run_id)


def _looks_like_legacy_mock_run(run_id: str, run: dict[str, Any]) -> bool:
    if str(run_id).startswith(("RUN_HISTORY_", "RUN_MOCK_")):
        return True
    if str(run.get("runId", "")).startswith(("RUN_HISTORY_", "RUN_MOCK_")):
        return True
    if str(run.get("auditId", "")).startswith(("AUD_RUN_MOCK", "AUD_MOCK")):
        return True
    return False


def _run_sort_key(run: dict[str, Any]) -> str:
    return str(run.get("updatedAt") or run.get("updated_at") or run.get("createdAt") or run.get("created_at") or "")


def _run_date(run: dict[str, Any]) -> datetime:
    value = _run_sort_key(run)
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


def _backtest_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role in {"baseline", "candidate"}:
        return role
    return "candidate"


def _backtest_evidence_payload(report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    camel, snake = _backtest_evidence_aliases(report)
    normalized = {**snake, **camel}
    if "can_support_research_verdict" in normalized and "canSupportResearchVerdict" not in normalized:
        normalized["canSupportResearchVerdict"] = normalized.get("can_support_research_verdict")
    if "research_usage" in normalized and "researchUsage" not in normalized:
        normalized["researchUsage"] = normalized.get("research_usage")
    if "reported_grade" in normalized and "reportedGrade" not in normalized:
        normalized["reportedGrade"] = normalized.get("reported_grade")
    if "reportedGrade" in normalized and "reported_grade" not in normalized:
        normalized["reported_grade"] = normalized.get("reportedGrade")
    grade = str(_backtest_evidence_grade(normalized) or "").upper()
    if not grade:
        grade = _backtest_evidence_strength(report)
    review_grade = _backtest_evidence_strength(report) if grade else "UNKNOWN"
    if grade and review_grade != grade:
        normalized.setdefault("reportedGrade", grade)
        normalized.setdefault("reported_grade", grade)
    if review_grade != "UNKNOWN":
        normalized["grade"] = review_grade
    normalized["canSupportResearchVerdict"] = False
    normalized["can_support_research_verdict"] = False
    normalized["weakSample"] = True
    normalized["weak_sample"] = True
    normalized["researchUsage"] = "supporting_only"
    normalized["research_usage"] = "supporting_only"
    if "limitations" not in normalized and isinstance(report.get("limitations"), list):
        normalized["limitations"] = report.get("limitations")
    return normalized


def _backtest_review_conclusion(evidence_strength: dict[str, Any], requested: str) -> str:
    requested_value = str(requested or "").strip().upper()
    strong_requested_values = {
        "ACCEPT",
        "ACCEPTED",
        "APPROVED",
        "HIGH",
        "PASS",
        "PRIMARY",
        "PRIMARY_EVIDENCE",
        "PRIMARY_EVIDENCE_READY",
        "READY",
        "RESEARCH_GRADE",
        "STRONG",
    }
    if requested_value and requested_value not in strong_requested_values:
        return requested_value
    return "SUPPORTING_ONLY"


def _backtest_evidence_strength(report: dict[str, Any]) -> str:
    camel, snake = _backtest_evidence_aliases(report)
    grades = [
        _backtest_review_grade(_backtest_evidence_grade(camel)),
        _backtest_review_grade(_backtest_evidence_grade(snake)),
    ]
    grades = [grade for grade in grades if grade != "UNKNOWN"]
    if not grades:
        return "UNKNOWN"
    rank = {"LOW": 1, "MEDIUM": 2}
    return min(grades, key=lambda grade: rank.get(grade, 0))


def _backtest_evidence_aliases(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(report, dict):
        return {}, {}
    camel = report.get("evidenceStrength") if isinstance(report.get("evidenceStrength"), dict) else {}
    snake = report.get("evidence_strength") if isinstance(report.get("evidence_strength"), dict) else {}
    return camel, snake


def _backtest_evidence_grade(evidence: dict[str, Any]) -> Any:
    if not isinstance(evidence, dict):
        return None
    return evidence.get("grade") or evidence.get("reportedGrade") or evidence.get("reported_grade")


def _backtest_reported_evidence_quality(evidence: dict[str, Any], quality: str) -> Optional[str]:
    if not isinstance(evidence, dict):
        return None
    reported = str(evidence.get("reportedGrade") or evidence.get("reported_grade") or "").strip().upper()
    gated = str(quality or "").strip().upper()
    if reported and reported != gated:
        return reported
    return None


def _backtest_review_grade(value: Any) -> str:
    grade = str(value or "").strip().upper()
    if grade in {"HIGH", "STRONG", "PRIMARY", "PRIMARY_EVIDENCE", "PRIMARY_EVIDENCE_READY", "RESEARCH_GRADE", "PASS", "READY"}:
        return "MEDIUM"
    if grade in {"MEDIUM", "LOW"}:
        return grade
    if grade in {"SUPPORTING_ONLY", "WEAK", "WARN", "REVIEW", "REVIEW_ONLY"}:
        return "LOW"
    return "UNKNOWN"


def _run_evidence_quality(run: dict[str, Any]) -> str:
    if str(run.get("status") or "").upper() == "STALE":
        return "LOW"
    compressed = run.get("compressedSummary") if isinstance(run.get("compressedSummary"), dict) else {}
    quality = compressed.get("quality") if isinstance(compressed.get("quality"), dict) else {}
    level = str(quality.get("level") or "").upper()
    if level in {"HIGH", "MEDIUM", "LOW"}:
        return level
    score = quality.get("score")
    if isinstance(score, (int, float)):
        if score >= 80:
            return "HIGH"
        if score >= 60:
            return "MEDIUM"
        return "LOW"
    return "UNKNOWN"


def _bottom_research_iteration_metrics(
    *,
    bottom: dict[str, Any],
    backtest_run: dict[str, Any],
    run_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
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
            "sampleQuality": mfe_eval.get("sampleQuality"),
        }
    parameters = backtest_run.get("parameters") if isinstance(backtest_run.get("parameters"), dict) else {}
    report = backtest_run.get("report") if isinstance(backtest_run.get("report"), dict) else {}
    provenance_report = report.get("provenance") if isinstance(report.get("provenance"), dict) else {}
    backtest_id = str(backtest_run.get("run_id") or "").strip()
    signal_hash = (
        parameters.get("mfe_mae_research_signal_hash")
        or parameters.get("bottom_research_signal_hash")
        or provenance_report.get("mfeMaeResearchSignalHash")
        or provenance_report.get("bottomResearchSignalHash")
        or ""
    )
    signal_count = (
        parameters.get("mfe_mae_research_signal_count")
        if parameters.get("mfe_mae_research_signal_count") is not None
        else parameters.get("bottom_research_signal_count")
        if parameters.get("bottom_research_signal_count") is not None
        else provenance_report.get("mfeMaeResearchSignalCount")
        if provenance_report.get("mfeMaeResearchSignalCount") is not None
        else provenance_report.get("bottomResearchSignalCount")
    )
    mfe_probability = bottom.get("mfeFavorableProbability", bottom.get("bottomRepairProbability"))
    mae_probability = bottom.get("maeBreachProbability", bottom.get("breakdownRiskProbability"))
    metrics = {
        "mfe_mae_research_status": bottom.get("status"),
        "mfe_mae_research_run_id": run_id,
        "mfe_favorable_probability": mfe_probability,
        "mae_breach_probability": mae_probability,
        "mfe_proxy": bottom.get("mfeProxy"),
        "mae_proxy": bottom.get("maeProxy"),
        "risk_reward_proxy": bottom.get("riskRewardProxy"),
        "mfe_mae_risk_policy": bottom.get("riskPolicy"),
        "mfe_mae_research_regime": bottom.get("regimeState"),
        "mfe_mae_research_model_version": provenance.get("modelVersion") or diagnostics.get("modelVersion"),
        "mfe_mae_research_sample_count": diagnostics.get("sampleCount"),
        "mfe_mae_rank_ic": mfe_eval.get("rankIc"),
        "mfe_mae_quantile_coverage": mfe_eval.get("quantileCoverage"),
        "mfe_mae_research_fold_count": bottom_walk.get("foldCount"),
        "mfe_mae_research_evidence_grade": diagnostics.get("evidenceGrade"),
        "mfe_mae_research_signal_hash": signal_hash,
        "mfe_mae_research_signal_count": signal_count,
        "mfe_mae_research_backtest_id": backtest_id,
        "mfe_mae_research_backtest_window": {"start_date": start_date, "end_date": end_date},
        "mfe_mae_research_walk_forward": bottom_walk,
        "mfe_mae_research_supporting_only": True,
    }
    return {
        **metrics,
        "bottom_research_status": bottom.get("status"),
        "bottom_research_run_id": run_id,
        "bottom_repair_probability": mfe_probability,
        "breakdown_risk_probability": mae_probability,
        "bottom_research_regime": bottom.get("regimeState"),
        "bottom_research_model_version": provenance.get("modelVersion") or diagnostics.get("modelVersion"),
        "bottom_research_sample_count": diagnostics.get("sampleCount"),
        "bottom_research_brier": bottom_walk.get("brier"),
        "bottom_research_pr_auc": bottom_walk.get("prAuc"),
        "bottom_research_fold_count": bottom_walk.get("foldCount"),
        "bottom_research_evidence_grade": diagnostics.get("evidenceGrade"),
        "bottom_research_signal_hash": signal_hash,
        "bottom_research_signal_count": signal_count,
        "bottom_research_backtest_id": backtest_id,
        "backtest_run_id": backtest_id,
        "candidate_backtest_id": backtest_id,
        "bottom_research_backtest_window": {"start_date": start_date, "end_date": end_date},
        "bottom_research_walk_forward": bottom_walk,
        "bottom_research_supporting_only": True,
        "simulation_only": True,
        "is_real_trade": False,
    }


def _bottom_research_evidence_quality(bottom: dict[str, Any]) -> str:
    diagnostics = bottom.get("modelDiagnostics") if isinstance(bottom.get("modelDiagnostics"), dict) else {}
    grade = str(diagnostics.get("evidenceGrade") or "").strip().upper()
    if grade in {"HIGH", "MEDIUM", "LOW"}:
        return grade
    status = str(bottom.get("status") or "").strip().upper()
    if status in {"PASS", "WARN"}:
        return status
    return "UNKNOWN"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _workflow_strength_from_status(status: str, has_missing_items: bool) -> str:
    if has_missing_items:
        return "MISSING"
    status_value = str(status or "").upper()
    if status_value in {"PASS", "READY"}:
        return "MEDIUM"
    if status_value == "WARN":
        return "LOW"
    if status_value in {"WAIT", "BLOCKED"}:
        return "MISSING"
    return "UNKNOWN"


def _workflow_review_strength(value: str) -> str:
    normalized = str(value or "").strip().upper()
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
    if normalized in {"MEDIUM", "LOW", "MISSING", "PENDING", "UNKNOWN"}:
        return normalized
    if normalized in {"SUPPORTING_ONLY", "WARN", "REVIEW", "REVIEW_ONLY"}:
        return "LOW"
    if normalized in {"FAIL", "FAILED", "BLOCKED"}:
        return "MISSING"
    return "UNKNOWN"


def _workflow_min_review_strength(*values: str) -> str:
    rank = {
        "MISSING": 0,
        "PENDING": 1,
        "UNKNOWN": 1,
        "LOW": 2,
        "MEDIUM": 3,
    }
    strengths = [_workflow_review_strength(value) for value in values]
    return min(strengths, key=lambda item: rank.get(item, 1), default="UNKNOWN")


def _workflow_step_default_action(status: str, has_missing_items: bool) -> tuple[str, str]:
    status_value = str(status or "").upper()
    if has_missing_items:
        return "resolve_missing_items", "Resolve missing items"
    if status_value == "PASS":
        return "no_action_required", "No action required"
    if status_value == "READY":
        return "review_decision", "Review decision"
    if status_value == "WARN":
        return "review_evidence", "Review evidence"
    return "continue_workflow", "Continue workflow"


def _first_text(mapping: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _signalops_tick_for_signal(signal_id: str, result: dict[str, Any]) -> dict[str, Any]:
    if not result:
        return {}
    if str(result.get("signal_id") or "") == signal_id:
        return result
    results = result.get("results") if isinstance(result.get("results"), list) else []
    for item in results:
        if isinstance(item, dict) and str(item.get("signal_id") or "") == signal_id:
            return item
    return {}


def _signalops_evidence_quality(
    signal: dict[str, Any],
    tick: dict[str, Any],
    transitions: list[Any],
    reviews: list[Any],
) -> str:
    if tick and (
        tick.get("decision_card")
        or _metric_mapping(tick.get("module_evidence"))
        or _metric_mapping(tick.get("portfolio_snapshot"))
    ):
        return "MEDIUM"
    status = str(signal.get("status") or "").upper()
    if status in {"PAPER_TEST", "QUALIFIED", "TRADE_PLAN", "MANUAL_CONFIRMED", "EXECUTION_REVIEW"} and (
        transitions or reviews
    ):
        return "MEDIUM"
    return "LOW"


def _strings_from_metric(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _metric_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _research_quality_blockers(
    metrics: dict[str, Any],
    portfolio_snapshot_id: Optional[str],
    backtest_id: Optional[str],
    evaluation_id: Optional[str],
    knowledge_version_id: Optional[str],
) -> list[str]:
    reasons: list[str] = []
    if not portfolio_snapshot_id:
        reasons.append("No imported holdings snapshot is linked; portfolio evidence remains user-input or template context.")
    if not backtest_id:
        return _dedupe(reasons)

    evidence = _metric_mapping(
        metrics.get("candidate_backtest_evidence_strength")
        or metrics.get("backtest_evidence_strength")
    )
    review_conclusion = str(
        metrics.get("candidate_backtest_review_conclusion")
        or metrics.get("backtest_review_conclusion")
        or ""
    ).upper()
    grade = str(evidence.get("grade") or "").upper()
    usage = str(evidence.get("researchUsage") or evidence.get("research_usage") or "").upper()
    can_support = _evidence_all_truthy(evidence, "canSupportResearchVerdict", "can_support_research_verdict")
    weak_sample = _evidence_any_truthy(evidence, "weakSample", "weak_sample")

    if review_conclusion == "SUPPORTING_ONLY" or usage == "SUPPORTING_ONLY" or weak_sample:
        reasons.append("Backtest evidence is supporting-only and cannot be promoted to a strong research conclusion.")
    if grade in {"LOW", "MEDIUM"} or (grade and grade != "HIGH"):
        reasons.append(f"Backtest evidence strength is {grade}; HIGH evidence is required before strong research conclusions.")
    if evidence and not can_support:
        reasons.append("Backtest evidence does not meet canSupportResearchVerdict.")

    sample_window = _metric_mapping(metrics.get("backtest_sample_window"))
    statistical = _metric_mapping(metrics.get("backtest_statistical_confidence"))
    limitations = _strings_from_metric(metrics.get("backtest_limitations")) + _strings_from_metric(evidence.get("limitations"))
    lower_limitations = " ".join(limitations).lower()
    missing_reasons = " ".join(_strings_from_metric(metrics.get("missing_reasons")) + _strings_from_metric(metrics.get("quality_warnings"))).lower()
    combined = f"{lower_limitations} {missing_reasons}"

    if "mock" in combined or "fallback" in combined:
        reasons.append("Backtest uses mock or fallback market data.")
    if not sample_window and not metrics.get("out_of_sample_start") and "out_of_sample" not in statistical:
        reasons.append("Backtest has no explicit out-of-sample or walk-forward evidence.")
    if "benchmark" in combined and ("missing" in combined or "unavailable" in combined):
        reasons.append("Backtest benchmark evidence is missing or unavailable.")
    return _dedupe(reasons)


def _backtest_quality_has_blockers(reasons: list[str]) -> bool:
    return any("Backtest" in reason or "benchmark" in reason or "out-of-sample" in reason for reason in reasons)


def _truthy_metric(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "pass", "passed", "accepted", "ready"}


def _evidence_all_truthy(evidence: dict[str, Any], *keys: str) -> bool:
    values = [_truthy_metric(evidence[key]) for key in keys if key in evidence]
    return bool(values) and all(values)


def _evidence_any_truthy(evidence: dict[str, Any], *keys: str) -> bool:
    return any(_truthy_metric(evidence[key]) for key in keys if key in evidence)


def _join_detail(values: list[str]) -> str:
    return "; ".join(_dedupe(values))


def _model_to_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return dict(model)


def _model_update_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    if hasattr(model, "dict"):
        return model.dict(exclude_unset=True)
    return dict(model)


def _review_gate_evidence_quality(quality: Any) -> str:
    normalized = str(quality or "").strip().upper()
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


def _review_gate_evidence_payload(evidence: Any) -> dict[str, Any]:
    payload = _model_to_dict(evidence)
    quality = str(payload.get("quality") or "").strip().upper()
    reported_quality = str(payload.get("reportedQuality") or payload.get("reported_quality") or "").strip().upper()
    gated_quality = _review_gate_evidence_quality(quality or reported_quality)
    if not reported_quality and quality and quality != gated_quality:
        reported_quality = quality
    if reported_quality:
        payload["reportedQuality"] = reported_quality
        payload["reported_quality"] = reported_quality
    payload["quality"] = gated_quality
    return payload


def _merge_evidence_links(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*existing, *incoming]:
        payload = _review_gate_evidence_payload(item)
        key = f"{str(payload.get('source_type') or '').strip().upper()}:{str(payload.get('source_id') or '').strip()}"
        if key == ":":
            continue
        previous = merged.get(key) or {}
        previous_reported_quality = previous.get("reportedQuality") or previous.get("reported_quality")
        if previous_reported_quality and not (payload.get("reportedQuality") or payload.get("reported_quality")):
            payload["reportedQuality"] = previous_reported_quality
            payload["reported_quality"] = previous_reported_quality
        merged[key] = payload
    return list(merged.values())


research_loop_store = ResearchLoopStore()
