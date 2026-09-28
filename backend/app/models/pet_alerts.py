from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PetAlertSeverity = Literal["info", "warning", "critical"]


class PetAlertItem(BaseModel):
    id: str
    severity: PetAlertSeverity = "info"
    source: str = "system"
    title: str = "Quant alert"
    message: str = ""
    symbol: str = ""
    event_type: str = "GENERAL"
    created_at: str
    dedupe_key: str = ""
    action_url: str = ""
    acknowledged: bool = False


class PetAlertLatestResponse(BaseModel):
    generated_at: str
    count: int
    next_after_id: str = ""
    alerts: list[PetAlertItem] = Field(default_factory=list)


class PetAlertStatusResponse(BaseModel):
    generated_at: str
    enabled: bool = True
    queue_size: int
    unacknowledged_count: int
    last_alert_at: str = ""
    sources: list[str] = Field(default_factory=list)
    min_supported_poll_seconds: int = 3


class PetAlertAckResponse(BaseModel):
    id: str
    acknowledged: bool
