from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from ..models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    FallbackStep,
    Freshness,
    MarketDataResponse,
    MarketDataStatusMatrix,
)
from .market_data_reconciler import MarketDataReconciler


logger = logging.getLogger(__name__)


def _summarize_fallback_errors(chain: List[FallbackStep]) -> str:
    parts = [
        f"{step.provider}: {step.error}"
        for step in chain
        if not step.success and step.error
    ]
    return "；".join(parts[:3])


class BaseMarketDataAdapter(ABC):
    adapter_id: str
    provider_name: str
    label: str = ""
    priority: int = 10
    capabilities: Set[AdapterCapability] = set()
    timeout_seconds: int = 15
    enabled: bool = True

    @abstractmethod
    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        ...

    @abstractmethod
    async def fetch_historical_quote(
        self, symbol: str, start: str, end: str
    ) -> List[MarketDataResponse]:
        ...

    @abstractmethod
    async def fetch_auxiliary(
        self, symbol: str, category: str
    ) -> AuxiliaryDataResponse:
        ...

    @abstractmethod
    async def health_check(self) -> DataSourceHealth:
        ...

    def can_handle(self, capability: AdapterCapability) -> bool:
        return capability in self.capabilities

    def apply_runtime_config(self, config: Any) -> None:
        self.enabled = bool(getattr(config, "enabled", self.enabled))
        self.priority = int(getattr(config, "priority", self.priority))
        self.timeout_seconds = int(getattr(config, "timeout_seconds", self.timeout_seconds))

    def _is_installed(self) -> bool:
        return True

    def _metadata_health(self, message: str = "") -> DataSourceHealth:
        return DataSourceHealth(
            adapter_id=self.adapter_id,
            provider=self.provider_name,
            label=self.label,
            capabilities=list(self.capabilities),
            configured=self.enabled,
            healthy=False,
            upstream_healthy=False,
            live_data_usable=False,
            last_error=message,
            message=message,
            enabled=self.enabled,
            installed=self._is_installed(),
        )

    def _build_fallback_response(
        self,
        symbol: str,
        error: str,
        attempted_adapters: List[BaseMarketDataAdapter],
    ) -> MarketDataResponse:
        chain = [
            FallbackStep(
                adapter_id=a.adapter_id,
                provider=a.provider_name,
                attempt_at=datetime.now(timezone.utc).isoformat(),
                success=False,
                error=error if a.adapter_id == self.adapter_id else "",
            )
            for a in attempted_adapters
        ]
        return MarketDataResponse(
            symbol=symbol,
            source="mock",
            provider="mock",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.UNKNOWN,
            confidence=0.0,
            error=error,
            data_mode=DataMode.MOCK,
            degradation_chain=chain,
        )

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class MarketDataAdapterRegistry:
    def __init__(self):
        self._adapters: Dict[str, BaseMarketDataAdapter] = {}

    def register(self, adapter: BaseMarketDataAdapter) -> None:
        self._adapters[adapter.adapter_id] = adapter

    def unregister(self, adapter_id: str) -> None:
        self._adapters.pop(adapter_id, None)

    def get_adapter(self, adapter_id: str) -> Optional[BaseMarketDataAdapter]:
        return self._adapters.get(adapter_id)

    def get_adapters_by_capability(
        self, capability: AdapterCapability
    ) -> List[BaseMarketDataAdapter]:
        candidates = [
            a
            for a in self._adapters.values()
            if a.enabled and a.can_handle(capability)
        ]
        candidates.sort(key=lambda a: a.priority)
        return candidates

    def list_adapters(self) -> List[DataSourceHealth]:
        results: List[DataSourceHealth] = []
        for adapter in self._adapters.values():
            results.append(
                DataSourceHealth(
                    adapter_id=adapter.adapter_id,
                    provider=adapter.provider_name,
                    label=adapter.label,
                    capabilities=list(adapter.capabilities),
                    configured=adapter.enabled,
                    enabled=adapter.enabled,
                    installed=adapter._is_installed(),
                )
            )
        return results

    async def health_check_adapter(self, adapter_id: str) -> Optional[DataSourceHealth]:
        adapter = self.get_adapter(adapter_id)
        if adapter is None:
            return None
        return await self._run_health_check(adapter)

    async def _run_health_check(self, adapter: BaseMarketDataAdapter) -> DataSourceHealth:
        if not adapter.enabled:
            return adapter._metadata_health("适配器已禁用")

        started = time.perf_counter()
        try:
            health = await asyncio.wait_for(
                adapter.health_check(),
                timeout=adapter.timeout_seconds,
            )
            health.configured = adapter.enabled and health.configured
            if health.upstream_healthy is None:
                health.upstream_healthy = health.healthy
            if health.live_data_usable is None:
                health.live_data_usable = health.healthy
            if not health.healthy and not health.last_error:
                health.last_error = health.message
            return health
        except asyncio.TimeoutError:
            latency = int((time.perf_counter() - started) * 1000)
            return DataSourceHealth(
                adapter_id=adapter.adapter_id,
                provider=adapter.provider_name,
                label=adapter.label,
                capabilities=list(adapter.capabilities),
                configured=adapter.enabled,
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                last_error=f"timeout after {adapter.timeout_seconds}s",
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=latency,
                message=f"健康检查超时：超过 {adapter.timeout_seconds}s 未返回",
                enabled=adapter.enabled,
                installed=adapter._is_installed(),
            )
        except Exception:
            logger.exception("health_check failed for %s", adapter.adapter_id)
            return DataSourceHealth(
                adapter_id=adapter.adapter_id,
                provider=adapter.provider_name,
                label=adapter.label,
                capabilities=list(adapter.capabilities),
                configured=adapter.enabled,
                healthy=False,
                upstream_healthy=False,
                live_data_usable=False,
                last_error="health check failed",
                last_check_at=datetime.now(timezone.utc).isoformat(),
                latency_avg_ms=int((time.perf_counter() - started) * 1000),
                message="健康检查失败，请稍后重试",
                enabled=adapter.enabled,
                installed=adapter._is_installed(),
            )

    async def health_check_all(self) -> List[DataSourceHealth]:
        return await asyncio.gather(*[
            self._run_health_check(adapter)
            for adapter in self._adapters.values()
        ])

    async def fetch_realtime_quote_with_fallback(
        self,
        symbol: str,
        fallback_to_mock: bool = True,
    ) -> MarketDataResponse:
        adapters = self.get_adapters_by_capability(AdapterCapability.REALTIME_QUOTE)
        if not adapters:
            if fallback_to_mock:
                return self._mock_quote(symbol)
            return MarketDataResponse(
                symbol=symbol,
                error="No adapter available for realtime quote",
                data_mode=DataMode.MOCK,
            )

        return await self._attempt_adapters(
            capability=AdapterCapability.REALTIME_QUOTE,
            adapters=adapters,
            symbol=symbol,
            fetch_fn=lambda a, s: a.fetch_realtime_quote(s),
            fallback_to_mock=fallback_to_mock,
        )

    async def fetch_auxiliary_with_fallback(
        self,
        symbol: str,
        category: str,
        fallback_to_mock: bool = True,
    ) -> AuxiliaryDataResponse:
        capability = self._category_to_capability(category)
        if capability is None:
            return AuxiliaryDataResponse(
                category=category,
                error=f"Unknown auxiliary category: {category}",
                data_mode=DataMode.MOCK,
            )

        adapters = self.get_adapters_by_capability(capability)
        if not adapters:
            if fallback_to_mock:
                return self._mock_auxiliary(category)
            return AuxiliaryDataResponse(
                category=category,
                error=f"No adapter available for {category}",
                data_mode=DataMode.MOCK,
            )

        return await self._attempt_auxiliary_adapters(
            capability=capability,
            adapters=adapters,
            symbol=symbol,
            category=category,
            fetch_fn=lambda a, s: a.fetch_auxiliary(s, category),
            fallback_to_mock=fallback_to_mock,
        )

    async def fetch_historical_quote_with_fallback(
        self,
        symbol: str,
        start: str,
        end: str,
        fallback_to_mock: bool = True,
    ) -> List[MarketDataResponse]:
        adapters = self.get_adapters_by_capability(AdapterCapability.HISTORICAL_QUOTE)
        if not adapters:
            if fallback_to_mock:
                return self._mock_historical_quotes(symbol, start, end)
            return []
        groups: List[tuple[str, str, List[MarketDataResponse]]] = []
        chain: List[FallbackStep] = []
        for adapter in adapters:
            attempt_at = datetime.now(timezone.utc).isoformat()
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    adapter.fetch_historical_quote(symbol, start, end),
                    timeout=adapter.timeout_seconds,
                )
                latency = int((time.perf_counter() - started) * 1000)
                if result:
                    chain.append(
                        FallbackStep(
                            adapter_id=adapter.adapter_id,
                            provider=adapter.provider_name,
                            attempt_at=attempt_at,
                            success=True,
                            latency_ms=latency,
                        )
                    )
                    groups.append((adapter.adapter_id, adapter.provider_name, result))
                else:
                    chain.append(
                        FallbackStep(
                            adapter_id=adapter.adapter_id,
                            provider=adapter.provider_name,
                            attempt_at=attempt_at,
                            success=False,
                            error="no records returned",
                            latency_ms=latency,
                        )
                    )
            except asyncio.TimeoutError:
                latency = int((time.perf_counter() - started) * 1000)
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=False,
                        error=f"timeout after {adapter.timeout_seconds}s",
                        latency_ms=latency,
                    )
                )
            except Exception:
                logger.exception("fetch_historical_quote failed for %s", adapter.adapter_id)
                latency = int((time.perf_counter() - started) * 1000)
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=False,
                        error="data fetch failed",
                        latency_ms=latency,
                    )
                )
        if groups:
            return MarketDataReconciler.reconcile_historical(groups, chain)
        if fallback_to_mock:
            result = self._mock_historical_quotes(symbol, start, end)
            for row in result:
                row.degradation_chain = chain
            return result
        return []

    def _mock_historical_quotes(
        self, symbol: str, start: str, end: str
    ) -> List[MarketDataResponse]:
        from datetime import timedelta
        results: List[MarketDataResponse] = []
        try:
            sd = datetime.strptime(start[:10], "%Y-%m-%d")
            ed = datetime.strptime(end[:10], "%Y-%m-%d")
        except ValueError:
            return results
        base_price = 50.0
        current = sd
        while current <= ed:
            if current.weekday() < 5:
                random.seed(hash(f"{symbol}{current.date()}") & 0xFFFFFFFF)
                price = base_price * (1 + random.uniform(-0.15, 0.15))
                base_price = price
                results.append(MarketDataResponse(
                    symbol=symbol,
                    name=symbol,
                    price=round(price, 2),
                    change_percent=round(random.uniform(-3, 3), 2),
                    volume=round(random.uniform(10000, 1000000)),
                    timestamp=current.strftime("%Y-%m-%d"),
                    source="mock",
                    provider="mock",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    freshness=Freshness.EOD,
                    confidence=0.3,
                    data_mode=DataMode.MOCK,
                ))
            current += timedelta(days=1)
        return results

    async def build_status_matrix(self) -> MarketDataStatusMatrix:
        categories = {
            "realtime_quote": AdapterCapability.REALTIME_QUOTE,
            "historical_quote": AdapterCapability.HISTORICAL_QUOTE,
            "fundamentals": AdapterCapability.FUNDAMENTALS,
            "announcements": AdapterCapability.ANNOUNCEMENTS,
            "moneyflow": AdapterCapability.MONEYFLOW,
            "chip": AdapterCapability.CHIP,
            "macro": AdapterCapability.MACRO,
            "index_sector": AdapterCapability.INDEX,
        }
        matrix: Dict[str, Dict[str, DataSourceHealth]] = {}
        category_adapters: Dict[str, List[BaseMarketDataAdapter]] = {}
        unique_adapters: Dict[str, BaseMarketDataAdapter] = {}

        for cat_key, capability in categories.items():
            adapters = self.get_adapters_by_capability(capability)
            category_adapters[cat_key] = adapters
            for adapter in adapters:
                unique_adapters[adapter.adapter_id] = adapter

        health_cache: Dict[str, DataSourceHealth] = {}
        if unique_adapters:
            health_results = await asyncio.gather(
                *[self._run_health_check(adapter) for adapter in unique_adapters.values()]
            )
            health_cache = dict(zip(unique_adapters.keys(), health_results))

        for cat_key, adapters in category_adapters.items():
            matrix[cat_key] = {}
            for adapter in adapters:
                matrix[cat_key][adapter.adapter_id] = health_cache[adapter.adapter_id]

        return MarketDataStatusMatrix(
            categories=matrix,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _attempt_adapters(
        self,
        capability: AdapterCapability,
        adapters: List[BaseMarketDataAdapter],
        symbol: str,
        fetch_fn,
        fallback_to_mock: bool,
    ) -> MarketDataResponse:
        chain: List[FallbackStep] = []
        successful: List[MarketDataResponse] = []
        for adapter in adapters:
            attempt_at = datetime.now(timezone.utc).isoformat()
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    fetch_fn(adapter, symbol),
                    timeout=adapter.timeout_seconds,
                )
                latency = int((time.perf_counter() - started) * 1000)
                if result.error:
                    chain.append(
                        FallbackStep(
                            adapter_id=adapter.adapter_id,
                            provider=adapter.provider_name,
                            attempt_at=attempt_at,
                            success=False,
                            error=result.error,
                            latency_ms=latency,
                        )
                    )
                    continue
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=True,
                        latency_ms=latency,
                    )
                )
                result.degradation_chain = chain
                successful.append(result)
            except asyncio.TimeoutError:
                latency = int((time.perf_counter() - started) * 1000)
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=False,
                        error=f"timeout after {adapter.timeout_seconds}s",
                        latency_ms=latency,
                    )
                )
            except Exception as exc:
                logger.exception("fetch_realtime_quote failed for %s", adapter.adapter_id)
                latency = int((time.perf_counter() - started) * 1000)
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=False,
                        error="数据获取失败，请稍后重试",
                        latency_ms=latency,
                    )
                )

        if successful:
            return MarketDataReconciler.reconcile_quote(capability, successful, chain)

        if fallback_to_mock:
            mock_result = self._mock_quote(symbol)
            mock_result.degradation_chain = chain
            mock_result.data_mode = DataMode.FALLBACK
            return mock_result

        return MarketDataResponse(
            symbol=symbol,
            error="All adapters failed",
            data_mode=DataMode.FALLBACK,
            degradation_chain=chain,
        )

    async def _attempt_auxiliary_adapters(
        self,
        capability: AdapterCapability,
        adapters: List[BaseMarketDataAdapter],
        symbol: str,
        category: str,
        fetch_fn,
        fallback_to_mock: bool,
    ) -> AuxiliaryDataResponse:
        chain: List[FallbackStep] = []
        successful: List[AuxiliaryDataResponse] = []
        for adapter in adapters:
            attempt_at = datetime.now(timezone.utc).isoformat()
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    fetch_fn(adapter, symbol),
                    timeout=adapter.timeout_seconds,
                )
                latency = int((time.perf_counter() - started) * 1000)
                if result.error and result.data_mode == DataMode.MOCK:
                    chain.append(
                        FallbackStep(
                            adapter_id=adapter.adapter_id,
                            provider=adapter.provider_name,
                            attempt_at=attempt_at,
                            success=False,
                            error=result.error,
                            latency_ms=latency,
                        )
                    )
                    continue
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=True,
                        latency_ms=latency,
                    )
                )
                result.degradation_chain = chain
                successful.append(result)
            except asyncio.TimeoutError:
                latency = int((time.perf_counter() - started) * 1000)
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=False,
                        error=f"timeout after {adapter.timeout_seconds}s",
                        latency_ms=latency,
                    )
                )
            except Exception as exc:
                logger.exception("fetch_auxiliary failed for %s", adapter.adapter_id)
                latency = int((time.perf_counter() - started) * 1000)
                chain.append(
                    FallbackStep(
                        adapter_id=adapter.adapter_id,
                        provider=adapter.provider_name,
                        attempt_at=attempt_at,
                        success=False,
                        error="数据获取失败，请稍后重试",
                        latency_ms=latency,
                    )
                )

        if successful:
            return MarketDataReconciler.reconcile_auxiliary(capability, successful, chain)

        if fallback_to_mock:
            mock_result = self._mock_auxiliary(category)
            mock_result.degradation_chain = chain
            mock_result.data_mode = DataMode.FALLBACK
            return mock_result

        error_summary = _summarize_fallback_errors(chain)
        return AuxiliaryDataResponse(
            category=category,
            error=error_summary or "All adapters failed",
            data_mode=DataMode.FALLBACK,
            degradation_chain=chain,
        )

    @staticmethod
    def _category_to_capability(category: str) -> Optional[AdapterCapability]:
        mapping = {
            "fundamentals": AdapterCapability.FUNDAMENTALS,
            "announcements": AdapterCapability.ANNOUNCEMENTS,
            "news": AdapterCapability.ANNOUNCEMENTS,
            "moneyflow": AdapterCapability.MONEYFLOW,
            "chip": AdapterCapability.CHIP,
            "macro": AdapterCapability.MACRO,
            "historical_quote": AdapterCapability.HISTORICAL_QUOTE,
            "index": AdapterCapability.INDEX,
            "index_sector": AdapterCapability.INDEX,
        }
        return mapping.get(str(category or "").strip().lower())

    @staticmethod
    def _mock_quote(symbol: str) -> MarketDataResponse:
        base_price = random.uniform(10, 100)
        change_pct = random.uniform(-5, 5)
        return MarketDataResponse(
            symbol=symbol,
            name=f"Mock {symbol}",
            price=round(base_price, 2),
            change_percent=round(change_pct, 2),
            volume=random.randint(1000000, 50000000),
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="mock",
            provider="mock",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.UNKNOWN,
            confidence=0.1,
            data_mode=DataMode.MOCK,
        )

    @staticmethod
    def _mock_auxiliary(category: str) -> AuxiliaryDataResponse:
        return AuxiliaryDataResponse(
            category=category,
            source="mock",
            provider="mock",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.UNKNOWN,
            confidence=0.1,
            data_mode=DataMode.MOCK,
            records=[],
            record_count=0,
        )


