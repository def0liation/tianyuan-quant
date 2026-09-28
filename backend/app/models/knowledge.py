from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator


def _supporting_confidence_value(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return "MEDIUM" if normalized in {"HIGH", "MEDIUM"} else "LOW"


def _supporting_evidence_strength_value(value: Any) -> str:
    normalized = str(value or "MISSING").strip().upper()
    if normalized in {"HIGH", "STRONG", "PRIMARY", "PRIMARY_EVIDENCE", "PASS", "READY"}:
        return "MEDIUM"
    if normalized in {"SUPPORTING_ONLY", "REVIEW", "REVIEW_ONLY", "WARN"}:
        return "LOW"
    if normalized in {"MEDIUM", "LOW", "MISSING", "PENDING"}:
        return normalized
    return "MISSING"


class KnowledgeItem(BaseModel):
    item_id: str
    version: int = 0
    status: str = "PENDING_REVIEW"
    category: str
    source_run_id: Optional[str] = None
    source_audit_id: Optional[str] = None
    source_run_verified: bool = False
    title: str
    thesis: str
    evidence: List[str] = Field(default_factory=list)
    decision_impact: str = ""
    guardrail_notes: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    confidence: str = "MEDIUM"
    evidence_usage: str = "supporting_only"
    evidence_strength: str = "MISSING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strong_conclusion_allowed: bool = False
    created_at: str
    updated_at: str
    reviewed_at: Optional[str] = None
    reviewer: Optional[str] = None
    review_note: Optional[str] = None


class KnowledgeSummary(BaseModel):
    total: int
    active_count: int
    pending_count: int
    rejected_count: int
    archived_count: int
    latest_version: int
    categories: dict[str, int]
    updated_at: str


class ActiveKnowledgeContextItem(BaseModel):
    itemId: str
    version: int = 0
    category: str = ""
    title: str = ""
    thesis: str = ""
    decisionImpact: str = ""
    tags: List[str] = Field(default_factory=list)
    confidence: str = "MEDIUM"
    evidenceUsage: str = "supporting_only"
    evidenceStrength: str = "MISSING"
    simulationOnly: bool = True
    isRealTrade: bool = False
    strongConclusionAllowed: bool = False

    @model_validator(mode="after")
    def enforce_supporting_only_boundary(self) -> "ActiveKnowledgeContextItem":
        self.confidence = _supporting_confidence_value(self.confidence)
        self.evidenceUsage = "supporting_only"
        self.evidenceStrength = _supporting_evidence_strength_value(self.evidenceStrength)
        self.simulationOnly = True
        self.isRealTrade = False
        self.strongConclusionAllowed = False
        return self


class KnowledgeContextResponse(BaseModel):
    items: List[ActiveKnowledgeContextItem] = Field(default_factory=list)


class CreateKnowledgeItemRequest(BaseModel):
    category: str = "RUN_REVIEW"
    title: str
    thesis: str
    evidence: List[str] = Field(default_factory=list)
    decision_impact: str = ""
    guardrail_notes: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    confidence: str = "MEDIUM"
    source_run_id: Optional[str] = None
    source_audit_id: Optional[str] = None


class ReviewKnowledgeItemRequest(BaseModel):
    action: str
    reviewer: str = "human"
    note: str = ""


class GenerateKnowledgeFromRunRequest(BaseModel):
    force: bool = False
