from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Query

from ..core.global_market_service import get_global_market_payload


router = APIRouter()


@router.get("/market-data/global")
async def get_global_market(
    range_: str = Query("4m", alias="range", pattern="^4m$"),
) -> Dict[str, Any]:
    return await asyncio.to_thread(get_global_market_payload, range_)
