from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AutoPaperTradingConfig(BaseModel):
    enabled: bool = False
    automation_mode: str = "SIMULATION"
    simulation_module: Dict[str, Any] = Field(default_factory=dict)
    live_module: Dict[str, Any] = Field(default_factory=dict)
    symbol: str = ""
    stock_name: str = ""
    signal_id: Optional[str] = None
    signal_ids: Dict[str, str] = Field(default_factory=dict)
    initial_buy_signal: str = ""
    final_sell_signal: str = ""
    initial_buy_signals: Dict[str, str] = Field(default_factory=dict)
    final_sell_signals: Dict[str, str] = Field(default_factory=dict)
    initial_cash: float = 100000.0
    max_position_ratio: float = 0.5
    min_order_value: float = 1000.0
    commission_rate: float = 0.0001
    commission_min_fee: float = 5.0
    commission_min_trade_value: float = 50000.0
    stamp_duty_rate: float = 0.0005
    realtime_interval_seconds: int = 30
    kline_interval_seconds: int = 300
    weekly_monthly_interval_seconds: int = 86400
    tick_interval_seconds: int = 60
    min_order_interval_seconds: int = 900
    use_llm: bool = True
    max_llm_calls_per_day: int = 6
    min_llm_interval_minutes: int = 120
    auto_fill: bool = True
    adaptive_tuning_enabled: bool = True
    buy_change_threshold_pct: float = 0.5
    close_change_threshold_pct: float = -2.0
    watch_position_ratio: float = 0.15
    probe_position_ratio: float = 0.35
    positive_position_ratio: float = 0.50
    breakout_position_ratio: float = 0.65
    defensive_position_ratio: float = 0.25
    existing_position_ratio: float = 0.45
    strength_follow_position_ratio: float = 0.65
    factor_adjustments: Dict[str, Any] = Field(default_factory=dict)
    performance_stats: Dict[str, Any] = Field(default_factory=dict)
    last_research_review_date: str = ""
    last_research_review: Dict[str, Any] = Field(default_factory=dict)
    updated_at: str = ""
    last_tick_at: str = ""
    last_market_fetch_at: str = ""
    last_kline_fetch_at: str = ""
    last_weekly_monthly_fetch_at: str = ""
    last_llm_at: str = ""
    last_order_at: str = ""
    last_market_fetch_by_symbol: Dict[str, str] = Field(default_factory=dict)
    last_kline_fetch_by_symbol: Dict[str, str] = Field(default_factory=dict)
    last_weekly_monthly_fetch_by_symbol: Dict[str, str] = Field(default_factory=dict)
    last_kline_snapshot_by_symbol: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    last_order_by_symbol: Dict[str, str] = Field(default_factory=dict)
    llm_budget_date: str = ""
    llm_calls_used_today: int = 0
    llm_gate_status: str = ""
    last_llm_close_call_date: str = ""
    last_decision: Dict[str, Any] = Field(default_factory=dict)
    last_module_evidence: Dict[str, Any] = Field(default_factory=dict)
    last_portfolio_snapshot: Dict[str, Any] = Field(default_factory=dict)
    last_tick_result: Dict[str, Any] = Field(default_factory=dict)
    cleaned_record_history: List[Dict[str, Any]] = Field(default_factory=list)
    compressed_observation_history: Dict[str, Any] = Field(default_factory=dict)
    review_queue_state: Dict[str, Any] = Field(default_factory=dict)
    review_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    experiment_validation_state: Dict[str, Any] = Field(default_factory=dict)
    random_validation_state: Dict[str, Any] = Field(default_factory=dict)
    decision_tree_state: Dict[str, Any] = Field(default_factory=dict)
    last_success_at: str = ""
    last_error: str = ""
    storage_warning: str = ""


class UpdateAutoPaperTradingConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    automation_mode: Optional[str] = None
    simulation_module: Optional[Dict[str, Any]] = None
    live_module: Optional[Dict[str, Any]] = None
    symbol: Optional[str] = None
    stock_name: Optional[str] = None
    initial_buy_signal: Optional[str] = None
    final_sell_signal: Optional[str] = None
    initial_buy_signals: Optional[Dict[str, str]] = None
    final_sell_signals: Optional[Dict[str, str]] = None
    initial_cash: Optional[float] = None
    max_position_ratio: Optional[float] = None
    min_order_value: Optional[float] = None
    commission_rate: Optional[float] = None
    commission_min_fee: Optional[float] = None
    commission_min_trade_value: Optional[float] = None
    stamp_duty_rate: Optional[float] = None
    realtime_interval_seconds: Optional[int] = None
    kline_interval_seconds: Optional[int] = None
    weekly_monthly_interval_seconds: Optional[int] = None
    tick_interval_seconds: Optional[int] = None
    min_order_interval_seconds: Optional[int] = None
    use_llm: Optional[bool] = None
    max_llm_calls_per_day: Optional[int] = None
    min_llm_interval_minutes: Optional[int] = None
    auto_fill: Optional[bool] = None
    adaptive_tuning_enabled: Optional[bool] = None
    buy_change_threshold_pct: Optional[float] = None
    close_change_threshold_pct: Optional[float] = None
    watch_position_ratio: Optional[float] = None
    probe_position_ratio: Optional[float] = None
    positive_position_ratio: Optional[float] = None
    breakout_position_ratio: Optional[float] = None
    defensive_position_ratio: Optional[float] = None
    existing_position_ratio: Optional[float] = None
    strength_follow_position_ratio: Optional[float] = None


