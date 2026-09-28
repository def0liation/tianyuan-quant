from fastapi import APIRouter, HTTPException, Path, Query

from ..core.agent_runtime_store import save_run
from ..core.analysis_run_registry import get_run, iter_runs
from ..core.constants import RUN_ID_PATH_PATTERN
from ..core.data_pipeline import (
    compression_overview,
    distill_knowledge_items,
    mark_summary_persisted,
    persisted_compression_summary,
    score_run_quality,
    summarize_run,
)
from ..core.knowledge_store import list_knowledge_items
from ..models.data_pipeline import (
    CompressionOverview,
    DataQualityScore,
    KnowledgeDistillationGroup,
    RunCompressionSummary,
)


router = APIRouter()


@router.get("/data-pipeline/overview", response_model=CompressionOverview)
async def data_pipeline_overview(limit: int = Query(default=50, ge=1, le=500)):
    runs = sorted(
        (run for _run_id, run in iter_runs()),
        key=lambda item: item.get("updatedAt") or item.get("createdAt") or "",
        reverse=True,
    )[:limit]
    return compression_overview(runs)


@router.get("/data-pipeline/runs/{run_id}/quality", response_model=DataQualityScore)
async def run_quality(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run_data = _get_run(run_id)
    return score_run_quality(run_data)


@router.get("/data-pipeline/runs/{run_id}/summary", response_model=RunCompressionSummary)
async def run_summary(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run_data = _get_run(run_id)
    persisted = persisted_compression_summary(run_data)
    if persisted is not None:
        return persisted
    return summarize_run(run_data)


@router.post("/data-pipeline/runs/{run_id}/compress", response_model=RunCompressionSummary)
async def compress_run(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run_data = _get_run(run_id)
    persisted = persisted_compression_summary(run_data)
    if persisted is not None:
        return persisted

    summary = mark_summary_persisted(run_data, summarize_run(run_data))
    run_data["compressedSummary"] = summary.model_dump()
    save_run(run_data)
    return summary


@router.get("/data-pipeline/knowledge/distill", response_model=list[KnowledgeDistillationGroup])
async def distill_knowledge(
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    min_group_size: int = Query(default=2, ge=2, le=20),
):
    items = list_knowledge_items(status=status, category=category)
    return distill_knowledge_items(items, min_group_size=min_group_size)


def _get_run(run_id: str) -> dict:
    run_data = get_run(run_id)
    if run_data is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_data
