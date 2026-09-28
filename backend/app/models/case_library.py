from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class CaseLibraryItem(BaseModel):
    case_id: str
    run_id: str
    audit_id: str
    symbol: str
    stock_name: str = ""
    task_type: str = ""
    run_mode: str = "STANDARD_MODE"
    final_action: str = "WAIT"
    final_action_correct: Optional[bool] = None
    conclusion_correct: Optional[bool] = None
    data_sufficiency: str = "ADEQUATE"
    optimism_bias: str = "NONE"
    key_lessons: List[str] = Field(default_factory=list)
    market_context: str = ""
    tags: List[str] = Field(default_factory=list)
    reviewer: Optional[str] = None
    review_note: str = ""
    review_status: str = "PENDING"
    evidence_usage: str = "supporting_only"
    evidence_strength: str = "PENDING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    created_at: str
    updated_at: str


class CaseLibrarySummary(BaseModel):
    total: int
    pending: int
    reviewed: int
    correct_conclusions: int
    accuracy_rate: float


class CreateCaseRequest(BaseModel):
    run_id: str
    reviewer: str = "system"


class UpdateCaseReviewRequest(BaseModel):
    final_action_correct: Optional[bool] = None
    conclusion_correct: Optional[bool] = None
    data_sufficiency: Optional[str] = None
    optimism_bias: Optional[str] = None
    key_lessons: Optional[List[str]] = None
    market_context: Optional[str] = None
    tags: Optional[List[str]] = None
    reviewer: Optional[str] = None
    review_note: Optional[str] = None
    review_status: Optional[str] = None


class ReviewTagItem(BaseModel):
    tag_id: str
    case_id: str
    run_id: str
    tag_type: str
    tag_value: str
    severity: str = "MEDIUM"
    description: str = ""
    node: Optional[str] = None
    reviewer: str = "human"
    created_at: str


class CreateReviewTagRequest(BaseModel):
    tag_type: str
    tag_value: str
    severity: str = "MEDIUM"
    description: str = ""
    node: Optional[str] = None
    reviewer: str = "human"


class ReviewTagSummary(BaseModel):
    total: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]


class ErrorLedgerItem(BaseModel):
    entry_id: str
    run_id: str
    audit_id: str
    node: Optional[str] = None
    error_type: str
    error_reason: str = ""
    repeated_count: int = 1
    patch_required: bool = False
    patch_candidate_id: Optional[str] = None
    attribution: Dict[str, Any] = Field(default_factory=dict)
    status: str = "OPEN"
    evidence_usage: str = "review_gate_only"
    evidence_strength: str = "LOW"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    reported_simulation_only: Optional[bool] = None
    reported_is_real_trade: Optional[bool] = None
    resolved_at: Optional[str] = None
    created_at: str
    updated_at: str


class ErrorLedgerSummary(BaseModel):
    total: int
    open: int
    resolved: int
    by_type: Dict[str, int]
    by_node: Dict[str, int]


class CreateErrorEntryRequest(BaseModel):
    node: Optional[str] = None
    error_type: str
    error_reason: str = ""
    repeated_count: int = 1
    patch_required: bool = False
    attribution: Dict[str, Any] = Field(default_factory=dict)


class UpdateErrorEntryRequest(BaseModel):
    status: Optional[str] = None
    patch_candidate_id: Optional[str] = None
    repeated_count: Optional[int] = None


class KnowledgePatchItem(BaseModel):
    patch_id: str
    source_error_id: Optional[str] = None
    source_case_id: Optional[str] = None
    title: str
    reason: str = ""
    affected_modules: List[str] = Field(default_factory=list)
    patch_content: Dict[str, Any] = Field(default_factory=dict)
    risk_note: str = ""
    rollback_plan: str = ""
    backtest_required: bool = True
    backtest_result: Dict[str, Any] = Field(default_factory=dict)
    approval_status: str = "CANDIDATE"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    evidence_usage: str = "review_gate_only"
    evidence_strength: str = "PENDING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    created_at: str
    updated_at: str


class KnowledgePatchSummary(BaseModel):
    total: int
    candidate: int
    approved: int
    rejected: int


class CreateKnowledgePatchRequest(BaseModel):
    title: str
    reason: str = ""
    affected_modules: List[str] = Field(default_factory=list)
    patch_content: Dict[str, Any] = Field(default_factory=dict)
    source_error_id: Optional[str] = None
    source_case_id: Optional[str] = None


class ReviewPatchRequest(BaseModel):
    action: str
    reviewer: str = "human"
    note: str = ""


class UpdateBacktestRequest(BaseModel):
    backtest_result: Dict[str, Any]