def register_default_market_data_adapters(
    registry: Optional[MarketDataAdapterRegistry] = None,
) -> MarketDataAdapterRegistry:
    from .adapters.akshare_adapter import AkShareAdapter
    from .adapters.ifind_adapter import IFindAdapter
    from .adapters.sina_adapter import SinaAdapter
    from .adapters.tencent_finance_adapter import TencentFinanceAdapter
    from .adapters.tongdaxin_adapter import TongdaxinAdapter
    from .adapters.tushare_adapter import TushareAdapter
    from .agent_runtime_store import get_default_market_data_profile, get_market_data_adapter_configs

    registry = registry or get_adapter_registry()
    configs = {
        config.adapter_id: config
        for config in get_market_data_adapter_configs()
    }
    tushare_profile = get_default_market_data_profile()

    for adapter in (
        TushareAdapter(tushare_profile),
        TencentFinanceAdapter(),
        TongdaxinAdapter(),
        IFindAdapter(),
        AkShareAdapter(),
        SinaAdapter(),
    ):
        target = registry.get_adapter(adapter.adapter_id) or adapter
        if target.adapter_id == "tushare" and hasattr(target, "update_profile"):
            target.update_profile(tushare_profile)
        config = configs.get(target.adapter_id)
        if config is not None:
            target.apply_runtime_config(config)
        if registry.get_adapter(target.adapter_id) is None:
            registry.register(target)

    return registry


_registry: Optional[MarketDataAdapterRegistry] = None


def get_adapter_registry() -> MarketDataAdapterRegistry:
    global _registry
    if _registry is None:
        _registry = MarketDataAdapterRegistry()
    return _registry


def reset_adapter_registry() -> None:
    global _registry
    _registry = None
