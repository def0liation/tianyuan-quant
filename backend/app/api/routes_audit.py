from fastapi import APIRouter, HTTPException

from ..core.analysis_run_registry import get_run
from ..db.repositories import AuditRepository


router = APIRouter()


@router.get("/analysis/runs/{run_id}/audit")
async def get_audit_log(run_id: str):
    run = get_run(run_id)
    if run is not None:
        return run.get("auditLog", [])

    logs = await AuditRepository().find_by_run_id(run_id)
    if logs:
        return logs

    raise HTTPException(status_code=404, detail="Run not found")
