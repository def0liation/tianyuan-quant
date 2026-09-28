from typing import Any, List, Optional

from pydantic import BaseModel, Field


class DataFingerprint(BaseModel):
    namespace: str
    fingerprint: str
    size_bytes: int
    canonical_keys: List[str] = Field(default_factory=list)
    created_at: str


class DataQualityScore(BaseModel):
    score: int
    level: str
    issues: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    source_coverage: str = "0/0"
    missing_critical_fields: List[str] = Field(default_factory=list)


class RunCompressionSummary(BaseModel):
    run_id: str
    symbol: str
    stock_name: str = ""
    status: str
    run_mode: str
    final_action: str
    data_fingerprint: DataFingerprint
    quality: DataQualityScore
    keep_fields: List[str]
    key_metrics: dict[str, Any]
    decision_summary: str
    guardrail_summary: List[str]
    evidence_summary: List[str]
    agent_summary: dict[str, Any]
    token_budget_estimate: int
    retention_action: str
    retention_reason: str
    created_at: str
    compression_persisted: bool = False
    artifact_path: Optional[str] = None
    compressed_at: Optional[str] = None


class KnowledgeDistillationGroup(BaseModel):
    group_id: str
    category: str
    fingerprint: str
    item_ids: List[str]
    representative_item_id: str
    duplicate_count: int
    shared_tags: List[str] = Field(default_factory=list)
    suggested_action: str
    reason: str


class CompressionOverview(BaseModel):
    total_runs: int
    summarized_runs: int
    average_quality_score: float
    high_quality_count: int
    medium_quality_count: int
    low_quality_count: int
    retention_actions: dict[str, int]
    latest_run_id: Optional[str] = None
