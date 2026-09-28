from __future__ import annotations
import logging
from typing import Any, Dict, Optional, Type

from .base_agent import BaseAgent, AgentResult
from .router import RouterAgent
from .orchestrator import OrchestratorAgent
from .state_validation import StateValidationAgent
from .data_fetch import DataFetchAgent
from .chip_kb import ChipKbAgent
from .dvg_evidence_gate import DvgEvidenceGateAgent
from .guardrail_hub import GuardrailHubAgent
from .hallucination_guardrail import HallucinationGuardrailAgent
from .risk_firewall import RiskFirewallAgent
from .atrade import ATradeAgent
from .flash_crash import FlashCrashAgent
from .market_regime import MarketRegimeAgent
from .technical_kline_analyst import TechnicalKlineAnalystAgent
from .market_technical_analyst import MarketTechnicalAnalystAgent
from .bottom_research import BottomResearchAgent
from .quant_core import QuantCoreAgent
from .sector_rotation import SectorRotationAgent
from .factor_slicing import FactorSlicingAgent
from .factor_engine import FactorEngineAgent
from .calculation_authority import CalculationAuthorityAgent
from .qiam import QiamAgent
from .scenario_engine import ScenarioEngineAgent
from .simulation_agent import SimulationAgent
from .portfolio import PortfolioAgent
from .execution import ExecutionAgent
from .anti_conclusion import AntiConclusionAgent
from .signalops import SignalopsAgent
from .paper_trading_agent import PaperTradingAgent
from .review_agent import ReviewAgent
from .error_ledger import ErrorLedgerAgent
from .meta_agent import MetaAgent
from .memory_agent import MemoryAgent
from .state_serialization import StateSerializationAgent
from .final_writer import FinalWriterAgent

logger = logging.getLogger(__name__)

_AGENT_CLASSES: Dict[str, Type[BaseAgent]] = {
    "router": RouterAgent,
    "orchestrator": OrchestratorAgent,
    "state_validation": StateValidationAgent,
    "data_fetch": DataFetchAgent,
    "data_reliability_engine": DataFetchAgent,
    "data_engine": DataFetchAgent,
    "chip_kb": ChipKbAgent,
    "dvg_evidence_gate": DvgEvidenceGateAgent,
    "dvg_gate": DvgEvidenceGateAgent,
    "guardrail_hub": GuardrailHubAgent,
    "hallucination_guardrail": HallucinationGuardrailAgent,
    "risk_firewall": RiskFirewallAgent,
    "atrade": ATradeAgent,
    "trade_micro": ATradeAgent,
    "flash_crash": FlashCrashAgent,
    "market_regime": MarketRegimeAgent,
    "technical_kline_analyst": TechnicalKlineAnalystAgent,
    "market_technical_analyst": MarketTechnicalAnalystAgent,
    "bottom_research": BottomResearchAgent,
    "quant_core": QuantCoreAgent,
    "sector_rotation": SectorRotationAgent,
    "factor_slicing": FactorSlicingAgent,
    "factor_engine": FactorEngineAgent,
    "calculation_authority": CalculationAuthorityAgent,
    "qiam": QiamAgent,
    "quant_engine": QiamAgent,
    "scenario_engine": ScenarioEngineAgent,
    "simulation_agent": SimulationAgent,
    "portfolio": PortfolioAgent,
    "execution": ExecutionAgent,
    "anti_conclusion": AntiConclusionAgent,
    "signalops": SignalopsAgent,
    "paper_trading_agent": PaperTradingAgent,
    "review_agent": ReviewAgent,
    "error_ledger": ErrorLedgerAgent,
    "meta_agent": MetaAgent,
    "memory_agent": MemoryAgent,
    "state_serialization": StateSerializationAgent,
    "final_writer": FinalWriterAgent,
    "meta_review": MetaAgent,
}

_instances: Dict[str, BaseAgent] = {}


def get_agent(agent_id: str) -> Optional[BaseAgent]:
    cls = _AGENT_CLASSES.get(agent_id)
    if cls is None:
        return None
    if agent_id not in _instances:
        _instances[agent_id] = cls()
    return _instances[agent_id]


def run_agent(agent_id: str, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
    agent = get_agent(agent_id)
    if agent is None:
        return AgentResult(
            node=agent_id,
            status="SKIPPED",
            skipped_reason=f"No agent implementation for {agent_id}",
        )
    try:
        return agent.process(run_context, prior_outputs)
    except Exception as exc:
        logger.exception("Agent %s raised exception", agent_id)
        return AgentResult(
            node=agent_id,
            status="FAILED",
            skipped_reason=f"Agent {agent_id} 执行异常",
            data={"error": "内部错误"},
        )


def run_all_agents(
    agent_ids: list[str],
    run_context: Dict[str, Any],
) -> Dict[str, AgentResult]:
    results: Dict[str, AgentResult] = {}
    for agent_id in agent_ids:
        results[agent_id] = run_agent(agent_id, run_context, results)
    return results


def registered_agents() -> list[str]:
    from ..core.agent_framework import AGENT_MANIFEST

    return [agent["id"] for agent in AGENT_MANIFEST]
