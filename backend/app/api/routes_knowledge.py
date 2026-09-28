import logging

from fastapi import APIRouter, HTTPException, Path, Query

from ..core.analysis_run_registry import get_run
from ..core.constants import RUN_ID_PATH_PATTERN
from ..core.knowledge_store import (
    create_knowledge_item,
    create_learning_candidate_from_run,
    get_active_knowledge_context,
    get_knowledge_summary,
    list_knowledge_items,
    review_knowledge_item,
)
from ..models.knowledge import (
    CreateKnowledgeItemRequest,
    GenerateKnowledgeFromRunRequest,
    KnowledgeContextResponse,
    KnowledgeItem,
    KnowledgeSummary,
    ReviewKnowledgeItemRequest,
)


logger = logging.getLogger(__name__)

router = APIRouter()


def _validated_manual_source_run_id(source_run_id: str | None) -> str | None:
    normalized_run_id = str(source_run_id or "").strip()
    if not normalized_run_id:
        return None

    run_data = get_run(normalized_run_id)
    if run_data is None:
        raise HTTPException(
            status_code=400,
            detail="source_run_id must reference an existing non-legacy analysis run",
        )

    canonical_run_id = str(run_data.get("runId") or normalized_run_id).strip()
    if canonical_run_id != normalized_run_id:
        raise HTTPException(
            status_code=400,
            detail="source_run_id does not match the canonical analysis run",
        )
    return canonical_run_id


@router.get("/knowledge/summary", response_model=KnowledgeSummary)
async def knowledge_summary():
    return get_knowledge_summary()


@router.get("/knowledge/items", response_model=list[KnowledgeItem])
async def knowledge_items(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
):
    return list_knowledge_items(status=status, category=category)


@router.get("/knowledge/context", response_model=KnowledgeContextResponse)
async def knowledge_context(limit: int = Query(default=8, ge=1, le=50)):
    return KnowledgeContextResponse(items=get_active_knowledge_context(limit=limit))


@router.post("/knowledge/items", response_model=KnowledgeItem)
async def create_knowledge_item_route(request: CreateKnowledgeItemRequest):
    try:
        source_run_id = _validated_manual_source_run_id(request.source_run_id)
        return create_knowledge_item(
            request.model_copy(update={"source_run_id": source_run_id}),
            source_run_verified=source_run_id is not None,
        )
    except ValueError as exc:
        logger.exception("知识项创建失败")
        raise HTTPException(status_code=400, detail="知识项创建失败") from exc


@router.post("/knowledge/items/{item_id}/review", response_model=KnowledgeItem)
async def review_knowledge_item_route(item_id: str, request: ReviewKnowledgeItemRequest):
    try:
        return review_knowledge_item(item_id, request)
    except KeyError as exc:
        logger.exception("知识项不存在")
        raise HTTPException(status_code=404, detail="知识项不存在") from exc
    except ValueError as exc:
        logger.exception("请求参数错误")
        raise HTTPException(status_code=400, detail="请求参数错误") from exc


@router.post("/knowledge/from-run/{run_id}", response_model=KnowledgeItem)
async def create_knowledge_from_run(
    run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN),
    request: GenerateKnowledgeFromRunRequest | None = None,
):
    run_data = get_run(run_id)
    if run_data is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return create_learning_candidate_from_run(
        run_data,
        force=bool(request.force) if request else False,
    )
