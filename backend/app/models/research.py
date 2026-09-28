from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .case_library import CaseLibraryItem, ErrorLedgerItem, KnowledgePatchItem
from .evaluation import EvaluationRunItem
from .knowledge import KnowledgeItem


def _review_gate_evidence_quality(quality: Any) -> str:
    normalized = str(quality or "").strip().upper()
    if normalized in {
        "HIGH",
        "PASS",
        "READY",
        "STRONG",
        "PRIMARY",
        "PRIMARY_EVIDENCE",
        "PRIMARY_EVIDENCE_READY",
        "RESEARCH_GRADE",
    }:
        return "MEDIUM"
    if normalized in {"SUPPORTING_ONLY", "WARN", "REVIEW", "REVIEW_ONLY"}:
        return "LOW"
    if normalized in {"FAIL", "FAILED", "BLOCKED"}:
        return "MISSING"
    if normalized in {"MEDIUM", "LOW", "MISSING", "PENDING", "UNKNOWN"}:
        return normalized
    return "UNKNOWN"


class LinkedProjectRef(BaseModel):
    project: str
    module: str
    path: str = ""
    expected_version: str = ""
    sync_status: str = "PENDING"
    note: str = ""


class ResearchEvidenceLink(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: str
    source_id: str
    label: str = ""
    quality: str = "UNKNOWN"
    reported_quality: Optional[str] = Field(default=None, alias="reportedQuality")
    created_at: str

    @model_validator(mode="after")
    def cap_quality_to_review_gate(self) -> "ResearchEvidenceLink":
        raw_quality = str(self.quality or "").strip().upper()
        reported_quality = str(self.reported_quality or "").strip().upper()
        gated_quality = _review_gate_evidence_quality(raw_quality or reported_quality)
        if not reported_quality and raw_quality and raw_quality != gated_quality:
            reported_quality = raw_quality
        self.quality = gated_quality
        self.reported_quality = reported_quality or None
        return self


class ResearchFeedbackEvent(BaseModel):
    event_id: str
    action: str
    verdict: str = "PENDING"
    note: str = ""
    reviewer: str = "human"
    created_at: str


class ResearchMetricComparisonRow(BaseModel):
    key: str
    label: str = ""
    baseline: Any = None
    current: Any = None
    delta: Any = None
    quality: str = ""
    warning: str = ""


class ResearchVerdictEvidence(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: str
    source_id: str
    label: str = ""
    quality: str = "UNKNOWN"
    reported_quality: Optional[str] = Field(default=None, alias="reportedQuality")
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def cap_quality_to_review_gate(self) -> "ResearchVerdictEvidence":
        raw_quality = str(self.quality or "").strip().upper()
        reported_quality = str(self.reported_quality or "").strip().upper()
        gated_quality = _review_gate_evidence_quality(raw_quality or reported_quality)
        if not reported_quality and raw_quality and raw_quality != gated_quality:
            reported_quality = raw_quality
        self.quality = gated_quality
        self.reported_quality = reported_quality or None
        return self


class ResearchVerdictInputs(BaseModel):
    iteration_id: str
    loop_id: str
    status: str
    current_verdict: str
    engine_verdict: str = "NEEDS_MORE_DATA"
    suggested_feedback_verdict: str = "PENDING"
    confidence: float = 0.0
    can_accept_feedback: bool = False
    blocking_reasons: List[str] = Field(default_factory=list)
    quality_warnings: List[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    baseline: dict[str, Any] = Field(default_factory=dict)
    current: dict[str, Any] = Field(default_factory=dict)
    comparison: List[ResearchMetricComparisonRow] = Field(default_factory=list)
    evidence: List[ResearchVerdictEvidence] = Field(default_factory=list)
    generated_at: str


class ResearchIteration(BaseModel):
    iteration_id: str
    loop_id: str
    order: int
    status: str = "DRAFT"
    hypothesis: str
    plan: str = ""
    target_modules: List[str] = Field(default_factory=list)
    linked_run_id: Optional[str] = None
    linked_backtest_id: Optional[str] = None
    linked_case_id: Optional[str] = None
    linked_knowledge_item_id: Optional[str] = None
    linked_patch_id: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_links: List[ResearchEvidenceLink] = Field(default_factory=list)
    feedback_events: List[ResearchFeedbackEvent] = Field(default_factory=list)
    verdict: str = "PENDING"
    created_at: str
    updated_at: str


class ResearchLoop(BaseModel):
    loop_id: str
    title: str
    objective: str
    status: str = "ACTIVE"
    action_target: str = "factor"
    owner: str = "human"
    tags: List[str] = Field(default_factory=list)
    linked_projects: List[LinkedProjectRef] = Field(default_factory=list)
    source: str = "super"
    current_iteration_id: Optional[str] = None
    iteration_count: int = 0
    created_at: str
    updated_at: str


class ResearchWorkflowStep(BaseModel):
    key: str
    label: str
    status: str = "WAIT"
    ref_id: Optional[str] = None
    detail: str = ""
    source: str = ""
    source_timestamp: str = ""
    evidence_strength: str = "UNKNOWN"
    evidence_usage: str = "review_gate_only"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    missing_items: List[str] = Field(default_factory=list)
    next_action: str = ""
    next_action_label: str = ""


class ResearchWorkflowState(BaseModel):
    maturity_score: int = 0
    maturity_level: str = "missing_data"
    maturity_label: str = "Missing data"
    maturity_reasons: List[str] = Field(default_factory=list)
    stage: str = "empty"
    next_action: str = "create_iteration"
    next_action_label: str = "Create first iteration"
    blocking_reasons: List[str] = Field(default_factory=list)
    steps: List[ResearchWorkflowStep] = Field(default_factory=list)
    evidence_strength: str = "UNKNOWN"
    evidence_usage: str = "review_gate_only"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False


class ResearchLoopDetail(BaseModel):
    loop: ResearchLoop
    iterations: List[ResearchIteration] = Field(default_factory=list)
    workflow_state: ResearchWorkflowState = Field(default_factory=ResearchWorkflowState)



class ResearchSummary(BaseModel):
    total_loops: int
    active_loops: int
    paused_loops: int
    completed_loops: int
    total_iterations: int
    pending_iterations: int
    accepted_iterations: int
    rejected_iterations: int
    patch_required_iterations: int
    linked_project_count: int
    updated_at: str


class CreateResearchLoopRequest(BaseModel):
    title: str
    objective: str
    hypothesis: str = ""
    plan: str = ""
    action_target: str = "factor"
    owner: str = "human"
    tags: List[str] = Field(default_factory=list)
    target_modules: List[str] = Field(default_factory=list)
    linked_projects: List[LinkedProjectRef] = Field(default_factory=list)


class UpdateResearchLoopRequest(BaseModel):
    title: Optional[str] = None
    objective: Optional[str] = None
    status: Optional[str] = None
    action_target: Optional[str] = None
    owner: Optional[str] = None
    tags: Optional[List[str]] = None
    linked_projects: Optional[List[LinkedProjectRef]] = None


class ArchiveResearchLoopRequest(BaseModel):
    reviewer: str = "human"
    note: str = ""


class CreateResearchIterationRequest(BaseModel):
    hypothesis: str
    plan: str = ""
    target_modules: List[str] = Field(default_factory=list)
    linked_run_id: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class UpdateResearchIterationRequest(BaseModel):
    status: Optional[str] = None
    hypothesis: Optional[str] = None
    plan: Optional[str] = None
    target_modules: Optional[List[str]] = None
    linked_run_id: Optional[str] = None
    linked_backtest_id: Optional[str] = None
    linked_case_id: Optional[str] = None
    linked_knowledge_item_id: Optional[str] = None
    linked_patch_id: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None
    verdict: Optional[str] = None


class AttachResearchRunRequest(BaseModel):
    run_id: str
    status: str = "RUN_ATTACHED"
    note: str = ""
    reviewer: str = "human"
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_links: List[ResearchEvidenceLink] = Field(default_factory=list)


class AttachResearchBacktestRequest(BaseModel):
    backtest_run_id: str
    status: str = "BACKTEST_ATTACHED"
    note: str = ""
    reviewer: str = "human"
    role: str = "candidate"
    review_conclusion: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_links: List[ResearchEvidenceLink] = Field(default_factory=list)


class CreateResearchBacktestVerdictInputsRequest(BaseModel):
    iteration_id: str
    reviewer: str = "human"
    note: str = ""
    role: str = "candidate"
    review_conclusion: str = ""
    refresh: bool = True


class ResearchBacktestVerdictInputsResponse(BaseModel):
    iteration: ResearchIteration
    verdict_inputs: ResearchVerdictInputs
    evidence_usage: str = "supporting_only"
    supporting_only: bool = True
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False


class CreateResearchSignalOpsEvidenceRequest(BaseModel):
    iteration_id: str
    reviewer: str = "human"
    note: str = ""
    refresh: bool = True


class ResearchSignalOpsEvidenceResponse(BaseModel):
    iteration: ResearchIteration
    verdict_inputs: ResearchVerdictInputs
    evidence_usage: str = "supporting_only"
    supporting_only: bool = True
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False


class CreateNextResearchIterationRequest(BaseModel):
    hypothesis: Optional[str] = None
    plan: str = ""
    target_modules: List[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    reviewer: str = "human"
    note: str = ""


class StartResearchRunRequest(BaseModel):
    symbol: str
    task_type: str = "research_iteration"
    run_mode: str = "STANDARD_MODE"
    quant_engine_mode: Optional[str] = None
    bottom_research_config: Optional[dict[str, Any]] = None
    scenario_id: str = "qiam_discounted"
    user_constraints: dict[str, Any] = Field(default_factory=dict)
    config_profile_id: str = "default"
    portfolio_snapshot_id: Optional[str] = None
    auto_start: bool = False


class StartResearchRunResponse(BaseModel):
    run_id: str
    status: str
    stream_url: str
    iteration: ResearchIteration


class BottomResearchBacktestRequest(BaseModel):
    run_id: Optional[str] = None
    force_new: bool = False
    reviewer: str = "human"


class CreateSampleResearchLoopRequest(BaseModel):
    run_id: Optional[str] = None
    symbol: Optional[str] = None
    force_backtest: bool = False
    materialize_artifacts: bool = False
    run_evaluation: bool = False
    reviewer: str = "human"


class CreateSampleResearchLoopResponse(BaseModel):
    created: bool = False
    detail: Optional[ResearchLoopDetail] = None
    missing_reasons: List[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    artifact_context: dict[str, Any] = Field(default_factory=dict)


class ClosedLoopStepStatus(BaseModel):
    key: str
    label: str
    status: str = "WAIT"
    ref_id: Optional[str] = None
    note: str = ""
    evidence_usage: str = "review_gate_only"
    evidence_strength: str = "PENDING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    missing_items: List[str] = Field(default_factory=list)
    next_action: str = ""
    next_action_label: str = ""


class CreateP2ClosedLoopSampleRequest(BaseModel):
    symbol: str = "P2SAMPLE.SZ"
    stock_name: str = "P2 Sample Stock"
    portfolio_snapshot_id: Optional[str] = None
    force_backtest: bool = False
    materialize_artifacts: bool = True
    run_evaluation: bool = True
    promote_knowledge_version: bool = True
    reviewer: str = "human"


class CreateP2ClosedLoopSampleResponse(BaseModel):
    created: bool = False
    simulation_only: bool = True
    is_real_trade: bool = False
    portfolio_snapshot_id: Optional[str] = None
    run_id: Optional[str] = None
    signal_id: Optional[str] = None
    backtest_run_id: Optional[str] = None
    loop_id: Optional[str] = None
    iteration_id: Optional[str] = None
    case_id: Optional[str] = None
    knowledge_item_id: Optional[str] = None
    patch_id: Optional[str] = None
    evaluation_id: Optional[str] = None
    knowledge_version_id: Optional[str] = None
    knowledge_version_status: Optional[str] = None
    sample_loop: Optional[CreateSampleResearchLoopResponse] = None
    steps: List[ClosedLoopStepStatus] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ResearchTraceImportRequest(BaseModel):
    trace: dict[str, Any]
    source_id: Optional[str] = None
    dry_run: bool = False
    reviewer: str = "human"
    note: str = ""


class ResearchTraceImportIteration(BaseModel):
    order: int
    iteration: Optional[ResearchIteration] = None
    hypothesis: str
    external_verdict: str = "PENDING"
    evidence_count: int = 0


class ResearchTraceImportResponse(BaseModel):
    imported: bool
    loop: Optional[ResearchLoop] = None
    loop_preview: CreateResearchLoopRequest
    iterations: List[ResearchTraceImportIteration] = Field(default_factory=list)
    external_source: dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class ResearchIterationFeedbackRequest(BaseModel):
    action: str = "REVIEW"
    verdict: str = "PENDING"
    note: str = ""
    reviewer: str = "human"
    status: Optional[str] = None
    linked_run_id: Optional[str] = None
    linked_backtest_id: Optional[str] = None
    linked_case_id: Optional[str] = None
    linked_knowledge_item_id: Optional[str] = None
    linked_patch_id: Optional[str] = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_links: List[ResearchEvidenceLink] = Field(default_factory=list)
    override_blocking_reasons: bool = False
    override_reason: str = ""


class ResearchArtifactMaterializeRequest(BaseModel):
    create_case: bool = True
    create_knowledge_item: bool = True
    create_error_entry: bool = True
    create_patch: bool = True
    run_evaluation: bool = False
    force: bool = False
    reviewer: str = "human"
    note: str = ""
    patch_content: dict[str, Any] = Field(default_factory=dict)


class ResearchArtifactMaterializeResult(BaseModel):
    iteration: ResearchIteration
    case: Optional[CaseLibraryItem] = None
    knowledge_item: Optional[KnowledgeItem] = None
    error_entry: Optional[ErrorLedgerItem] = None
    patch: Optional[KnowledgePatchItem] = None
    evaluation: Optional[EvaluationRunItem] = None
    provenance_chain: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ResearchHypothesisDraftRequest(BaseModel):
    iteration_id: Optional[str] = None
    context_metrics: dict[str, Any] = Field(default_factory=dict)
    use_llm: bool = False
    llm_profile_id: Optional[str] = None
    max_drafts: int = Field(default=3, ge=1, le=5)
    reviewer: str = "human"


class ConfirmResearchHypothesisDraftRequest(BaseModel):
    selected_index: int = Field(default=0, ge=0, le=4)
    reviewer: str = "human"
    note: str = ""


class ResearchActionSelection(BaseModel):
    target: str
    rule_id: str
    reason: str
    confidence: float = 0.0
    evidence: List[str] = Field(default_factory=list)


class ResearchHypothesisDraft(BaseModel):
    hypothesis: str
    plan: str = ""
    action_target: str
    target_modules: List[str] = Field(default_factory=list)
    rationale: str = ""
    source: str = "RULE"


class ResearchHypothesisDraftResponse(BaseModel):
    draft_id: str
    loop_id: str
    iteration_id: Optional[str] = None
    status: str = "DRAFT_READY"
    action_selection: ResearchActionSelection
    drafts: List[ResearchHypothesisDraft] = Field(default_factory=list)
    prompt_provenance: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, Any] = Field(default_factory=dict)
    llm_status: str = "NOT_REQUESTED"
    llm_error: str = ""
    token_usage_link: str = "/debate"
    confirmation_required: bool = True
    auto_run_started: bool = False
    confirmed_iteration_id: Optional[str] = None
    created_at: str
