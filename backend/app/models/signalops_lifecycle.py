from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


SignalStatus = str


class GateCheck(BaseModel):
    key: str
    passed: bool
    message: str = ""


class SignalItem(BaseModel):
    signal_id: str
    symbol: str
    stock_name: str = ""
    status: SignalStatus = "IDEA"
    source_run_id: Optional[str] = None
    latest_run_id: Optional[str] = None
    audit_id: str
    risk_passed: bool = False
    dvg_passed: bool = False
    dvg_status: str = ""
    qiam_passed: bool = False
    qiam_status: str = ""
    execution_reachable: bool = False
    portfolio_allowed: bool = True
    trigger_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    review_fields: List[str] = Field(default_factory=list)
    attached_runs: List[str] = Field(default_factory=list)
    blocked_reason: str = ""
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class CreateSignalRequest(BaseModel):
    symbol: str
    stock_name: str = ""
    source_run_id: Optional[str] = None
    audit_id: Optional[str] = None
    risk_passed: bool = False
    dvg_passed: bool = False
    dvg_status: str = ""
    qiam_passed: bool = False
    qiam_status: str = ""
    execution_reachable: bool = False
    portfolio_allowed: bool = True
    trigger_conditions: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    review_fields: List[str] = Field(default_factory=list)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class SignalTransitionRequest(BaseModel):
    target_status: SignalStatus
    audit_id: Optional[str] = None
    run_id: Optional[str] = None
    actor: str = "human"
    reason: str = ""
    gate_context: Dict[str, Any] = Field(default_factory=dict)


class SignalTransitionItem(BaseModel):
    transition_id: str
    signal_id: str
    from_status: str
    to_status: str
    audit_id: str
    run_id: Optional[str] = None
    actor: str = "system"
    reason: str = ""
    gate_checks: List[GateCheck] = Field(default_factory=list)
    passed: bool = False
    simulation_only: bool = True
    is_real_trade: bool = False
    created_at: str


class AttachRunRequest(BaseModel):
    run_id: str
    audit_id: Optional[str] = None


class UpdateSignalConditionsRequest(BaseModel):
    audit_id: Optional[str] = None
    trigger_conditions: Optional[List[str]] = None
    invalidation_conditions: Optional[List[str]] = None
    review_fields: Optional[List[str]] = None


class SignalReviewRequest(BaseModel):
    audit_id: Optional[str] = None
    reviewer: str = "human"
    review_type: str = "MANUAL"
    decision: str = "PENDING"
    note: str = ""
    review_fields: List[str] = Field(default_factory=list)


class SignalReviewItem(BaseModel):
    review_id: str
    signal_id: str
    audit_id: str
    reviewer: str
    review_type: str
    decision: str
    note: str
    review_fields: List[str] = Field(default_factory=list)
    simulation_only: bool = True
    is_real_trade: bool = False
    created_at: str


class SignalDetail(BaseModel):
    signal: SignalItem
    transitions: List[SignalTransitionItem] = Field(default_factory=list)
    reviews: List[SignalReviewItem] = Field(default_factory=list)


class PaperPortfolioItem(BaseModel):
    portfolio_id: str
    signal_id: str
    audit_id: str
    run_id: Optional[str] = None
    symbol: str
    initial_cash: float
    available_cash: float
    market_value: float
    max_drawdown: float = 0.0
    risk_budget: Dict[str, Any] = Field(default_factory=dict)
    created_by_agent: str = "signalops"
    simulation_only: bool = True
    is_real_trade: bool = False
    created_at: str
    updated_at: str


class PaperPortfolioRequest(BaseModel):
    audit_id: Optional[str] = None
    run_id: Optional[str] = None
    initial_cash: float = 100000.0
    risk_budget: Dict[str, Any] = Field(default_factory=dict)
    created_by_agent: str = "signalops"


class PaperPositionItem(BaseModel):
    position_id: str
    portfolio_id: str
    signal_id: str
    symbol: str
    quantity: float
    virtual_cost: float
    current_value: float
    floating_pnl: float
    max_drawdown: float = 0.0
    simulation_only: bool = True
    is_real_trade: bool = False
    updated_at: str


class PaperOrderItem(BaseModel):
    order_id: str
    paper_portfolio_id: str
    signal_id: str
    audit_id: str
    run_id: Optional[str] = None
    agent_id: str
    action: str
    action_reason: str = ""
    simulated_price: float = 0.0
    simulated_quantity: float = 0.0
    fill_status: str = "PENDING"
    risk_constraints: Dict[str, Any] = Field(default_factory=dict)
    invalidation_conditions: List[str] = Field(default_factory=list)
    data_snapshot_hash: str = ""
    simulated_fill: Dict[str, Any] = Field(default_factory=dict)
    simulation_only: bool = True
    is_real_trade: bool = False
    created_at: str
    updated_at: str


class PaperOrderRequest(BaseModel):
    audit_id: Optional[str] = None
    run_id: Optional[str] = None
    agent_id: str = "paper_trading_agent"
    action: str
    action_reason: str = ""
    simulated_price: float = 0.0
    simulated_quantity: float = 0.0
    risk_constraints: Dict[str, Any] = Field(default_factory=dict)
    data_snapshot_hash: str = ""


class PaperFillRequest(BaseModel):
    audit_id: Optional[str] = None
    filled_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    fees: float = 0.0
    slippage: float = 0.0
    fill_status: str = "FILLED"
    rule_checks: List[Dict[str, Any]] = Field(default_factory=list)


class AgentSimulationCaseItem(BaseModel):
    case_id: str
    case_source: str = "AGENT_SIMULATION"
    operator_type: str = "AGENT"
    source_signal_id: str
    source_paper_order_id: str
    run_id: Optional[str] = None
    agent_id: str = "paper_trading_agent"
    audit_id: str
    simulation_only: bool = True
    is_real_trade: bool = False
    outcome: Dict[str, Any] = Field(default_factory=dict)
    failure_tags: List[str] = Field(default_factory=list)
    knowledge_candidate_status: str = "REVIEWING"
    created_at: str
    updated_at: str


class AgentSimulationCaseRequest(BaseModel):
    audit_id: Optional[str] = None
    source_paper_order_id: str
    outcome: Dict[str, Any] = Field(default_factory=dict)
    failure_tags: List[str] = Field(default_factory=list)
    knowledge_candidate_status: str = "REVIEWING"
