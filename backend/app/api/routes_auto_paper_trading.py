from typing import Any

from fastapi import APIRouter, Query

from ..core.auto_paper_trading import auto_paper_trading_store
from ..core.signalops_decision_tree import compact_decision_tree_state
from ..models.auto_paper_trading import (
    AutoPaperTradingCommandRequest,
    AutoPaperTradingCommandResult,
    AutoPaperTradingConfig,
    AutoPaperTradingDailyReviewRequest,
    AutoPaperTradingDailyReviewResult,
    AutoPaperTradingReviewDecisionEventVerifyRequest,
    AutoPaperTradingReviewDecisionRequest,
    AutoPaperTradingReviewDecisionResult,
    AutoPaperTradingStatus,
    AutoPaperTradingTickRequest,
    AutoPaperTradingTickResult,
    UpdateAutoPaperTradingConfigRequest,
)


router = APIRouter()


@router.get("/signalops/auto-paper/config", response_model=AutoPaperTradingConfig)
async def get_auto_paper_config(
    compact: bool = Query(default=False, description="Return a smaller read-only payload for the SignalOps page."),
):
    config = auto_paper_trading_store.get_config()
    return _compact_config(config) if compact else config


@router.patch("/signalops/auto-paper/config", response_model=AutoPaperTradingConfig)
async def update_auto_paper_config(request: UpdateAutoPaperTradingConfigRequest):
    return auto_paper_trading_store.update_config(request.model_dump())


@router.get("/signalops/auto-paper/status", response_model=AutoPaperTradingStatus)
async def get_auto_paper_status(
    compact: bool = Query(default=False, description="Return a smaller read-only payload for the SignalOps page."),
):
    status = auto_paper_trading_store.get_status()
    return _compact_status(status) if compact else status


@router.post("/signalops/auto-paper/tick", response_model=AutoPaperTradingTickResult)
async def run_auto_paper_tick(request: AutoPaperTradingTickRequest):
    return await auto_paper_trading_store.tick(force=request.force)


@router.post("/signalops/auto-paper/daily-review", response_model=AutoPaperTradingDailyReviewResult)
async def run_auto_paper_daily_review(request: AutoPaperTradingDailyReviewRequest):
    return await auto_paper_trading_store.run_daily_research_review(
        force=request.force,
        trading_date=request.trading_date,
        reviewer=request.reviewer,
    )


@router.post("/signalops/auto-paper/command", response_model=AutoPaperTradingCommandResult)
async def run_auto_paper_command(request: AutoPaperTradingCommandRequest):
    return await auto_paper_trading_store.command(
        symbol=request.symbol,
        command=request.command,
        reason=request.reason,
    )


@router.post("/signalops/auto-paper/review-decisions", response_model=AutoPaperTradingReviewDecisionResult)
async def record_auto_paper_review_decision(request: AutoPaperTradingReviewDecisionRequest):
    return await auto_paper_trading_store.record_review_decision(request.model_dump())


@router.get("/signalops/auto-paper/review-decision-events")
async def export_auto_paper_review_decision_events(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum append-only SignalOps review decision events to return.",
    ),
):
    return auto_paper_trading_store.export_review_decision_events(limit=limit)


@router.post("/signalops/auto-paper/review-decision-events/verify")
async def verify_auto_paper_review_decision_event_export(
    request: AutoPaperTradingReviewDecisionEventVerifyRequest,
):
    return auto_paper_trading_store.verify_review_decision_event_export(request.bundle)


@router.post("/signalops/auto-paper/review-decision-events/handoff")
async def handoff_auto_paper_review_decision_event_export(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum append-only SignalOps review decision events to include in the signed handoff bundle.",
    ),
):
    return auto_paper_trading_store.handoff_review_decision_event_export(limit=limit)


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def _compact_config(config: AutoPaperTradingConfig) -> dict[str, Any]:
    payload = _model_dump(config)
    payload["last_tick_result"] = {}
    payload["last_module_evidence"] = {}
    payload["last_portfolio_snapshot"] = {}
    payload["last_kline_snapshot_by_symbol"] = {}
    payload["last_decision"] = {}
    payload["cleaned_record_history"] = []
    payload["last_research_review"] = {}
    payload["review_queue_state"] = {}
    payload["review_decisions"] = []
    payload["experiment_validation_state"] = {}
    payload["random_validation_state"] = {}
    payload["decision_tree_state"] = compact_decision_tree_state(payload.get("decision_tree_state"))
    return payload


def _compact_status(status: dict[str, Any]) -> dict[str, Any]:
    payload = dict(status)
    payload["last_tick_result"] = _compact_tick_result(payload.get("last_tick_result"))
    payload["last_module_evidence"] = _compact_module_evidence(payload.get("last_module_evidence"))
    payload["last_portfolio_snapshot"] = _compact_portfolio_snapshot(payload.get("last_portfolio_snapshot"))
    payload["last_research_review"] = _compact_research_review(payload.get("last_research_review"))
    payload["decision_tree_state"] = compact_decision_tree_state(payload.get("decision_tree_state"))
    return payload


