from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Freshness(str, Enum):
    REALTIME = "REALTIME"
    DELAYED_15MIN = "DELAYED_15MIN"
    EOD = "EOD"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class DataMode(str, Enum):
    LIVE = "LIVE"
    MOCK = "MOCK"
    MIXED = "MIXED"
    FALLBACK = "FALLBACK"


class AdapterCapability(str, Enum):
    REALTIME_QUOTE = "REALTIME_QUOTE"
    HISTORICAL_QUOTE = "HISTORICAL_QUOTE"
    FUNDAMENTALS = "FUNDAMENTALS"
    ANNOUNCEMENTS = "ANNOUNCEMENTS"
    MONEYFLOW = "MONEYFLOW"
    CHIP = "CHIP"
    MACRO = "MACRO"
    INDEX = "INDEX"
    BOND = "BOND"
    FUTURES = "FUTURES"


class FallbackStep(BaseModel):
    adapter_id: str = ""
    provider: str = ""
    attempt_at: str = ""
    success: bool = False
    error: str = ""
    latency_ms: int = 0

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "provider": self.provider,
            "attemptAt": self.attempt_at,
            "success": self.success,
            "error": self.error,
            "latencyMs": self.latency_ms,
        }


class MarketDataResponse(BaseModel):
    symbol: str
    name: str = ""
    price: Optional[float] = None
    change_percent: Optional[float] = None
    volume: Optional[float] = None
    timestamp: str = ""
    source: str = ""
    provider: str = ""
    fetched_at: str = ""
    freshness: Freshness = Freshness.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error: str = ""
    data_mode: DataMode = DataMode.MOCK
    degradation_chain: List[FallbackStep] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)

    def to_public_dict(self) -> Dict[str, Any]:
        if self.error:
            status = "FAILED"
        elif self.data_mode in (DataMode.LIVE, DataMode.FALLBACK):
            status = "READY"
        elif self.data_mode == DataMode.MOCK:
            status = "MOCK"
        else:
            status = "UNKNOWN"

        quote: Dict[str, Any] = {
            "price": self.price,
            "name": self.name,
            "changePercent": self.change_percent,
            "volume": self.volume,
        }

        return {
            "status": status,
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "changePercent": self.change_percent,
            "volume": self.volume,
            "quote": quote,
            "timestamp": self.timestamp,
            "source": self.source,
            "provider": self.provider,
            "fetchedAt": self.fetched_at,
            "freshness": self.freshness.value,
            "confidence": self.confidence,
            "error": self.error,
            "dataMode": self.data_mode.value,
            "degradationChain": [step.to_public_dict() for step in self.degradation_chain],
            "extra": self.extra,
        }


class AuxiliaryDataResponse(BaseModel):
    category: str
    source: str = ""
    provider: str = ""
    fetched_at: str = ""
    freshness: Freshness = Freshness.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error: str = ""
    data_mode: DataMode = DataMode.MOCK
    records: List[Dict[str, Any]] = Field(default_factory=list)
    record_count: int = 0
    degradation_chain: List[FallbackStep] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "source": self.source,
            "provider": self.provider,
            "fetchedAt": self.fetched_at,
            "freshness": self.freshness.value,
            "confidence": self.confidence,
            "error": self.error,
            "dataMode": self.data_mode.value,
            "records": self.records,
            "recordCount": self.record_count,
            "degradationChain": [step.to_public_dict() for step in self.degradation_chain],
            "extra": self.extra,
        }


class DataSourceHealth(BaseModel):
    adapter_id: str
    provider: str
    label: str = ""
    capabilities: List[AdapterCapability] = Field(default_factory=list)
    configured: bool = True
    healthy: bool = False
    upstream_healthy: Optional[bool] = None
    live_data_usable: Optional[bool] = None
    fallback_used: bool = False
    last_error: str = ""
    freshness: str = ""
    last_check_at: str = ""
    latency_avg_ms: int = 0
    message: str = ""
    enabled: bool = True
    installed: bool = True

    def to_public_dict(self) -> Dict[str, Any]:
        upstream_healthy = self.healthy if self.upstream_healthy is None else self.upstream_healthy
        live_data_usable = self.healthy if self.live_data_usable is None else self.live_data_usable
        last_error = self.last_error or ("" if self.healthy else self.message)
        return {
            "adapterId": self.adapter_id,
            "provider": self.provider,
            "label": self.label,
            "capabilities": [c.value for c in self.capabilities],
            "configured": self.configured,
            "healthy": self.healthy,
            "upstreamHealthy": upstream_healthy,
            "liveDataUsable": live_data_usable,
            "fallbackUsed": self.fallback_used,
            "lastError": last_error,
            "freshness": self.freshness,
            "lastCheckAt": self.last_check_at,
            "latencyAvgMs": self.latency_avg_ms,
            "message": self.message,
            "enabled": self.enabled,
            "installed": self.installed,
        }


class MarketDataStatusMatrix(BaseModel):
    categories: Dict[str, Dict[str, DataSourceHealth]] = Field(default_factory=dict)
    generated_at: str = ""

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "categories": {
                cat: {aid: health.to_public_dict() for aid, health in adapters.items()}
                for cat, adapters in self.categories.items()
            },
            "generatedAt": self.generated_at,
        }
