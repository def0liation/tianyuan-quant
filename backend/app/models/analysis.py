from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Dict, Any, Optional
from datetime import datetime

from .knowledge import ActiveKnowledgeContextItem
from .portfolio import (
    PORTFOLIO_ALLOWED_EVIDENCE_STRENGTHS,
    PORTFOLIO_SUPPORTING_EVIDENCE_USAGE,
)


SIM_ORDER_NAMESPACE = "SIM_*"
SIM_HOLD_ACTION = "SIM_HOLD"
AGENT_NODE_EVIDENCE_USAGE = "simulation_only"
AGENT_NODE_ALLOWED_EVIDENCE_STRENGTHS = {
    "LOW",
    "MEDIUM",
    "PENDING",
}
QUANT_CORE_ACTION_BOUNDARY = "READ_ONLY_NO_PERMISSION_CHANGE"
QUANT_CORE_EVIDENCE_USAGE = "simulation_only"
QUANT_CORE_ALLOWED_EVIDENCE_STRENGTHS = {
    "LOW",
    "MEDIUM",
    "PENDING",
}
REVIEW_GATE_EVIDENCE_STRENGTH_ALIASES = {
    "HIGH",
    "STRONG",
    "PRIMARY",
    "PRIMARY_EVIDENCE",
    "PRIMARY_EVIDENCE_READY",
    "RESEARCH_GRADE",
    "PASS",
    "READY",
}


def _review_gate_evidence_strength(value: Any) -> Optional[str]:
    normalized = str(value or "").strip().upper()
    return "MEDIUM" if normalized in REVIEW_GATE_EVIDENCE_STRENGTH_ALIASES else None


def _sim_action(value: Any) -> str:
    action = str(value or "").strip().upper()
    return action if action.startswith("SIM_") else SIM_HOLD_ACTION


