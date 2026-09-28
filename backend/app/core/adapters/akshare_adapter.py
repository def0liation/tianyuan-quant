from __future__ import annotations

import importlib.util
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import List

logger = logging.getLogger(__name__)

from ..market_data_adapter import BaseMarketDataAdapter
from ...models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    DataMode,
    DataSourceHealth,
    Freshness,
    MarketDataResponse,
)


class AkShareAdapter(BaseMarketDataAdapter):
    adapter_id = "akshare"
    provider_name = "akshare"
    label = "AkShare (东方财富)"
    priority = 2
    capabilities = {
        AdapterCapability.HISTORICAL_QUOTE,
        AdapterCapability.FUNDAMENTALS,
        AdapterCapability.MONEYFLOW,
    }
    timeout_seconds = 15

    def __init__(self):
        self._installed = self._detect_installed()

    def _detect_installed(self) -> bool:
        return importlib.util.find_spec("akshare") is not None

    def _is_installed(self) -> bool:
        if self._installed:
            return True
        self._installed = self._detect_installed()
        return self._installed

    async def fetch_realtime_quote(self, symbol: str) -> MarketDataResponse:
        if not self._is_installed():
            return MarketDataResponse(
                symbol=symbol,
                error="akshare package is not installed",
                provider=self.provider_name,
                data_mode=DataMode.MOCK,
            )
        return MarketDataResponse(
            symbol=symbol,
            source="akshare",
            provider=self.provider_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.UNKNOWN,
            confidence=0.0,
            error="AkShare realtime push2 quote is disabled in this runtime; use Tushare/Sina for realtime quotes.",
            data_mode=DataMode.MOCK,
        )

    async def fetch_historical_quote(
        self, symbol: str, start: str, end: str
    ) -> List[MarketDataResponse]:
        if not self._is_installed():
            return []

        try:
            import asyncio

            code = _akshare_code(symbol)
            return await asyncio.to_thread(self._fetch_historical_sync, code, start, end)
        except Exception as exc:
            logger.warning(
                "AkShare historical_quote unavailable for %s after retries: %s",
                symbol,
                _short_error(exc),
            )
            return []

    async def fetch_auxiliary(self, symbol: str, category: str) -> AuxiliaryDataResponse:
        if not self._is_installed():
            return AuxiliaryDataResponse(
                category=category,
                error="akshare package is not installed",
                provider=self.provider_name,
                data_mode=DataMode.MOCK,
            )

        try:
            import asyncio

            code = _akshare_code(symbol)
            fetch_map = {
                "fundamentals": self._fetch_fundamentals_sync,
                "moneyflow": self._fetch_moneyflow_sync,
                "chip": self._fetch_chip_sync,
                "announcements": None,
            }
            if category not in fetch_map or fetch_map[category] is None:
                return AuxiliaryDataResponse(
                    category=category,
                    error=f"AkShare does not support auxiliary category: {category}",
                    data_mode=DataMode.MOCK,
                )

            return await asyncio.to_thread(fetch_map[category], code)
        except Exception:
            logger.exception("AkShare fetch_auxiliary %s failed for %s", category, symbol)
            return AuxiliaryDataResponse(
                category=category,
                source="akshare",
                provider=self.provider_name,
                error="数据获取失败，请稍后重试",
                data_mode=DataMode.MOCK,
            )

    async def health_check(self) -> DataSourceHealth:
        started = time.perf_counter()
        if not self._is_installed():
            return DataSourceHealth(
                adapter_id=self.adapter_id,
                provider=self.provider_name,
                label=self.label,
                capabilities=list(self.capabilities),
                healthy=False,
                message="akshare package is not installed",
                enabled=self.enabled,
                installed=False,
            )

        import asyncio

        sample_code = "603663"
        check_timeout = min(max(self.timeout_seconds, 3), 8)
        historical_error = ""
        moneyflow_error = ""
        historical_ok = False
        moneyflow_ok = False

        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        try:
            history = await asyncio.wait_for(
                asyncio.to_thread(
                    self._fetch_historical_sync,
                    sample_code,
                    start_date.strftime("%Y-%m-%d"),
                    end_date.strftime("%Y-%m-%d"),
                ),
                timeout=check_timeout,
            )
            historical_ok = len(history) > 0
            if not historical_ok:
                historical_error = "historical quote returned no rows"
        except Exception as exc:
            historical_error = _short_error(exc)
            logger.warning("AkShare historical health probe failed: %s", historical_error)

        try:
            moneyflow = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_moneyflow_sync, sample_code),
                timeout=check_timeout,
            )
            moneyflow_ok = not moneyflow.error and moneyflow.record_count > 0
            if not moneyflow_ok:
                moneyflow_error = moneyflow.error or "moneyflow returned no records"
        except Exception as exc:
            moneyflow_error = _short_error(exc)
            logger.warning("AkShare moneyflow health probe failed: %s", moneyflow_error)

        latency = int((time.perf_counter() - started) * 1000)
        upstream_ok = historical_ok or moneyflow_ok
        if upstream_ok:
            working = []
            if historical_ok:
                working.append("历史K线")
            if moneyflow_ok:
                working.append("资金流")
            message = (
                f"AkShare 可用：{', '.join(working)}接口可用；"
                "实时行情 push2 接口在当前运行环境中不作为 AkShare 源使用。"
            )
            last_error = ""
        else:
            detail = "; ".join(
                item
                for item in (
                    f"historical={historical_error}" if historical_error else "",
                    f"moneyflow={moneyflow_error}" if moneyflow_error else "",
                )
                if item
            )
            message = f"AkShare 已安装，但可用性探测失败：{detail or 'unknown error'}"
            last_error = detail

        return DataSourceHealth(
            adapter_id=self.adapter_id,
            provider=self.provider_name,
            label=self.label,
            capabilities=list(self.capabilities),
            healthy=upstream_ok,
            upstream_healthy=upstream_ok,
            live_data_usable=False,
            last_error=last_error,
            last_check_at=datetime.now(timezone.utc).isoformat(),
            latency_avg_ms=latency,
            message=message,
            enabled=self.enabled,
            installed=True,
        )

    def _fetch_historical_sync(self, code: str, start: str, end: str) -> List[MarketDataResponse]:
        import akshare as ak

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=_akshare_date(start),
                    end_date=_akshare_date(end),
                    adjust="",
                    timeout=self.timeout_seconds,
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt >= 2:
                    raise
                logger.warning(
                    "AkShare historical_quote transient failure for %s, retrying (%s/3): %s",
                    code,
                    attempt + 1,
                    _short_error(exc),
                )
                time.sleep(0.4 * (attempt + 1))
        else:
            raise last_error or RuntimeError("AkShare historical_quote failed")

        records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
        results: List[MarketDataResponse] = []
        for record in records:
            price = _to_float(record.get("收盘"))
            pre_close = None
            change_pct = _to_float(record.get("涨跌幅"))
            results.append(
                MarketDataResponse(
                    symbol=str(record.get("股票代码") or code),
                    name="",
                    price=price,
                    change_percent=change_pct,
                    volume=_to_float(record.get("成交量")),
                    timestamp=str(record.get("日期") or ""),
                    source="akshare_eastmoney_hist",
                    provider=self.provider_name,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    freshness=Freshness.EOD,
                    confidence=0.82,
                    data_mode=DataMode.LIVE,
                    extra={
                        "open": _to_float(record.get("开盘")),
                        "high": _to_float(record.get("最高")),
                        "low": _to_float(record.get("最低")),
                        "amount": _to_float(record.get("成交额")),
                        "amplitude": _to_float(record.get("振幅")),
                        "change": _to_float(record.get("涨跌额")),
                        "turnoverRate": _to_float(record.get("换手率")),
                        "preClose": pre_close,
                    },
                )
            )
        results.sort(key=lambda item: item.timestamp)
        return results

    def _fetch_fundamentals_sync(self, code: str) -> AuxiliaryDataResponse:
        import akshare as ak

        try:
            df = ak.stock_individual_info_em(symbol=code, timeout=self.timeout_seconds)
            records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
            return AuxiliaryDataResponse(
                category="fundamentals",
                source="akshare_eastmoney",
                provider=self.provider_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                freshness=Freshness.EOD,
                confidence=0.82,
                data_mode=DataMode.LIVE,
                records=records,
                record_count=len(records),
            )
        except Exception:
            logger.exception("AkShare fetch_auxiliary fundamentals failed for %s", code)
            return AuxiliaryDataResponse(
                category="fundamentals",
                source="akshare",
                provider=self.provider_name,
                error="基本面数据获取失败，请稍后重试",
                data_mode=DataMode.MOCK,
            )

    def _fetch_moneyflow_sync(self, code: str) -> AuxiliaryDataResponse:
        import akshare as ak

        try:
            df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("60") else "sz")
            records = df.to_dict(orient="records") if hasattr(df, "to_dict") else []
            return AuxiliaryDataResponse(
                category="moneyflow",
                source="akshare_eastmoney",
                provider=self.provider_name,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                freshness=Freshness.DELAYED_15MIN,
                confidence=0.83,
                data_mode=DataMode.LIVE,
                records=records,
                record_count=len(records),
            )
        except Exception:
            logger.exception("AkShare fetch_auxiliary moneyflow failed for %s", code)
            return AuxiliaryDataResponse(
                category="moneyflow",
                source="akshare",
                provider=self.provider_name,
                error="资金流向数据获取失败，请稍后重试",
                data_mode=DataMode.MOCK,
            )

    def _fetch_chip_sync(self, code: str) -> AuxiliaryDataResponse:
        return AuxiliaryDataResponse(
            category="chip",
            source="akshare",
            provider=self.provider_name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            freshness=Freshness.UNKNOWN,
            confidence=0.0,
            data_mode=DataMode.MOCK,
            records=[],
            record_count=0,
            error="AkShare does not support chip distribution data",
        )


def _akshare_code(symbol: str) -> str:
    code = re.sub(r"[^0-9]", "", symbol.strip())
    return code[:6] if len(code) >= 6 else code


def _akshare_date(value: str) -> str:
    cleaned = re.sub(r"[^0-9]", "", str(value))
    return cleaned[:8] if len(cleaned) >= 8 else cleaned


def _to_float(value: object) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _short_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:220]
