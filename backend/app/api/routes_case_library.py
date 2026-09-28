import logging

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

logger = logging.getLogger(__name__)

from ..core.case_library_store import (
    case_library_store,
    review_tag_store,
    error_ledger_store,
    knowledge_patch_store,
)
from ..core.analysis_run_registry import get_run
from ..models.case_library import (
    CaseLibraryItem,
    CaseLibrarySummary,
    CreateCaseRequest,
    UpdateCaseReviewRequest,
    ReviewTagItem,
    CreateReviewTagRequest,
    ReviewTagSummary,
    ErrorLedgerItem,
    ErrorLedgerSummary,
    CreateErrorEntryRequest,
    UpdateErrorEntryRequest,
    KnowledgePatchItem,
    KnowledgePatchSummary,
    CreateKnowledgePatchRequest,
    ReviewPatchRequest,
    UpdateBacktestRequest,
)

router = APIRouter()


@router.get("/case-library/summary", response_model=CaseLibrarySummary)
async def get_case_library_summary():
    return await case_library_store.get_summary()


@router.get("/case-library/cases", response_model=list[CaseLibraryItem])
async def list_cases(
    symbol: Optional[str] = Query(default=None),
    task_type: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    cases = await case_library_store.list_cases(
        symbol=symbol,
        task_type=task_type,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )
    return [CaseLibraryItem(**case) for case in cases]


@router.get("/case-library/cases/{case_id}", response_model=CaseLibraryItem)
async def get_case(case_id: str):
    case = await case_library_store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseLibraryItem(**case)


@router.post("/case-library/cases", response_model=CaseLibraryItem)
async def create_case(request: CreateCaseRequest):
    run_data = get_run(request.run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Run not found")
    case = await case_library_store.create_case(run_data, reviewer=request.reviewer)
    return CaseLibraryItem(**case_library_store._case_to_dict(case))


@router.post("/case-library/cases/{case_id}/review", response_model=CaseLibraryItem)
async def update_case_review(case_id: str, request: UpdateCaseReviewRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    case = await case_library_store.update_case_review(case_id, updates)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseLibraryItem(**case)


@router.get("/case-library/tags/summary", response_model=ReviewTagSummary)
async def get_review_tag_summary():
    return await review_tag_store.get_tag_summary()


@router.get("/case-library/tags", response_model=list[ReviewTagItem])
async def list_review_tags(
    case_id: Optional[str] = Query(default=None),
    tag_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    tags = await review_tag_store.list_tags(case_id=case_id, tag_type=tag_type, limit=limit)
    return [ReviewTagItem(**tag) for tag in tags]


@router.post("/case-library/cases/{case_id}/tags", response_model=ReviewTagItem)
async def create_review_tag(case_id: str, request: CreateReviewTagRequest):
    case = await case_library_store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    tag = await review_tag_store.create_tag(
        case_id=case_id,
        run_id=case["run_id"],
        tag_data=request.model_dump(),
    )
    return ReviewTagItem(**review_tag_store._tag_to_dict(tag))


@router.get("/case-library/error-ledger/summary", response_model=ErrorLedgerSummary)
async def get_error_ledger_summary():
    return await error_ledger_store.get_summary()


@router.get("/case-library/error-ledger", response_model=list[ErrorLedgerItem])
async def list_error_entries(
    status: Optional[str] = Query(default=None),
    error_type: Optional[str] = Query(default=None),
    node: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    entries = await error_ledger_store.list_entries(
        status=status, error_type=error_type, node=node, limit=limit
    )
    return [ErrorLedgerItem(**entry) for entry in entries]


@router.post("/case-library/error-ledger", response_model=ErrorLedgerItem)
async def create_error_entry(request: CreateErrorEntryRequest):
    run_id = str(request.attribution.get("run_id") or "").strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="attribution.run_id is required")
    run_data = get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Run not found")
    canonical_run_id = str(run_data.get("runId") or "").strip()
    if canonical_run_id != run_id:
        raise HTTPException(
            status_code=400,
            detail="attribution.run_id does not match canonical analysis run",
        )
    error_data = request.model_dump()
    attribution = dict(error_data.get("attribution") or {})
    attribution["run_id"] = canonical_run_id
    error_data["attribution"] = attribution
    entry = await error_ledger_store.create_entry(
        run_data, error_data=error_data
    )
    return ErrorLedgerItem(**error_ledger_store._entry_to_dict(entry))


@router.post("/case-library/error-ledger/{entry_id}", response_model=ErrorLedgerItem)
async def update_error_entry(entry_id: str, request: UpdateErrorEntryRequest):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    entry = await error_ledger_store.update_entry(entry_id, updates)
    if not entry:
        raise HTTPException(status_code=404, detail="Error entry not found")
    return ErrorLedgerItem(**entry)


@router.get("/case-library/patches/summary", response_model=KnowledgePatchSummary)
async def get_knowledge_patch_summary():
    return await knowledge_patch_store.get_summary()


@router.get("/case-library/patches", response_model=list[KnowledgePatchItem])
async def list_knowledge_patches(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    patches = await knowledge_patch_store.list_patches(status=status, limit=limit)
    return [KnowledgePatchItem(**patch) for patch in patches]


@router.post("/case-library/patches", response_model=KnowledgePatchItem)
async def create_knowledge_patch(request: CreateKnowledgePatchRequest):
    source_error_id = str(request.source_error_id or "").strip() or None
    source_case_id = str(request.source_case_id or "").strip() or None
    source_error = None
    source_case = None
    if source_error_id:
        source_error = await error_ledger_store.get_entry(source_error_id)
        if not source_error:
            raise HTTPException(status_code=404, detail="Source error entry not found")
    if source_case_id:
        source_case = await case_library_store.get_case(source_case_id)
        if not source_case:
            raise HTTPException(status_code=404, detail="Source case not found")
    if source_error and source_case:
        same_run = source_error.get("run_id") == source_case.get("run_id")
        same_audit = source_error.get("audit_id") == source_case.get("audit_id")
        if not (same_run and same_audit):
            raise HTTPException(
                status_code=400,
                detail="source_error_id and source_case_id must reference the same run",
            )
    patch = await knowledge_patch_store.create_patch(
        title=request.title,
        reason=request.reason,
        affected_modules=request.affected_modules,
        patch_content=request.patch_content,
        source_error_id=source_error_id,
        source_case_id=source_case_id,
    )
    return KnowledgePatchItem(**knowledge_patch_store._patch_to_dict(patch))


@router.post("/case-library/patches/{patch_id}/review", response_model=KnowledgePatchItem)
async def review_knowledge_patch(patch_id: str, request: ReviewPatchRequest):
    try:
        patch = await knowledge_patch_store.review_patch(
            patch_id=patch_id,
            action=request.action,
            reviewer=request.reviewer,
            note=request.note,
        )
    except ValueError as exc:
        logger.exception("请求参数错误")
        raise HTTPException(status_code=400, detail="请求参数错误") from exc
    if not patch:
        raise HTTPException(status_code=404, detail="Patch not found")
    return KnowledgePatchItem(**patch)


@router.delete("/case-library/cases/{case_id}")
async def delete_case(case_id: str):
    deleted = await case_library_store.delete_case(case_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"deleted": case_id}


@router.delete("/case-library/tags/{tag_id}")
async def delete_tag(tag_id: str):
    deleted = await review_tag_store.delete_tag(tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")
    return {"deleted": tag_id}


@router.delete("/case-library/error-ledger/{entry_id}")
async def delete_error_entry(entry_id: str):
    deleted = await error_ledger_store.delete_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Error entry not found")
    return {"deleted": entry_id}


@router.delete("/case-library/patches/{patch_id}")
async def delete_knowledge_patch(patch_id: str):
    deleted = await knowledge_patch_store.delete_patch(patch_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Patch not found")
    return {"deleted": patch_id}


@router.post("/case-library/patches/{patch_id}/backtest", response_model=KnowledgePatchItem)
async def update_patch_backtest(patch_id: str, request: UpdateBacktestRequest):
    patch = await knowledge_patch_store.update_backtest_result(
        patch_id=patch_id,
        backtest_result=request.backtest_result,
    )
    if not patch:
        raise HTTPException(status_code=404, detail="Patch not found")
    return KnowledgePatchItem(**patch)
