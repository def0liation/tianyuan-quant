from __future__ import annotations

from fastapi import APIRouter, Path, Query

from ..core.pet_alerts import pet_alert_center
from ..models.pet_alerts import PetAlertAckResponse, PetAlertLatestResponse, PetAlertStatusResponse


router = APIRouter()


@router.get("/pet/alerts/latest", response_model=PetAlertLatestResponse)
async def get_pet_alerts_latest(
    after_id: str = Query("", max_length=128),
    min_severity: str = Query("info", max_length=16),
    limit: int = Query(20, ge=1, le=100),
):
    return pet_alert_center.latest(after_id=after_id, min_severity=min_severity, limit=limit)


@router.get("/pet/alerts/status", response_model=PetAlertStatusResponse)
async def get_pet_alerts_status():
    return pet_alert_center.status()


@router.post("/pet/alerts/{alert_id}/ack", response_model=PetAlertAckResponse)
async def ack_pet_alert(alert_id: str = Path(..., min_length=1, max_length=128)):
    return {"id": alert_id, "acknowledged": pet_alert_center.ack(alert_id)}