class AutoPaperTradingTickRequest(BaseModel):
    force: bool = False


class AutoPaperTradingDailyReviewRequest(BaseModel):
    force: bool = False
    trading_date: Optional[str] = None
    reviewer: str = "auto_research_reviewer"


class AutoPaperTradingStatus(BaseModel):
    enabled: bool
    automation_mode: str = "SIMULATION"
    automation_modules: Dict[str, Any] = Field(default_factory=dict)
    loop_running: bool
    loop_health: str
    loop_last_error: str = ""
    loop_started_at: str = ""
    loop_heartbeat_at: str = ""
    heartbeat_at: str
    current_time: str
    last_tick_at: str = ""
    last_success_at: str = ""
    last_error: str = ""
    config_updated_at: str = ""
    tick_interval_seconds: int
    next_tick_due_at: Optional[str] = None
    seconds_until_next_tick: Optional[int] = None
    last_tick_result: Dict[str, Any] = Field(default_factory=dict)
    last_module_evidence: Dict[str, Any] = Field(default_factory=dict)
    last_portfolio_snapshot: Dict[str, Any] = Field(default_factory=dict)
    last_research_review: Dict[str, Any] = Field(default_factory=dict)
    compressed_observation_history: Dict[str, Any] = Field(default_factory=dict)
    review_queue_state: Dict[str, Any] = Field(default_factory=dict)
    review_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    review_decision_event_ledger: Dict[str, Any] = Field(default_factory=dict)
    experiment_validation_state: Dict[str, Any] = Field(default_factory=dict)
    random_validation_state: Dict[str, Any] = Field(default_factory=dict)
    decision_tree_state: Dict[str, Any] = Field(default_factory=dict)
    storage_warning: str = ""


class AutoPaperTradingCommandRequest(BaseModel):
    symbol: str
    command: str = "FORCE_CLOSE_AND_REMOVE"
    reason: str = "User requested AI paper close and remove."


class AutoPaperTradingReviewDecisionRequest(BaseModel):
    queue_item_id: str = ""
    experiment_id: str = ""
    signal_id: Optional[str] = None
    symbol: str = ""
    action: str
    reviewer: str = "human"
    reason: str = ""
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    review_fields: List[str] = Field(default_factory=list)


class AutoPaperTradingReviewDecisionEventVerifyRequest(BaseModel):
    bundle: Dict[str, Any] = Field(default_factory=dict)


class AutoPaperTradingTickResult(BaseModel):
    status: str
    message: str
    symbol: Optional[str] = None
    signal_id: Optional[str] = None
    config: AutoPaperTradingConfig
    market_snapshot: Dict[str, Any] = Field(default_factory=dict)
    kline_snapshot: Dict[str, Any] = Field(default_factory=dict)
    decision: Dict[str, Any] = Field(default_factory=dict)
    decision_card: Dict[str, Any] = Field(default_factory=dict)
    module_evidence: Dict[str, Any] = Field(default_factory=dict)
    portfolio_snapshot: Dict[str, Any] = Field(default_factory=dict)
    order: Optional[Dict[str, Any]] = None
    portfolio: Optional[Dict[str, Any]] = None
    llm_trace: Optional[Dict[str, Any]] = None
    daily_review: Optional[Dict[str, Any]] = None
    decision_tree_branch: Dict[str, Any] = Field(default_factory=dict)
    decision_tree_review: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    results: List[Dict[str, Any]] = Field(default_factory=list)


class AutoPaperTradingDailyReviewResult(BaseModel):
    status: str
    message: str
    trading_date: str
    loop_id: Optional[str] = None
    iteration_id: Optional[str] = None
    reviewed_symbols: List[Dict[str, Any]] = Field(default_factory=list)
    case_ids: List[str] = Field(default_factory=list)
    evidence_links: List[Dict[str, Any]] = Field(default_factory=list)
    review_fields: List[str] = Field(default_factory=list)
    tuning_update: Dict[str, Any] = Field(default_factory=dict)
    cleaned_records: List[Dict[str, Any]] = Field(default_factory=list)
    review_queue_state: Dict[str, Any] = Field(default_factory=dict)
    review_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    experiment_validation_state: Dict[str, Any] = Field(default_factory=dict)
    random_validation_state: Dict[str, Any] = Field(default_factory=dict)
    decision_tree_reviews: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    config: AutoPaperTradingConfig


class AutoPaperTradingCommandResult(BaseModel):
    status: str
    message: str
    symbol: str
    signal_id: Optional[str] = None
    config: AutoPaperTradingConfig
    order: Optional[Dict[str, Any]] = None
    portfolio: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)


class AutoPaperTradingReviewDecisionResult(BaseModel):
    status: str
    message: str
    decision: Dict[str, Any] = Field(default_factory=dict)
    queue_item: Dict[str, Any] = Field(default_factory=dict)
    config: AutoPaperTradingConfig
    warnings: List[str] = Field(default_factory=list)
