import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from ..core import analysis_lifecycle_service
from ..core.analysis_run_registry import get_run
from ..core.portfolio_store import build_snapshot, get_snapshot, save_snapshot
from ..core.bottom_research import normalize_bottom_research_config
from ..core.research_artifact_store import research_artifact_store
from ..core.research_hypothesis_store import research_hypothesis_store
from ..core.research_store import research_loop_store
from ..core.research_trace_adapter import normalize_rd_agent_trace
from ..core.research_verdict_store import research_verdict_store
from ..models.portfolio import HoldingPosition
from ..models.research import (
    ArchiveResearchLoopRequest,
    AttachResearchBacktestRequest,
    AttachResearchRunRequest,
    BottomResearchBacktestRequest,
    ConfirmResearchHypothesisDraftRequest,
    CreateNextResearchIterationRequest,
    CreateP2ClosedLoopSampleRequest,
    CreateP2ClosedLoopSampleResponse,
    CreateResearchBacktestVerdictInputsRequest,
    CreateResearchIterationRequest,
    CreateResearchLoopRequest,
    CreateResearchSignalOpsEvidenceRequest,
    CreateSampleResearchLoopRequest,
    CreateSampleResearchLoopResponse,
    ClosedLoopStepStatus,
    ResearchBacktestVerdictInputsResponse,
    ResearchArtifactMaterializeRequest,
    ResearchArtifactMaterializeResult,
    ResearchHypothesisDraftRequest,
    ResearchHypothesisDraftResponse,
    ResearchEvidenceLink,
    ResearchIteration,
    ResearchIterationFeedbackRequest,
    ResearchLoop,
    ResearchLoopDetail,
    ResearchSignalOpsEvidenceResponse,
    ResearchSummary,
    ResearchTraceImportIteration,
    ResearchTraceImportRequest,
    ResearchTraceImportResponse,
    ResearchVerdictInputs,
    StartResearchRunRequest,
    StartResearchRunResponse,
    UpdateResearchIterationRequest,
    UpdateResearchLoopRequest,
)
from ..models.analysis import CreateAnalysisRequest


logger = logging.getLogger(__name__)

router = APIRouter()


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _feedback_links_from_verdict_inputs(inputs: ResearchVerdictInputs) -> list[ResearchEvidenceLink]:
    links: list[ResearchEvidenceLink] = []
    seen: set[tuple[str, str]] = set()
    for evidence in inputs.evidence:
        key = (evidence.source_type.strip().upper(), evidence.source_id.strip())
        if key in seen:
            continue
        seen.add(key)
        links.append(
            ResearchEvidenceLink(
                source_type=evidence.source_type,
                source_id=evidence.source_id,
                label=evidence.label,
                quality=evidence.quality,
                reported_quality=evidence.reported_quality,
                created_at=evidence.created_at,
            )
        )
    return links


@router.get("/research/summary", response_model=ResearchSummary)
async def research_summary():
    return await research_loop_store.get_summary()


@router.get("/research/loops", response_model=list[ResearchLoop])
async def research_loops(status: str | None = Query(default=None)):
    if not isinstance(status, str):
        status = None
    return await research_loop_store.list_loops(status=status)


@router.post("/research/loops", response_model=ResearchLoopDetail)
async def create_research_loop_route(request: CreateResearchLoopRequest):
    try:
        return await research_loop_store.create_loop(request)
    except ValueError as exc:
        logger.exception("Research loop creation failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/research/sample-loop/from-latest-run", response_model=CreateSampleResearchLoopResponse)
