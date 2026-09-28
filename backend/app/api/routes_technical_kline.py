from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..core.analysis_run_registry import get_run
from ..core.case_library_store import case_library_store, review_tag_store
from ..core.technical_kline_agent import (
    TECHNICAL_KLINE_AGENT_PROMPT,
    build_technical_kline_analysis,
    build_technical_kline_governance,
    build_technical_signal_backtest,
)
from ..core.technical_kline_governance_store import (
    active_governance_config,
    link_case_library_case,
    public_governance_state,
    record_case,
    rollback_governance_config,
    save_governance_config,
)
from ..core.kline_service import get_multi_period_kline_payloads
from ..core.tushare_chip_service import get_tushare_chip_payload


router = APIRouter()
logger = logging.getLogger(__name__)


class TechnicalKlineGovernanceUpdateRequest(BaseModel):
    ma_short: int | None = Field(default=None, ge=2, le=120)
    ma_medium: int | None = Field(default=None, ge=2, le=160)
    ma_long: int | None = Field(default=None, ge=2, le=240)
    volume_recent: int | None = Field(default=None, ge=1, le=60)
    volume_baseline: int | None = Field(default=None, ge=2, le=240)
    support_short: int | None = Field(default=None, ge=2, le=240)
    support_long: int | None = Field(default=None, ge=2, le=500)
    high_volume_ratio: float | None = Field(default=None, ge=0.1, le=10)
    near_support_distance: float | None = Field(default=None, ge=0, le=1)
    near_resistance_distance: float | None = Field(default=None, ge=0, le=1)
    case_classification: str | None = None
    changed_by: str = "frontend"
    change_reason: str = ""


class TechnicalKlineGovernanceRollbackRequest(BaseModel):
    changed_by: str = "frontend"
    reason: str = ""


class TechnicalKlineCaseRecordRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    classification: str
    note: str = ""
    run_id: str = ""
    analysis_status: str = ""
    technical_bias: str = ""
    config_hash: str = ""
    prompt_version: str = ""


def _governance_config(
    ma_short: int | None = None,
    ma_medium: int | None = None,
    ma_long: int | None = None,
    volume_recent: int | None = None,
    volume_baseline: int | None = None,
    support_short: int | None = None,
    support_long: int | None = None,
    high_volume_ratio: float | None = None,
    near_support_distance: float | None = None,
    near_resistance_distance: float | None = None,
    case_classification: str | None = None,
) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    moving_average = {
        key: value
        for key, value in {
            "short": ma_short,
            "medium": ma_medium,
            "long": ma_long,
        }.items()
        if value is not None
    }
    if moving_average:
        config["movingAverageWindows"] = moving_average
    volume_windows = {
        key: value
        for key, value in {
            "recent": volume_recent,
            "baseline": volume_baseline,
        }.items()
        if value is not None
    }
    if volume_windows:
        config["volumeWindows"] = volume_windows
    support_windows = {
        key: value
        for key, value in {
            "short": support_short,
            "long": support_long,
        }.items()
        if value is not None
    }
    if support_windows:
        config["supportResistanceWindows"] = support_windows
    risk_thresholds = {
        key: value
        for key, value in {
            "highVolumeRatio": high_volume_ratio,
            "nearSupportDistance": near_support_distance,
            "nearResistanceDistance": near_resistance_distance,
        }.items()
        if value is not None
    }
    if risk_thresholds:
        config["riskThresholds"] = risk_thresholds
    if case_classification:
        config["caseClassification"] = case_classification
    return config


def _governance_response(config: Dict[str, Any]) -> Dict[str, Any]:
    payload = build_technical_kline_governance(config)
    payload["savedGovernance"] = public_governance_state(
        current_config_hash=str(payload.get("analysisConfig", {}).get("configHash") or ""),
        current_prompt_version=str(payload.get("promptGovernance", {}).get("version") or ""),
    )
    return payload


def _case_library_run_data(request: TechnicalKlineCaseRecordRequest, record: Dict[str, Any]) -> Dict[str, Any]:
    run_data = dict(get_run(request.run_id, include_legacy=True) or {})
    run_id = request.run_id or record.get("caseId") or "TECHNICAL_KLINE_REVIEW"
    run_data.setdefault("runId", run_id)
    run_data.setdefault("auditId", f"AUD_{run_id}")
    run_data.setdefault("stockCode", request.symbol)
    run_data.setdefault("stockName", "")
    run_data.setdefault("taskType", "TECHNICAL_KLINE_REVIEW")
    run_data.setdefault("runMode", "REVIEW_ONLY")
    run_data.setdefault("finalAction", "WAIT")
    return run_data