def _compact_research_review(value: Any) -> dict[str, Any]:
    review = value if isinstance(value, dict) else {}
    if not review:
        return {}
    tuning = review.get("tuning_update") if isinstance(review.get("tuning_update"), dict) else {}
    compact_tuning = {
        key: tuning[key]
        for key in [
            "status",
            "application_status",
            "application_reason",
            "review_reason",
            "sample_count",
            "current_sample_count",
            "current_no_trade_count",
            "compressed_observation_count",
            "trade_count",
            "wins",
            "failures",
            "risk_tightened",
            "before",
            "recommended_parameters",
            "applied_parameters",
            "next_parameters",
            "performance_summary",
            "walk_forward_validation",
            "kline_evidence_package",
            "stability_evidence_package",
            "candidate_evidence_package",
            "strategy_experiment",
            "compressed_observation_history",
        ]
        if key in tuning
    }
    compact_review = {
        key: review[key]
        for key in [
            "status",
            "message",
            "trading_date",
            "updated_at",
            "loop_id",
            "iteration_id",
            "reviewed_symbols",
            "cleaned_records",
            "decision_tree_reviews",
            "warnings",
            "compressed_observation_history",
        ]
        if key in review
    }
    if isinstance(compact_review.get("cleaned_records"), list):
        compact_review["cleaned_records"] = [
            item for item in compact_review["cleaned_records"]
            if isinstance(item, dict) and _compact_record_has_order(item)
        ]
    return compact_review | {"tuning_update": compact_tuning}


def _compact_record_has_order(value: dict[str, Any]) -> bool:
    try:
        return int(value.get("order_count") or 0) > 0
    except (TypeError, ValueError):
        return False


def _compact_tick_result(value: Any) -> dict[str, Any]:
    result = value if isinstance(value, dict) else {}
    if not result:
        return {}
    compact = _compact_tick_result_one(result)
    results = result.get("results") if isinstance(result.get("results"), list) else []
    if results:
        compact["results"] = [_compact_tick_result_one(item) for item in results if isinstance(item, dict)]
    return compact


def _compact_tick_result_one(result: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: result[key]
        for key in ["status", "message", "symbol", "signal_id", "updated_at", "warnings"]
        if key in result
    }
    market_snapshot = result.get("market_snapshot") if isinstance(result.get("market_snapshot"), dict) else {}
    quote = market_snapshot.get("quote") if isinstance(market_snapshot.get("quote"), dict) else {}
    if market_snapshot or quote:
        compact["market_snapshot"] = {
            "symbol": market_snapshot.get("symbol") or quote.get("symbol") or result.get("symbol"),
            "quote": {
                key: quote[key]
                for key in [
                    "symbol",
                    "name",
                    "stockName",
                    "stock_name",
                    "securityName",
                    "price",
                    "changePercent",
                    "change_percent",
                    "pct_chg",
                ]
                if key in quote
            },
        }
    card = result.get("decision_card")
    if not isinstance(card, dict):
        decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
        card = decision.get("decision_card")
    if isinstance(card, dict):
        compact["decision_card"] = _compact_decision_card(card)
    if isinstance(result.get("decision_tree_branch"), dict):
        compact["decision_tree_branch"] = result["decision_tree_branch"]
    if isinstance(result.get("decision_tree_review"), dict):
        compact["decision_tree_review"] = result["decision_tree_review"]
    if isinstance(result.get("module_evidence"), dict):
        compact["module_evidence"] = _compact_module_evidence(result["module_evidence"])
    if isinstance(result.get("portfolio_snapshot"), dict):
        compact["portfolio_snapshot"] = _compact_portfolio_snapshot(result["portfolio_snapshot"])
    return compact


def _compact_module_evidence(value: Any) -> dict[str, Any]:
    evidence = value if isinstance(value, dict) else {}
    if not evidence:
        return {}
    return {
        key: evidence[key]
        for key in [
            "version",
            "generated_at",
            "symbol",
            "automation_modules",
            "sequence",
            "llm_policy",
            "trade_boundary",
            "dvg",
            "riskFirewall",
            "tradeMicro",
            "technicalKline",
            "mfeMaeResearch",
            "qiam",
            "quantCore",
            "execution",
            "antiConclusion",
            "warnings",
            "simulation_only",
            "is_real_trade",
        ]
        if key in evidence
    }


def _compact_portfolio_snapshot(value: Any) -> dict[str, Any]:
    snapshot = value if isinstance(value, dict) else {}
    if not snapshot:
        return {}
    return {
        key: snapshot[key]
        for key in [
            "snapshotId",
            "sourceType",
            "sourceName",
            "accountName",
            "totalAssets",
            "stockMarketValue",
            "cash",
            "availableCash",
            "totalPositionRatio",
            "positionCount",
            "qualityStatus",
            "importedAt",
            "updatedAt",
            "simulation_only",
            "is_real_trade",
        ]
        if key in snapshot
    }


def _compact_decision_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        key: card[key]
        for key in [
            "action",
            "reason",
            "capital_before",
            "capital_after",
            "cash_available",
            "position_value",
            "budget_used",
            "commission_fee",
            "stamp_duty_fee",
            "total_fee",
            "blockers",
            "capital_attribution",
            "pre_buy_quality",
            "kline_signal_quality",
            "strategy_stability_quality",
            "kline_strategy",
            "ladder_buy_policy",
            "stability_strategy",
            "meta_label_gate",
            "volatility_sizing_policy",
            "quant_core_path_risk",
            "quant_core_path_risk_policy",
            "quant_core_path_risk_avoids_new_buy",
            "future_trend_probability",
            "decision_tree",
            "review_fields",
            "research_tuning_refs",
            "simulation_only",
            "is_real_trade",
        ]
        if key in card
    }
