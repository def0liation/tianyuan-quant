from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


AGENT_NAMES: Dict[str, str] = {
    "router": "Router",
    "orchestrator": "Orchestrator",
    "state_validation": "State Validation",
    "data_fetch": "Data Fetch",
    "data_reliability_engine": "数据可靠性引擎",
    "data_engine": "Data Engine",
    "chip_kb": "Chip KB",
    "dvg_evidence_gate": "DVG Evidence Gate",
    "dvg_gate": "DVG Gate",
    "guardrail_hub": "Guardrail Hub",
    "hallucination_guardrail": "Hallucination Guardrail",
    "risk_firewall": "Risk Firewall",
    "atrade": "A-Trade Microstructure",
    "trade_micro": "Trade Micro",
    "flash_crash": "Flash Crash / Liquidity Trap",
    "market_regime": "Market Regime",
    "technical_kline_analyst": "Technical Kline Analyst",
    "market_technical_analyst": "Market Technical Analyst",
    "bottom_research": "MFE/MAE Path Research",
    "quant_core": "量化核心",
    "sector_rotation": "Sector Rotation",
    "factor_slicing": "Factor Slicing",
    "factor_engine": "Factor Engine",
    "calculation_authority": "Calculation Authority",
    "qiam": "QIAM",
    "quant_engine": "Quant Engine",
    "scenario_engine": "Scenario Engine",
    "simulation_agent": "Simulation Agent",
    "portfolio": "Portfolio",
    "execution": "Execution",
    "anti_conclusion": "Anti-Conclusion",
    "signalops": "SignalOps",
    "paper_trading_agent": "Paper Trading Agent",
    "review_agent": "Review Agent",
    "error_ledger": "Error Ledger Agent",
    "meta_agent": "Meta-Agent",
    "meta_review": "Meta Review",
    "memory_agent": "Memory Agent",
    "state_serialization": "State Serialization",
    "final_writer": "Final Writer",
}


class AgentResult:
    node: str
    name: str
    status: str
    allowed_actions: List[str]
    blocked_actions: List[str]
    hard_stop: bool
    final_decision_cap: Optional[str]
    confidence: str
    reasons: List[str]
    missing_data: List[str]
    warnings: List[str]
    data: Dict[str, Any]
    audit_id: str
    elapsed_ms: int
    skipped_reason: Optional[str]

    def __init__(
        self,
        node: str,
        status: str = "PASS",
        allowed_actions: Optional[List[str]] = None,
        blocked_actions: Optional[List[str]] = None,
        hard_stop: bool = False,
        final_decision_cap: Optional[str] = None,
        confidence: str = "HIGH",
        reasons: Optional[List[str]] = None,
        missing_data: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
        audit_id: Optional[str] = None,
        elapsed_ms: int = 0,
        skipped_reason: Optional[str] = None,
    ):
        self.node = node
        self.name = AGENT_NAMES.get(node, node)
        self.status = status
        self.allowed_actions = allowed_actions or []
        self.blocked_actions = blocked_actions or []
        self.hard_stop = hard_stop
        self.final_decision_cap = final_decision_cap
        self.confidence = confidence
        self.reasons = reasons or []
        self.missing_data = missing_data or []
        self.warnings = warnings or []
        self.data = data or {}
        self.audit_id = audit_id or f"AUD_{node.upper()}"
        self.elapsed_ms = elapsed_ms
        self.skipped_reason = skipped_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node": self.node,
            "name": self.name,
            "status": self.status,
            "allowed_actions": self.allowed_actions,
            "blocked_actions": self.blocked_actions,
            "hard_stop": self.hard_stop,
            "final_decision_cap": self.final_decision_cap,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "missing_data": self.missing_data,
            "warnings": self.warnings,
            "data": self.data,
            "audit_id": self.audit_id,
            "elapsed_ms": self.elapsed_ms,
            "skipped_reason": self.skipped_reason or "",
        }


class BaseAgent:
    node: str
    name: str
    stage: str
    rule_engine_only: bool = True

    def __init__(self):
        cls = self.__class__
        self.node = getattr(cls, "node", None) or cls.__name__[:1].lower() + cls.__name__[1:]
        self.name = cls.__dict__.get("name") or AGENT_NAMES.get(self.node, self.node)

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        raise NotImplementedError

    def _audit(self, run_id: str = "") -> str:
        return f"AUD_{self.node.upper()}" if not run_id else f"AUD_{run_id}_{self.node.upper()}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]