async def create_sample_research_loop_route(request: CreateSampleResearchLoopRequest | None = None):
    request = request or CreateSampleResearchLoopRequest()
    response = await research_loop_store.create_sample_loop_from_latest_run(request)
    if not response.created or not response.detail or not (request.materialize_artifacts or request.run_evaluation):
        return response

    iteration = (
        next(
            (
                item for item in response.detail.iterations
                if item.iteration_id == response.detail.loop.current_iteration_id
            ),
            None,
        )
        or (response.detail.iterations[-1] if response.detail.iterations else None)
    )
    if iteration is None:
        response.missing_reasons.append("Research loop was created but no iteration is available for artifact materialization.")
        return response

    try:
        artifacts = await research_artifact_store.materialize_iteration_artifacts(
            iteration.iteration_id,
            ResearchArtifactMaterializeRequest(
                create_case=True,
                create_knowledge_item=True,
                create_error_entry=True,
                create_patch=True,
                run_evaluation=request.run_evaluation,
                reviewer=request.reviewer,
                note="Materialize P2 sample closed-loop artifacts.",
                patch_content={"source": "p2_closed_loop_sample"},
            ),
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if artifacts is None:
        response.missing_reasons.append("Research artifacts could not be materialized for the sample iteration.")
        return response

    artifact_context = {
        "iteration_id": artifacts.iteration.iteration_id,
        "case_id": artifacts.case.case_id if artifacts.case else None,
        "knowledge_item_id": artifacts.knowledge_item.item_id if artifacts.knowledge_item else None,
        "error_entry_id": artifacts.error_entry.entry_id if artifacts.error_entry else None,
        "patch_id": artifacts.patch.patch_id if artifacts.patch else None,
        "evaluation_id": artifacts.evaluation.eval_id if artifacts.evaluation else None,
        "provenance_chain": artifacts.provenance_chain,
        "warnings": artifacts.warnings,
    }
    response.artifact_context = artifact_context
    response.context["artifact_context"] = artifact_context
    for warning in artifacts.warnings:
        note = f"Artifact materialization warning: {warning}"
        if note not in response.missing_reasons:
            response.missing_reasons.append(note)
    refreshed = await research_loop_store.get_loop_detail(artifacts.iteration.loop_id)
    if refreshed is not None:
        response.detail = refreshed
    return response


@router.post("/research/p2/closed-loop-sample", response_model=CreateP2ClosedLoopSampleResponse)
async def create_p2_closed_loop_sample_route(request: CreateP2ClosedLoopSampleRequest | None = None):
    request = request or CreateP2ClosedLoopSampleRequest()
    symbol = request.symbol.strip() or "P2SAMPLE.SZ"
    stock_name = request.stock_name.strip() or symbol
    warnings: list[str] = []
    steps: list[ClosedLoopStepStatus] = []

    snapshot = await get_snapshot(request.portfolio_snapshot_id) if request.portfolio_snapshot_id else None
    if request.portfolio_snapshot_id and snapshot is None:
        raise HTTPException(status_code=404, detail="Portfolio snapshot not found")
    if snapshot is None:
        now = datetime.now(timezone.utc).isoformat()
        snapshot = await save_snapshot(
            build_snapshot(
                positions=[
                    HoldingPosition(
                        symbol=symbol,
                        name=stock_name,
                        shares=1000,
                        availableShares=1000,
                        costPrice=10.0,
                        marketValue=10000.0,
                        industry="P2 sample",
                        style="sample",
                        theme="closed-loop",
                        riskFactor="sample",
                        weight=0.1,
                        updatedAt=now,
                    )
                ],
                issues=[],
                source_type="MANUAL",
                source_name="P2 closed-loop sample holdings",
                account_name="P2 sample",
                cash=90000.0,
                available_cash=90000.0,
                total_assets=100000.0,
            )
        )
    steps.append(
        ClosedLoopStepStatus(
            key="portfolio",
            label="持仓导入",
            status="PASS",
            ref_id=snapshot.snapshotId,
            note=snapshot.sourceType,
        )
    )

    run_response = await analysis_lifecycle_service.create_run(
        CreateAnalysisRequest(
            symbol=symbol,
            task_type="P2_CLOSED_LOOP_SAMPLE",
            run_mode="STANDARD_MODE",
            scenario_id="qiam_discounted",
            user_constraints={
                "position_ratio": 0.1,
                "shares": 1000,
                "cost_price": 10.0,
                "max_drawdown": 0.08,
                "allow_add": False,
                "allow_t0": True,
            },
            config_profile_id="default",
            portfolio_snapshot_id=snapshot.snapshotId,
        )
    )
    run_data = get_run(run_response.run_id)
    if not run_data:
        raise HTTPException(status_code=500, detail="P2 sample run was not created")

    now = datetime.now(timezone.utc).isoformat()
    run_data["status"] = "COMPLETED"
    run_data["updatedAt"] = now
    run_data["stockName"] = stock_name
    run_data["finalAction"] = "WAIT"
    run_data.setdefault("compressedSummary", {"quality": {"score": 84, "level": "MEDIUM"}})
    run_data.setdefault("finalWriter", {})
    run_data["finalWriter"].update(
        {
            "mode": "NORMAL",
            "finalAction": "WAIT",
            "humanConfirmationRequired": True,
        }
    )
    run_data.setdefault("signalOps", {})
    run_data["signalOps"].update(
        {
            "signalStatus": "WATCH",
            "riskPassed": True,
            "dvgPassed": True,
            "qiamPassed": True,
            "executionReachable": True,
            "triggerConditions": ["P2 sample trigger"],
            "invalidationConditions": ["P2 sample invalidation"],
            "reviewFields": ["portfolio_snapshot", "backtest_evidence", "knowledge_candidate"],
            "blockedReason": "",
            "auditId": f"AUD_SIGNALOPS_{run_response.run_id}",
        }
    )
    run_data.setdefault("auditLog", []).append(
        {
            "timestamp": now,
            "runId": run_response.run_id,
            "node": "research_lab",
            "eventType": "RUN_FINISHED",
            "message": "P2 closed-loop sample run completed deterministically.",
            "statusBefore": "CREATED",
            "statusAfter": "COMPLETED",
            "inputHash": "",
            "outputHash": "",
            "auditId": f"AUD_P2_SAMPLE_{run_response.run_id}",
        }
    )
    await analysis_lifecycle_service.persist_run(run_data, run_response.run_id, symbol)
    signal_id = (run_data.get("signalOpsLifecycle") or {}).get("signalId")
    steps.append(
        ClosedLoopStepStatus(
            key="run",
            label="Run",
            status="PASS",
            ref_id=run_response.run_id,
            note="COMPLETED",
        )
    )
    steps.append(
        ClosedLoopStepStatus(
            key="signalops",
            label="SignalOps",
            status="PASS" if signal_id else "WARN",
            ref_id=signal_id,
            note="Lifecycle signal materialized" if signal_id else "SignalOps lifecycle id missing",
        )
    )
    if not signal_id:
        warnings.append("SignalOps lifecycle id was not returned after sample run persistence.")

    sample_response = await create_sample_research_loop_route(
        CreateSampleResearchLoopRequest(
            run_id=run_response.run_id,
            symbol=symbol,
            force_backtest=request.force_backtest,
            materialize_artifacts=request.materialize_artifacts,
            run_evaluation=request.run_evaluation,
            reviewer=request.reviewer,
        )
    )
    warnings.extend(sample_response.missing_reasons)
    artifact_context = sample_response.artifact_context or {}
    context = sample_response.context or {}
    loop_id = sample_response.detail.loop.loop_id if sample_response.detail else None
    iteration = sample_response.detail.iterations[0] if sample_response.detail and sample_response.detail.iterations else None
    backtest_run_id = str(context.get("backtest_run_id") or "") or None
    backtest_evidence = context.get("backtest_evidence_strength")
    backtest_evidence_strength = (
        str(backtest_evidence.get("grade") or "").upper()
        if isinstance(backtest_evidence, dict)
        else ""
    ) or "UNKNOWN"
    backtest_missing_items = [
        warning
        for warning in warnings
        if "backtest" in warning.lower()
    ]
    backtest_needs_review = bool(backtest_run_id and backtest_missing_items)
    backtest_step_status = "WARN" if backtest_needs_review else ("PASS" if backtest_run_id else "WARN")
    backtest_step_note = (
        backtest_missing_items[0]
        if backtest_needs_review
        else ("SignalOps backtest linked" if backtest_run_id else "Backtest missing")
    )
    backtest_step_next_action = (
        "review_evidence"
        if backtest_needs_review
        else ("" if backtest_run_id else "attach_or_create_backtest")
    )
    backtest_step_next_action_label = (
        "Review evidence"
        if backtest_needs_review
        else ("" if backtest_run_id else "Attach or create backtest")
    )
    case_id = str(artifact_context.get("case_id") or "") or None
    knowledge_item_id = str(artifact_context.get("knowledge_item_id") or "") or None
    patch_id = str(artifact_context.get("patch_id") or "") or None
    evaluation_id = str(artifact_context.get("evaluation_id") or "") or None
    knowledge_version_id = None
    knowledge_version_status = None
    knowledge_version_evidence_strength = "PENDING"
    if request.promote_knowledge_version and patch_id and evaluation_id:
        from ..core.case_library_store import knowledge_patch_store
        from ..core.evaluation_store import knowledge_version_store

        try:
            governance = await knowledge_version_store.build_promotion_governance(
                patch_id=patch_id,
                evidence={
                    "run_id": run_response.run_id,
                    "case_id": case_id,
                    "backtest_id": backtest_run_id,
                    "evaluation_id": evaluation_id,
                    "verdict_id": iteration.iteration_id if iteration else None,
                    "verdict": iteration.verdict if iteration else None,
                    "approval_record": {
                        "reviewer": request.reviewer,
                        "decision": "AUTO_SAMPLE_PROMOTION",
                    },
                    "rollback_impact": {
                        "rollback_plan": "Archive the sample-promoted patch and restore the previous active knowledge version.",
                        "affected_modules": ["research", "case_library", "evaluation"],
                    },
                },
                reviewer=request.reviewer,
            )
            patch = await knowledge_patch_store.get_patch(patch_id)
            if patch:
                approval_record = dict(governance.get("approval_record", {}))
                approval_record.setdefault("decision", "AUTO_SAMPLE_REVIEW_PROMOTION")
                approval_record.setdefault("activation", "review_only")
                version = await knowledge_version_store.create_version(
                    description="P2 closed-loop sample knowledge review version.",
                    source_run_id=governance.get("source_run_id"),
                    source_case_id=governance.get("source_case_id"),
                    source_patch_id=patch_id,
                    source_evaluation_id=governance.get("source_evaluation_id"),
                    source_verdict_id=governance.get("source_verdict_id"),
                    scope=governance.get("scope", "knowledge_patch_promotion"),
                    risk_boundary=governance.get("risk_boundary", ""),
                    approval_record=approval_record,
                    rollback_impact=governance.get("rollback_impact", {}),
                    status="review",
                    created_by=request.reviewer,
                )
                knowledge_version_id = str(version.get("version_id") or "") or None
                knowledge_version_status = str(version.get("status") or "") or None
                knowledge_version_evidence_strength = str(version.get("evidence_strength") or "LOW").upper()
                artifact_context["knowledge_version_id"] = knowledge_version_id
                artifact_context["knowledge_version_status"] = knowledge_version_status
                sample_response.context["artifact_context"] = artifact_context
                warnings.append("Knowledge version staged in review status; sample evidence remains review-gate only.")
                if iteration:
                    existing_links = (
                        iteration.metrics.get("artifact_links")
                        if isinstance(iteration.metrics.get("artifact_links"), dict)
                        else {}
                    )
                    await research_loop_store.update_iteration(
                        iteration.iteration_id,
                        UpdateResearchIterationRequest(
                            metrics={
                                "artifact_links": {
                                    **existing_links,
                                    "portfolio_snapshot_id": snapshot.snapshotId,
                                    "run_id": run_response.run_id,
                                    "backtest_run_id": backtest_run_id,
                                    "case_id": case_id,
                                    "knowledge_item_id": knowledge_item_id,
                                    "patch_id": patch_id,
                                    "evaluation_id": evaluation_id,
                                    "knowledge_version_id": knowledge_version_id,
                                    "knowledge_version_status": knowledge_version_status,
                                },
                                "knowledge_version_id": knowledge_version_id,
                                "knowledge_version_status": knowledge_version_status,
                            }
                        ),
                    )
        except (KeyError, ValueError) as exc:
            warnings.append(f"Knowledge version promotion skipped: {exc}")
    knowledge_version_review_only = bool(
        knowledge_version_id
        and knowledge_version_status
        and knowledge_version_status.lower() != "active"
    )
    knowledge_version_missing_items = (
        [f"Knowledge version is {knowledge_version_status} and cannot activate feedback acceptance."]
        if knowledge_version_review_only
        else []
    )
    knowledge_version_step_status = "PASS"
    knowledge_version_step_note = "Knowledge version ready"
    knowledge_version_step_next_action = ""
    knowledge_version_step_next_action_label = ""
    if knowledge_version_review_only:
        knowledge_version_step_status = "WARN"
        knowledge_version_step_note = "Knowledge version staged for review"
        knowledge_version_step_next_action = "review_knowledge_version"
        knowledge_version_step_next_action_label = "Review knowledge version"
    elif not knowledge_version_id:
        knowledge_version_step_status = "WAIT" if not request.promote_knowledge_version else "WARN"
        knowledge_version_step_note = (
            "Promotion not requested"
            if not request.promote_knowledge_version
            else "Knowledge version promotion missing"
        )
        knowledge_version_step_next_action = "promote_knowledge_version"
        knowledge_version_step_next_action_label = "Promote knowledge version"
    steps.extend(
        [
            ClosedLoopStepStatus(
                key="backtest",
                label="Backtest",
                status=backtest_step_status,
                ref_id=backtest_run_id,
                note=backtest_step_note,
                evidence_strength=backtest_evidence_strength if backtest_run_id else "PENDING",
                missing_items=backtest_missing_items if backtest_needs_review else [],
                next_action=backtest_step_next_action,
                next_action_label=backtest_step_next_action_label,
            ),
            ClosedLoopStepStatus(
                key="research",
                label="Research",
                status="PASS" if iteration else "WARN",
                ref_id=iteration.iteration_id if iteration else None,
                note=iteration.verdict if iteration else "Iteration missing",
            ),
            ClosedLoopStepStatus(
                key="knowledge",
                label="Knowledge",
                status="PASS" if knowledge_item_id else "WARN",
                ref_id=knowledge_item_id,
                note="Knowledge candidate materialized" if knowledge_item_id else "Knowledge candidate missing",
            ),
            ClosedLoopStepStatus(
                key="case",
                label="Case",
                status="PASS" if case_id else "WARN",
                ref_id=case_id,
                note="Case materialized" if case_id else "Case missing",
            ),
            ClosedLoopStepStatus(
                key="evaluation",
                label="Evaluation",
                status="PASS" if evaluation_id else ("WAIT" if not request.run_evaluation else "WARN"),
                ref_id=evaluation_id,
                note="Evaluation completed" if evaluation_id else "Evaluation not requested" if not request.run_evaluation else "Evaluation missing",
            ),
            ClosedLoopStepStatus(
                key="knowledge_version",
                label="Knowledge Version",
                status=knowledge_version_step_status,
                ref_id=knowledge_version_id,
                note=knowledge_version_step_note,
                evidence_strength=knowledge_version_evidence_strength if knowledge_version_id else "PENDING",
                missing_items=knowledge_version_missing_items,
                next_action=knowledge_version_step_next_action,
                next_action_label=knowledge_version_step_next_action_label,
            ),
        ]
    )

    return CreateP2ClosedLoopSampleResponse(
        created=sample_response.created,
        simulation_only=True,
        is_real_trade=False,
        portfolio_snapshot_id=snapshot.snapshotId,
        run_id=run_response.run_id,
        signal_id=signal_id,
        backtest_run_id=backtest_run_id,
        loop_id=loop_id,
        iteration_id=iteration.iteration_id if iteration else None,
        case_id=case_id,
        knowledge_item_id=knowledge_item_id,
        patch_id=patch_id,
        evaluation_id=evaluation_id,
        knowledge_version_id=knowledge_version_id,
        knowledge_version_status=knowledge_version_status,
        sample_loop=sample_response,
        steps=steps,
        warnings=_dedupe_strings(warnings),
    )


@router.patch("/research/loops/{loop_id}", response_model=ResearchLoopDetail)
async def update_research_loop_route(loop_id: str, request: UpdateResearchLoopRequest):
    try:
        detail = await research_loop_store.update_loop(loop_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Research loop not found")
    return detail


@router.post("/research/loops/{loop_id}/archive", response_model=ResearchLoopDetail)
async def archive_research_loop_route(
    loop_id: str,
    request: ArchiveResearchLoopRequest | None = None,
):
    detail = await research_loop_store.archive_loop(loop_id, request or ArchiveResearchLoopRequest())
    if detail is None:
        raise HTTPException(status_code=404, detail="Research loop not found")
    return detail


@router.get("/research/loops/{loop_id}", response_model=ResearchLoopDetail)
async def research_loop_detail(loop_id: str):
    detail = await research_loop_store.get_loop_detail(loop_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Research loop not found")
    return detail


@router.get("/research/iterations", response_model=list[ResearchIteration])
async def research_iterations(loop_id: str | None = Query(default=None)):
    if not isinstance(loop_id, str):
        loop_id = None
    return await research_loop_store.list_iterations(loop_id=loop_id)


@router.get("/research/iterations/{iteration_id}", response_model=ResearchIteration)
async def research_iteration_detail(iteration_id: str):
    iteration = await research_loop_store.get_iteration(iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return iteration


@router.post("/research/loops/{loop_id}/hypotheses/draft", response_model=ResearchHypothesisDraftResponse)
async def draft_research_hypothesis_route(
    loop_id: str,
    request: ResearchHypothesisDraftRequest | None = None,
):
    try:
        response = await research_hypothesis_store.generate_draft(
            loop_id,
            request or ResearchHypothesisDraftRequest(),
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if response is None:
        raise HTTPException(status_code=404, detail="Research loop not found")
    return response


@router.post("/research/loops/{loop_id}/hypothesis-drafts", response_model=ResearchHypothesisDraftResponse)
async def create_research_hypothesis_draft_route(
    loop_id: str,
    request: ResearchHypothesisDraftRequest | None = None,
):
    return await draft_research_hypothesis_route(loop_id, request)


@router.get("/research/loops/{loop_id}/hypothesis-drafts", response_model=list[ResearchHypothesisDraftResponse])
async def list_research_hypothesis_drafts_route(loop_id: str):
    response = await research_hypothesis_store.list_drafts(loop_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Research loop not found")
    return response


@router.get("/research/hypothesis-drafts/{draft_id}", response_model=ResearchHypothesisDraftResponse)
async def get_research_hypothesis_draft_route(draft_id: str):
    response = await research_hypothesis_store.get_draft(draft_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Research hypothesis draft not found")
    return response


@router.post("/research/hypothesis-drafts/{draft_id}/confirm", response_model=ResearchIteration)
async def confirm_research_hypothesis_draft_route(
    draft_id: str,
    request: ConfirmResearchHypothesisDraftRequest | None = None,
):
    try:
        response = await research_hypothesis_store.confirm_draft(
            draft_id,
            request or ConfirmResearchHypothesisDraftRequest(),
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail="Research hypothesis draft not found")
    return response


@router.post("/research/loops/{loop_id}/iterations", response_model=ResearchIteration)
async def create_research_iteration_route(
    loop_id: str,
    request: CreateResearchIterationRequest,
):
    try:
        iteration = await research_loop_store.create_iteration(loop_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research loop not found")
    return iteration


@router.patch("/research/iterations/{iteration_id}", response_model=ResearchIteration)
async def update_research_iteration_route(
    iteration_id: str,
    request: UpdateResearchIterationRequest,
):
    try:
        iteration = await research_loop_store.update_iteration(iteration_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return iteration


@router.post("/research/iterations/{iteration_id}/attach-run", response_model=ResearchIteration)
async def attach_research_iteration_run_route(
    iteration_id: str,
    request: AttachResearchRunRequest,
):
    try:
        iteration = await research_loop_store.attach_run(iteration_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return iteration


@router.post("/research/iterations/{iteration_id}/attach-backtest", response_model=ResearchIteration)
async def attach_research_iteration_backtest_route(
    iteration_id: str,
    request: AttachResearchBacktestRequest,
):
    try:
        iteration = await research_loop_store.attach_backtest(iteration_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return iteration


@router.post("/research/backtest/runs/{run_id}/verdict-inputs", response_model=ResearchBacktestVerdictInputsResponse)
async def create_research_backtest_verdict_inputs_route(
    run_id: str,
    request: CreateResearchBacktestVerdictInputsRequest,
):
    try:
        iteration = await research_loop_store.attach_backtest(
            request.iteration_id,
            AttachResearchBacktestRequest(
                backtest_run_id=run_id,
                reviewer=request.reviewer,
                note=request.note or f"Create verdict inputs from backtest {run_id}.",
                role=request.role,
                review_conclusion=request.review_conclusion,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    inputs = (
        await research_verdict_store.refresh_inputs(iteration.iteration_id)
        if request.refresh
        else await research_verdict_store.get_inputs(iteration.iteration_id)
    )
    if inputs is None:
        raise HTTPException(status_code=404, detail="Research verdict inputs not found")
    return ResearchBacktestVerdictInputsResponse(iteration=iteration, verdict_inputs=inputs)


@router.post("/research/signalops/signals/{signal_id}/evidence", response_model=ResearchSignalOpsEvidenceResponse)
async def create_research_signalops_evidence_route(
    signal_id: str,
    request: CreateResearchSignalOpsEvidenceRequest,
):
    try:
        iteration = await research_loop_store.attach_signalops_evidence(
            request.iteration_id,
            signal_id,
            reviewer=request.reviewer,
            note=request.note or f"Create Research evidence from SignalOps signal {signal_id}.",
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    inputs = (
        await research_verdict_store.refresh_inputs(iteration.iteration_id)
        if request.refresh
        else await research_verdict_store.get_inputs(iteration.iteration_id)
    )
    if inputs is None:
        raise HTTPException(status_code=404, detail="Research verdict inputs not found")
    return ResearchSignalOpsEvidenceResponse(iteration=iteration, verdict_inputs=inputs)


@router.post("/research/iterations/{iteration_id}/next", response_model=ResearchIteration)
async def create_next_research_iteration_route(
    iteration_id: str,
    request: CreateNextResearchIterationRequest | None = None,
):
    iteration = await research_loop_store.create_next_iteration(
        iteration_id,
        request or CreateNextResearchIterationRequest(),
    )
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return iteration


@router.post("/research/iterations/{iteration_id}/start-run", response_model=StartResearchRunResponse)
async def start_research_iteration_run_route(
    iteration_id: str,
    request: StartResearchRunRequest,
):
    iteration = await research_loop_store.get_iteration(iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")

    run_response = await analysis_lifecycle_service.create_run(
        _research_iteration_analysis_request(request, iteration.loop_id, iteration.iteration_id)
    )
    status = run_response.status
    if request.auto_start:
        started = await analysis_lifecycle_service.start_run(run_response.run_id)
        status = started.status
    attached = await research_loop_store.attach_run(
        iteration_id,
        AttachResearchRunRequest(
            run_id=run_response.run_id,
            status=status,
            note="Created guarded analysis run from research iteration.",
            metrics={"auto_start": request.auto_start},
        ),
    )
    if attached is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return StartResearchRunResponse(
        run_id=run_response.run_id,
        status=status,
        stream_url=run_response.stream_url,
        iteration=attached,
    )


def _research_iteration_analysis_request(
    request: StartResearchRunRequest,
    loop_id: str,
    iteration_id: str,
) -> CreateAnalysisRequest:
    task_type = request.task_type or ""
    run_mode = request.run_mode or "STANDARD_MODE"
    quant_engine_mode = request.quant_engine_mode
    bottom_research_config = request.bottom_research_config
    is_bottom_research = _is_bottom_research_task_type(task_type, bottom_research_config)
    if is_bottom_research:
        run_mode = "STANDARD_MODE" if run_mode == "FAST_MODE" else run_mode
        quant_engine_mode = quant_engine_mode or "LOW_FREQ_MID_LONG"
        bottom_research_config = normalize_bottom_research_config(
            bottom_research_config,
            symbol=request.symbol,
        )
    return CreateAnalysisRequest(
        symbol=request.symbol,
        task_type=task_type,
        run_mode=run_mode,
        quant_engine_mode=quant_engine_mode,
        bottom_research_config=bottom_research_config,
        scenario_id=request.scenario_id,
        user_constraints=request.user_constraints,
        config_profile_id=request.config_profile_id,
        portfolio_snapshot_id=request.portfolio_snapshot_id,
        research_loop_id=loop_id,
        research_iteration_id=iteration_id,
    )


def _is_bottom_research_task_type(task_type: str, bottom_research_config: dict[str, object] | None) -> bool:
    if bottom_research_config is not None:
        return True
    raw = str(task_type or "")
    normalized = raw.strip().lower().replace("-", "_").replace(" ", "_")
    return (
        "bottom" in normalized
        or "bottom_research" in normalized
        or "mfe" in normalized
        or "mae" in normalized
        or "mfe_mae" in normalized
        or "\u5e95\u90e8" in raw
        or "MFE" in raw.upper()
        or "MAE" in raw.upper()
    )


@router.post("/research/iterations/{iteration_id}/bottom-research/backtest", response_model=ResearchIteration)
async def retry_bottom_research_backtest_route(
    iteration_id: str,
    request: BottomResearchBacktestRequest | None = None,
):
    request = request or BottomResearchBacktestRequest()
    iteration = await research_loop_store.close_bottom_research_backtest(
        iteration_id,
        run_id=request.run_id,
        force_new=request.force_new,
        reviewer=request.reviewer,
    )
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration or linked run not found")
    return iteration


@router.post("/research/iterations/{iteration_id}/mfe-mae/backtest", response_model=ResearchIteration)
async def retry_mfe_mae_research_backtest_route(
    iteration_id: str,
    request: BottomResearchBacktestRequest | None = None,
):
    return await retry_bottom_research_backtest_route(iteration_id, request)


@router.post("/research/iterations/{iteration_id}/feedback", response_model=ResearchIteration)
async def record_research_iteration_feedback_route(
    iteration_id: str,
    request: ResearchIterationFeedbackRequest,
):
    accepted_inputs: ResearchVerdictInputs | None = None
    if (request.verdict or "").strip().upper() == "ACCEPTED":
        inputs = await research_verdict_store.get_inputs(iteration_id)
        if inputs is None:
            raise HTTPException(status_code=404, detail="Research iteration not found")
        if not inputs.can_accept_feedback and not request.override_blocking_reasons:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Research iteration cannot be accepted without resolving verdict blocking reasons.",
                    "blocking_reasons": inputs.blocking_reasons,
                    "quality_warnings": inputs.quality_warnings,
                    "override": "Set override_blocking_reasons=true and provide override_reason for manual override.",
                },
            )
        accepted_inputs = inputs
    if request.override_blocking_reasons and not request.override_reason.strip():
        raise HTTPException(status_code=400, detail="override_reason is required when overriding verdict gates")
    if accepted_inputs is not None:
        override_metrics = {}
        if request.override_blocking_reasons:
            override_metrics = {
                "verdict_gate_override_inputs_generated_at": accepted_inputs.generated_at,
                "verdict_gate_override_can_accept_feedback": accepted_inputs.can_accept_feedback,
                "verdict_gate_override_blocking_reasons": accepted_inputs.blocking_reasons,
                "verdict_gate_override_quality_warnings": accepted_inputs.quality_warnings,
                "verdict_gate_override_evidence_usage": "review_gate_only",
                "verdict_gate_override_strong_conclusion_allowed": False,
                "verdict_gate_override_simulation_only": True,
                "verdict_gate_override_is_real_trade": False,
            }
        request = request.model_copy(
            update={
                "metrics": {
                    **accepted_inputs.metrics,
                    **(request.metrics or {}),
                    "verdict_inputs_generated_at": accepted_inputs.generated_at,
                    **override_metrics,
                },
                "evidence_links": [
                    *request.evidence_links,
                    *_feedback_links_from_verdict_inputs(accepted_inputs),
                ],
            },
            deep=True,
        )
    iteration = await research_loop_store.record_feedback(iteration_id, request)
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return iteration


@router.get("/research/iterations/{iteration_id}/verdict-inputs", response_model=ResearchVerdictInputs)
async def research_iteration_verdict_inputs(
    iteration_id: str,
    baseline_run_id: str | None = Query(default=None),
    candidate_run_id: str | None = Query(default=None),
):
    inputs = await research_verdict_store.get_inputs(
        iteration_id,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
    )
    if inputs is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return inputs


@router.get("/research/traces", response_model=list[ResearchLoop])
async def research_traces(
    loop_id: str | None = Query(default=None),
    iteration_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
):
    if not isinstance(loop_id, str):
        loop_id = None
    if not isinstance(iteration_id, str):
        iteration_id = None
    if not isinstance(source, str):
        source = None
    loops = await research_loop_store.list_loops()
    traces = [
        loop for loop in loops
        if "external-import" in {tag.lower() for tag in loop.tags}
        or loop.source.lower() in {"rd-agent", "external"}
    ]
    if loop_id:
        traces = [loop for loop in traces if loop.loop_id == loop_id]
    if source:
        source_filter = source.strip().lower()
        traces = [
            loop for loop in traces
            if loop.source.lower() == source_filter
            or source_filter in {tag.lower() for tag in loop.tags}
        ]
    if iteration_id:
        iteration = await research_loop_store.get_iteration(iteration_id)
        traces = [
            loop for loop in traces
            if iteration is not None and loop.loop_id == iteration.loop_id
        ]
    return traces


@router.post("/research/traces/preview", response_model=ResearchTraceImportResponse)
async def preview_rd_agent_trace_route(request: ResearchTraceImportRequest):
    return await _import_rd_agent_trace(request, dry_run=True)


@router.post("/research/traces/import", response_model=ResearchTraceImportResponse)
async def import_rd_agent_trace_route(request: ResearchTraceImportRequest):
    return await _import_rd_agent_trace(request, dry_run=request.dry_run)


@router.post("/research/imports/rd-agent-trace", response_model=ResearchTraceImportResponse)
async def import_rd_agent_trace_alias_route(request: ResearchTraceImportRequest):
    return await import_rd_agent_trace_route(request)


@router.get("/research/traces/{loop_id}", response_model=ResearchLoopDetail)
async def research_trace_detail(loop_id: str):
    return await research_loop_detail(loop_id)


@router.post("/research/iterations/{iteration_id}/verdict-inputs/refresh", response_model=ResearchVerdictInputs)
async def refresh_research_iteration_verdict_inputs(
    iteration_id: str,
    baseline_run_id: str | None = Query(default=None),
    candidate_run_id: str | None = Query(default=None),
):
    inputs = await research_verdict_store.refresh_inputs(
        iteration_id,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
    )
    if inputs is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return inputs


@router.post("/research/iterations/{iteration_id}/artifacts/materialize", response_model=ResearchArtifactMaterializeResult)
async def materialize_research_iteration_artifacts(
    iteration_id: str,
    request: ResearchArtifactMaterializeRequest | None = None,
):
    try:
        result = await research_artifact_store.materialize_iteration_artifacts(
            iteration_id,
            request or ResearchArtifactMaterializeRequest(),
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return result


@router.post("/research/iterations/{iteration_id}/compress-evidence", response_model=ResearchIteration)
async def compress_research_iteration_evidence_route(iteration_id: str):
    iteration = await research_loop_store.get_iteration(iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    if not iteration.linked_run_id:
        raise HTTPException(status_code=400, detail="Research iteration has no linked run")

    from . import routes_data_pipeline

    summary = await routes_data_pipeline.compress_run(iteration.linked_run_id)
    evidence = {
        "quality_score": getattr(summary.quality, "score", None),
        "quality_level": getattr(summary.quality, "level", None),
        "artifact_path": summary.artifact_path,
        "compressed_at": summary.compressed_at or summary.created_at,
    }
    updated = await research_loop_store.record_feedback(
        iteration_id,
        ResearchIterationFeedbackRequest(
            action="RESEARCH_EVIDENCE_COMPRESSED",
            verdict=iteration.verdict,
            status="EVIDENCE_COMPRESSED",
            note=f"Compressed linked run evidence for {iteration.linked_run_id}.",
            linked_run_id=iteration.linked_run_id,
            metrics=evidence,
            evidence_links=[
                {
                    "source_type": "COMPRESSED_RUN",
                    "source_id": iteration.linked_run_id,
                    "label": "Compressed run evidence",
                    "quality": str(evidence.get("quality_level") or "UNKNOWN"),
                    "created_at": evidence.get("compressed_at") or "",
                }
            ],
        ),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Research iteration not found")
    return updated


@router.post("/research/iterations/{iteration_id}/create-case", response_model=ResearchArtifactMaterializeResult)
async def create_research_iteration_case_route(iteration_id: str):
    return await materialize_research_iteration_artifacts(
        iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=True,
            create_knowledge_item=False,
            create_error_entry=False,
            create_patch=False,
            run_evaluation=False,
            note="Create case from research iteration.",
        ),
    )


@router.post("/research/iterations/{iteration_id}/create-knowledge", response_model=ResearchArtifactMaterializeResult)
async def create_research_iteration_knowledge_route(iteration_id: str):
    return await materialize_research_iteration_artifacts(
        iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=False,
            create_knowledge_item=True,
            create_error_entry=False,
            create_patch=False,
            run_evaluation=False,
            note="Create knowledge candidate from research iteration.",
        ),
    )


@router.post("/research/iterations/{iteration_id}/create-patch", response_model=ResearchArtifactMaterializeResult)
async def create_research_iteration_patch_route(iteration_id: str):
    return await materialize_research_iteration_artifacts(
        iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=False,
            create_knowledge_item=False,
            create_error_entry=True,
            create_patch=True,
            run_evaluation=False,
            note="Create patch candidate from research iteration.",
        ),
    )


@router.post("/research/iterations/{iteration_id}/evaluate", response_model=ResearchArtifactMaterializeResult)
async def evaluate_research_iteration_route(iteration_id: str):
    return await materialize_research_iteration_artifacts(
        iteration_id,
        ResearchArtifactMaterializeRequest(
            create_case=False,
            create_knowledge_item=False,
            create_error_entry=False,
            create_patch=True,
            run_evaluation=True,
            note="Evaluate research iteration patch candidate.",
        ),
    )


async def _import_rd_agent_trace(
    request: ResearchTraceImportRequest,
    *,
    dry_run: bool,
) -> ResearchTraceImportResponse:
    try:
        normalized = normalize_rd_agent_trace(request.trace, source_id=request.source_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    preview_iterations = [
        ResearchTraceImportIteration(
            order=item.order,
            iteration=None,
            hypothesis=item.create_request.hypothesis,
            external_verdict=item.feedback_request.verdict,
            evidence_count=len(item.feedback_request.evidence_links),
        )
        for item in normalized.iterations
    ]
    if dry_run:
        return ResearchTraceImportResponse(
            imported=False,
            loop=None,
            loop_preview=normalized.loop_create_request,
            iterations=preview_iterations,
            external_source=normalized.external_source,
            warnings=normalized.warnings,
        )

    detail = await research_loop_store.create_loop(normalized.loop_create_request)
    imported_iterations: list[ResearchTraceImportIteration] = []
    for index, item in enumerate(normalized.iterations):
        if index == 0 and detail.iterations:
            iteration = detail.iterations[0]
            updated = await research_loop_store.update_iteration(
                iteration.iteration_id,
                UpdateResearchIterationRequest(
                    plan=item.create_request.plan,
                    target_modules=item.create_request.target_modules,
                    linked_run_id=item.create_request.linked_run_id,
                    linked_backtest_id=item.feedback_request.linked_backtest_id,
                    metrics={
                        **item.create_request.metrics,
                        "external_source": item.external_source,
                        "trace_imported": True,
                    },
                ),
            )
            iteration = updated or iteration
        else:
            created = await research_loop_store.create_iteration(detail.loop.loop_id, item.create_request)
            if created is None:
                raise HTTPException(status_code=404, detail="Research loop not found during trace import")
            iteration = created

        feedback = await research_loop_store.record_feedback(
            iteration.iteration_id,
            ResearchIterationFeedbackRequest(
                action="IMPORT_RD_AGENT_TRACE",
                verdict="PENDING",
                status="EXTERNAL_IMPORTED",
                note=(
                    request.note
                    or item.feedback_request.note
                    or "Imported external RD-Agent trace. External conclusions are review-only until evaluated by super."
                ),
                reviewer=request.reviewer or "human",
                linked_run_id=item.feedback_request.linked_run_id,
                linked_backtest_id=item.feedback_request.linked_backtest_id,
                linked_case_id=item.feedback_request.linked_case_id,
                linked_knowledge_item_id=item.feedback_request.linked_knowledge_item_id,
                linked_patch_id=item.feedback_request.linked_patch_id,
                metrics={
                    **item.feedback_request.metrics,
                    "external_source": item.external_source,
                    "external_verdict": item.feedback_request.verdict,
                    "external_feedback_action": item.feedback_request.action,
                    "external_review_only": True,
                },
                evidence_links=item.feedback_request.evidence_links,
            ),
        )
        imported_iterations.append(
            ResearchTraceImportIteration(
                order=item.order,
                iteration=feedback or iteration,
                hypothesis=item.create_request.hypothesis,
                external_verdict=item.feedback_request.verdict,
                evidence_count=len(item.feedback_request.evidence_links),
            )
        )

    refreshed = await research_loop_store.get_loop_detail(detail.loop.loop_id)
    return ResearchTraceImportResponse(
        imported=True,
        loop=(refreshed.loop if refreshed else detail.loop),
        loop_preview=normalized.loop_create_request,
        iterations=imported_iterations,
        external_source=normalized.external_source,
        warnings=normalized.warnings,
    )
