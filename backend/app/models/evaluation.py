from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class EvaluationRunItem(BaseModel):
    eval_id: str
    patch_id: str
    status: str
    total_cases: int = 0
    passed_cases: int = 0
    improved_cases: int = 0
    regressed_cases: int = 0
    unchanged_cases: int = 0
    pass_rate: float = 0.0
    improvement_rate: float = 0.0
    elapsed_ms: int = 0
    per_case_results: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    strategy_experiment_report: Optional[Dict[str, Any]] = None
    evidence_usage: str = "review_gate_only"
    evidence_strength: str = "MISSING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    error: Optional[str] = None
    created_at: str
    updated_at: str


class RunEvaluationRequest(BaseModel):
    force: bool = False


class StrategyExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    config_id: Optional[str] = None
    label: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class StrategyExperimentRequest(BaseModel):
    hypothesis: str
    strategy_configs: List[StrategyExperimentConfig] = Field(default_factory=list)
    sample_window: Dict[str, Any] = Field(default_factory=dict)


class StrategyExperimentReport(BaseModel):
    experiment_id: str
    hypothesis: str
    strategy_count: int
    baseline_config_id: str
    winner_config_id: str
    sample_window: Dict[str, Any] = Field(default_factory=dict)
    metrics_by_strategy: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    evidence_usage: str = "review_gate_only"
    evidence_strength: str = "LOW"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    created_at: str


class KnowledgeVersionItem(BaseModel):
    version_id: str
    version_number: int
    version_label: str = ""
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    active_patches: List[str] = Field(default_factory=list)
    active_rules: List[str] = Field(default_factory=list)
    patch_delta: Dict[str, Any] = Field(default_factory=dict)
    source_patch_id: Optional[str] = None
    source_run_id: Optional[str] = None
    source_case_id: Optional[str] = None
    source_evaluation_id: Optional[str] = None
    source_verdict_id: Optional[str] = None
    scope: str = "knowledge_base"
    risk_boundary: str = ""
    approval_record: Dict[str, Any] = Field(default_factory=dict)
    rollback_impact: Dict[str, Any] = Field(default_factory=dict)
    post_publish_regression: Optional[Dict[str, Any]] = None
    status: str = "active"
    evidence_usage: str = "review_gate_only"
    evidence_strength: str = "PENDING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    created_by: str = "system"
    description: str = ""
    created_at: str


class CreateVersionRequest(BaseModel):
    description: str = ""
    source_run_id: Optional[str] = None
    source_case_id: Optional[str] = None
    source_patch_id: Optional[str] = None
    source_evaluation_id: Optional[str] = None
    source_verdict_id: Optional[str] = None
    scope: str = "knowledge_base"
    risk_boundary: str = ""
    approval_record: Dict[str, Any] = Field(default_factory=dict)
    rollback_impact: Dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


class PromotePatchRequest(BaseModel):
    performed_by: str = "human"
    backtest_id: Optional[str] = None
    evaluation_id: Optional[str] = None
    verdict_id: Optional[str] = None
    source_run_id: Optional[str] = None
    source_case_id: Optional[str] = None
    scope: str = "knowledge_patch_promotion"
    risk_boundary: str = ""
    approval_record: Dict[str, Any] = Field(default_factory=dict)
    rollback_impact: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    allow_regression_override: bool = False
    regression_override_reason: str = ""
    regression_override_approval_id: str = ""
    regression_override_approver_role: str = ""


class RollbackRequest(BaseModel):
    performed_by: str = "human"
    approval_record: Dict[str, Any] = Field(default_factory=dict)
    rollback_impact: Dict[str, Any] = Field(default_factory=dict)


class VersionDiffResult(BaseModel):
    version_a: Dict[str, Any]
    version_b: Dict[str, Any]
    patches_added: List[str] = Field(default_factory=list)
    patches_removed: List[str] = Field(default_factory=list)
    rules_added: List[str] = Field(default_factory=list)
    rules_removed: List[str] = Field(default_factory=list)
    patch_count_diff: int = 0


class RollbackResult(BaseModel):
    rollback_target: KnowledgeVersionItem
    new_version: KnowledgeVersionItem
    restored_patches: int = 0
