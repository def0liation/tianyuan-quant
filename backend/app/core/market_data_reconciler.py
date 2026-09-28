from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from ..models.market_data import (
    AdapterCapability,
    AuxiliaryDataResponse,
    FallbackStep,
    MarketDataResponse,
)


class MarketDataReconciler:
    """Selects a primary source and marks conflicts between live data providers."""

    SOURCE_PRIORITY: Dict[AdapterCapability, List[str]] = {
        AdapterCapability.REALTIME_QUOTE: ["tushare", "tencent_finance", "tongdaxin", "ifind", "sina", "akshare", "mock"],
        AdapterCapability.HISTORICAL_QUOTE: ["tushare", "tencent_finance", "tongdaxin", "ifind", "akshare", "sina", "mock"],
        AdapterCapability.FUNDAMENTALS: ["tushare", "ifind", "tongdaxin", "akshare", "mock"],
        AdapterCapability.ANNOUNCEMENTS: ["tushare", "ifind", "tencent_finance", "akshare", "mock"],
        AdapterCapability.MONEYFLOW: ["akshare", "tushare", "tencent_finance", "tongdaxin", "ifind", "sina", "mock"],
        AdapterCapability.CHIP: ["tushare", "ifind", "tongdaxin", "akshare", "mock"],
        AdapterCapability.MACRO: ["tushare", "ifind", "mock"],
        AdapterCapability.INDEX: ["tushare", "tencent_finance", "tongdaxin", "ifind", "akshare", "mock"],
    }

    PRICE_REL_TOLERANCE = 0.005
    HIST_PRICE_REL_TOLERANCE = 0.002
    VOLUME_REL_TOLERANCE = 0.05
    AUX_RECORD_COUNT_REL_TOLERANCE = 0.30

    @classmethod
    def reconcile_quote(
        cls,
        capability: AdapterCapability,
        responses: Sequence[MarketDataResponse],
        chain: Sequence[FallbackStep],
    ) -> MarketDataResponse:
        valid = [response for response in responses if not response.error]
        selected = cls._select_response(capability, valid)
        if selected is None:
            raise ValueError("reconcile_quote requires at least one valid response")

        conflicts: List[Dict[str, Any]] = []
        for other in valid:
            if other is selected:
                continue
            conflicts.extend(cls._quote_conflicts(selected, other))

        selected.degradation_chain = list(chain)
        cls._attach_arbitration(
            selected.extra,
            capability=capability.value,
            selected_source=cls._source_id(selected.provider or selected.source),
            candidates=cls._quote_candidates(valid),
            conflicts=conflicts,
        )
        return selected

    @classmethod
    def reconcile_historical(
        cls,
        groups: Sequence[Tuple[str, str, List[MarketDataResponse]]],
        chain: Sequence[FallbackStep],
    ) -> List[MarketDataResponse]:
        valid = [(adapter_id, provider, rows) for adapter_id, provider, rows in groups if rows]
        if not valid:
            return []

        selected = min(
            valid,
            key=lambda item: (
                cls._source_rank(AdapterCapability.HISTORICAL_QUOTE, cls._source_id(item[1] or item[0])),
                -len(item[2]),
            ),
        )
        selected_source = cls._source_id(selected[1] or selected[0])
        selected_rows = cls._sort_historical_rows(selected[2])
        conflicts: List[Dict[str, Any]] = []
        for adapter_id, provider, rows in valid:
            if rows is selected[2]:
                continue
            conflicts.extend(
                cls._historical_conflicts(
                    selected_source,
                    selected_rows,
                    cls._source_id(provider or adapter_id),
                    cls._sort_historical_rows(rows),
                )
            )

        arbitration = cls._arbitration_payload(
            capability=AdapterCapability.HISTORICAL_QUOTE.value,
            selected_source=selected_source,
            candidates=[
                {
                    "adapterId": adapter_id,
                    "source": cls._source_id(provider or adapter_id),
                    "provider": provider,
                    "recordCount": len(rows),
                    **cls._historical_range(rows),
                }
                for adapter_id, provider, rows in valid
            ],
            conflicts=conflicts,
        )
        for row in selected_rows:
            row.degradation_chain = list(chain)
            row.extra = {**row.extra, "arbitration": arbitration}
        return selected_rows

    @classmethod
    def _sort_historical_rows(
        cls, rows: Sequence[MarketDataResponse]
    ) -> List[MarketDataResponse]:
        return sorted(rows, key=lambda row: cls._date_key(row.timestamp) or str(row.timestamp or ""))

    @classmethod
    def _historical_range(cls, rows: Sequence[MarketDataResponse]) -> Dict[str, str]:
        sorted_rows = cls._sort_historical_rows(rows)
        return {
            "firstTimestamp": sorted_rows[0].timestamp if sorted_rows else "",
            "lastTimestamp": sorted_rows[-1].timestamp if sorted_rows else "",
        }

    @classmethod
    def reconcile_auxiliary(
        cls,
        capability: AdapterCapability,
        responses: Sequence[AuxiliaryDataResponse],
        chain: Sequence[FallbackStep],
    ) -> AuxiliaryDataResponse:
        valid = [response for response in responses if not response.error]
        selected = cls._select_auxiliary(capability, valid)
        if selected is None:
            raise ValueError("reconcile_auxiliary requires at least one valid response")

        conflicts: List[Dict[str, Any]] = []
        for other in valid:
            if other is selected:
                continue
            conflicts.extend(cls._auxiliary_conflicts(selected, other))

        selected.degradation_chain = list(chain)
        cls._attach_arbitration(
            selected.extra,
            capability=capability.value,
            selected_source=cls._source_id(selected.provider or selected.source),
            candidates=cls._auxiliary_candidates(valid),
            conflicts=conflicts,
        )
        return selected

    @classmethod
    def _select_response(
        cls, capability: AdapterCapability, responses: Sequence[MarketDataResponse]
    ) -> MarketDataResponse | None:
        if not responses:
            return None
        return min(
            responses,
            key=lambda response: (
                cls._source_rank(capability, cls._source_id(response.provider or response.source)),
                -float(response.confidence or 0.0),
            ),
        )

    @classmethod
    def _select_auxiliary(
        cls, capability: AdapterCapability, responses: Sequence[AuxiliaryDataResponse]
    ) -> AuxiliaryDataResponse | None:
        if not responses:
            return None
        return min(
            responses,
            key=lambda response: (
                cls._source_rank(capability, cls._source_id(response.provider or response.source)),
                -int(response.record_count or 0),
                -float(response.confidence or 0.0),
            ),
        )

    @classmethod
    def _source_rank(cls, capability: AdapterCapability, source: str) -> int:
        priorities = cls.SOURCE_PRIORITY.get(capability, [])
        try:
            return priorities.index(source)
        except ValueError:
            return len(priorities) + 10

    @staticmethod
    def _source_id(value: str) -> str:
        text = (value or "").lower()
        if "tushare" in text:
            return "tushare"
        if "tencent" in text or "qq" in text or "腾讯" in text:
            return "tencent_finance"
        if "tongdaxin" in text or "tdx" in text or "通达信" in text:
            return "tongdaxin"
        if "ifind" in text or "51ifind" in text or "同花顺" in text:
            return "ifind"
        if "akshare" in text or "eastmoney" in text:
            return "akshare"
        if "sina" in text:
            return "sina"
        if "mock" in text:
            return "mock"
        return text or "unknown"

    @classmethod
    def _quote_conflicts(
        cls, primary: MarketDataResponse, other: MarketDataResponse
    ) -> List[Dict[str, Any]]:
        conflicts: List[Dict[str, Any]] = []
        primary_source = cls._source_id(primary.provider or primary.source)
        other_source = cls._source_id(other.provider or other.source)
        cls._append_numeric_conflict(
            conflicts,
            field="price",
            primary_source=primary_source,
            primary_value=primary.price,
            other_source=other_source,
            other_value=other.price,
            tolerance=cls.PRICE_REL_TOLERANCE,
            severity="HIGH",
        )
        cls._append_numeric_conflict(
            conflicts,
            field="volume",
            primary_source=primary_source,
            primary_value=primary.volume,
            other_source=other_source,
            other_value=other.volume,
            tolerance=cls.VOLUME_REL_TOLERANCE,
            severity="MEDIUM",
        )
        return conflicts

    @classmethod
    def _historical_conflicts(
        cls,
        primary_source: str,
        primary_rows: Sequence[MarketDataResponse],
        other_source: str,
        other_rows: Sequence[MarketDataResponse],
    ) -> List[Dict[str, Any]]:
        conflicts: List[Dict[str, Any]] = []
        primary_by_date = {cls._date_key(row.timestamp): row for row in primary_rows if cls._date_key(row.timestamp)}
        other_by_date = {cls._date_key(row.timestamp): row for row in other_rows if cls._date_key(row.timestamp)}
        overlap = sorted(set(primary_by_date) & set(other_by_date))
        if not overlap:
            return [
                {
                    "field": "timestamp",
                    "severity": "HIGH",
                    "primarySource": primary_source,
                    "otherSource": other_source,
                    "message": "No overlapping trading dates between sources.",
                }
            ]

        for trade_date in overlap:
            primary = primary_by_date[trade_date]
            other = other_by_date[trade_date]
            before = len(conflicts)
            cls._append_numeric_conflict(
                conflicts,
                field="close",
                primary_source=primary_source,
                primary_value=primary.price,
                other_source=other_source,
                other_value=other.price,
                tolerance=cls.HIST_PRICE_REL_TOLERANCE,
                severity="HIGH",
                context={"date": trade_date},
            )
            cls._append_numeric_conflict(
                conflicts,
                field="volume",
                primary_source=primary_source,
                primary_value=primary.volume,
                other_source=other_source,
                other_value=other.volume,
                tolerance=cls.VOLUME_REL_TOLERANCE,
                severity="MEDIUM",
                context={"date": trade_date},
            )
            if len(conflicts) > before + 1:
                break

        if len(overlap) < max(len(primary_by_date), len(other_by_date)) * 0.5:
            conflicts.append(
                {
                    "field": "coverage",
                    "severity": "MEDIUM",
                    "primarySource": primary_source,
                    "otherSource": other_source,
                    "primaryCount": len(primary_by_date),
                    "otherCount": len(other_by_date),
                    "overlapCount": len(overlap),
                    "message": "Historical K-line overlap is below 50%.",
                }
            )
        return conflicts

    @classmethod
    def _auxiliary_conflicts(
        cls, primary: AuxiliaryDataResponse, other: AuxiliaryDataResponse
    ) -> List[Dict[str, Any]]:
        conflicts: List[Dict[str, Any]] = []
        cls._append_numeric_conflict(
            conflicts,
            field="recordCount",
            primary_source=cls._source_id(primary.provider or primary.source),
            primary_value=primary.record_count,
            other_source=cls._source_id(other.provider or other.source),
            other_value=other.record_count,
            tolerance=cls.AUX_RECORD_COUNT_REL_TOLERANCE,
            severity="MEDIUM",
        )
        return conflicts

    @staticmethod
    def _date_key(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        digits = "".join(ch for ch in text[:10] if ch.isdigit())
        if len(digits) >= 8:
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
        return text[:10]

    @classmethod
    def _append_numeric_conflict(
        cls,
        conflicts: List[Dict[str, Any]],
        *,
        field: str,
        primary_source: str,
        primary_value: Any,
        other_source: str,
        other_value: Any,
        tolerance: float,
        severity: str,
        context: Dict[str, Any] | None = None,
    ) -> None:
        primary_number = cls._to_float(primary_value)
        other_number = cls._to_float(other_value)
        if primary_number is None or other_number is None:
            return
        baseline = max(abs(primary_number), abs(other_number), 1.0)
        relative_diff = abs(primary_number - other_number) / baseline
        if relative_diff <= tolerance:
            return
        conflicts.append(
            {
                "field": field,
                "severity": severity,
                "primarySource": primary_source,
                "primaryValue": primary_number,
                "otherSource": other_source,
                "otherValue": other_number,
                "relativeDiff": round(relative_diff, 6),
                "tolerance": tolerance,
                **(context or {}),
            }
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _quote_candidates(cls, responses: Iterable[MarketDataResponse]) -> List[Dict[str, Any]]:
        return [
            {
                "source": cls._source_id(response.provider or response.source),
                "provider": response.provider,
                "rawSource": response.source,
                "price": response.price,
                "volume": response.volume,
                "timestamp": response.timestamp,
                "confidence": response.confidence,
                "dataMode": response.data_mode.value,
            }
            for response in responses
        ]

    @classmethod
    def _auxiliary_candidates(cls, responses: Iterable[AuxiliaryDataResponse]) -> List[Dict[str, Any]]:
        return [
            {
                "source": cls._source_id(response.provider or response.source),
                "provider": response.provider,
                "rawSource": response.source,
                "recordCount": response.record_count,
                "confidence": response.confidence,
                "dataMode": response.data_mode.value,
            }
            for response in responses
        ]

    @classmethod
    def _attach_arbitration(
        cls,
        extra: Dict[str, Any],
        *,
        capability: str,
        selected_source: str,
        candidates: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
    ) -> None:
        extra["arbitration"] = cls._arbitration_payload(
            capability=capability,
            selected_source=selected_source,
            candidates=candidates,
            conflicts=conflicts,
        )

    @classmethod
    def _arbitration_payload(
        cls,
        *,
        capability: str,
        selected_source: str,
        candidates: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not candidates:
            consensus = "NO_DATA"
        elif len(candidates) == 1:
            consensus = "SINGLE_SOURCE"
        elif conflicts:
            consensus = "DIVERGED"
        else:
            consensus = "CONSENSUS"
        quality = cls._quality_payload(consensus, conflicts)
        return {
            "capability": capability,
            "selectedSource": selected_source,
            "sourceConsensus": consensus,
            "resolution": "SOURCE_PRIORITY_REVIEW_ONLY" if quality["reviewOnly"] else "SOURCE_PRIORITY",
            "checkedSources": candidates,
            "conflicts": conflicts,
            "dataQuality": quality,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _quality_payload(consensus: str, conflicts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        high_count = sum(1 for conflict in conflicts if conflict.get("severity") == "HIGH")
        medium_count = sum(1 for conflict in conflicts if conflict.get("severity") == "MEDIUM")
        review_only = high_count > 0
        if consensus == "CONSENSUS":
            score = 0.95
        elif consensus == "SINGLE_SOURCE":
            score = 0.75
        elif consensus == "DIVERGED":
            score = 0.55
        else:
            score = 0.0
        score = max(0.0, score - high_count * 0.25 - medium_count * 0.1)
        if review_only:
            level = "REVIEW_ONLY"
        elif score >= 0.8:
            level = "HIGH"
        elif score >= 0.55:
            level = "MEDIUM"
        else:
            level = "LOW"
        return {
            "score": round(score, 3),
            "level": level,
            "reviewOnly": review_only,
            "highConflictCount": high_count,
            "mediumConflictCount": medium_count,
        }
