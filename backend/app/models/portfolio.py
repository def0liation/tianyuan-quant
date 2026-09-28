from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


PORTFOLIO_SUPPORTING_EVIDENCE_USAGE = "supporting_only"
PORTFOLIO_ALLOWED_EVIDENCE_STRENGTHS = {"MEDIUM", "LOW", "MISSING", "PENDING"}


def _safe_portfolio_evidence_strength(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in PORTFOLIO_ALLOWED_EVIDENCE_STRENGTHS else "PENDING"


def _supporting_only_portfolio_boundary(data: Any) -> Any:
    if not isinstance(data, dict):
        return data

    normalized = dict(data)
    normalized["evidenceUsage"] = PORTFOLIO_SUPPORTING_EVIDENCE_USAGE
    normalized["evidenceStrength"] = _safe_portfolio_evidence_strength(
        normalized.get("evidenceStrength")
    )
    normalized["simulationOnly"] = True
    normalized["isRealTrade"] = False
    normalized["strongConclusionAllowed"] = False
    return normalized


class HoldingPosition(BaseModel):
    symbol: str
    name: str = ""
    shares: float = 0.0
    availableShares: float = 0.0
    costPrice: float = 0.0
    marketValue: float = 0.0
    pnl: float = 0.0
    industry: str = ""
    style: str = ""
    theme: str = ""
    riskFactor: str = ""
    weight: float = 0.0
    updatedAt: str = ""
    raw: Dict[str, Any] = Field(default_factory=dict)


class HoldingValidationIssue(BaseModel):
    rowNumber: int = 0
    symbol: str = ""
    field: str = ""
    level: str = "WARN"
    message: str


class PortfolioSnapshot(BaseModel):
    snapshotId: str
    sourceType: str = "MANUAL"
    sourceName: str = ""
    accountName: str = ""
    totalAssets: float = 0.0
    cash: float = 0.0
    stockMarketValue: float = 0.0
    availableCash: float = 0.0
    totalPositionRatio: float = 0.0
    maxSinglePositionRatio: float = 0.0
    positionCount: int = 0
    qualityStatus: str = "OK"
    issueCount: int = 0
    brokerTemplateId: str = "manual_entry"
    brokerTemplateLabel: str = "Manual entry"
    templateConfidence: float = 1.0
    templateWarnings: List[str] = Field(default_factory=list)
    evidenceUsage: str = "supporting_only"
    evidenceStrength: str = "PENDING"
    simulationOnly: bool = True
    isRealTrade: bool = False
    strongConclusionAllowed: bool = False
    importedAt: str = ""
    updatedAt: str = ""
    positions: List[HoldingPosition] = Field(default_factory=list)
    issues: List[HoldingValidationIssue] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def enforce_supporting_only_boundary(cls, data: Any) -> Any:
        return _supporting_only_portfolio_boundary(data)


class PortfolioSnapshotSummary(BaseModel):
    snapshotId: str
    sourceType: str
    sourceName: str
    accountName: str
    totalAssets: float
    stockMarketValue: float
    cash: float
    totalPositionRatio: float
    maxSinglePositionRatio: float
    positionCount: int
    qualityStatus: str
    issueCount: int
    brokerTemplateId: str = "manual_entry"
    brokerTemplateLabel: str = "Manual entry"
    templateConfidence: float = 1.0
    templateWarnings: List[str] = Field(default_factory=list)
    evidenceUsage: str = "supporting_only"
    evidenceStrength: str = "PENDING"
    simulationOnly: bool = True
    isRealTrade: bool = False
    strongConclusionAllowed: bool = False
    importedAt: str
    updatedAt: str

    @model_validator(mode="before")
    @classmethod
    def enforce_supporting_only_boundary(cls, data: Any) -> Any:
        return _supporting_only_portfolio_boundary(data)


class HoldingImportResponse(BaseModel):
    jobId: str
    status: str
    message: str
    snapshot: PortfolioSnapshot


class HoldingImportJob(BaseModel):
    jobId: str
    snapshotId: Optional[str] = None
    filename: str = ""
    sourceType: str = "CSV"
    status: str = "COMPLETED"
    rowsTotal: int = 0
    rowsImported: int = 0
    issueCount: int = 0
    brokerTemplateId: str = "manual_entry"
    brokerTemplateLabel: str = "Manual entry"
    templateConfidence: float = 1.0
    templateWarnings: List[str] = Field(default_factory=list)
    message: str = ""
    importError: Optional[Dict[str, Any]] = None
    createdAt: str = ""


class ManualPortfolioRequest(BaseModel):
    sourceName: str = "manual"
    accountName: str = ""
    totalAssets: float = 0.0
    cash: float = 0.0
    availableCash: float = 0.0
    positions: List[HoldingPosition]
