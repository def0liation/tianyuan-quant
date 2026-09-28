from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from ..core.kline_service import get_kline_payload


router = APIRouter()


@router.get("/market-data/kline")
async def get_kline(
    symbol: str = Query(..., min_length=1),
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    range_: str = Query("3m", alias="range", pattern="^(3m|6m|2y)$"),
) -> Dict[str, Any]:
    return get_kline_payload(symbol, period, range_)