def _case_library_review_update(request: TechnicalKlineCaseRecordRequest, record: Dict[str, Any]) -> Dict[str, Any]:
    classification = str(record.get("classification") or request.classification or "valid").lower()
    is_misjudge = classification == "misjudge"
    is_insufficient = classification == "insufficient_data"
    tags = [
        "technical_kline",
        f"technical_kline:{classification}",
        f"technical_bias:{request.technical_bias or 'UNKNOWN'}",
    ]
    if request.config_hash:
        tags.append(f"technical_config:{request.config_hash}")
    if request.prompt_version:
        tags.append(f"technical_prompt:{request.prompt_version}")
    default_lesson = {
        "valid": "Technical Kline conclusion was reviewed as valid evidence.",
        "misjudge": "Technical Kline conclusion was reviewed as a misjudgment sample.",
        "insufficient_data": "Technical Kline conclusion was reviewed as data-insufficient evidence.",
    }.get(classification, "Technical Kline conclusion was reviewed.")
    return {
        "review_status": "REVIEWED",
        "reviewer": "technical_kline",
        "review_note": request.note or default_lesson,
        "conclusion_correct": False if is_misjudge else (None if is_insufficient else True),
        "data_sufficiency": "INSUFFICIENT" if is_insufficient else "ADEQUATE",
        "optimism_bias": "OVER_OPTIMISTIC" if is_misjudge and str(request.technical_bias).upper() == "BULLISH" else "NONE",
        "key_lessons": [request.note or default_lesson],
        "market_context": (
            f"Technical Kline case {record.get('caseId')} mirrored from governance review; "
            f"status={request.analysis_status or 'UNKNOWN'}; bias={request.technical_bias or 'UNKNOWN'}; "
            f"config={request.config_hash or 'UNKNOWN'}; prompt={request.prompt_version or 'UNKNOWN'}."
        ),
        "tags": tags,
    }


