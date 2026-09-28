import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core.evaluation_store import evaluation_sandbox_store, knowledge_version_store
from ..models.evaluation import (
    CreateVersionRequest,
    EvaluationRunItem,
    KnowledgeVersionItem,
    PromotePatchRequest,
    RollbackRequest,
    RollbackResult,
    RunEvaluationRequest,
    StrategyExperimentReport,
    StrategyExperimentRequest,
    VersionDiffResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/case-library/patches/{patch_id}/evaluate", response_model=EvaluationRunItem)
async def run_patch_evaluation(patch_id: str, request: RunEvaluationRequest | None = None):
    try:
        result = await evaluation_sandbox_store.run_evaluation(
            patch_id=patch_id,
            force=bool(request.force) if request else False,
        )
    except KeyError as exc:
        logger.exception("Evaluation target not found for patch %s", patch_id)
        raise HTTPException(status_code=404, detail="Evaluation target not found") from exc
    return EvaluationRunItem(**result)


@router.post("/case-library/patches/{patch_id}/strategy-experiment", response_model=StrategyExperimentReport)
async def run_patch_strategy_experiment(patch_id: str, request: StrategyExperimentRequest):
    try:
        report = await evaluation_sandbox_store.run_strategy_experiment(
            patch_id=patch_id,
            hypothesis=request.hypothesis,
            strategy_configs=[cfg.model_dump() for cfg in request.strategy_configs],
            sample_window=request.sample_window,
        )
    except KeyError as exc:
        logger.exception("Strategy experiment patch not found: %s", patch_id)
        raise HTTPException(status_code=404, detail="Patch not found") from exc
    except ValueError as exc:
        logger.exception("Strategy experiment rejected for patch %s", patch_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StrategyExperimentReport(**report)


@router.get("/case-library/evaluations/{eval_id}", response_model=EvaluationRunItem)
async def get_evaluation(eval_id: str):
    result = await evaluation_sandbox_store.get_evaluation(eval_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return EvaluationRunItem(**result)


@router.get("/case-library/evaluations", response_model=list[EvaluationRunItem])
async def list_evaluations(
    patch_id: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    results = await evaluation_sandbox_store.list_evaluations(patch_id=patch_id, limit=limit)
    return [EvaluationRunItem(**r) for r in results]


@router.get("/case-library/knowledge-versions", response_model=list[KnowledgeVersionItem])
async def list_knowledge_versions(limit: int = Query(default=20, ge=1, le=100)):
    versions = await knowledge_version_store.list_versions(limit=limit)
    return [KnowledgeVersionItem(**v) for v in versions]


@router.post("/case-library/knowledge-versions", response_model=KnowledgeVersionItem)
async def create_knowledge_version(request: CreateVersionRequest | None = None):
    request = request or CreateVersionRequest()
    requested_status = str(request.status or "draft").lower()
    if requested_status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Direct knowledge version creation is draft-only; use approve-with-evaluation or rollback for governed versions.",
        )

    direct_source_fields = [
        field
        for field in (
            "source_run_id",
            "source_case_id",
            "source_patch_id",
            "source_evaluation_id",
            "source_verdict_id",
        )
        if getattr(request, field)
    ]
    if direct_source_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Direct draft creation cannot attach unvalidated source field(s): {', '.join(direct_source_fields)}.",
        )

    approval_record = dict(request.approval_record or {})
    if approval_record.get("evidence_refs"):
        raise HTTPException(
            status_code=400,
            detail="Direct draft creation cannot attach unvalidated approval_record.evidence_refs.",
        )

    version = await knowledge_version_store.create_version(
        description=request.description,
        source_run_id=None,
        source_case_id=None,
        source_patch_id=None,
        source_evaluation_id=None,
        source_verdict_id=None,
        scope=request.scope,
        risk_boundary=request.risk_boundary,
        approval_record=approval_record,
        rollback_impact=request.rollback_impact,
        status="draft",
    )
    return KnowledgeVersionItem(**version)


@router.get("/case-library/knowledge-versions/{version_id}", response_model=KnowledgeVersionItem)
async def get_knowledge_version(version_id: str):
    version = await knowledge_version_store.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return KnowledgeVersionItem(**version)


@router.post("/case-library/knowledge-versions/{version_id}/regression", response_model=KnowledgeVersionItem)
async def rerun_knowledge_version_regression(version_id: str):
    try:
        version = await knowledge_version_store.run_post_publish_regression(
            version_id,
            performed_by="human",
        )
    except KeyError as exc:
        logger.exception("Regression version not found: %s", version_id)
        raise HTTPException(status_code=404, detail="Version not found") from exc
    except ValueError as exc:
        logger.exception("Regression version rejected: %s", version_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeVersionItem(**version)


@router.get("/case-library/knowledge-versions/{ver_a}/diff/{ver_b}", response_model=VersionDiffResult)
async def diff_knowledge_versions(ver_a: str, ver_b: str):
    try:
        diff = await knowledge_version_store.diff_versions(ver_a, ver_b)
    except KeyError as exc:
        logger.exception("Version diff not found for %s vs %s", ver_a, ver_b)
        raise HTTPException(status_code=404, detail="Version diff target not found") from exc
    return VersionDiffResult(**diff)


@router.post("/case-library/knowledge-versions/{version_id}/rollback", response_model=RollbackResult)
async def rollback_knowledge_version(version_id: str, request: RollbackRequest | None = None):
    try:
        result = await knowledge_version_store.rollback_to(
            version_id=version_id,
            performed_by=request.performed_by if request else "human",
            approval_record=request.approval_record if request else {},
            rollback_impact=request.rollback_impact if request else {},
        )
    except KeyError as exc:
        logger.exception("Rollback version not found: %s", version_id)
        raise HTTPException(status_code=404, detail="Version not found") from exc
    except ValueError as exc:
        logger.exception("Rollback rejected for version %s", version_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RollbackResult(**result)


@router.post("/case-library/patches/{patch_id}/approve-with-evaluation", response_model=KnowledgeVersionItem)
async def approve_patch_with_evaluation(patch_id: str, request: PromotePatchRequest | None = None):
    from ..core.case_library_store import knowledge_patch_store

    payload = request.model_dump() if request else {}
    reviewer = request.performed_by if request else "human"
    try:
        governance = await knowledge_version_store.build_promotion_governance(
            patch_id=patch_id,
            evidence=payload,
            reviewer=reviewer,
        )
    except KeyError as exc:
        logger.exception("Promotion patch not found: %s", patch_id)
        raise HTTPException(status_code=404, detail="Patch not found") from exc
    except ValueError as exc:
        logger.exception("Promotion rejected for patch %s", patch_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    patch = await knowledge_patch_store.review_patch(
        patch_id=patch_id,
        action="APPROVE",
        reviewer=reviewer,
    )
    if not patch:
        raise HTTPException(status_code=404, detail="Patch not found")

    evidence_count = len(governance.get("approval_record", {}).get("evidence_refs", []))
    version = await knowledge_version_store.create_version(
        description=f"Promoted patch '{patch['title']}' with {evidence_count} evidence reference(s).",
        source_run_id=governance.get("source_run_id"),
        source_case_id=governance.get("source_case_id"),
        source_patch_id=patch_id,
        source_evaluation_id=governance.get("source_evaluation_id"),
        source_verdict_id=governance.get("source_verdict_id"),
        scope=governance.get("scope", "knowledge_patch_promotion"),
        risk_boundary=governance.get("risk_boundary", ""),
        approval_record=governance.get("approval_record", {}),
        rollback_impact=governance.get("rollback_impact", {}),
        status=governance.get("status", "active"),
        created_by=reviewer,
    )
    return KnowledgeVersionItem(**version)