def _simulation_action_entry(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    entry = dict(value)
    action = _sim_action(
        entry.get("latest_action") or entry.get("paper_action") or entry.get("action")
    )
    entry["simulation_only"] = True
    entry["simulationOnly"] = True
    entry["is_real_trade"] = False
    entry["isRealTrade"] = False
    entry["allowed_order_namespace"] = SIM_ORDER_NAMESPACE
    entry["order_namespace"] = SIM_ORDER_NAMESPACE
    entry["orderNamespace"] = SIM_ORDER_NAMESPACE
    entry["latest_action"] = action
    entry["paper_action"] = action
    entry["action"] = action
    return entry


class PaperTradingBoundary(BaseModel):
    model_config = ConfigDict(extra="allow")

    simulation_only: bool = True
    simulationOnly: bool = True
    is_real_trade: bool = False
    isRealTrade: bool = False
    allowed_order_namespace: str = SIM_ORDER_NAMESPACE
    order_namespace: str = SIM_ORDER_NAMESPACE
    orderNamespace: str = SIM_ORDER_NAMESPACE
    latest_action: str = SIM_HOLD_ACTION
    paper_action: str = SIM_HOLD_ACTION
    action: str = SIM_HOLD_ACTION
    simulationActions: List[Any] = Field(default_factory=list)
    simulation_actions: List[Any] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def enforce_simulation_boundary(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        action = _sim_action(
            normalized.get("latest_action")
            or normalized.get("paper_action")
            or normalized.get("action")
        )
        normalized["simulation_only"] = True
        normalized["simulationOnly"] = True
        normalized["is_real_trade"] = False
        normalized["isRealTrade"] = False
        normalized["allowed_order_namespace"] = SIM_ORDER_NAMESPACE
        normalized["order_namespace"] = SIM_ORDER_NAMESPACE
        normalized["orderNamespace"] = SIM_ORDER_NAMESPACE
        normalized["latest_action"] = action
        normalized["paper_action"] = action
        normalized["action"] = action

        for actions_key in ("simulationActions", "simulation_actions"):
            actions = normalized.get(actions_key)
            if isinstance(actions, list):
                normalized[actions_key] = [
                    _simulation_action_entry(entry) for entry in actions
                ]

        return normalized


def _portfolio_evidence_strength(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in PORTFOLIO_ALLOWED_EVIDENCE_STRENGTHS else "PENDING"


def _safe_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _agent_node_evidence_strength(data: Dict[str, Any]) -> str:
    raw_json = data.get("rawJson") if isinstance(data.get("rawJson"), dict) else {}
    existing = str(data.get("evidenceStrength") or "").strip().upper()
    status = str(data.get("status") or "").strip().upper()
    runner = raw_json.get("llmRunner") if isinstance(raw_json.get("llmRunner"), dict) else {}
    runner_status = str(runner.get("status") or "").strip().upper()
    node_type = str(raw_json.get("nodeType") or "").strip().lower()

    if (
        existing == "SUPPORTING_ONLY"
        or node_type == "plugin_observation"
        or raw_json.get("directExecution") is False
        or raw_json.get("canExecuteCode") is False
    ):
        return "LOW"
    if (
        data.get("isSkipped") is True
        or data.get("isBlocked") is True
        or status in {"WAIT", "WARN", "REVIEW_ONLY", "SKIPPED", "BLOCK", "BLOCK_BUY", "FAIL", "ERROR"}
        or runner_status in {"FAILED", "SKIPPED"}
        or bool(_safe_string_list(data.get("missingData")))
        or bool(_safe_string_list(data.get("downgradeReasons")))
    ):
        return "LOW"
    review_gate_strength = _review_gate_evidence_strength(existing)
    if review_gate_strength is not None:
        return review_gate_strength
    if existing in AGENT_NODE_ALLOWED_EVIDENCE_STRENGTHS and existing != "PENDING":
        return existing
    return "MEDIUM"


def _quant_core_evidence_strength(data: Dict[str, Any]) -> str:
    existing = str(data.get("evidenceStrength") or "").strip().upper()
    status = str(data.get("status") or "").strip().upper()
    if data.get("legacyCompatibilityOnly") is True:
        return "LOW"
    if not isinstance(data.get("coreInterpretation"), dict):
        return "LOW"
    if (
        status in {"", "WAIT", "WARN", "REVIEW_ONLY", "SKIPPED", "BLOCK", "BLOCK_BUY", "FAIL", "ERROR"}
        or bool(_safe_string_list(data.get("missingData")))
        or bool(_safe_string_list(data.get("warnings")))
    ):
        return "LOW"
    review_gate_strength = _review_gate_evidence_strength(existing)
    if review_gate_strength is not None:
        return review_gate_strength
    if existing in QUANT_CORE_ALLOWED_EVIDENCE_STRENGTHS and existing != "PENDING":
        return existing
    return "MEDIUM"


def _readonly_quant_core_payload(value: Any, evidence_strength: str) -> Any:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    normalized["actionBoundary"] = QUANT_CORE_ACTION_BOUNDARY
    normalized["evidenceUsage"] = QUANT_CORE_EVIDENCE_USAGE
    normalized["evidenceStrength"] = evidence_strength
    normalized["simulation_only"] = True
    normalized["is_real_trade"] = False
    normalized["strongConclusionAllowed"] = False
    return normalized


class AgentNodeBoundary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    status: str
    isRunning: bool
    isSkipped: bool
    isBlocked: bool
    duration: float = 0
    auditId: str
    inputSummary: Optional[str] = None
    outputSummary: Optional[str] = None
    missingData: List[str] = Field(default_factory=list)
    downgradeReasons: List[str] = Field(default_factory=list)
    blockedPaths: List[str] = Field(default_factory=list)
    allowedNextActions: List[str] = Field(default_factory=list)
    rawJson: Dict[str, Any] = Field(default_factory=dict)
    evidenceUsage: str = AGENT_NODE_EVIDENCE_USAGE
    evidenceStrength: str = "PENDING"
    simulationOnly: bool = True
    isRealTrade: bool = False
    strongConclusionAllowed: bool = False

    @model_validator(mode="before")
    @classmethod
    def enforce_node_boundary(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        node_id = str(normalized.get("id") or "unknown_node").strip() or "unknown_node"
        normalized["id"] = node_id
        normalized["name"] = str(normalized.get("name") or node_id)
        normalized["status"] = str(normalized.get("status") or "WAIT")
        normalized["isRunning"] = normalized.get("isRunning") is True
        normalized["isSkipped"] = normalized.get("isSkipped") is True
        normalized["isBlocked"] = normalized.get("isBlocked") is True
        normalized["auditId"] = str(
            normalized.get("auditId") or f"AUD_{node_id.replace(':', '_').upper()}"
        )
        for field in (
            "missingData",
            "downgradeReasons",
            "blockedPaths",
            "allowedNextActions",
        ):
            normalized[field] = _safe_string_list(normalized.get(field))

        evidence_strength = _agent_node_evidence_strength(normalized)
        normalized["evidenceUsage"] = AGENT_NODE_EVIDENCE_USAGE
        normalized["evidenceStrength"] = evidence_strength
        normalized["simulationOnly"] = True
        normalized["isRealTrade"] = False
        normalized["strongConclusionAllowed"] = False

        raw_json = (
            dict(normalized.get("rawJson"))
            if isinstance(normalized.get("rawJson"), dict)
            else {}
        )
        raw_json["evidenceUsage"] = AGENT_NODE_EVIDENCE_USAGE
        raw_json["evidenceStrength"] = evidence_strength
        raw_json["simulationOnly"] = True
        raw_json["isRealTrade"] = False
        raw_json["strongConclusionAllowed"] = False
        raw_json["allowTradeAction"] = False
        if not raw_json.get("finalDecisionCap") or raw_json.get("finalDecisionCap") == "UPSTREAM_ONLY":
            raw_json["finalDecisionCap"] = "NO_DIRECT_TRADE_ACTION"
        normalized["rawJson"] = raw_json

        return normalized


class QuantCoreBoundary(BaseModel):
    model_config = ConfigDict(extra="allow")

    actionBoundary: str = QUANT_CORE_ACTION_BOUNDARY
    evidenceUsage: str = QUANT_CORE_EVIDENCE_USAGE
    evidenceStrength: str = "PENDING"
    simulation_only: bool = True
    is_real_trade: bool = False
    strongConclusionAllowed: bool = False
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def enforce_readonly_boundary(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        evidence_strength = _quant_core_evidence_strength(normalized)
        normalized["actionBoundary"] = QUANT_CORE_ACTION_BOUNDARY
        normalized["evidenceUsage"] = QUANT_CORE_EVIDENCE_USAGE
        normalized["evidenceStrength"] = evidence_strength
        normalized["simulation_only"] = True
        normalized["is_real_trade"] = False
        normalized["strongConclusionAllowed"] = False
        normalized["warnings"] = _safe_string_list(normalized.get("warnings"))
        normalized["missingData"] = _safe_string_list(normalized.get("missingData"))

        provenance = (
            dict(normalized.get("provenance"))
            if isinstance(normalized.get("provenance"), dict)
            else {}
        )
        provenance["actionBoundary"] = QUANT_CORE_ACTION_BOUNDARY
        provenance["evidenceUsage"] = QUANT_CORE_EVIDENCE_USAGE
        provenance["evidenceStrength"] = evidence_strength
        provenance["simulation_only"] = True
        provenance["is_real_trade"] = False
        provenance["strongConclusionAllowed"] = False
        normalized["provenance"] = provenance

        for key in ("coreInterpretation", "pathRiskFilter", "visualDecisionPanel"):
            if isinstance(normalized.get(key), dict):
                normalized[key] = _readonly_quant_core_payload(
                    normalized[key],
                    evidence_strength,
                )
        interpretation = normalized.get("coreInterpretation")
        if isinstance(interpretation, dict):
            for nested_key in ("pathRiskFilter", "futureTrendProbability", "visualDecisionPanel"):
                if isinstance(interpretation.get(nested_key), dict):
                    interpretation[nested_key] = _readonly_quant_core_payload(
                        interpretation[nested_key],
                        evidence_strength,
                    )
            normalized["coreInterpretation"] = interpretation

        return normalized


class PortfolioRunBoundary(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidenceUsage: str = PORTFOLIO_SUPPORTING_EVIDENCE_USAGE
    evidenceStrength: str = "PENDING"
    simulationOnly: bool = True
    isRealTrade: bool = False
    strongConclusionAllowed: bool = False
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def enforce_supporting_only_boundary(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        normalized["evidenceUsage"] = PORTFOLIO_SUPPORTING_EVIDENCE_USAGE
        normalized["evidenceStrength"] = _portfolio_evidence_strength(
            normalized.get("evidenceStrength")
        )
        normalized["simulationOnly"] = True
        normalized["isRealTrade"] = False
        normalized["strongConclusionAllowed"] = False

        provenance = (
            dict(normalized.get("provenance"))
            if isinstance(normalized.get("provenance"), dict)
            else {}
        )
        if normalized.get("portfolioCoverage") and not provenance.get("coverage"):
            provenance["coverage"] = normalized.get("portfolioCoverage")
        if normalized.get("snapshotId") and not provenance.get("snapshotId"):
            provenance["snapshotId"] = normalized.get("snapshotId")
        provenance["evidenceUsage"] = PORTFOLIO_SUPPORTING_EVIDENCE_USAGE
        provenance["evidenceStrength"] = normalized["evidenceStrength"]
        provenance["simulationOnly"] = True
        provenance["isRealTrade"] = False
        provenance["strongConclusionAllowed"] = False
        normalized["provenance"] = provenance

        return normalized


class AnalysisRun(BaseModel):
    runId: str
    runMode: str
    environment: str
    dataMode: Optional[str] = None
    dataSources: Optional[Dict[str, Any]] = None
    dataReliabilityEngine: Optional[Dict[str, Any]] = None
    dashboardSummary: Optional[Dict[str, Any]] = None
    stockCode: str
    stockName: str
    taskType: str
    userPosition: Dict[str, Any]
    nodes: List[AgentNodeBoundary]
    guardrailHub: Optional[Dict[str, Any]] = None
    dvg: Dict[str, Any]
    risk: Dict[str, Any]
    atrade: Dict[str, Any]
    market: Dict[str, Any]
    factorSlicing: Dict[str, Any]
    quantEngine: Optional[Dict[str, Any]] = None
    quantCore: Optional[QuantCoreBoundary] = None
    chipKb: Dict[str, Any]
    qiam: Dict[str, Any]
    portfolio: PortfolioRunBoundary
    execution: Dict[str, Any]
    signalOps: Dict[str, Any]
    paperTrading: PaperTradingBoundary
    marketData: Optional[Dict[str, Any]] = None
    marketTechnical: Optional[Dict[str, Any]] = None
    technicalKline: Optional[Dict[str, Any]] = None
    mfeMaeResearch: Optional[Dict[str, Any]] = None
    bottomResearch: Optional[Dict[str, Any]] = None
    auxiliaryData: Optional[Dict[str, Any]] = None
    agentRuntime: Optional[Dict[str, Any]] = None
    knowledgeContext: Optional[List[ActiveKnowledgeContextItem]] = None
    compressedSummary: Optional[Dict[str, Any]] = None
    agentModuleResults: Optional[Dict[str, Any]] = None
    agentResults: Optional[List[Dict[str, Any]]] = None
    dagEvents: Optional[List[Dict[str, Any]]] = None
    skippedNodes: Optional[List[Dict[str, Any]]] = None
    tokenUsage: Optional[Dict[str, Any]] = None
    debateArtifacts: Optional[Dict[str, Any]] = None
    orchestratorPlan: Optional[Dict[str, Any]] = None
    finalContext: Optional[Dict[str, Any]] = None
    agentOutputs: Optional[Dict[str, Any]] = None
    llmTrace: Optional[List[Dict[str, Any]]] = None
    finalAction: str
    killSwitch: Dict[str, Any]
    auditLog: List[Dict[str, Any]]
    streamEvents: Optional[List[Dict[str, Any]]] = None
    reviewLedger: Optional[List[Dict[str, Any]]] = None
    finalWriter: Optional[Dict[str, Any]] = None
    finalReportAsset: Optional[Dict[str, Any]] = None
    rdResearch: Optional[Dict[str, Any]] = None
    job: Optional[Dict[str, Any]] = None
    retry: Optional[Dict[str, Any]] = None
    cancelRequested: Optional[bool] = None
    failReason: Optional[str] = None
    failureCategory: Optional[str] = None
    recovery: Optional[Dict[str, Any]] = None
    recoveryEvents: Optional[List[Dict[str, Any]]] = None
    createdAt: str
    updatedAt: str
    status: str

class CreateAnalysisRequest(BaseModel):
    symbol: str
    task_type: str
    run_mode: str
    scenario_id: str
    user_constraints: Dict[str, Any]
    config_profile_id: str
    quant_engine_mode: Optional[str] = None
    bottom_research_config: Optional[Dict[str, Any]] = None
    portfolio_snapshot_id: Optional[str] = None
    research_loop_id: Optional[str] = None
    research_iteration_id: Optional[str] = None

class CreateAnalysisResponse(BaseModel):
    run_id: str
    status: str
    stream_url: str

class StartAnalysisResponse(BaseModel):
    run_id: str
    status: str

class BackendHealth(BaseModel):
    status: str
    version: str
    mode: str
    tradingEnabled: bool
    autoOrderEnabled: bool
    lastCheck: str
    latency: int

class ConfigProfile(BaseModel):
    profile_id: str
    version: int
    locked_guardrails: Dict[str, Any]
    safe_runtime_config: Dict[str, Any]
    review_required_config: Dict[str, Any]
    sandbox_config: Dict[str, Any]
    created_at: str
    updated_at: str

class ConfigSchemaItem(BaseModel):
    key: str
    label: str
    type: str
    layer: str
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[List[str]] = None
    default: Any
    current: Any
    editable: bool
    direction: str
    description: str

class ConfigDraft(BaseModel):
    draft_id: str
    status: str
    changes: Dict[str, Any]
    reason: str
    policy_check: Dict[str, Any]
    audit_id: str
    created_at: str

class PolicyCheckResult(BaseModel):
    passed: bool
    level: str
    warnings: List[str]
    blocked_reasons: List[str]
    effective_changes: Dict[str, Any]

class AuditLogEvent(BaseModel):
    timestamp: str
    run_id: str
    node: str
    event_type: str
    message: str
    status_before: str
    status_after: str
    input_hash: str
    output_hash: str
    audit_id: str