async def _mirror_case_to_case_library(
    request: TechnicalKlineCaseRecordRequest,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    case_record = await case_library_store.create_case(
        _case_library_run_data(request, record),
        reviewer="technical_kline",
    )
    case_data = case_library_store._case_to_dict(case_record)
    updates = _case_library_review_update(request, record)
    reviewed = await case_library_store.update_case_review(case_record.case_id, updates) or case_data
    classification = str(record.get("classification") or request.classification or "valid").lower()
    severity = "HIGH" if classification == "misjudge" else ("MEDIUM" if classification == "insufficient_data" else "LOW")
    tag_payloads = [
        {
            "tag_type": "MODULE",
            "tag_value": "technical_kline",
            "severity": severity,
            "description": "Technical Kline case mirrored into the main Case Library.",
            "node": "technical_kline_analyst",
            "reviewer": "technical_kline",
        },
        {
            "tag_type": "CASE_CLASSIFICATION",
            "tag_value": classification,
            "severity": severity,
            "description": request.note or "Technical Kline case classification.",
            "node": "technical_kline_analyst",
            "reviewer": "technical_kline",
        },
    ]
    if request.technical_bias:
        tag_payloads.append(
            {
                "tag_type": "TECHNICAL_BIAS",
                "tag_value": request.technical_bias,
                "severity": severity,
                "description": "Technical Kline bias observed when the case was recorded.",
                "node": "technical_kline_analyst",
                "reviewer": "technical_kline",
            }
        )
    for payload in tag_payloads:
        await review_tag_store.create_tag(
            case_id=case_record.case_id,
            run_id=case_data["run_id"],
            tag_data=payload,
        )
    return reviewed


def _config_from_update_request(request: TechnicalKlineGovernanceUpdateRequest) -> Dict[str, Any]:
    return _governance_config(
        request.ma_short,
        request.ma_medium,
        request.ma_long,
        request.volume_recent,
        request.volume_baseline,
        request.support_short,
        request.support_long,
        request.high_volume_ratio,
        request.near_support_distance,
        request.near_resistance_distance,
        request.case_classification,
    )


@router.get("/technical-kline/analysis")
async def get_technical_kline_analysis(
    symbol: str = Query(..., min_length=1),
    ma_short: int | None = Query(None, ge=2, le=120),
    ma_medium: int | None = Query(None, ge=2, le=160),
    ma_long: int | None = Query(None, ge=2, le=240),
    volume_recent: int | None = Query(None, ge=1, le=60),
    volume_baseline: int | None = Query(None, ge=2, le=240),
    support_short: int | None = Query(None, ge=2, le=240),
    support_long: int | None = Query(None, ge=2, le=500),
    high_volume_ratio: float | None = Query(None, ge=0.1, le=10),
    near_support_distance: float | None = Query(None, ge=0, le=1),
    near_resistance_distance: float | None = Query(None, ge=0, le=1),
    case_classification: str | None = Query(None),
) -> Dict[str, Any]:
    payloads = get_multi_period_kline_payloads(symbol)
    chip_payload = get_tushare_chip_payload(symbol)
    query_config = _governance_config(
        ma_short,
        ma_medium,
        ma_long,
        volume_recent,
        volume_baseline,
        support_short,
        support_long,
        high_volume_ratio,
        near_support_distance,
        near_resistance_distance,
        case_classification,
    )
    config = active_governance_config(query_config)
    return build_technical_kline_analysis(symbol, payloads, config, chip_payload)


@router.get("/technical-kline/governance")
async def get_technical_kline_governance(
    ma_short: int | None = Query(None, ge=2, le=120),
    ma_medium: int | None = Query(None, ge=2, le=160),
    ma_long: int | None = Query(None, ge=2, le=240),
    volume_recent: int | None = Query(None, ge=1, le=60),
    volume_baseline: int | None = Query(None, ge=2, le=240),
    support_short: int | None = Query(None, ge=2, le=240),
    support_long: int | None = Query(None, ge=2, le=500),
    high_volume_ratio: float | None = Query(None, ge=0.1, le=10),
    near_support_distance: float | None = Query(None, ge=0, le=1),
    near_resistance_distance: float | None = Query(None, ge=0, le=1),
    case_classification: str | None = Query(None),
) -> Dict[str, Any]:
    query_config = _governance_config(
        ma_short,
        ma_medium,
        ma_long,
        volume_recent,
        volume_baseline,
        support_short,
        support_long,
        high_volume_ratio,
        near_support_distance,
        near_resistance_distance,
        case_classification,
    )
    return _governance_response(active_governance_config(query_config))


@router.put("/technical-kline/governance")
async def put_technical_kline_governance(request: TechnicalKlineGovernanceUpdateRequest) -> Dict[str, Any]:
    config = _config_from_update_request(request)
    save_governance_config(
        config,
        case_classification=request.case_classification or "",
        changed_by=request.changed_by,
        change_reason=request.change_reason,
    )
    return _governance_response(active_governance_config())


@router.post("/technical-kline/governance/rollback")
async def rollback_technical_kline_governance(
    request: TechnicalKlineGovernanceRollbackRequest,
) -> Dict[str, Any]:
    rollback_governance_config(changed_by=request.changed_by, reason=request.reason)
    return _governance_response(active_governance_config())


@router.post("/technical-kline/cases")
async def record_technical_kline_case(request: TechnicalKlineCaseRecordRequest) -> Dict[str, Any]:
    record = record_case(request.model_dump())
    try:
        case_library_case = await _mirror_case_to_case_library(request, record)
    except Exception as exc:  # pragma: no cover - defensive boundary for optional sedimentation
        logger.exception("Failed to mirror Technical Kline case into Case Library")
        linked = link_case_library_case(
            record["caseId"],
            status="FAILED",
            error=str(exc),
        )
        return linked or {**record, "caseLibraryStatus": "FAILED", "caseLibraryError": str(exc)[:240]}
    linked = link_case_library_case(
        record["caseId"],
        case_library_case_id=str(case_library_case.get("case_id") or ""),
        status="MIRRORED",
    )
    return linked or {
        **record,
        "caseLibraryCaseId": str(case_library_case.get("case_id") or ""),
        "caseLibraryStatus": "MIRRORED",
    }


@router.get("/technical-kline/signal-backtest")
async def get_technical_signal_backtest(
    symbol: str = Query(..., min_length=1),
    horizon_days: int = Query(5, ge=1, le=20),
) -> Dict[str, Any]:
    payloads = get_multi_period_kline_payloads(symbol)
    return build_technical_signal_backtest(symbol, payloads, horizon_days)


@router.get("/technical-kline/prompt")
async def get_technical_kline_prompt() -> Dict[str, Any]:
    governance = _governance_response(active_governance_config())
    return {
        "agent": "technical_kline_analyst",
        "prompt": TECHNICAL_KLINE_AGENT_PROMPT,
        "promptGovernance": governance["promptGovernance"],
        "analysisConfig": governance["analysisConfig"],
        "caseClassification": governance["caseClassification"],
        "outputMode": "STRICT_JSON",
        "dataPolicy": "REAL_TUSHARE_KLINE_ONLY",
        "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
        "savedGovernance": governance["savedGovernance"],
    }
