from __future__ import annotations

import copy
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .quant_engine_modes import quant_engine_profile


FRAMEWORK_NAME = "tianyuan_quant_agent_v10_2_multi_agent"
FRAMEWORK_VERSION = "10.2"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_ROOT = (
    WORKSPACE_ROOT
    / "tianyuan_quant_v10_2_multi_agent_files"
    / "tianyuan_quant_v10_2_multi_agent"
)

SHARED_RULES = {
    "compliance_first": True,
    "no_auto_order": True,
    "no_profit_promise": True,
    "require_human_confirmation": True,
    "evidence_tags": ["C", "I", "U"],
    "no_level2_no_orderbook_claim": True,
    "no_tools_no_exact_calculation": True,
}

RUN_MODE_TOOL_BUDGET = {
    "FAST_MODE": {
        "max_total_tool_calls": 5,
        "high_cost_tools_allowed": False,
    },
    "STANDARD_MODE": {
        "max_total_tool_calls": 10,
        "high_cost_tools_allowed": False,
    },
    "DEEP_MODE": {
        "max_total_tool_calls": 16,
        "high_cost_tools_allowed": True,
    },
}

RUN_MODE_NODES = {
    "FAST_MODE": [
        "orchestrator",
        "data_reliability_engine",
        "guardrail_hub",
        "quant_core",
        "final_writer",
    ],
    "STANDARD_MODE": [
        "orchestrator",
        "data_reliability_engine",
        "guardrail_hub",
        "quant_core",
        "execution",
        "anti_conclusion",
        "signalops",
        "final_writer",
    ],
    "DEEP_MODE": [
        "orchestrator",
        "data_reliability_engine",
        "guardrail_hub",
        "quant_core",
        "execution",
        "anti_conclusion",
        "signalops",
        "final_writer",
    ],
}

CONSOLIDATED_AGENT_REDIRECTS = {
    "router": "orchestrator",
    "state_validation": "orchestrator",
    "chip_kb": "data_reliability_engine",
    "memory_agent": "data_reliability_engine",
    "hallucination_guardrail": "guardrail_hub",
    "dvg_evidence_gate": "guardrail_hub",
    "dvg_gate": "guardrail_hub",
    "risk_firewall": "guardrail_hub",
    "atrade": "guardrail_hub",
    "trade_micro": "guardrail_hub",
    "flash_crash": "guardrail_hub",
    "sector_rotation": "quant_core",
    "market_regime": "quant_core",
    "technical_kline_analyst": "quant_core",
    "market_technical_analyst": "quant_core",
    "bottom_research": "quant_core",
    "factor_engine": "quant_core",
    "calculation_authority": "quant_core",
    "quant_engine": "quant_core",
    "scenario_engine": "quant_core",
    "simulation_agent": "quant_core",
    "paper_trading_agent": "signalops",
    "review_agent": "signalops",
    "error_ledger": "signalops",
    "meta_agent": "final_writer",
    "state_serialization": "final_writer",
    "data_fetch": "data_reliability_engine",
    "data_engine": "data_reliability_engine",
    "portfolio": "guardrail_hub",
    "factor_slicing": "quant_core",
    "qiam": "quant_core",
    "meta_review": "final_writer",
}

KILL_SWITCH_RULES = {
    "compliance_violation": {
        "level": "COMPLIANCE",
        "final_writer_mode": "COMPLIANCE_REFUSAL",
        "blocked_paths": ["ALL_TRADE_RELATED"],
        "allowed_paths": ["REVIEW_ONLY"],
    },
    "risk_hard_reject": {
        "level": "HARD",
        "final_writer_mode": "HARD_RISK_FINAL_ONLY",
        "blocked_paths": ["BUY", "ADD", "CHASE", "HEAVY_POSITION", "EXECUTION_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY", "HOLD", "REDUCE"],
    },
    "dvg_block_buy": {
        "level": "HARD",
        "final_writer_mode": "HARD_RISK_FINAL_ONLY",
        "blocked_paths": ["BUY", "ADD", "QIAM_POSITIVE", "SCENARIO_BUY", "EXECUTION_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY", "HOLD", "REDUCE"],
    },
    "atrade_not_reachable": {
        "level": "HARD",
        "final_writer_mode": "HARD_RISK_FINAL_ONLY",
        "blocked_paths": ["EXECUTION_PLAN", "MARKET_ORDER", "CHASE_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY", "HOLD", "REDUCE"],
    },
    "qiam_block_buy": {
        "level": "HARD",
        "final_writer_mode": "HARD_RISK_FINAL_ONLY",
        "blocked_paths": ["BUY", "ADD", "EXECUTION_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY", "HOLD", "REDUCE"],
    },
}


def _agent(
    agent_id: str,
    name: str,
    stage: str,
    role: str,
    prompt_ref: str,
    prompt_file: str,
    node_type: str,
    tool_scope: Iterable[str],
    next_nodes: Iterable[str],
    run_modes: Iterable[str],
    allow_trade_action: bool = False,
) -> Dict[str, Any]:
    return {
        "id": agent_id,
        "name": name,
        "stage": stage,
        "role": role,
        "system_prompt_ref": prompt_ref,
        "prompt_file": prompt_file,
        "node_type": node_type,
        "tool_scope": list(tool_scope),
        "next_nodes": list(next_nodes),
        "run_modes": list(run_modes),
        "allow_trade_action": allow_trade_action,
        "final_decision_cap": "UPSTREAM_ONLY" if allow_trade_action else "NO_DIRECT_TRADE_ACTION",
    }


_RAW_AGENT_MANIFEST = [
    _agent(
        "router",
        "Router",
        "control",
        "Identifies task type, run mode, required agents, tools, and missing inputs.",
        "03_ROUTER",
        "03_ROUTER_Agent.md",
        "llm_json",
        ["control"],
        ["orchestrator"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "orchestrator",
        "Orchestrator",
        "control",
        "Controls routing, tool budget, hard stops, degradation, kill switch, and final context.",
        "02_ORCHESTRATOR",
        "02_ORCHESTRATOR_主控编排Agent.md",
        "policy_engine",
        ["control", "policy"],
        ["state_validation", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "state_validation",
        "State Validation",
        "control",
        "Validates required input fields and schema version before downstream execution.",
        "STATE_VALIDATION",
        "STATE_VALIDATION.md",
        "rule_engine",
        ["control"],
        ["data_fetch"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "data_fetch",
        "Data Fetch",
        "data",
        "Collects public market, company, and user position inputs without making judgments.",
        "04_DATA_FETCH",
        "04_DATA_FETCH_Agent.md",
        "tool_layer",
        ["data"],
        ["chip_kb", "dvg_evidence_gate"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "chip_kb",
        "Chip KB",
        "data",
        "Analyses chip distribution, migration direction, and risk/positive patches.",
        "CHIP_KB",
        "CHIP_KB.md",
        "tool_layer",
        ["data"],
        ["dvg_evidence_gate"],
        ["DEEP_MODE"],
    ),
    _agent(
        "dvg_evidence_gate",
        "DVG Evidence Gate",
        "guardrail",
        "Labels evidence, checks freshness and hallucination risk, and caps downstream permissions.",
        "05_DVG_EVIDENCE_GATE",
        "05_DVG_Evidence_Gate_Agent.md",
        "llm_json_or_rule_engine",
        ["guardrail", "evidence"],
        ["hallucination_guardrail", "risk_firewall", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "hallucination_guardrail",
        "Hallucination Guardrail",
        "guardrail",
        "Checks hallucination risk score and restricts Final Writer output sections.",
        "HALLUCINATION_GUARDRAIL",
        "HALLUCINATION_GUARDRAIL.md",
        "rule_engine",
        ["guardrail"],
        ["risk_firewall", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "risk_firewall",
        "Risk Firewall",
        "guardrail",
        "Applies compliance, hard-risk, liquidity, and portfolio red-line checks.",
        "06_RISK_FIREWALL",
        "06_RISK_Firewall_Agent.md",
        "llm_json_or_rule_engine",
        ["guardrail", "risk"],
        ["atrade", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "atrade",
        "A-Trade Microstructure",
        "analysis",
        "Checks A-share T+1, limit-up/down, Level-2 availability, and execution reachability.",
        "07_ATRADE",
        "07_ATRADE_Agent.md",
        "llm_json_or_rule_engine",
        ["analysis", "microstructure"],
        ["flash_crash", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "flash_crash",
        "Flash Crash / Liquidity Trap",
        "guardrail",
        "Detects flash crash vacuum, extreme volatility, and liquidity crisis conditions.",
        "FLASH_CRASH",
        "FLASH_CRASH.md",
        "rule_engine",
        ["guardrail"],
        ["market_regime", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "market_regime",
        "Market Regime",
        "analysis",
        "Classifies market sentiment, theme status, liquidity regime, and style environment.",
        "08_MARKET_REGIME",
        "08_MARKET_Regime_Agent.md",
        "llm_json",
        ["analysis", "market"],
        ["sector_rotation"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "sector_rotation",
        "Sector Rotation",
        "analysis",
        "Analyses sector rotation patterns, strength, and style bias.",
        "SECTOR_ROTATION",
        "SECTOR_ROTATION.md",
        "rule_engine",
        ["analysis", "market"],
        ["factor_slicing"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "factor_slicing",
        "Factor Slicing",
        "analysis",
        "Slices factor exposures and detects factor pollution, conflicts, and missing factor data.",
        "09_FACTOR_SLICING",
        "09_FACTOR_SLICING_Agent.md",
        "llm_json_or_tool",
        ["analysis", "factor"],
        ["factor_engine", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "factor_engine",
        "Factor Engine",
        "analysis",
        "Runs multi-factor analysis engine, validates factor stability and missing data.",
        "FACTOR_ENGINE",
        "FACTOR_ENGINE.md",
        "rule_engine",
        ["analysis", "factor"],
        ["calculation_authority", "qiam"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "calculation_authority",
        "Calculation Authority",
        "control",
        "Checks calculation tool availability and prohibits LLM mental math.",
        "CALCULATION_AUTHORITY",
        "CALCULATION_AUTHORITY.md",
        "rule_engine",
        ["control"],
        ["qiam"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "qiam",
        "QIAM",
        "analysis",
        "Calibrates quantitative suitability with DVG discounts and blocks unsafe positive use.",
        "10_QIAM",
        "10_QIAM_Agent.md",
        "llm_json_or_tool",
        ["analysis", "quant"],
        ["scenario_engine", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "scenario_engine",
        "Scenario Engine",
        "analysis",
        "Builds bull/base/bear branches and payoff-quality summaries within permission caps.",
        "11_SCENARIO_ENGINE",
        "11_SCENARIO_ENGINE_Agent.md",
        "tool_or_qualitative",
        ["analysis", "scenario"],
        ["simulation_agent"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "simulation_agent",
        "Simulation Agent",
        "analysis",
        "Runs Monte Carlo / historical replay simulations for probabilistic outcomes.",
        "SIMULATION_AGENT",
        "SIMULATION_AGENT.md",
        "tool_layer",
        ["analysis"],
        ["portfolio"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "portfolio",
        "Portfolio",
        "risk",
        "Checks position role, concentration, drawdown budget, and add-position permissions.",
        "12_PORTFOLIO",
        "12_PORTFOLIO_Agent.md",
        "llm_json_or_rule_engine",
        ["risk", "portfolio"],
        ["execution"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "execution",
        "Execution",
        "risk",
        "Converts upstream caps into manual execution review paths and forbidden action lists.",
        "13_EXECUTION",
        "13_EXECUTION_Agent.md",
        "llm_json_or_rule_engine",
        ["risk", "execution"],
        ["anti_conclusion"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "anti_conclusion",
        "Anti-Conclusion",
        "review",
        "Challenges premature conclusions and blocks semantic drift after guardrail stops.",
        "14_ANTI_CONCLUSION",
        "14_ANTI_CONCLUSION_Agent.md",
        "llm_json",
        ["review"],
        ["signalops", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "signalops",
        "SignalOps",
        "ops",
        "Maps decisions into lifecycle state and automatic simulation-only stock-pool tracking.",
        "15_SIGNALOPS",
        "15_SIGNALOPS_Agent.md",
        "optional_ledger",
        ["ops", "signal", "paper", "review"],
        ["paper_trading_agent", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "paper_trading_agent",
        "Paper Trading Agent",
        "ops",
        "Summarizes automatic simulation-only paper trading state owned by SignalOps.",
        "PAPER_TRADING",
        "PAPER_TRADING.md",
        "optional_ledger",
        ["ops"],
        ["review_agent", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "review_agent",
        "Review Agent",
        "review",
        "Reviews decision chain attribution, mistakes, and ledger entries.",
        "REVIEW_AGENT",
        "REVIEW_AGENT.md",
        "llm_json",
        ["review"],
        ["error_ledger", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "error_ledger",
        "Error Ledger Agent",
        "review",
        "Records LLM failures and module blocks into the error ledger for meta-review.",
        "ERROR_LEDGER",
        "ERROR_LEDGER.md",
        "rule_engine",
        ["review"],
        ["meta_agent", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "meta_agent",
        "Meta-Agent",
        "review",
        "Reviews consistency, error ledger patterns, repeated failures, and patch candidates.",
        "16_META_REVIEW",
        "16_META_REVIEW_Agent.md",
        "optional_governance",
        ["review", "governance"],
        ["memory_agent", "final_writer"],
        ["DEEP_MODE"],
    ),
    _agent(
        "memory_agent",
        "Memory Agent",
        "data",
        "Loads prior analysis history and signal records for context-aware analysis.",
        "MEMORY_AGENT",
        "MEMORY_AGENT.md",
        "tool_layer",
        ["data"],
        ["state_serialization"],
        ["DEEP_MODE"],
    ),
    _agent(
        "state_serialization",
        "State Serialization",
        "output",
        "Generates state snapshots with schema version validation and checksums.",
        "STATE_SERIALIZATION",
        "STATE_SERIALIZATION.md",
        "rule_engine",
        ["output"],
        ["final_writer"],
        ["DEEP_MODE"],
    ),
    _agent(
        "final_writer",
        "Final Writer",
        "output",
        "Writes the final bounded human-readable output without changing upstream decisions.",
        "17_FINAL_WRITER",
        "17_FINAL_WRITER_Agent.md",
        "llm_text",
        ["output"],
        [],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    # ---- Consolidated agent entries (v10.3) ----
    _agent(
        "data_reliability_engine",
        "数据可靠性引擎",
        "data",
        "Collects market data, chip distribution, prior-context, fundamentals, and data reliability evidence.",
        "DATA_RELIABILITY_ENGINE",
        "04_DATA_FETCH_Agent.md",
        "tool_layer",
        ["data", "memory", "reliability"],
        ["guardrail_hub"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "guardrail_hub",
        "Guardrail Hub",
        "guardrail",
        "Runs DVG, risk firewall, kill switch, trade microstructure, and execution reachability as the canonical guardrail node.",
        "GUARDRAIL_HUB",
        "GUARDRAIL_HUB.md",
        "rule_engine",
        ["guardrail", "evidence", "risk", "microstructure", "execution"],
        ["quant_core", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "dvg_gate",
        "DVG Gate",
        "guardrail",
        "Labels evidence, checks freshness, hallucination risk, and caps downstream permissions.",
        "DVG_GATE",
        "05_DVG_Evidence_Gate_Agent.md",
        "llm_json_or_rule_engine",
        ["guardrail", "evidence"],
        ["risk_firewall", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "trade_micro",
        "Trade Micro",
        "analysis",
        "Checks A-share T+1, limit-up/down, Level-2, execution reachability, and position/portfolio constraints.",
        "TRADE_MICRO",
        "07_ATRADE_Agent.md",
        "llm_json_or_rule_engine",
        ["analysis", "risk", "portfolio"],
        ["quant_core", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "quant_core",
        "量化核心",
        "analysis",
        "Fuses market regime, K-line technical evidence, MFE/MAE Path Research, Quant/QIAM, and Scenario Engine into one canonical analysis node.",
        "QUANT_CORE",
        "QUANT_CORE.md",
        "rule_engine",
        ["analysis", "market", "technical", "kline", "research", "factor", "calculation", "quant", "scenario"],
        ["execution", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "market_technical_analyst",
        "Market Technical Analyst",
        "analysis",
        "Fuses market regime and real K-line technical evidence while preserving legacy market and technical outputs.",
        "MARKET_TECHNICAL_ANALYST",
        "MARKET_TECHNICAL_ANALYST.md",
        "rule_engine",
        ["analysis", "market", "technical", "kline"],
        ["bottom_research", "quant_engine", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "technical_kline_analyst",
        "Technical Kline Analyst",
        "analysis",
        "Reads real Tushare daily/weekly/monthly K-line data and explains technical structure without producing trade actions.",
        "TECHNICAL_KLINE_ANALYST",
        "TECHNICAL_KLINE_ANALYST.md",
        "rule_engine",
        ["analysis", "technical", "kline"],
        ["quant_engine", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "bottom_research",
        "MFE/MAE Path Research",
        "analysis",
        "Estimates MFE favorable and MAE breach probabilities from historical K-line structure as research-only evidence.",
        "MFE_MAE_PATH_RESEARCH",
        "MFE_MAE_PATH_RESEARCH.md",
        "rule_engine",
        ["analysis", "research", "kline", "backtest"],
        ["quant_engine", "final_writer"],
        ["STANDARD_MODE", "DEEP_MODE"],
    ),
    _agent(
        "quant_engine",
        "Quant Engine",
        "analysis",
        "Slices factor exposures, runs factor stability checks, enforces calculation authority, calibrates QIAM suitability.",
        "QUANT_ENGINE",
        "10_QIAM_Agent.md",
        "llm_json_or_tool",
        ["analysis", "factor", "calculation", "quant"],
        ["scenario_engine", "final_writer"],
        ["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
    ),
]

ACTIVE_AGENT_IDS = [
    "orchestrator",
    "data_reliability_engine",
    "guardrail_hub",
    "quant_core",
    "execution",
    "anti_conclusion",
    "signalops",
    "final_writer",
]

CONSOLIDATED_AGENT_OVERRIDES = {
    "orchestrator": {
        "name": "Orchestrator",
        "role": "Routes tasks, runs input/state validation, controls tool budget, hard stops, degradation, kill switch, and final context.",
        "tool_scope": ["control", "policy"],
        "next_nodes": ["data_reliability_engine", "final_writer"],
    },
    "data_reliability_engine": {
        "name": "数据可靠性引擎",
        "role": "Collects market data, source health, freshness, fallback, chip distribution, prior-context, and fundamentals without making judgments.",
        "tool_scope": ["data", "memory", "reliability"],
        "next_nodes": ["guardrail_hub"],
    },
    "guardrail_hub": {
        "name": "Guardrail Hub",
        "role": "Canonical active guardrail node for DVG data verification, risk firewall, kill switch, trade microstructure, and execution reachability.",
        "tool_scope": ["guardrail", "evidence", "risk", "microstructure", "execution"],
        "next_nodes": ["quant_core", "final_writer"],
    },
    "dvg_gate": {
        "name": "DVG Gate",
        "role": "Labels evidence (C/I/U), checks freshness, hallucination risk, and caps downstream permissions.",
        "tool_scope": ["guardrail", "evidence"],
        "next_nodes": ["risk_firewall", "final_writer"],
    },
    "risk_firewall": {
        "name": "Risk Firewall",
        "role": "Applies compliance, hard-risk, flash-crash, liquidity-trap, and portfolio red-line checks.",
        "tool_scope": ["guardrail", "risk"],
        "next_nodes": ["trade_micro", "final_writer"],
    },
    "trade_micro": {
        "name": "Trade Micro",
        "role": "Checks A-share T+1, limit-up/down, Level-2, execution reachability, and position/portfolio constraints.",
        "tool_scope": ["analysis", "risk", "portfolio"],
        "next_nodes": ["quant_core", "final_writer"],
    },
    "quant_core": {
        "name": "量化核心",
        "role": "Fuses market regime, real K-line technical evidence, MFE/MAE Path Research, Quant/QIAM, and Scenario Engine while preserving legacy public fields.",
        "tool_scope": ["analysis", "market", "technical", "kline", "research", "factor", "calculation", "quant", "scenario"],
        "next_nodes": ["execution", "final_writer"],
    },
    "execution": {
        "name": "Execution",
    },
    "anti_conclusion": {
        "name": "Anti-Conclusion",
    },
    "signalops": {
        "name": "SignalOps",
        "role": "Maps decisions into lifecycle state and automatic simulation-only stock-pool tracking.",
        "tool_scope": ["ops", "signal", "paper", "review"],
        "next_nodes": ["final_writer"],
    },
    "final_writer": {
        "name": "Final Writer",
        "role": "Writes final report, runs meta-review, serializes state snapshots without changing upstream decisions.",
        "tool_scope": ["output", "review", "serialization"],
    },
}

_RAW_AGENT_BY_ID = {agent["id"]: agent for agent in _RAW_AGENT_MANIFEST}

AGENT_MANIFEST = [
    {**_RAW_AGENT_BY_ID[agent_id], **CONSOLIDATED_AGENT_OVERRIDES.get(agent_id, {})}
    for agent_id in ACTIVE_AGENT_IDS
    if agent_id in _RAW_AGENT_BY_ID
]

AGENT_BY_ID = {agent["id"]: agent for agent in AGENT_MANIFEST}


@lru_cache(maxsize=None)
def load_agent_prompt(agent_id: str) -> str:
    agent = AGENT_BY_ID.get(agent_id)
    if agent is None:
        replacement_id = CONSOLIDATED_AGENT_REDIRECTS.get(agent_id)
        replacement = AGENT_BY_ID.get(replacement_id or "")
        if replacement is not None:
            return "\n".join(
                [
                    f"# {agent_id}",
                    "",
                    "## Consolidated Agent",
                    f"Legacy agent ID: {agent_id}",
                    f"Consolidated into: {replacement['id']} ({replacement['name']})",
                    f"Replacement role: {replacement['role']}",
                    "",
                    "This legacy agent no longer runs as a standalone node.",
                    "Use the replacement agent's backend module output and shared guardrails as the source of truth.",
                ]
            )
        raise KeyError(f"Unknown agent: {agent_id}")

    prompt_path = FRAMEWORK_ROOT / agent["prompt_file"]
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")

    return "\n".join(
        [
            f"# {agent['name']}",
            "",
            "## Prompt 模板",
            f"System prompt ref: {agent['system_prompt_ref']}",
            f"Agent ID: {agent['id']}",
            f"Role: {agent['role']}",
            f"Node type: {agent['node_type']}",
            "",
            "This agent is implemented by backend rule/tool logic and does not have a standalone prompt file.",
            "Use the backend module output and shared guardrails as the source of truth.",
        ]
    )


def _prompt_hash(agent_id: str) -> str:
    prompt = load_agent_prompt(agent_id)
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _prompt_excerpt(agent_id: str, max_chars: int = 520) -> str:
    prompt = load_agent_prompt(agent_id)
    marker = "## Prompt 模板"
    if marker in prompt:
        prompt = prompt.split(marker, 1)[1].strip()
    prompt = " ".join(prompt.split())
    return prompt[:max_chars]


def get_agent_prompt_payload(agent_id: str) -> Dict[str, Any]:
    agent = AGENT_BY_ID.get(agent_id)
    if agent is None:
        replacement_id = CONSOLIDATED_AGENT_REDIRECTS.get(agent_id)
        replacement = AGENT_BY_ID.get(replacement_id or "")
        if replacement is None:
            raise KeyError(f"Unknown agent: {agent_id}")
        prompt = load_agent_prompt(agent_id)
        return {
            "agent_id": agent_id,
            "consolidated_into": replacement_id,
            "framework_name": FRAMEWORK_NAME,
            "framework_version": FRAMEWORK_VERSION,
            "system_prompt_ref": replacement["system_prompt_ref"],
            "prompt_file": replacement["prompt_file"],
            "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            "prompt": prompt,
            "shared_rules": SHARED_RULES,
        }

    return {
        "agent_id": agent_id,
        "framework_name": FRAMEWORK_NAME,
        "framework_version": FRAMEWORK_VERSION,
        "system_prompt_ref": agent["system_prompt_ref"],
        "prompt_file": agent["prompt_file"],
        "prompt_hash": _prompt_hash(agent_id),
        "prompt": load_agent_prompt(agent_id),
        "shared_rules": SHARED_RULES,
    }


def agent_definitions(default_profile_id: str) -> List[Dict[str, Any]]:
    definitions = []
    for agent in AGENT_MANIFEST:
        agent_id = agent["id"]
        definitions.append(
            {
                **agent,
                "enabled": True,
                "status": "READY",
                "llm_profile_id": default_profile_id,
                "prompt_source": str(
                    Path("tianyuan_quant_v10_2_multi_agent_files")
                    / "tianyuan_quant_v10_2_multi_agent"
                    / agent["prompt_file"]
                ),
                "prompt_hash": _prompt_hash(agent_id),
                "system_prompt_excerpt": _prompt_excerpt(agent_id),
                "framework_version": FRAMEWORK_VERSION,
            }
        )
    return definitions


def sync_agent_state(
    persisted_agents: List[Dict[str, Any]],
    default_profile_id: str,
) -> List[Dict[str, Any]]:
    persisted_by_id = {agent.get("id"): agent for agent in persisted_agents}
    synced_agents = []

    for agent in agent_definitions(default_profile_id):
        existing = persisted_by_id.get(agent["id"], {})
        if not existing and agent["id"] == "data_reliability_engine":
            existing = persisted_by_id.get("data_engine", {})
        if not existing and agent["id"] == "guardrail_hub":
            existing = next(
                (
                    persisted_by_id[legacy_id]
                    for legacy_id in ("dvg_gate", "risk_firewall", "trade_micro", "atrade", "dvg_evidence_gate")
                    if isinstance(persisted_by_id.get(legacy_id), dict)
                ),
                {},
            )
        merged = {
            **agent,
            "enabled": existing.get("enabled", agent["enabled"]),
            "status": existing.get("status", agent["status"]),
            "llm_profile_id": existing.get("llm_profile_id", agent["llm_profile_id"]),
        }
        synced_agents.append(merged)

    return synced_agents


def get_framework_payload() -> Dict[str, Any]:
    return {
        "workflow_name": FRAMEWORK_NAME,
        "version": FRAMEWORK_VERSION,
        "mode": "api_orchestrated",
        "shared_rules": SHARED_RULES,
        "run_modes": {
            mode: {
                **RUN_MODE_TOOL_BUDGET[mode],
                "enabled_nodes": nodes,
            }
            for mode, nodes in RUN_MODE_NODES.items()
        },
        "kill_switch": KILL_SWITCH_RULES,
        "nodes": AGENT_MANIFEST,
        "active_agent_count": len(AGENT_MANIFEST),
        "consolidated_agents": CONSOLIDATED_AGENT_REDIRECTS,
        "framework_root": str(FRAMEWORK_ROOT),
    }


def apply_agent_framework_to_run(
    run_data: Dict[str, Any],
    request_payload: Dict[str, Any],
    runtime_summary: Dict[str, Any],
) -> Dict[str, Any]:
    run = copy.deepcopy(run_data)
    run_mode = request_payload.get("run_mode") or run.get("runMode") or "STANDARD_MODE"
    if run_mode not in RUN_MODE_NODES:
        run_mode = "STANDARD_MODE"

    run["runMode"] = run_mode
    run["stockCode"] = request_payload.get("symbol", run.get("stockCode", "UNKNOWN"))
    run["taskType"] = request_payload.get("task_type", run.get("taskType", "UNKNOWN"))
    run["quantEngine"] = quant_engine_profile(
        request_payload.get("quant_engine_mode") or (run.get("quantEngine") or {}).get("mode"),
        run.get("taskType"),
    )
    if isinstance(request_payload.get("bottom_research_config"), dict):
        run["bottomResearchConfig"] = copy.deepcopy(request_payload["bottom_research_config"])
    run["agentRuntime"] = {
        **runtime_summary,
        "workflowName": FRAMEWORK_NAME,
        "workflowVersion": FRAMEWORK_VERSION,
        "runMode": run_mode,
        "quantEngineMode": run["quantEngine"]["mode"],
        "enabledNodeOrder": RUN_MODE_NODES[run_mode],
        "toolBudget": RUN_MODE_TOOL_BUDGET[run_mode],
    }

    kill_switch = _normalize_kill_switch(run)
    run["killSwitch"] = kill_switch
    run["nodes"] = _build_agent_nodes(run, run_mode, runtime_summary, kill_switch)
    normalize_run_artifacts(run)
    run["finalContext"] = _build_final_context(run, kill_switch)
    run["auditLog"] = _build_audit_log(run)
    run["orchestratorPlan"] = _build_orchestrator_plan(run, run_mode, kill_switch)
    return run


MARKET_REGIME_RESULT_FIELDS = {
    "marketSentiment",
    "volatilityIndex",
    "liquidityIndex",
    "institutionalActivity",
    "retailSentiment",
    "sectorRotation",
    "macroIndicators",
    "regimeClassification",
    "provenance",
}

TECHNICAL_KLINE_MISSING_MARKER = "technicalKline live Tushare validation missing"
PRE_EXECUTION_QUANT_CORE_INTERPRETATION_STATUSES = {"CREATED", "PENDING", "QUEUED"}


def apply_market_regime_data(run: Dict[str, Any], data: Any) -> bool:
    if not isinstance(data, dict):
        return False

    update = {key: data[key] for key in MARKET_REGIME_RESULT_FIELDS if key in data}
    if not update:
        return False

    market = run.setdefault("market", {})
    before = {key: market.get(key) for key in update}
    market.update(update)
    return any(before.get(key) != market.get(key) for key in update)


def apply_technical_kline_data(run: Dict[str, Any], data: Any) -> bool:
    if not isinstance(data, dict) or not data:
        return False

    before = copy.deepcopy(run.get("technicalKline") if isinstance(run.get("technicalKline"), dict) else {})
    technical = {**before, **data}
    run["technicalKline"] = technical

    quality = technical.get("dataQuality") if isinstance(technical.get("dataQuality"), dict) else {}
    verified = _verified_technical_kline_for_repair(technical)
    dvg = run.setdefault("dvg", {})
    provenance = dvg.setdefault("provenance", {})
    provenance["technicalKline"] = {
        "sourceType": "LIVE" if verified else "MISSING",
        "provider": quality.get("provider", ""),
        "dataMode": quality.get("dataMode", "UNAVAILABLE"),
        "dailyCount": quality.get("dailyCount", 0),
        "validatedFields": ["open", "high", "low", "close", "volume", "tradeDate"] if verified else [],
        "note": "DVG recorded technical K-line field validation after market/technical analysis.",
    }
    if not verified:
        missing = list(dvg.get("criticalMissingData") or [])
        if TECHNICAL_KLINE_MISSING_MARKER not in missing:
            missing.append(TECHNICAL_KLINE_MISSING_MARKER)
        dvg["criticalMissingData"] = missing

    return before != technical


def apply_market_technical_data(run: Dict[str, Any], data: Any) -> bool:
    if not isinstance(data, dict) or not data:
        return False

    changed = False
    current = run.get("marketTechnical") if isinstance(run.get("marketTechnical"), dict) else {}
    merged = {**current, **data}
    if merged != current:
        run["marketTechnical"] = merged
        changed = True

    market_data = data.get("market") if isinstance(data.get("market"), dict) else {}
    if market_data:
        changed = apply_market_regime_data(run, market_data) or changed

    technical_data = data.get("technicalKline") if isinstance(data.get("technicalKline"), dict) else {}
    if technical_data:
        changed = apply_technical_kline_data(run, technical_data) or changed

    return changed


def apply_quant_core_data(run: Dict[str, Any], data: Any) -> bool:
    if not isinstance(data, dict) or not data:
        return False

    data = _readonly_quant_core_data(_quant_core_data_with_legacy_markers(data))
    changed = False
    current = run.get("quantCore") if isinstance(run.get("quantCore"), dict) else {}
    merged = {**current, **data}
    if merged != current:
        run["quantCore"] = merged
        changed = True

    if apply_market_technical_data(run, data.get("marketTechnical")):
        changed = True

    bottom = data.get("bottomResearch") if isinstance(data.get("bottomResearch"), dict) else {}
    if bottom:
        current_bottom = run.get("bottomResearch") if isinstance(run.get("bottomResearch"), dict) else {}
        merged_bottom = {**current_bottom, **bottom}
        if merged_bottom != current_bottom:
            run["bottomResearch"] = merged_bottom
            changed = True
        current_mfe = run.get("mfeMaeResearch") if isinstance(run.get("mfeMaeResearch"), dict) else {}
        merged_mfe = {**current_mfe, **bottom}
        if merged_mfe != current_mfe:
            run["mfeMaeResearch"] = merged_mfe
            changed = True

    mfe_research = data.get("mfeMaeResearch") if isinstance(data.get("mfeMaeResearch"), dict) else {}
    if mfe_research:
        current_mfe = run.get("mfeMaeResearch") if isinstance(run.get("mfeMaeResearch"), dict) else {}
        merged_mfe = {**current_mfe, **mfe_research}
        if merged_mfe != current_mfe:
            run["mfeMaeResearch"] = merged_mfe
            changed = True

    for target, source in (
        ("factorSlicing", "factorSlicing"),
        ("factorEngine", "factorEngine"),
        ("calculationAuthority", "calculationAuthority"),
        ("qiam", "qiam"),
    ):
        value = data.get(source)
        if isinstance(value, dict) and value:
            current_value = run.get(target) if isinstance(run.get(target), dict) else {}
            merged_value = {**current_value, **value}
            if merged_value != current_value:
                run[target] = merged_value
                changed = True

    quant_engine = data.get("quantEngine") if isinstance(data.get("quantEngine"), dict) else {}
    if quant_engine:
        current_quant_engine = run.get("quantEngine") if isinstance(run.get("quantEngine"), dict) else {}
        merged_quant_engine = {**current_quant_engine, **quant_engine}
        if merged_quant_engine != current_quant_engine:
            run["quantEngine"] = merged_quant_engine
            changed = True

    changed = _mirror_quant_core_legacy_results(run, data) or changed
    return changed


def _mirror_quant_core_legacy_results(run: Dict[str, Any], data: Dict[str, Any]) -> bool:
    changed = False
    legacy_results = data.get("legacyOutputs") if isinstance(data.get("legacyOutputs"), dict) else {}
    if legacy_results:
        module_results = run.setdefault("agentModuleResults", {})
        for key, value in legacy_results.items():
            if isinstance(value, dict):
                legacy_result = _quant_core_legacy_payload(value)
                if module_results.get(key) != legacy_result:
                    module_results[key] = legacy_result
                    changed = True

    legacy_agent_outputs = data.get("legacyAgentOutputs") if isinstance(data.get("legacyAgentOutputs"), dict) else {}
    if legacy_agent_outputs:
        agent_outputs = run.setdefault("agentOutputs", {})
        for key, value in legacy_agent_outputs.items():
            if isinstance(value, dict):
                legacy_output = _quant_core_legacy_payload(value)
                if agent_outputs.get(key) != legacy_output:
                    agent_outputs[key] = legacy_output
                    changed = True
    return changed


def _quant_core_data_with_legacy_markers(data: Dict[str, Any]) -> Dict[str, Any]:
    legacy_results = data.get("legacyOutputs") if isinstance(data.get("legacyOutputs"), dict) else {}
    legacy_agent_outputs = data.get("legacyAgentOutputs") if isinstance(data.get("legacyAgentOutputs"), dict) else {}
    if not legacy_results and not legacy_agent_outputs:
        return data

    normalized = dict(data)
    if legacy_results:
        normalized["legacyOutputs"] = {
            key: _quant_core_legacy_payload(value) if isinstance(value, dict) else value
            for key, value in legacy_results.items()
        }
    if legacy_agent_outputs:
        normalized["legacyAgentOutputs"] = {
            key: _quant_core_legacy_payload(value) if isinstance(value, dict) else value
            for key, value in legacy_agent_outputs.items()
        }
    return normalized


def _readonly_quant_core_data(data: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(data)
    evidence_strength = _quant_core_evidence_strength(normalized)
    normalized["actionBoundary"] = "READ_ONLY_NO_PERMISSION_CHANGE"
    normalized["evidenceUsage"] = "simulation_only"
    normalized["evidenceStrength"] = evidence_strength
    normalized["simulation_only"] = True
    normalized["is_real_trade"] = False
    normalized["strongConclusionAllowed"] = False
    normalized["warnings"] = _string_list(normalized.get("warnings"))
    normalized["missingData"] = _string_list(normalized.get("missingData"))
    provenance = dict(normalized.get("provenance")) if isinstance(normalized.get("provenance"), dict) else {}
    provenance["actionBoundary"] = "READ_ONLY_NO_PERMISSION_CHANGE"
    provenance["evidenceUsage"] = "simulation_only"
    provenance["evidenceStrength"] = evidence_strength
    provenance["simulation_only"] = True
    provenance["is_real_trade"] = False
    provenance["strongConclusionAllowed"] = False
    normalized["provenance"] = provenance
    return normalized


def _quant_core_evidence_strength(data: Dict[str, Any]) -> str:
    existing = str(data.get("evidenceStrength") or "").strip().upper()
    status = str(data.get("status") or "").strip().upper()
    if data.get("legacyCompatibilityOnly") is True:
        return "LOW"
    if not isinstance(data.get("coreInterpretation"), dict):
        return "LOW"
    if (
        status in {"", "WAIT", "WARN", "REVIEW_ONLY", "SKIPPED", "BLOCK", "BLOCK_BUY", "FAIL", "ERROR"}
        or bool(_string_list(data.get("missingData")))
        or bool(_string_list(data.get("warnings")))
    ):
        return "LOW"
    if existing == "SUPPORTING_ONLY":
        return "LOW"
    if existing in {"LOW", "MEDIUM"}:
        return existing
    return "MEDIUM"


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _quant_core_legacy_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    marked = dict(payload)
    marked["legacyCompatibilityOnly"] = True
    marked["canonicalNode"] = "quant_core"
    marked["activeNode"] = False
    return marked


def sync_quant_core_from_agent_module(run: Dict[str, Any]) -> bool:
    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get("quant_core")
    if not isinstance(module_result, dict):
        return False
    data = module_result.get("data")
    return apply_quant_core_data(run, data)


def sync_market_technical_from_agent_results(run: Dict[str, Any]) -> bool:
    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get("market_technical_analyst")
    if isinstance(module_result, dict):
        data = module_result.get("data")
        if isinstance(data, dict) and data:
            apply_market_technical_data(run, data)
            return True

    for result in run.get("agentResults") or []:
        if not isinstance(result, dict) or result.get("node") != "market_technical_analyst":
            continue
        data = result.get("data")
        if isinstance(data, dict) and data:
            apply_market_technical_data(run, data)
            return True
    return False


def sync_market_regime_from_agent_results(run: Dict[str, Any]) -> bool:
    module_result = (run.get("agentModuleResults") or {}).get("market_regime", {})
    if isinstance(module_result, dict) and apply_market_regime_data(run, module_result.get("data")):
        return True

    for result in run.get("agentResults") or []:
        if not isinstance(result, dict) or result.get("node") != "market_regime":
            continue
        return apply_market_regime_data(run, result.get("data"))
    return False


def sync_technical_kline_from_agent_results(run: Dict[str, Any]) -> bool:
    module_result = (run.get("agentModuleResults") or {}).get("technical_kline_analyst", {})
    if isinstance(module_result, dict) and apply_technical_kline_data(run, module_result.get("data")):
        return True

    for result in run.get("agentResults") or []:
        if not isinstance(result, dict) or result.get("node") != "technical_kline_analyst":
            continue
        return apply_technical_kline_data(run, result.get("data"))
    return False


def sync_quant_engine_rule_outputs_from_current_inputs(run: Dict[str, Any]) -> bool:
    """Recompute stale rule-only Quant Engine artifacts from canonical run state."""
    changed = False
    dvg_changed = False
    if _should_repair_dvg_output(run):
        dvg_changed = _recompute_dvg_output(run)
        changed = changed or dvg_changed
    if _should_repair_qiam_output(run) or (dvg_changed and isinstance(run.get("qiam"), dict)):
        changed = _recompute_qiam_output(run) or changed
    return changed


def sync_quant_core_interpretation(run: Dict[str, Any]) -> bool:
    if _should_suppress_quant_core_interpretation(run):
        return _clear_quant_core_interpretation(run)

    if not _has_quant_core_interpretation_inputs(run):
        return False

    from ..modules.quant_core import build_quant_core_interpretation

    quant_core = run.get("quantCore") if isinstance(run.get("quantCore"), dict) else {}
    run["quantCore"] = quant_core
    scenario = quant_core.get("scenario") if isinstance(quant_core.get("scenario"), dict) else {}
    if not scenario:
        scenario = _module_result_data(run, "scenario_engine")

    interpretation = build_quant_core_interpretation(
        run,
        marketTechnical=run.get("marketTechnical") if isinstance(run.get("marketTechnical"), dict) else None,
        bottomResearch=(
            run.get("mfeMaeResearch")
            if isinstance(run.get("mfeMaeResearch"), dict)
            else run.get("bottomResearch")
            if isinstance(run.get("bottomResearch"), dict)
            else None
        ),
        factorSlicing=run.get("factorSlicing") if isinstance(run.get("factorSlicing"), dict) else None,
        qiam=run.get("qiam") if isinstance(run.get("qiam"), dict) else None,
        scenario=scenario,
        quantEngine=run.get("quantEngine") if isinstance(run.get("quantEngine"), dict) else None,
    )

    changed = False
    if quant_core.get("coreInterpretation") != interpretation:
        quant_core["coreInterpretation"] = interpretation
        changed = True

    for artifact in _quant_core_artifact_dicts(run):
        if artifact.get("coreInterpretation") != interpretation:
            artifact["coreInterpretation"] = copy.deepcopy(interpretation)
            changed = True

    agent_outputs = run.get("agentOutputs") if isinstance(run.get("agentOutputs"), dict) else {}
    quant_output = agent_outputs.get("quant_core")
    if isinstance(quant_output, dict) and quant_output.get("coreInterpretation") != interpretation:
        quant_output["coreInterpretation"] = copy.deepcopy(interpretation)
        changed = True

    changed = _sync_final_context_core_interpretation(run, interpretation) or changed
    changed = _sync_final_context_mfe_mae_research(run) or changed
    return changed


def _should_suppress_quant_core_interpretation(run: Dict[str, Any]) -> bool:
    status = str(run.get("status") or "").upper()
    if status not in PRE_EXECUTION_QUANT_CORE_INTERPRETATION_STATUSES:
        return False
    return not _has_materialized_quant_core_output(run)


def _has_materialized_quant_core_output(run: Dict[str, Any]) -> bool:
    module_data = _module_result_data(run, "quant_core")
    if _is_materialized_quant_core_payload(module_data, allow_interpretation_only=True):
        return True

    agent_outputs = run.get("agentOutputs")
    if isinstance(agent_outputs, Mapping) and _is_materialized_quant_core_payload(
        agent_outputs.get("quant_core"),
        allow_interpretation_only=True,
    ):
        return True

    return _is_materialized_quant_core_payload(
        run.get("quantCore"),
        allow_interpretation_only=False,
    )


def _is_materialized_quant_core_payload(
    payload: Any,
    *,
    allow_interpretation_only: bool,
) -> bool:
    if not isinstance(payload, Mapping) or not payload:
        return False

    materialized_fields = (
        "marketTechnical",
        "technicalKline",
        "mfeMaeResearch",
        "bottomResearch",
        "factorSlicing",
        "qiam",
        "scenario",
        "quantEngine",
        "legacyOutputs",
        "legacyAgentOutputs",
    )
    for key in materialized_fields:
        value = payload.get(key)
        if isinstance(value, Mapping) and value:
            return True
        if isinstance(value, list) and value:
            return True

    return bool(
        allow_interpretation_only
        and isinstance(payload.get("coreInterpretation"), Mapping)
        and payload.get("coreInterpretation")
    )


def _clear_quant_core_interpretation(run: Dict[str, Any]) -> bool:
    changed = False

    quant_core = run.get("quantCore")
    if isinstance(quant_core, dict) and "coreInterpretation" in quant_core:
        next_quant_core = dict(quant_core)
        next_quant_core.pop("coreInterpretation", None)
        run["quantCore"] = next_quant_core or None
        changed = True

    final_context = run.get("finalContext")
    if isinstance(final_context, dict):
        inputs = final_context.get("conclusion_derivation_inputs")
        if isinstance(inputs, dict):
            if inputs.pop("core_interpretation", None) is not None:
                changed = True
            quant_core_summary = inputs.get("quant_core_summary")
            if (
                isinstance(quant_core_summary, dict)
                and "coreInterpretation" in quant_core_summary
            ):
                next_summary = dict(quant_core_summary)
                next_summary.pop("coreInterpretation", None)
                inputs["quant_core_summary"] = next_summary
                changed = True

    return changed


def _has_quant_core_interpretation_inputs(run: Dict[str, Any]) -> bool:
    return any(
        isinstance(run.get(key), dict) and bool(run.get(key))
        for key in ("quantCore", "qiam", "mfeMaeResearch", "bottomResearch", "technicalKline", "marketTechnical", "factorSlicing")
    )


def _sync_final_context_core_interpretation(run: Dict[str, Any], interpretation: Dict[str, Any]) -> bool:
    final_context = run.get("finalContext")
    if not isinstance(final_context, dict):
        return False
    inputs = final_context.get("conclusion_derivation_inputs")
    if not isinstance(inputs, dict):
        inputs = {}
        final_context["conclusion_derivation_inputs"] = inputs
    if inputs.get("core_interpretation") == interpretation:
        return False
    inputs["core_interpretation"] = copy.deepcopy(interpretation)
    return True


def _mfe_mae_conclusion_inputs(run: Dict[str, Any]) -> Dict[str, Any]:
    research = _mfe_mae_research_payload(run)
    qiam = run.get("qiam") if isinstance(run.get("qiam"), dict) else {}
    return {
        "mfe_favorable_probability": research.get("mfeFavorableProbability") if isinstance(research, dict) else None,
        "mae_breach_probability": research.get("maeBreachProbability") if isinstance(research, dict) else None,
        "mfe_proxy": research.get("mfeProxy") if isinstance(research, dict) else None,
        "mae_proxy": research.get("maeProxy") if isinstance(research, dict) else None,
        "risk_reward_proxy": research.get("riskRewardProxy") if isinstance(research, dict) else None,
        "risk_policy": research.get("riskPolicy") if isinstance(research, dict) else None,
        "horizon_forecasts": research.get("horizonForecasts", []) if isinstance(research, dict) else [],
        "trend_synthesis": research.get("trendSynthesis", {}) if isinstance(research, dict) else {},
        "qiam_adjustment_preview": research.get("qiamAdjustmentPreview", {}) if isinstance(research, dict) else {},
        "qiam_adjustment": qiam.get("mfeMaePathResearchAdjustment") or qiam.get("bottomResearchAdjustment"),
        "decision_policy": "CONTROLLED_ONE_STEP_QIAM_CALIBRATION_NO_TRADE_ACTION",
    }


def _sync_final_context_mfe_mae_research(run: Dict[str, Any]) -> bool:
    final_context = run.get("finalContext")
    if not isinstance(final_context, dict):
        return False
    inputs = final_context.get("conclusion_derivation_inputs")
    if not isinstance(inputs, dict):
        inputs = {}
        final_context["conclusion_derivation_inputs"] = inputs
    mfe_inputs = _mfe_mae_conclusion_inputs(run)
    if inputs.get("mfe_mae_path_research") == mfe_inputs:
        return False
    inputs["mfe_mae_path_research"] = copy.deepcopy(mfe_inputs)
    return True


def _guardrail_legacy_payload(legacy_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    marked = copy.deepcopy(payload)
    marked.setdefault("node", legacy_id)
    marked["legacyCompatibilityOnly"] = True
    marked["canonicalNode"] = "guardrail_hub"
    marked["activeNode"] = False
    return marked


def sync_guardrail_hub_from_agent_module(run: Dict[str, Any]) -> bool:
    module_results = run.setdefault("agentModuleResults", {})
    if not isinstance(module_results, dict):
        return False
    module_result = module_results.get("guardrail_hub")
    if not isinstance(module_result, dict):
        return False
    data = module_result.get("data")
    if not isinstance(data, dict):
        return False

    changed = _merge_guardrail_hub_payload(run, data)
    legacy_results = data.get("legacyModuleResults")
    if isinstance(legacy_results, dict):
        for legacy_id in ("dvg_gate", "dvg_evidence_gate", "risk_firewall", "trade_micro", "atrade"):
            legacy_result = legacy_results.get(legacy_id)
            if not isinstance(legacy_result, dict):
                continue
            marked_result = _guardrail_legacy_payload(legacy_id, legacy_result)
            if module_results.get(legacy_id) != marked_result:
                module_results[legacy_id] = marked_result
                changed = True
    return changed


def sync_guardrail_hub_from_legacy_fields(run: Dict[str, Any]) -> bool:
    if isinstance(run.get("guardrailHub"), dict):
        return False
    dvg = copy.deepcopy(run.get("dvg") if isinstance(run.get("dvg"), dict) else {})
    risk = copy.deepcopy(run.get("risk") if isinstance(run.get("risk"), dict) else {})
    atrade = copy.deepcopy(run.get("atrade") if isinstance(run.get("atrade"), dict) else {})
    if not any((dvg, risk, atrade, run.get("killSwitch"))):
        return False
    existing_kill_switch = run.get("killSwitch") if isinstance(run.get("killSwitch"), dict) else {}
    kill_switch = copy.deepcopy(existing_kill_switch) if existing_kill_switch.get("active") else _infer_kill_switch(run)
    payload = {
        "status": _guardrail_status_from_legacy(dvg, risk, atrade, kill_switch),
        "finalDecisionCap": _guardrail_final_cap_from_legacy(dvg, kill_switch),
        "killSwitch": kill_switch,
        "dvg": dvg,
        "risk": risk,
        "atrade": atrade,
        "gateResults": {
            "dvg": {"status": dvg.get("status"), "auditId": dvg.get("auditId", "AUD_DVG_LEGACY")},
            "risk": {"status": risk.get("status"), "auditId": risk.get("auditId", "AUD_RISK_LEGACY")},
            "atrade": {"status": atrade.get("status"), "auditId": atrade.get("auditId", "AUD_ATRADE_LEGACY")},
        },
        "warnings": _unique(
            list(dvg.get("warnings", []) or [])
            + list(risk.get("warnings", []) or [])
            + list(atrade.get("warnings", []) or [])
        ),
        "auditId": kill_switch.get("auditId") or "AUD_GUARDRAIL_HUB_LEGACY",
        "synthesizedFromLegacy": True,
    }
    run["guardrailHub"] = payload
    return True


def _merge_guardrail_hub_payload(run: Dict[str, Any], data: Dict[str, Any]) -> bool:
    changed = False
    if run.get("guardrailHub") != data:
        run["guardrailHub"] = copy.deepcopy(data)
        changed = True

    for child_key, run_key in (("dvg", "dvg"), ("risk", "risk"), ("atrade", "atrade")):
        child_data = data.get(child_key)
        if not isinstance(child_data, dict):
            continue
        merged = {**(run.get(run_key) if isinstance(run.get(run_key), dict) else {}), **copy.deepcopy(child_data)}
        if run.get(run_key) != merged:
            run[run_key] = merged
            changed = True
        if run_key == "dvg":
            changed = _sync_quant_engine_from_dvg(run, child_data) or changed

    kill_switch = data.get("killSwitch")
    if isinstance(kill_switch, dict) and run.get("killSwitch") != kill_switch:
        run["killSwitch"] = copy.deepcopy(kill_switch)
        changed = True
    return changed


def _sync_quant_engine_from_dvg(run: Dict[str, Any], dvg: Dict[str, Any]) -> bool:
    changed = False
    quant_engine = run.get("quantEngine")
    if not isinstance(quant_engine, dict):
        quant_engine = {}
        run["quantEngine"] = quant_engine
        changed = True
    if dvg.get("quantEngineMode") and quant_engine.get("mode") != dvg.get("quantEngineMode"):
        quant_engine["mode"] = dvg["quantEngineMode"]
        changed = True
    if dvg.get("parameterProfile") and quant_engine.get("parameterProfile") != dvg.get("parameterProfile"):
        quant_engine["parameterProfile"] = dvg["parameterProfile"]
        changed = True
    if "ignoredMissingData" in dvg:
        ignored = list(dvg.get("ignoredMissingData") or [])
        if quant_engine.get("ignoredMissingData") != ignored:
            quant_engine["ignoredMissingData"] = ignored
            changed = True
    return changed


def _guardrail_status_from_legacy(
    dvg: Dict[str, Any],
    risk: Dict[str, Any],
    atrade: Dict[str, Any],
    kill_switch: Dict[str, Any],
) -> str:
    if kill_switch.get("level") == "COMPLIANCE" or risk.get("status") == "BLOCK":
        return "BLOCK"
    if kill_switch.get("active") or dvg.get("status") == "BLOCK_BUY" or atrade.get("executionReachability") == "NOT_REACHABLE":
        return "BLOCK_BUY"
    if dvg.get("allowedOutputLevel") == "REVIEW_ONLY" or dvg.get("status") == "REVIEW_ONLY":
        return "REVIEW_ONLY"
    if dvg.get("status") == "WARN" or atrade.get("liquidityRisk") == "HIGH" or _risk_status({"risk": risk}) == "WARN":
        return "WARN"
    return "PASS"


def _guardrail_final_cap_from_legacy(dvg: Dict[str, Any], kill_switch: Dict[str, Any]) -> str:
    if kill_switch.get("active"):
        return "REJECT" if kill_switch.get("level") == "COMPLIANCE" else "BLOCK_BUY"
    cap = dvg.get("finalDecisionCap")
    if isinstance(cap, str) and cap:
        return cap
    if dvg.get("allowedOutputLevel") == "REVIEW_ONLY":
        return "REVIEW_ONLY"
    return "NO_CAP"


def _apply_kill_switch_to_existing_nodes(run: Dict[str, Any], kill_switch: Dict[str, Any]) -> bool:
    if not (kill_switch.get("active") and kill_switch.get("level") in {"HARD", "COMPLIANCE"}):
        return False
    nodes = run.get("nodes")
    if not isinstance(nodes, list):
        return False
    trigger_node = _canonical_dag_anchor(str(kill_switch.get("triggerNode") or ""))
    active_ids = [str(node.get("id") or "") for node in nodes if isinstance(node, dict) and not node.get("isSkipped")]
    if trigger_node not in active_ids:
        return False
    stop_index = active_ids.index(trigger_node)
    allowed_ids = set(active_ids[: stop_index + 1])
    allowed_ids.add("final_writer")
    changed = False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if node_id in active_ids and node_id not in allowed_ids:
            if not node.get("isSkipped") or node.get("status") != "SKIPPED":
                node["status"] = "SKIPPED"
                node["isRunning"] = False
                node["isSkipped"] = True
                node["isBlocked"] = True
                node["duration"] = 0
                node["allowedNextActions"] = []
                node["blockedPaths"] = list(kill_switch.get("blockedPaths") or [])
                node["downgradeReasons"] = [f"Kill switch {kill_switch.get('level')} routed remaining path to Final Writer."]
                changed = True
        elif node_id == trigger_node and node_id != "final_writer":
            allowed_next = ["final_writer"]
            blocked_paths = list(kill_switch.get("blockedPaths") or [])
            if node.get("allowedNextActions") != allowed_next:
                node["allowedNextActions"] = allowed_next
                changed = True
            if node.get("blockedPaths") != blocked_paths:
                node["blockedPaths"] = blocked_paths
                changed = True
            if node.get("status") not in {"BLOCK", "BLOCK_BUY", "FAIL"}:
                node["status"] = "BLOCK_BUY" if kill_switch.get("level") != "COMPLIANCE" else "FAIL"
                node["isBlocked"] = True
                changed = True
    return changed


def normalize_run_artifacts(run: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh derived 16-agent contract artifacts after node state changes."""
    sync_guardrail_hub_from_agent_module(run)
    sync_guardrail_hub_from_legacy_fields(run)
    run["killSwitch"] = _normalize_kill_switch(run)
    _apply_kill_switch_to_existing_nodes(run, run["killSwitch"])
    if sync_quant_core_from_agent_module(run):
        pass
    elif not sync_market_technical_from_agent_results(run):
        sync_market_regime_from_agent_results(run)
        sync_technical_kline_from_agent_results(run)
    sync_bottom_research_from_agent_module(run)
    sync_quant_engine_rule_outputs_from_current_inputs(run)
    sync_qiam_probability_from_agent_module(run)
    sync_qiam_score_fields_from_agent_module(run)
    sync_quant_core_interpretation(run)
    run["agentResults"] = _build_standard_agent_results(run)
    run["skippedNodes"] = _build_skipped_nodes(run)
    run["dagEvents"] = _build_dag_events(run)
    run["tokenUsage"] = _build_token_usage(run)
    run["debateArtifacts"] = _build_debate_artifacts(run)
    run["finalContext"] = _build_final_context(run, run["killSwitch"])
    if _should_suppress_quant_core_interpretation(run):
        _clear_quant_core_interpretation(run)
    run_mode = run.get("runMode") if run.get("runMode") in RUN_MODE_NODES else "STANDARD_MODE"
    run["orchestratorPlan"] = _build_orchestrator_plan(run, run_mode, run["killSwitch"])
    return run


def sync_bottom_research_from_agent_module(run: Dict[str, Any]) -> bool:
    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get("bottom_research")
    if not isinstance(module_result, dict):
        return False
    module_data = module_result.get("data") if isinstance(module_result.get("data"), dict) else {}
    if not module_data:
        return False

    current = run.get("bottomResearch") if isinstance(run.get("bottomResearch"), dict) else {}
    merged = {**current, **module_data}
    changed = False
    if merged != current:
        run["bottomResearch"] = merged
        changed = True
    current_mfe = run.get("mfeMaeResearch") if isinstance(run.get("mfeMaeResearch"), dict) else {}
    merged_mfe = {**current_mfe, **module_data}
    if merged_mfe != current_mfe:
        run["mfeMaeResearch"] = merged_mfe
        changed = True
    return changed


def _mfe_mae_research_payload(run: Dict[str, Any]) -> Dict[str, Any]:
    current = run.get("mfeMaeResearch")
    if isinstance(current, dict) and current:
        return current
    legacy = run.get("bottomResearch")
    return legacy if isinstance(legacy, dict) else {}


def _should_repair_dvg_output(run: Dict[str, Any]) -> bool:
    dvg = run.get("dvg")
    if not isinstance(dvg, dict) or not dvg:
        return False
    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    guardrail_result = module_results.get("guardrail_hub") if isinstance(module_results.get("guardrail_hub"), dict) else {}
    guardrail_data = guardrail_result.get("data") if isinstance(guardrail_result.get("data"), dict) else {}
    has_dvg_result = (
        isinstance(module_results.get("dvg_gate"), dict)
        or isinstance(module_results.get("dvg_evidence_gate"), dict)
        or isinstance(guardrail_data.get("dvg"), dict)
        or bool(dvg.get("status"))
        or bool(dvg.get("qiamPermission"))
    )
    if not has_dvg_result:
        return False
    if not dvg.get("activeModule") or not isinstance(dvg.get("dvgModules"), dict):
        return True

    critical_missing = _as_repair_list(dvg.get("criticalMissingData"))
    if _verified_technical_kline_for_repair(run.get("technicalKline")) and any(
        TECHNICAL_KLINE_MISSING_MARKER in str(item)
        or "technicalKline" in str(item)
        or "技术面 K 线真实数据校验" in str(item)
        for item in critical_missing
    ):
        return True

    qiam_permission = str(dvg.get("qiamPermission") or "").upper()
    if _is_low_frequency_quant_run(run) and qiam_permission == "ALLOW_WITH_DISCOUNT":
        high_frequency_markers = _high_frequency_missing_markers(run)
        return any(
            any(marker in str(item) for marker in high_frequency_markers)
            for item in critical_missing
        )
    return False


def _recompute_dvg_output(run: Dict[str, Any]) -> bool:
    from ..modules.dvg_evidence_gate import DvgEvidenceGateAgent

    result = DvgEvidenceGateAgent().process(run, {})
    result_dict = result.to_dict()
    data = dict(result_dict.get("data") or {})
    data["ruleRepairSource"] = "agent_framework.current_inputs"
    result_dict["data"] = data

    changed = False
    before_dvg = copy.deepcopy(run.get("dvg") if isinstance(run.get("dvg"), dict) else {})
    repaired_dvg = {**before_dvg, **data}
    if repaired_dvg != before_dvg:
        run["dvg"] = repaired_dvg
        _sync_quant_engine_metadata_from_rule_data(run, data)
        changed = True

    module_results = run.setdefault("agentModuleResults", {})
    if module_results.get("dvg_gate") != result_dict:
        module_results["dvg_gate"] = result_dict
        changed = True
    return changed


def _should_repair_qiam_output(run: Dict[str, Any]) -> bool:
    qiam = run.get("qiam")
    if not isinstance(qiam, dict) or not qiam:
        return False
    if _qiam_has_pending_seed_for_repair(qiam) and _quant_engine_submodules_completed_for_repair(run):
        return True
    if _qiam_technical_constraint_stale(run):
        return True
    if _qiam_dvg_discount_stale(run):
        return True
    if _qiam_low_frequency_high_frequency_discount_stale(run):
        return True
    return False


def _recompute_qiam_output(run: Dict[str, Any]) -> bool:
    from ..modules.qiam import QiamAgent

    result = QiamAgent().process(run, _qiam_repair_prior_outputs(run))
    result_dict = result.to_dict()
    data = dict(result_dict.get("data") or {})
    data["ruleRepairSource"] = "agent_framework.current_inputs"
    result_dict["data"] = data

    changed = False
    before_qiam = copy.deepcopy(run.get("qiam") if isinstance(run.get("qiam"), dict) else {})
    repaired_qiam = {**before_qiam, **data}
    if repaired_qiam != before_qiam:
        run["qiam"] = repaired_qiam
        _sync_quant_engine_metadata_from_rule_data(run, data)
        _sync_quant_core_qiam_repair_artifacts(run, data, result_dict)
        changed = True

    module_results = run.setdefault("agentModuleResults", {})
    if module_results.get("quant_engine") != result_dict:
        module_results["quant_engine"] = result_dict
        changed = True
    return changed


def _sync_quant_core_qiam_repair_artifacts(
    run: Dict[str, Any],
    data: Dict[str, Any],
    result_dict: Dict[str, Any],
) -> bool:
    changed = False
    quant_engine = run.get("quantEngine") if isinstance(run.get("quantEngine"), dict) else {}
    artifacts = _quant_core_artifact_dicts(run)
    sync_legacy_outputs = any(isinstance(core.get("legacyOutputs"), dict) for core in artifacts)
    sync_legacy_agent_outputs = any(isinstance(core.get("legacyAgentOutputs"), dict) for core in artifacts)
    legacy_result = _quant_core_legacy_payload(result_dict)
    legacy_output = _quant_core_legacy_payload(data)

    for core in artifacts:
        current_qiam = core.get("qiam") if isinstance(core.get("qiam"), dict) else {}
        merged_qiam = {**current_qiam, **data}
        if merged_qiam != current_qiam:
            core["qiam"] = merged_qiam
            changed = True

        current_quant_engine = core.get("quantEngine") if isinstance(core.get("quantEngine"), dict) else {}
        merged_quant_engine = {**current_quant_engine, **quant_engine}
        if merged_quant_engine != current_quant_engine:
            core["quantEngine"] = merged_quant_engine
            changed = True

        if sync_legacy_outputs:
            legacy_outputs = core.get("legacyOutputs")
            if not isinstance(legacy_outputs, dict):
                legacy_outputs = {}
                core["legacyOutputs"] = legacy_outputs
            for key in ("quant_engine", "qiam"):
                if legacy_outputs.get(key) != legacy_result:
                    legacy_outputs[key] = copy.deepcopy(legacy_result)
                    changed = True

        if sync_legacy_agent_outputs:
            legacy_agent_outputs = core.get("legacyAgentOutputs")
            if not isinstance(legacy_agent_outputs, dict):
                legacy_agent_outputs = {}
                core["legacyAgentOutputs"] = legacy_agent_outputs
            for key in ("quant_engine", "qiam"):
                if legacy_agent_outputs.get(key) != legacy_output:
                    legacy_agent_outputs[key] = copy.deepcopy(legacy_output)
                    changed = True

    return changed


def _quant_core_artifact_dicts(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    quant_core = run.get("quantCore")
    if isinstance(quant_core, dict):
        artifacts.append(quant_core)

    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get("quant_core")
    if isinstance(module_result, dict):
        data = module_result.get("data")
        if isinstance(data, dict):
            artifacts.append(data)
    return artifacts


def _sync_quant_engine_metadata_from_rule_data(run: Dict[str, Any], data: Dict[str, Any]) -> None:
    quant_engine = _ensure_quant_engine_dict_for_repair(run)
    if data.get("quantEngineMode"):
        quant_engine["mode"] = data["quantEngineMode"]
    if data.get("parameterProfile"):
        quant_engine["parameterProfile"] = data["parameterProfile"]
    if "ignoredMissingData" in data:
        quant_engine["ignoredMissingData"] = list(data.get("ignoredMissingData") or [])


def _ensure_quant_engine_dict_for_repair(run: Dict[str, Any]) -> Dict[str, Any]:
    quant_engine = run.get("quantEngine")
    if isinstance(quant_engine, dict):
        return quant_engine
    quant_engine = {}
    run["quantEngine"] = quant_engine
    return quant_engine


def _qiam_repair_prior_outputs(run: Dict[str, Any]) -> Dict[str, Any]:
    prior_outputs: Dict[str, Any] = {}
    for context_key, module_key in (
        ("dvg", "dvg_gate"),
        ("technicalKline", "technical_kline_analyst"),
        ("factorSlicing", "factor_slicing"),
        ("factorEngine", "factor_engine"),
        ("calculationAuthority", "calculation_authority"),
    ):
        data = _merged_repair_data(run, context_key, module_key)
        if data:
            prior_outputs[module_key] = data
    return prior_outputs


def _merged_repair_data(run: Dict[str, Any], context_key: str, module_key: str) -> Dict[str, Any]:
    module_data = _module_result_data(run, module_key)
    canonical = run.get(context_key)
    canonical_data = canonical if isinstance(canonical, dict) else {}
    return {**module_data, **canonical_data}


def _module_result_data(run: Dict[str, Any], module_key: str) -> Dict[str, Any]:
    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get(module_key)
    if not isinstance(module_result, dict):
        return {}
    data = module_result.get("data")
    return data if isinstance(data, dict) else {}


def _qiam_has_pending_seed_for_repair(qiam: Dict[str, Any]) -> bool:
    if str(qiam.get("probabilitySource") or "").upper() == "PENDING":
        return True
    return any(_is_qiam_pending_marker_for_repair(item) for item in _as_repair_list(qiam.get("missingData")))


def _qiam_technical_constraint_stale(run: Dict[str, Any]) -> bool:
    qiam = run.get("qiam") if isinstance(run.get("qiam"), dict) else {}
    technical = run.get("technicalKline")
    if not _verified_technical_kline_for_repair(technical):
        return False
    constraint = qiam.get("technicalKlineConstraint") if isinstance(qiam.get("technicalKlineConstraint"), dict) else {}
    downgrade_text = " ".join(str(item) for item in _as_repair_list(qiam.get("downgradeReasons")))
    if "technicalKline low confidence=0.00" in downgrade_text or "technicalKline insufficient_data" in downgrade_text:
        return True

    canonical_confidence = _repair_number((technical or {}).get("confidence"))
    constraint_confidence = _repair_number(constraint.get("confidence"))
    if (
        canonical_confidence is not None
        and constraint_confidence is not None
        and constraint_confidence + 0.001 < canonical_confidence
    ):
        return True

    constraint_bias = str(constraint.get("bias") or "").upper()
    technical_bias = str((technical or {}).get("technicalBias") or "").upper()
    return constraint_bias in {"INSUFFICIENT_DATA", "UNKNOWN"} and technical_bias not in {"", "INSUFFICIENT_DATA", "UNKNOWN"}


def _qiam_dvg_discount_stale(run: Dict[str, Any]) -> bool:
    dvg = run.get("dvg") if isinstance(run.get("dvg"), dict) else {}
    if str(dvg.get("qiamPermission") or "").upper() != "ALLOW":
        return False
    qiam = run.get("qiam") if isinstance(run.get("qiam"), dict) else {}
    remediation_reasons = [
        item.get("reason")
        for item in _as_repair_list(qiam.get("remediationItems"))
        if isinstance(item, dict)
    ]
    text = " ".join(str(item) for item in _as_repair_list(qiam.get("downgradeReasons")) + remediation_reasons)
    return any(token in text for token in ("DVG ALLOW_WITH_DISCOUNT", "DVG BLOCKED", "DVG REVIEW_ONLY"))


def _qiam_low_frequency_high_frequency_discount_stale(run: Dict[str, Any]) -> bool:
    if not _is_low_frequency_quant_run(run):
        return False

    qiam = run.get("qiam") if isinstance(run.get("qiam"), dict) else {}
    markers = _high_frequency_missing_markers(run)
    remediation_reasons = [
        item.get("reason")
        for item in _as_repair_list(qiam.get("remediationItems"))
        if isinstance(item, dict)
    ]
    stale_candidates = (
        _as_repair_list(qiam.get("missingData"))
        + _as_repair_list(qiam.get("downgradeReasons"))
        + remediation_reasons
    )
    return any(
        _contains_high_frequency_marker(item, markers)
        for item in stale_candidates
    )


def _quant_engine_submodules_completed_for_repair(run: Dict[str, Any]) -> bool:
    factor_slicing = _merged_repair_data(run, "factorSlicing", "factor_slicing")
    factor_engine = _merged_repair_data(run, "factorEngine", "factor_engine")
    calculation_authority = _merged_repair_data(run, "calculationAuthority", "calculation_authority")
    return (
        _factor_slicing_completed_for_repair(factor_slicing)
        and _factor_engine_completed_for_repair(factor_engine)
        and _calculation_authority_completed_for_repair(calculation_authority)
    )


def _factor_slicing_completed_for_repair(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    source = str(data.get("factorDataSource") or (data.get("provenance") or {}).get("sourceType") or "").upper()
    if not source or "PENDING" in source:
        return False
    if any(_is_qiam_pending_marker_for_repair(item) for item in _as_repair_list(data.get("missingFactorData"))):
        return False
    factors = data.get("factors")
    factor_count = _repair_int(data.get("factorCount"))
    return (isinstance(factors, list) and len(factors) > 0) or factor_count > 0


def _factor_engine_completed_for_repair(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    mode = str(data.get("engineMode") or data.get("mode") or "").upper()
    return bool(mode) and "PENDING" not in mode and mode not in {"WAIT", "CREATED"}


def _calculation_authority_completed_for_repair(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    status = str(data.get("calculationToolStatus") or data.get("authorityStatus") or "").upper()
    return "PENDING" not in status and status not in {"WAIT", "CREATED"}


def _verified_technical_kline_for_repair(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    quality = value.get("dataQuality") or {}
    if not isinstance(quality, dict):
        return False
    return (
        value.get("agent") == "technical_kline_analyst"
        and value.get("status") in {"PASS", "WARN"}
        and quality.get("provider") == "tushare"
        and quality.get("dataMode") == "LIVE"
        and _repair_int(quality.get("dailyCount")) >= 30
    )


def _is_low_frequency_quant_run(run: Dict[str, Any]) -> bool:
    mode = str((run.get("quantEngine") or {}).get("mode") or (run.get("qiam") or {}).get("quantEngineMode") or "").upper()
    if mode:
        return mode == "LOW_FREQ_MID_LONG"
    task_type = str(run.get("taskType") or "")
    return any(token in task_type for token in ("持仓", "中长线", "复核"))


def _high_frequency_missing_markers(run: Dict[str, Any]) -> List[str]:
    profile = quant_engine_profile((run.get("quantEngine") or {}).get("mode"), run.get("taskType"))
    parameter_profile = profile.get("parameterProfile") if isinstance(profile.get("parameterProfile"), dict) else {}
    markers = parameter_profile.get("highFrequencyMissingMarkers")
    if isinstance(markers, list) and markers:
        return [str(marker) for marker in markers]
    return ["Level-2", "Level2", "L2", "二级行情", "盘口深度", "分时", "逐笔", "资金流分解"]


def _contains_high_frequency_marker(value: Any, markers: List[str]) -> bool:
    text = str(value)
    return any(marker in text for marker in markers)


def _is_qiam_pending_marker_for_repair(value: Any) -> bool:
    text = str(value)
    return "QIAM 输入尚未完成" in text


def _as_repair_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _repair_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _repair_int(value: Any) -> int:
    number = _repair_number(value)
    return int(number) if number is not None else 0


def sync_qiam_probability_from_agent_module(run: Dict[str, Any]) -> bool:
    qiam = run.get("qiam")
    if not isinstance(qiam, dict):
        return False

    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get("quant_engine") or module_results.get("qiam")
    if not isinstance(module_result, dict):
        return False
    module_data = module_result.get("data") if isinstance(module_result.get("data"), dict) else {}
    if not module_data:
        return False

    module_bands = _qiam_probability_bands(module_data)
    current_bands = _qiam_probability_bands(qiam)
    if module_bands is None or current_bands is None:
        return False

    llm_output = qiam.get("llmOutput") if isinstance(qiam.get("llmOutput"), dict) else {}
    llm_bands_unknown = all(
        str(llm_output.get(key) or llm_output.get(camel_key) or "").upper() == "UNKNOWN"
        for key, camel_key in (
            ("probability_band_up", "probabilityBandUp"),
            ("probability_band_sideways", "probabilityBandSideways"),
            ("probability_band_down", "probabilityBandDown"),
        )
    )
    if not llm_bands_unknown and not (_is_flat_qiam_probability(current_bands) and not _is_flat_qiam_probability(module_bands)):
        return False

    qiam["probabilityBandUp"] = module_bands[0]
    qiam["probabilityBandSideways"] = module_bands[1]
    qiam["probabilityBandDown"] = module_bands[2]
    if module_data.get("probabilitySource"):
        qiam["probabilitySource"] = module_data["probabilitySource"]
    qiam["probabilityRepairSource"] = "agentModuleResults.quant_engine.data"
    return True


_QIAM_SCORE_REPAIR_FIELDS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("expectedPayoffQuality", ("expected_payoff_quality", "expectedPayoffQuality")),
    ("regimeFit", ("regime_fit", "regimeFit")),
    ("momentumQuality", ("momentum_quality", "momentumQuality")),
    ("volatilityCondition", ("volatility_condition", "volatilityCondition")),
    ("liquidityAdjustedSignal", ("liquidity_adjusted_signal", "liquidityAdjustedSignal")),
    ("modelConfidenceRaw", ("model_confidence_raw", "modelConfidenceRaw")),
    ("modelConfidenceFinal", ("model_confidence_final", "modelConfidenceFinal")),
    ("overfitRisk", ("overfit_risk", "overfitRisk")),
    ("distributionDrift", ("distribution_drift", "distributionDrift")),
    ("decisionEffect", ("decision_effect", "decisionEffect")),
)


def sync_qiam_score_fields_from_agent_module(run: Dict[str, Any]) -> bool:
    qiam = run.get("qiam")
    if not isinstance(qiam, dict):
        return False

    module_results = run.get("agentModuleResults") if isinstance(run.get("agentModuleResults"), dict) else {}
    module_result = module_results.get("quant_engine") or module_results.get("qiam")
    if not isinstance(module_result, dict):
        return False
    module_data = module_result.get("data") if isinstance(module_result.get("data"), dict) else {}
    if not module_data:
        return False

    llm_output = qiam.get("llmOutput") if isinstance(qiam.get("llmOutput"), dict) else {}
    changed = False
    for field, llm_keys in _QIAM_SCORE_REPAIR_FIELDS:
        module_value = module_data.get(field)
        if not _qiam_score_has_value(module_value):
            continue
        current_value = qiam.get(field)
        if not _qiam_score_is_empty(current_value):
            continue
        if llm_output and not _qiam_llm_score_unknown(llm_output, llm_keys):
            continue
        qiam[field] = module_value
        changed = True

    if changed:
        qiam["scoreRepairSource"] = "agentModuleResults.quant_engine.data"
    return changed


def _qiam_score_has_value(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0


def _qiam_score_is_empty(value: Any) -> bool:
    if value is None:
        return True
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) == 0


def _qiam_llm_score_unknown(llm_output: Dict[str, Any], keys: tuple[str, str]) -> bool:
    return any(str(llm_output.get(key) or "").upper() == "UNKNOWN" for key in keys)


def _qiam_probability_bands(source: Dict[str, Any]) -> tuple[float, float, float] | None:
    values = (
        source.get("probabilityBandUp"),
        source.get("probabilityBandSideways"),
        source.get("probabilityBandDown"),
    )
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return None
    return (float(values[0]), float(values[1]), float(values[2]))


def _is_flat_qiam_probability(bands: tuple[float, float, float]) -> bool:
    return max(bands) - min(bands) <= 0.005


def stream_events_for_run(run: Optional[Dict[str, Any]], run_id: str) -> List[Dict[str, Any]]:
    if not run:
        return [
            _stream_event("RUN_STARTED", run_id, "Analysis run started."),
            _stream_event("NODE_STARTED", run_id, "Router agent started.", "router"),
            _stream_event("NODE_FINISHED", run_id, "Router agent finished.", "router"),
            _stream_event("RUN_FINISHED", run_id, "Analysis run finished."),
        ]

    events = [_stream_event("RUN_STARTED", run_id, "Analysis run started.")]
    for node in run.get("nodes", []):
        if node.get("isSkipped"):
            events.append(
                _stream_event(
                    "NODE_SKIPPED",
                    run_id,
                    f"{node.get('name', node.get('id'))} skipped by run mode or kill switch.",
                    node.get("id"),
                    {"status": node.get("status")},
                    node.get("auditId"),
                )
            )
            continue
        events.append(
            _stream_event(
                "NODE_STARTED",
                run_id,
                f"{node.get('name', node.get('id'))} started.",
                node.get("id"),
                {"prompt_ref": node.get("rawJson", {}).get("systemPromptRef")},
                node.get("auditId"),
            )
        )
        events.append(
            _stream_event(
                "NODE_FINISHED",
                run_id,
                f"{node.get('name', node.get('id'))} finished with {node.get('status')}.",
                node.get("id"),
                {"status": node.get("status"), "output_summary": node.get("outputSummary")},
                node.get("auditId"),
            )
        )

    kill_switch = run.get("killSwitch", {})
    if kill_switch.get("active"):
        events.append(
            _stream_event(
                "KILL_SWITCH_TRIGGERED",
                run_id,
                f"Kill switch triggered by {kill_switch.get('triggerNode')}.",
                kill_switch.get("triggerNode") or "orchestrator",
                kill_switch,
                kill_switch.get("auditId"),
            )
        )

    events.append(_stream_event("RUN_FINISHED", run_id, "Analysis run finished."))
    return events


def _normalize_kill_switch(run: Dict[str, Any]) -> Dict[str, Any]:
    existing = copy.deepcopy(run.get("killSwitch") or {})
    inferred = _infer_kill_switch(run)

    if existing.get("active") or inferred.get("active"):
        severity = {"NONE": 0, "SOFT": 1, "HARD": 2, "COMPLIANCE": 3}
        existing_level = existing.get("level", "NONE")
        inferred_level = inferred.get("level", "NONE")
        primary = inferred if severity.get(inferred_level, 0) > severity.get(existing_level, 0) else existing
        secondary = existing if primary is inferred else inferred
        merged = {
            "active": True,
            "level": primary.get("level") or secondary.get("level", "HARD"),
            "triggerNode": _canonical_dag_anchor(
                str(primary.get("triggerNode") or secondary.get("triggerNode", "orchestrator"))
            ),
            "triggerRule": primary.get("triggerRule") or secondary.get("triggerRule", "risk_hard_reject"),
            "blockedPaths": primary.get("blockedPaths") or secondary.get("blockedPaths", []),
            "allowedPaths": primary.get("allowedPaths") or secondary.get("allowedPaths", []),
            "finalWriterMode": primary.get("finalWriterMode")
            or secondary.get("finalWriterMode", "HARD_RISK_FINAL_ONLY"),
            "auditId": primary.get("auditId") or secondary.get("auditId", "AUD_KILL_SWITCH"),
        }
        return merged

    return {
        "active": False,
        "level": existing.get("level", "NONE"),
        "triggerNode": existing.get("triggerNode", ""),
        "triggerRule": existing.get("triggerRule", ""),
        "blockedPaths": existing.get("blockedPaths", []),
        "allowedPaths": existing.get(
            "allowedPaths",
            ["WAIT", "REVIEW_ONLY", "HOLD", "LIGHT_WATCH", "BUY_CANDIDATE", "ADD_CANDIDATE"],
        ),
        "finalWriterMode": existing.get("finalWriterMode", "NORMAL"),
        "auditId": existing.get("auditId", "AUD_KS_NONE"),
    }


def _infer_kill_switch(run: Dict[str, Any]) -> Dict[str, Any]:
    guardrail_hub = run.get("guardrailHub") if isinstance(run.get("guardrailHub"), dict) else {}
    guardrail_kill_switch = guardrail_hub.get("killSwitch") if isinstance(guardrail_hub.get("killSwitch"), dict) else {}
    if guardrail_kill_switch.get("active"):
        return copy.deepcopy(guardrail_kill_switch)

    risk = run.get("risk", {})
    if risk.get("complianceRedLines"):
        return _kill_switch("guardrail_hub", "compliance_violation", "AUD_KS_COMPLIANCE")

    hard_risk_keys = [
        "f0IndividualHardRisks",
        "f1ExtremeChipCollapse",
        "f4ThreePartyFundResonanceOutflow",
        "l0AbsoluteLiquidityRedLine",
        "m0SystemicRisk",
        "portfolioRiskOverLimit",
        "executionUnreachable",
    ]
    if any(risk.get(key) for key in hard_risk_keys):
        return _kill_switch("guardrail_hub", "risk_hard_reject", "AUD_KS_RISK")

    dvg = run.get("dvg", {})
    if dvg.get("hardStop") or dvg.get("status") == "BLOCK_BUY" or dvg.get("finalDecisionCap") == "BLOCK_BUY":
        return _kill_switch("guardrail_hub", "dvg_block_buy", "AUD_KS_DVG")

    atrade = run.get("atrade", {})
    if atrade.get("executionReachability") == "NOT_REACHABLE" or atrade.get("flashCrashVacuumStatus"):
        return _kill_switch("guardrail_hub", "atrade_not_reachable", "AUD_KS_ATRADE")

    qiam = run.get("qiam", {})
    if qiam.get("finalBuySuitability") == "BLOCK_BUY":
        return _kill_switch("quant_core", "qiam_block_buy", "AUD_KS_QIAM")

    return {"active": False}


def _kill_switch(trigger_node: str, rule_id: str, audit_id: str) -> Dict[str, Any]:
    rule = KILL_SWITCH_RULES[rule_id]
    return {
        "active": True,
        "level": rule["level"],
        "triggerNode": trigger_node,
        "triggerRule": rule_id,
        "blockedPaths": rule["blocked_paths"],
        "allowedPaths": rule["allowed_paths"],
        "finalWriterMode": rule["final_writer_mode"],
        "auditId": audit_id,
    }


def _build_agent_nodes(
    run: Dict[str, Any],
    run_mode: str,
    runtime_summary: Dict[str, Any],
    kill_switch: Dict[str, Any],
) -> List[Dict[str, Any]]:
    enabled_by_runtime = {
        agent["id"]: agent.get("enabled", True)
        for agent in runtime_summary.get("agents", [])
    }
    mode_order = RUN_MODE_NODES[run_mode]
    active_order = [agent_id for agent_id in mode_order if enabled_by_runtime.get(agent_id, True)]

    stop_index = None
    if kill_switch.get("active") and kill_switch.get("level") in {"HARD", "COMPLIANCE"}:
        trigger_node = _canonical_dag_anchor(str(kill_switch.get("triggerNode") or ""))
        if trigger_node in active_order:
            stop_index = active_order.index(trigger_node)

    executed_ids = set(active_order)
    if stop_index is not None:
        executed_ids = set(active_order[: stop_index + 1])
        executed_ids.add("final_writer")

    nodes = []
    for agent in AGENT_MANIFEST:
        agent_id = agent["id"]
        is_mode_skipped = agent_id not in active_order
        is_runtime_skipped = not enabled_by_runtime.get(agent_id, True)
        is_kill_skipped = agent_id in active_order and agent_id not in executed_ids
        is_skipped = is_mode_skipped or is_runtime_skipped or is_kill_skipped
        status = "SKIPPED" if is_skipped else _status_for_agent(agent_id, run, kill_switch)
        next_node = _next_active_node(agent_id, active_order, executed_ids, kill_switch)
        missing_data = _missing_data(agent_id, run)
        downgrade_reasons = _downgrade_reasons(agent_id, run, is_skipped, kill_switch)
        evidence_strength = _agent_node_evidence_strength(
            status=status,
            is_skipped=is_skipped,
            is_blocked=status in {"BLOCK_BUY", "FAIL"} or is_kill_skipped,
            missing_data=missing_data,
            downgrade_reasons=downgrade_reasons,
        )
        raw_json = {
            "frameworkName": FRAMEWORK_NAME,
            "frameworkVersion": FRAMEWORK_VERSION,
            "systemPromptRef": agent["system_prompt_ref"],
            "promptFile": agent["prompt_file"],
            "promptHash": _prompt_hash(agent_id),
            "nodeType": agent["node_type"],
            "runModes": agent["run_modes"],
            "toolScope": agent["tool_scope"],
            "allowTradeAction": False,
            "finalDecisionCap": "NO_DIRECT_TRADE_ACTION",
            "evidenceUsage": "simulation_only",
            "evidenceStrength": evidence_strength,
            "simulationOnly": True,
            "isRealTrade": False,
            "strongConclusionAllowed": False,
        }

        nodes.append(
            {
                "id": agent_id,
                "name": agent["name"],
                "status": status,
                "isRunning": False,
                "isSkipped": is_skipped,
                "isBlocked": status in {"BLOCK_BUY", "FAIL"} or is_kill_skipped,
                "duration": 0 if is_skipped else _duration_for_agent(agent_id),
                "auditId": f"AUD_{agent_id.upper()}",
                "inputSummary": _input_summary(agent_id, run_mode, is_skipped, kill_switch),
                "outputSummary": _output_summary(agent_id, run, status),
                "missingData": missing_data,
                "downgradeReasons": downgrade_reasons,
                "blockedPaths": kill_switch.get("blockedPaths", []) if agent_id == kill_switch.get("triggerNode") else [],
                "allowedNextActions": [next_node] if next_node else [],
                "evidenceUsage": "simulation_only",
                "evidenceStrength": evidence_strength,
                "simulationOnly": True,
                "isRealTrade": False,
                "strongConclusionAllowed": False,
                "rawJson": raw_json,
            }
        )

    return _insert_plugin_runtime_nodes(nodes, runtime_summary)


def _insert_plugin_runtime_nodes(nodes: List[Dict[str, Any]], runtime_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    plugin_nodes = _build_plugin_runtime_nodes(runtime_summary)
    if not plugin_nodes:
        return nodes

    integrated = list(nodes)
    for plugin_node in plugin_nodes:
        registration = plugin_node.get("rawJson", {}).get("dagRegistration", {})
        insertion_after = _canonical_dag_anchor(str(registration.get("insertion_after") or "market_technical_analyst"))
        anchor_index = next((idx for idx, node in enumerate(integrated) if node.get("id") == insertion_after), None)
        if anchor_index is None:
            integrated.append(plugin_node)
            continue

        anchor = integrated[anchor_index]
        previous_next = list(anchor.get("allowedNextActions") or [])
        anchor["allowedNextActions"] = [plugin_node["id"]]
        plugin_node["allowedNextActions"] = previous_next
        plugin_node["inputSummary"] = (
            f"Read-only plugin observation inserted after {insertion_after}; "
            "uses current DAG context and cannot execute code or emit trade actions."
        )
        integrated.insert(anchor_index + 1, plugin_node)
    return integrated


def _canonical_dag_anchor(node_id: str) -> str:
    if node_id in {"data_fetch", "data_engine", "chip_kb", "memory_agent"}:
        return "data_reliability_engine"
    if node_id in {
        "hallucination_guardrail",
        "dvg_evidence_gate",
        "dvg_gate",
        "risk_firewall",
        "atrade",
        "trade_micro",
        "flash_crash",
        "portfolio",
    }:
        return "guardrail_hub"
    if node_id in {
        "market_regime",
        "technical_kline_analyst",
        "market_technical_analyst",
        "bottom_research",
        "factor_slicing",
        "factor_engine",
        "calculation_authority",
        "qiam",
        "quant_engine",
        "scenario_engine",
        "simulation_agent",
    }:
        return "quant_core"
    return node_id


def _build_plugin_runtime_nodes(runtime_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    plan = runtime_summary.get("pluginRuntimePlan") or {}
    plugin_agents = plan.get("agents") if isinstance(plan, dict) else []
    if not isinstance(plugin_agents, list):
        return []

    nodes: List[Dict[str, Any]] = []
    for agent in plugin_agents:
        if not isinstance(agent, dict) or not agent.get("eligible"):
            continue
        dag_node_id = str(agent.get("dag_node_id") or f"plugin:{agent.get('plugin_id')}:{agent.get('agent_id')}")
        audit_id = f"AUD_{dag_node_id.replace(':', '_').upper()}"
        registration = agent.get("dag_registration") if isinstance(agent.get("dag_registration"), dict) else {}
        nodes.append(
            {
                "id": dag_node_id,
                "name": str(agent.get("agent_name") or agent.get("agent_id") or dag_node_id),
                "status": "REVIEW_ONLY",
                "isRunning": False,
                "isSkipped": False,
                "isBlocked": False,
                "duration": 0,
                "auditId": audit_id,
                "inputSummary": "Plugin observation node registered from runtime manifest; no code execution.",
                "outputSummary": "Read-only plugin output is limited to review notes or DAG observations.",
                "missingData": [],
                "downgradeReasons": [],
                "blockedPaths": [],
                "allowedNextActions": [],
                "evidenceUsage": "simulation_only",
                "evidenceStrength": "LOW",
                "simulationOnly": True,
                "isRealTrade": False,
                "strongConclusionAllowed": False,
                "rawJson": {
                    "frameworkName": FRAMEWORK_NAME,
                    "frameworkVersion": FRAMEWORK_VERSION,
                    "nodeType": registration.get("node_type", "plugin_observation"),
                    "pluginId": agent.get("plugin_id"),
                    "pluginAgentId": agent.get("agent_id"),
                    "dagRegistration": registration,
                    "inputSchema": agent.get("input_schema") or {},
                    "outputSchema": agent.get("output_schema") or {},
                    "permissions": agent.get("permissions") or [],
                    "permissionSandbox": agent.get("permission_sandbox") or {},
                    "riskGate": agent.get("risk_gate") or {},
                    "allowTradeAction": False,
                    "finalDecisionCap": "NO_DIRECT_TRADE_ACTION",
                    "canExecuteCode": False,
                    "directExecution": False,
                    "evidenceUsage": "simulation_only",
                    "evidenceStrength": "LOW",
                    "simulationOnly": True,
                    "isRealTrade": False,
                    "strongConclusionAllowed": False,
                },
            }
        )
    return nodes


def _agent_node_evidence_strength(
    *,
    status: str,
    is_skipped: bool,
    is_blocked: bool,
    missing_data: List[str],
    downgrade_reasons: List[str],
) -> str:
    normalized_status = str(status or "").upper()
    if (
        is_skipped
        or is_blocked
        or normalized_status in {"WAIT", "WARN", "REVIEW_ONLY", "SKIPPED", "BLOCK", "BLOCK_BUY", "FAIL", "ERROR"}
        or bool(missing_data)
        or bool(downgrade_reasons)
    ):
        return "LOW"
    return "MEDIUM"


def _next_active_node(
    agent_id: str,
    active_order: List[str],
    executed_ids: set[str],
    kill_switch: Dict[str, Any],
) -> Optional[str]:
    if agent_id not in active_order or agent_id not in executed_ids:
        return None

    if (
        kill_switch.get("active")
        and kill_switch.get("level") in {"HARD", "COMPLIANCE"}
        and agent_id == kill_switch.get("triggerNode")
        and agent_id != "final_writer"
    ):
        return "final_writer"

    current_index = active_order.index(agent_id)
    for next_id in active_order[current_index + 1 :]:
        if next_id in executed_ids:
            return next_id
    return None


def _status_for_agent(agent_id: str, run: Dict[str, Any], kill_switch: Dict[str, Any]) -> str:
    if agent_id == "guardrail_hub":
        guardrail = run.get("guardrailHub", {}) if isinstance(run.get("guardrailHub"), dict) else {}
        if kill_switch.get("triggerNode") == "guardrail_hub":
            return "BLOCK_BUY" if kill_switch.get("level") != "COMPLIANCE" else "FAIL"
        return _frontend_status(str(guardrail.get("status") or "WARN"))
    if agent_id == "dvg_gate":
        return _frontend_status(run.get("dvg", {}).get("status", "WARN"))
    if agent_id == "risk_firewall":
        return "BLOCK_BUY" if kill_switch.get("triggerNode") == "risk_firewall" else _risk_status(run)
    if agent_id == "trade_micro":
        atrade = run.get("atrade", {})
        portfolio = run.get("portfolio", {})
        if atrade.get("executionReachability") == "NOT_REACHABLE":
            return "BLOCK_BUY"
        if portfolio.get("restrictionReasons") or not portfolio.get("allowAddPosition", False):
            return "WARN"
        return "WARN" if atrade.get("liquidityRisk") == "HIGH" or not atrade.get("level2Available") else "PASS"
    if agent_id == "quant_core":
        core = run.get("quantCore", {}) if isinstance(run.get("quantCore"), dict) else {}
        status = core.get("status")
        if status in {"PASS", "WARN", "SKIPPED", "REVIEW_ONLY"}:
            return status
        qiam = run.get("qiam", {}) if isinstance(run.get("qiam"), dict) else {}
        if qiam.get("finalBuySuitability") == "BLOCK_BUY":
            return "REVIEW_ONLY"
        if qiam.get("finalBuySuitability") == "REVIEW_ONLY":
            return "REVIEW_ONLY"
        return "WARN"
    if agent_id == "market_technical_analyst":
        fused = run.get("marketTechnical", {}) if isinstance(run.get("marketTechnical"), dict) else {}
        status = fused.get("status")
        if status in {"PASS", "WARN", "SKIPPED"}:
            return status
        technical = run.get("technicalKline", {})
        technical_status = technical.get("status") if isinstance(technical, dict) else None
        if technical_status == "SKIPPED":
            return "WARN"
        return "WARN"
    if agent_id == "technical_kline_analyst":
        technical = run.get("technicalKline", {})
        status = technical.get("status")
        if status in {"PASS", "WARN", "SKIPPED"}:
            return status
        if technical.get("technicalBias") == "INSUFFICIENT_DATA":
            return "SKIPPED"
        return "WARN"
    if agent_id == "bottom_research":
        bottom = _mfe_mae_research_payload(run)
        status = bottom.get("status") if isinstance(bottom, dict) else None
        if status in {"PASS", "WARN", "SKIPPED"}:
            return status
        diagnostics = bottom.get("modelDiagnostics", {}) if isinstance(bottom, dict) else {}
        if diagnostics.get("status") == "SUPPORTING_ONLY":
            return "WARN"
        return "WARN"
    if agent_id == "quant_engine":
        factor = run.get("factorSlicing", {})
        qiam = run.get("qiam", {})
        suitability = qiam.get("finalBuySuitability")
        if suitability == "BLOCK_BUY":
            return "BLOCK_BUY"
        if suitability == "REVIEW_ONLY":
            return "REVIEW_ONLY"
        if factor.get("missingFactorData"):
            return "WARN"
        if suitability == "NEUTRAL":
            return "WARN"
        return "PASS" if suitability == "FAVORABLE" else "WARN"
    if agent_id == "execution":
        execution = run.get("execution", {})
        if execution.get("executionReachability") == "NOT_REACHABLE":
            return "BLOCK_BUY"
        if execution.get("executionReachability") == "CONDITIONALLY_REACHABLE":
            return "WARN"
        return "PASS"
    if agent_id == "anti_conclusion":
        return "REVIEW_ONLY" if kill_switch.get("active") else "PASS"
    if agent_id == "signalops":
        blocked_reason = run.get("signalOps", {}).get("blockedReason")
        signal_status = run.get("signalOps", {}).get("signalStatus")
        if signal_status == "PAPER_TEST" and blocked_reason:
            return "WARN"
        return "REVIEW_ONLY" if blocked_reason else "PASS"
    if agent_id == "final_writer":
        if kill_switch.get("finalWriterMode") in {"HARD_RISK_FINAL_ONLY", "COMPLIANCE_REFUSAL"}:
            return "REVIEW_ONLY"
        return "PASS"
    return "PASS"


def _frontend_status(status: str) -> str:
    return {
        "BLOCK": "BLOCK_BUY",
        "BLOCKED": "BLOCK_BUY",
        "FAILED": "FAIL",
        "UNKNOWN": "WARN",
    }.get(status, status if status in {"PASS", "WARN", "REVIEW_ONLY", "BLOCK_BUY", "FAIL"} else "WARN")


def _risk_status(run: Dict[str, Any]) -> str:
    risk = run.get("risk", {})
    return "WARN" if any(value for value in risk.values() if isinstance(value, list)) else "PASS"


def _duration_for_agent(agent_id: str) -> int:
    order = [agent["id"] for agent in AGENT_MANIFEST]
    return 120 + (order.index(agent_id) * 35 if agent_id in order else 0)


def _input_summary(agent_id: str, run_mode: str, is_skipped: bool, kill_switch: Dict[str, Any]) -> str:
    if is_skipped:
        if kill_switch.get("active"):
            return "Skipped by run mode, runtime disablement, or kill-switch truncation."
        return f"Skipped because this agent is not enabled for {run_mode}."
    return f"Loaded v{FRAMEWORK_VERSION} prompt and {run_mode} workflow contract."


def _output_summary(agent_id: str, run: Dict[str, Any], status: str) -> str:
    if status == "SKIPPED":
        return "No output generated."
    if agent_id == "orchestrator":
        mode = run.get("killSwitch", {}).get("finalWriterMode", "NORMAL")
        return f"任务={run.get('taskType', 'UNKNOWN')}; 模式={run.get('runMode', 'STANDARD_MODE')}; final_writer_mode={mode}."
    if agent_id == "data_reliability_engine":
        market_data = run.get("marketData", {})
        return (
            f"行情={market_data.get('status', 'UNKNOWN')}; "
            f"来源={market_data.get('provider', 'not_configured')}."
        )
    if agent_id == "guardrail_hub":
        guardrail = run.get("guardrailHub", {}) if isinstance(run.get("guardrailHub"), dict) else {}
        dvg = guardrail.get("dvg") if isinstance(guardrail.get("dvg"), dict) else run.get("dvg", {})
        atrade = guardrail.get("atrade") if isinstance(guardrail.get("atrade"), dict) else run.get("atrade", {})
        kill_switch = guardrail.get("killSwitch") if isinstance(guardrail.get("killSwitch"), dict) else run.get("killSwitch", {})
        return (
            f"DVG={dvg.get('dataReliability')}; "
            f"可达性={atrade.get('executionReachability')}; "
            f"killSwitch={bool(kill_switch.get('active'))}."
        )
    if agent_id == "dvg_gate":
        dvg = run.get("dvg", {})
        return f"可靠性={dvg.get('dataReliability')}; 幻觉={dvg.get('hallucinationRiskLevel')}."
    if agent_id == "risk_firewall":
        return f"风险={status}; hard-stop={run.get('killSwitch', {}).get('active', False)}."
    if agent_id == "trade_micro":
        atrade = run.get("atrade", {})
        portfolio = run.get("portfolio", {})
        return f"可达性={atrade.get('executionReachability')}; 仓位={portfolio.get('singleStockPosition', 0)}; 可加仓={portfolio.get('allowAddPosition', False)}."
    if agent_id == "quant_core":
        market = run.get("market", {})
        technical = run.get("technicalKline", {})
        bottom = _mfe_mae_research_payload(run)
        qiam = run.get("qiam", {}) if isinstance(run.get("qiam"), dict) else {}
        core = run.get("quantCore", {}) if isinstance(run.get("quantCore"), dict) else {}
        interpretation = core.get("coreInterpretation") if isinstance(core.get("coreInterpretation"), dict) else {}
        scenario = _module_result_data(run, "scenario_engine")
        return (
            f"market={market.get('marketSentiment')}; "
            f"technical={technical.get('technicalBias')}; "
            f"mfeMae={bottom.get('riskPolicy') or bottom.get('regimeState', 'UNKNOWN')}; "
            f"QIAM final={qiam.get('finalBuySuitability')}; "
            f"coreScore={interpretation.get('overallScore', 'UNKNOWN')}; "
            f"scenario={scenario.get('status', 'UNKNOWN')}."
        )
    if agent_id == "market_regime":
        market = run.get("market", {})
        return f"情绪={market.get('marketSentiment')}; 流动性={market.get('liquidityIndex')}."
    if agent_id == "market_technical_analyst":
        market = run.get("market", {})
        technical = run.get("technicalKline", {})
        fused = run.get("marketTechnical", {}) if isinstance(run.get("marketTechnical"), dict) else {}
        return (
            f"market={market.get('marketSentiment')}; "
            f"technical={technical.get('technicalBias')}; "
            f"alignment={fused.get('alignment', 'UNKNOWN')}."
        )
    if agent_id == "quant_engine":
        factor = run.get("factorSlicing", {})
        qiam = run.get("qiam", {})
        quant_engine = run.get("quantEngine", {})
        return f"模式={quant_engine.get('mode', 'UNKNOWN')}; 因子={factor.get('mode')}; QIAM raw={qiam.get('rawBuySuitability')}→final={qiam.get('finalBuySuitability')}; discount={qiam.get('discountFactor')}."
    if agent_id == "bottom_research":
        bottom = _mfe_mae_research_payload(run)
        if not isinstance(bottom, dict) or not bottom:
            return "MFE/MAE Path Research pending; research-only probability evidence has not been produced."
        return (
            f"riskPolicy={bottom.get('riskPolicy', 'UNKNOWN')}; "
            f"mfe={bottom.get('mfeFavorableProbability', bottom.get('bottomRepairProbability'))}; "
            f"mae={bottom.get('maeBreachProbability', bottom.get('breakdownRiskProbability'))}; "
            "research-only, no trade permission."
        )
    if agent_id == "scenario_engine":
        return "情景分支已构建，受限于DVG和风险门禁。"
    if agent_id == "execution":
        execution = run.get("execution", {})
        return f"允许={execution.get('allowedActions', [])}; 禁止={execution.get('forbiddenActions', [])}."
    if agent_id == "anti_conclusion":
        return "反结论审查完成，确认输出无后门推理。"
    if agent_id == "signalops":
        signalops = run.get("signalOps", {})
        return f"SignalOps={signalops.get('signalStatus', 'UNKNOWN')}; auto-paper sandbox enabled for SIM_* only."
    if agent_id == "final_writer":
        return f"最终动作={run.get('finalAction', 'WAIT')}; 需人工确认。"
    return status


def _missing_data(agent_id: str, run: Dict[str, Any]) -> List[str]:
    if agent_id == "data_reliability_engine":
        market_data = run.get("marketData", {})
        status = market_data.get("status")
        if status and status != "READY":
            return [f"market_data_api:{status}"]
        return []
    if agent_id == "dvg_gate":
        return list(run.get("dvg", {}).get("criticalMissingData", []))
    if agent_id == "guardrail_hub":
        guardrail = run.get("guardrailHub", {}) if isinstance(run.get("guardrailHub"), dict) else {}
        dvg = guardrail.get("dvg") if isinstance(guardrail.get("dvg"), dict) else run.get("dvg", {})
        atrade = guardrail.get("atrade") if isinstance(guardrail.get("atrade"), dict) else run.get("atrade", {})
        missing = list(dvg.get("criticalMissingData", []) or [])
        if atrade.get("level2Available") is False:
            missing.append("Level-2 逐笔成交")
        if atrade.get("depthAvailable") is False:
            missing.append("盘口深度")
        return _unique(missing)
    if agent_id == "quant_core":
        core = run.get("quantCore", {}) if isinstance(run.get("quantCore"), dict) else {}
        if isinstance(core.get("missingData"), list):
            return list(core.get("missingData") or [])
        return _unique(
            list(run.get("factorSlicing", {}).get("missingFactorData", []))
            + list(run.get("qiam", {}).get("missingData", []))
            + list(_mfe_mae_research_payload(run).get("missingData", []))
        )
    if agent_id == "market_technical_analyst":
        technical = run.get("technicalKline", {}) if isinstance(run.get("technicalKline"), dict) else {}
        quality = technical.get("dataQuality") if isinstance(technical.get("dataQuality"), dict) else {}
        return list(quality.get("issues") or [])
    if agent_id == "quant_engine":
        return list(run.get("factorSlicing", {}).get("missingFactorData", []))
    if agent_id == "bottom_research":
        bottom = _mfe_mae_research_payload(run)
        return list(bottom.get("missingData", [])) if isinstance(bottom, dict) else []
    return []


def _downgrade_reasons(
    agent_id: str,
    run: Dict[str, Any],
    is_skipped: bool,
    kill_switch: Dict[str, Any],
) -> List[str]:
    if is_skipped and kill_switch.get("active"):
        return [f"Kill switch {kill_switch.get('level')} routed remaining path to Final Writer."]
    if agent_id == "quant_core":
        core = run.get("quantCore", {}) if isinstance(run.get("quantCore"), dict) else {}
        warnings = core.get("warnings") if isinstance(core.get("warnings"), list) else []
        qiam_downgrades = run.get("qiam", {}).get("downgradeReasons", [])
        bottom_warnings = _mfe_mae_research_payload(run).get("warnings", [])
        return _unique(list(warnings) + list(qiam_downgrades or []) + list(bottom_warnings or []))
    if agent_id == "quant_engine":
        return list(run.get("qiam", {}).get("downgradeReasons", []))
    if agent_id == "market_technical_analyst":
        fused = run.get("marketTechnical", {}) if isinstance(run.get("marketTechnical"), dict) else {}
        return list(fused.get("warnings", []))
    if agent_id == "bottom_research":
        bottom = _mfe_mae_research_payload(run)
        return list(bottom.get("warnings", [])) if isinstance(bottom, dict) else []
    return []


def _build_audit_log(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    run_id = run.get("runId", "RUN_UNKNOWN")
    audit_log = [
        {
            "timestamp": run.get("createdAt", ""),
            "runId": run_id,
            "node": "system",
            "eventType": "RUN_CREATED",
            "message": f"{FRAMEWORK_NAME} run created.",
            "statusBefore": "WAIT",
            "statusAfter": "PASS",
            "inputHash": "framework-input",
            "outputHash": "framework-output",
            "auditId": "AUD_RUN_CREATED",
        }
    ]

    for node in run.get("nodes", []):
        audit_log.append(
            {
                "timestamp": run.get("updatedAt", ""),
                "runId": run_id,
                "node": node["id"],
                "eventType": "NODE_SKIPPED" if node["isSkipped"] else "NODE_FINISHED",
                "message": node.get("outputSummary") or node["name"],
                "statusBefore": "WAIT",
                "statusAfter": node["status"],
                "inputHash": f"hash-input-{node['id']}",
                "outputHash": f"hash-output-{node['id']}",
                "auditId": node["auditId"],
            }
        )

    kill_switch = run.get("killSwitch", {})
    if kill_switch.get("active"):
        audit_log.append(
            {
                "timestamp": run.get("updatedAt", ""),
                "runId": run_id,
                "node": kill_switch.get("triggerNode", "orchestrator"),
                "eventType": "KILL_SWITCH_TRIGGERED",
                "message": f"Kill switch {kill_switch.get('level')} triggered by {kill_switch.get('triggerRule')}.",
                "statusBefore": "WAIT",
                "statusAfter": "BLOCK_BUY" if kill_switch.get("level") != "COMPLIANCE" else "FAIL",
                "inputHash": "hash-input-kill-switch",
                "outputHash": "hash-output-kill-switch",
                "auditId": kill_switch.get("auditId", "AUD_KILL_SWITCH"),
            }
        )

    return audit_log


def _build_standard_agent_results(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    kill_switch = run.get("killSwitch", {})
    execution = run.get("execution", {})

    for node in run.get("nodes", []):
        agent_id = node.get("id", "")
        module_result = (run.get("agentModuleResults") or {}).get(agent_id, {})
        if not isinstance(module_result, dict):
            module_result = {}
        is_trigger = agent_id == kill_switch.get("triggerNode")
        status = _standard_agent_status(node.get("status", "WARN"))
        skipped_reason = _skip_reason(node) if status == "SKIPPED" else ""

        allowed_actions = list(module_result.get("allowed_actions") or [])
        blocked_actions = list(module_result.get("blocked_actions") or node.get("blockedPaths") or [])
        if is_trigger:
            allowed_actions = allowed_actions or list(kill_switch.get("allowedPaths", []))
            blocked_actions = _unique(blocked_actions + list(kill_switch.get("blockedPaths", [])))
        elif agent_id in {"execution", "final_writer", "signalops"}:
            allowed_actions = allowed_actions or list(execution.get("allowedActions", []))
            blocked_actions = _unique(blocked_actions + list(execution.get("forbiddenActions", [])))
        elif not allowed_actions:
            allowed_actions = list(node.get("allowedNextActions") or [])

        rule_repaired = _is_rule_repaired_module_result(module_result)
        node_downgrades = [] if rule_repaired else list(node.get("downgradeReasons") or [])
        node_output_summary = "" if rule_repaired else _clean_debate_text(node.get("outputSummary", ""))
        reasons = _unique(
            list(module_result.get("reasons") or [])
            + node_downgrades
            + ([skipped_reason] if skipped_reason else [])
            + ([node_output_summary] if node_output_summary else [])
        )
        warnings = _unique(list(module_result.get("warnings") or []) + ([] if rule_repaired else _warnings_for_node(node, run)))
        data = module_result.get("data") if isinstance(module_result.get("data"), dict) else {}
        output_summary = _output_summary(agent_id, run, status) if rule_repaired else node.get("outputSummary", "")
        raw_json = {} if rule_repaired else node.get("rawJson", {})
        missing_data = (
            list(module_result.get("missing_data") or [])
            if "missing_data" in module_result
            else list(node.get("missingData") or [])
        )
        data = {
            **data,
            "input_summary": node.get("inputSummary", ""),
            "output_summary": output_summary,
            "raw": raw_json,
        }

        result = {
            "node": agent_id,
            "name": node.get("name", agent_id),
            "status": status,
            "allowed_actions": allowed_actions,
            "blocked_actions": blocked_actions,
            "hard_stop": bool(module_result.get("hard_stop")) or bool(is_trigger and kill_switch.get("active")) or status in {"BLOCK", "ERROR"},
            "final_decision_cap": module_result.get("final_decision_cap") or _final_decision_cap(run),
            "confidence": module_result.get("confidence") or _confidence_for_status(status),
            "reasons": reasons,
            "missing_data": missing_data,
            "warnings": warnings,
            "data": data,
            "audit_id": module_result.get("audit_id") or node.get("auditId", f"AUD_{agent_id.upper()}"),
            "elapsed_ms": int(module_result.get("elapsed_ms") or node.get("duration") or 0),
            "skipped_reason": skipped_reason,
        }
        if module_result.get("legacyCompatibilityOnly") is True:
            result["legacyCompatibilityOnly"] = True
            result["canonicalNode"] = module_result.get("canonicalNode")
            result["activeNode"] = bool(module_result.get("activeNode", False))
        results.append(result)

    return results


def _is_rule_repaired_module_result(module_result: Dict[str, Any]) -> bool:
    data = module_result.get("data") if isinstance(module_result.get("data"), dict) else {}
    return data.get("ruleRepairSource") == "agent_framework.current_inputs"


def _build_skipped_nodes(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "node": node.get("id", ""),
            "name": node.get("name", node.get("id", "")),
            "reason": _skip_reason(node),
            "audit_id": node.get("auditId", ""),
        }
        for node in run.get("nodes", [])
        if node.get("isSkipped")
    ]


def _build_dag_events(run: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = [
        {
            "event_type": "RUN_CREATED",
            "run_id": run.get("runId", ""),
            "node": "system",
            "status": "PASS",
            "message": f"{FRAMEWORK_NAME} run created.",
            "elapsed_ms": 0,
            "audit_id": "AUD_RUN_CREATED",
            "timestamp": run.get("createdAt", ""),
        }
    ]

    for index, node in enumerate(run.get("nodes", []), start=1):
        events.append(
            {
                "event_type": "NODE_SKIPPED" if node.get("isSkipped") else "NODE_FINISHED",
                "run_id": run.get("runId", ""),
                "node": node.get("id", ""),
                "order": index,
                "status": _standard_agent_status(node.get("status", "WARN")),
                "message": _skip_reason(node) if node.get("isSkipped") else node.get("outputSummary", ""),
                "elapsed_ms": int(node.get("duration") or 0),
                "audit_id": node.get("auditId", ""),
                "timestamp": run.get("updatedAt", ""),
            }
        )

    kill_switch = run.get("killSwitch", {})
    if kill_switch.get("active"):
        events.append(
            {
                "event_type": "KILL_SWITCH_TRIGGERED",
                "run_id": run.get("runId", ""),
                "node": kill_switch.get("triggerNode", "orchestrator"),
                "status": "BLOCK",
                "message": f"Kill switch {kill_switch.get('level')} triggered by {kill_switch.get('triggerRule')}.",
                "elapsed_ms": 0,
                "audit_id": kill_switch.get("auditId", "AUD_KILL_SWITCH"),
                "timestamp": run.get("updatedAt", ""),
            }
        )

    return events


def _build_token_usage(run: Dict[str, Any]) -> Dict[str, Any]:
    trace_by_node = {
        item.get("nodeId"): item
        for item in run.get("llmTrace", [])
        if isinstance(item, dict)
    }
    rows = []

    for node in run.get("nodes", []):
        agent_id = node.get("id", "")
        trace = trace_by_node.get(agent_id, {})
        runner = node.get("rawJson", {}).get("llmRunner", {}) if isinstance(node.get("rawJson"), dict) else {}
        usage = trace.get("usage") or runner.get("usage") or {}
        prompt_tokens = _token_number(trace.get("promptTokens"), usage, ("prompt_tokens", "input_tokens", "promptTokens", "inputTokens"))
        completion_tokens = _token_number(trace.get("completionTokens"), usage, ("completion_tokens", "output_tokens", "completionTokens", "outputTokens"))
        total_tokens = _token_number(trace.get("totalTokens"), usage, ("total_tokens", "totalTokens"))
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        rows.append(
            {
                "node": agent_id,
                "name": node.get("name", agent_id),
                "status": trace.get("status") or runner.get("status") or ("SKIPPED" if node.get("isSkipped") else "NOT_RUN"),
                "provider": trace.get("provider") or runner.get("provider", ""),
                "model": trace.get("model") or runner.get("model", ""),
                "profile_id": trace.get("profileId") or runner.get("profileId", ""),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": int(trace.get("latencyMs") or runner.get("latencyMs") or node.get("duration") or 0),
                "finish_reason": runner.get("finishReason", ""),
                "error": trace.get("error") or runner.get("error", ""),
                "audit_id": node.get("auditId", f"AUD_{agent_id.upper()}"),
            }
        )

    totals = {
        "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
        "completion_tokens": sum(row["completion_tokens"] for row in rows),
        "total_tokens": sum(row["total_tokens"] for row in rows),
        "latency_ms": sum(row["latency_ms"] for row in rows),
    }
    top_agent = max(rows, key=lambda row: row["total_tokens"], default=None)
    return {
        "rows": rows,
        "totals": totals,
        "top_agent": top_agent,
        "metering_status": "LIVE_USAGE" if any(row["total_tokens"] for row in rows) else "NO_PROVIDER_USAGE",
        "note": "Token usage is reported from provider usage fields when available. Agents that have not run or providers that omit usage are shown as 0.",
    }


def _build_debate_artifacts(run: Dict[str, Any]) -> Dict[str, Any]:
    agent_results = run.get("agentResults", [])
    token_rows = {
        row.get("node"): row
        for row in run.get("tokenUsage", {}).get("rows", [])
        if isinstance(row, dict)
    }
    turns = []

    for index, result in enumerate(agent_results, start=1):
        if not isinstance(result, dict):
            continue
        node = result.get("node", "")
        token_row = token_rows.get(node, {})
        turns.append(
            {
                "order": index,
                "node": node,
                "name": result.get("name", node),
                "stance": _debate_stance(result),
                "claim": _debate_claim(result),
                "evidence": _debate_evidence(result),
                "counterpoints": _debate_counterpoints(result),
                "decision_impact": _debate_impact(result),
                "status": result.get("status", "WARN"),
                "confidence": result.get("confidence", "UNKNOWN"),
                "source": _debate_source(result, token_row),
                "token_total": int(token_row.get("total_tokens") or 0),
                "latency_ms": int(token_row.get("latency_ms") or result.get("elapsed_ms") or 0),
                "audit_id": result.get("audit_id", ""),
            }
        )

    final_action = run.get("finalWriter", {}).get("finalAction") or run.get("finalAction", "WAIT")
    return {
        "run_id": run.get("runId", ""),
        "final_action": final_action,
        "final_decision_cap": _final_decision_cap(run),
        "kill_switch": run.get("killSwitch", {}),
        "turns": turns,
        "summary": _debate_summary(run, turns),
        "audit_id": "AUD_AGENT_DEBATE",
    }


def _token_number(primary: Any, usage: Dict[str, Any], keys: Iterable[str]) -> int:
    if isinstance(primary, (int, float)) and not isinstance(primary, bool):
        return int(primary)
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return 0


def _debate_stance(result: Dict[str, Any]) -> str:
    status = result.get("status")
    if status == "PASS":
        return "support"
    if status in {"BLOCK", "ERROR"} or result.get("hard_stop"):
        return "block"
    if status in {"WARN", "REVIEW_ONLY"}:
        return "challenge"
    return "observe"


def _debate_claim(result: Dict[str, Any]) -> str:
    name = str(result.get("name") or result.get("node") or "Agent")
    reasons = [_clean_debate_text(item) for item in (result.get("reasons") or [])]
    reasons = [item for item in reasons if item]
    if reasons:
        return f"{name}：{reasons[0]}"
    data = result.get("data") or {}
    summary = _clean_debate_text(data.get("output_summary") or data.get("input_summary"))
    if summary:
        return f"{name}：{summary}"
    return f"{name} 本轮实际状态为「{_status_label(str(result.get('status', 'WARN')))}」，未返回额外主张文本。"


def _debate_evidence(result: Dict[str, Any]) -> List[str]:
    evidence = []
    if result.get("missing_data"):
        evidence.append(f"缺失数据：{'、'.join(result.get('missing_data', []))}")
    data = result.get("data") or {}
    output_summary = _clean_debate_text(data.get("output_summary"))
    if output_summary:
        evidence.append(f"节点输出摘要：{output_summary}")
    if result.get("allowed_actions"):
        evidence.append(f"允许动作：{'、'.join(result.get('allowed_actions', []))}")
    return _unique(evidence)


def _debate_counterpoints(result: Dict[str, Any]) -> List[str]:
    counterpoints = [_clean_debate_text(item) for item in (result.get("warnings") or [])]
    counterpoints = [item for item in counterpoints if item]
    if result.get("blocked_actions"):
        counterpoints.append(f"阻断动作：{'、'.join(result.get('blocked_actions', []))}")
    if result.get("skipped_reason"):
        counterpoints.append(str(result.get("skipped_reason")))
    return _unique(counterpoints)


def _debate_impact(result: Dict[str, Any]) -> str:
    if result.get("hard_stop"):
        return "该节点触发或确认硬性阻断，下游正向交易路径必须被限制。"
    if result.get("status") == "REVIEW_ONLY":
        return "该节点把结论限制为仅复核语言，不能升级为买入或加仓。"
    if result.get("status") == "PASS":
        return "该节点允许流程在上游门禁范围内继续。"
    if result.get("status") == "SKIPPED":
        return "该节点被跳过，没有直接贡献本轮决策。"
    return "该节点为最终结论增加了谨慎条件或限制。"


def _debate_source(result: Dict[str, Any], token_row: Dict[str, Any]) -> str:
    audit_id = str(result.get("audit_id") or "")
    if "MOCK" in audit_id or str(result.get("node") or "").startswith("mock_"):
        return "MOCK"
    if token_row.get("status") == "COMPLETED" or int(token_row.get("total_tokens") or 0) > 0:
        return "LLM"
    return "RULE_ENGINE"


def _clean_debate_text(value: Any) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if not text:
        return ""
    if text.lower().startswith("llm completed for"):
        return ""
    return text


def _status_label(status: str) -> str:
    return {
        "PASS": "通过",
        "WARN": "需谨慎",
        "REVIEW_ONLY": "仅复核",
        "BLOCK": "阻断",
        "BLOCK_BUY": "阻断买入",
        "ERROR": "失败",
        "FAILED": "失败",
        "SKIPPED": "跳过",
    }.get(status, status)


def _debate_summary(run: Dict[str, Any], turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    hard_blocks = [turn for turn in turns if turn.get("stance") == "block"]
    challenges = [turn for turn in turns if turn.get("stance") == "challenge"]
    supporters = [turn for turn in turns if turn.get("stance") == "support"]
    return {
        "support_count": len(supporters),
        "challenge_count": len(challenges),
        "block_count": len(hard_blocks),
        "dominant_constraint": hard_blocks[0]["name"] if hard_blocks else (challenges[0]["name"] if challenges else ""),
        "final_action": run.get("finalWriter", {}).get("finalAction") or run.get("finalAction", "WAIT"),
        "human_confirmation_required": True,
    }


def _standard_agent_status(status: str) -> str:
    return {
        "PASS": "PASS",
        "WARN": "WARN",
        "REVIEW_ONLY": "REVIEW_ONLY",
        "BLOCK_BUY": "BLOCK",
        "BLOCK": "BLOCK",
        "FAIL": "ERROR",
        "ERROR": "ERROR",
        "SKIPPED": "SKIPPED",
        "RUNNING": "WARN",
        "WAIT": "SKIPPED",
    }.get(status, "WARN")


def _confidence_for_status(status: str) -> str:
    if status == "PASS":
        return "HIGH"
    if status in {"WARN", "REVIEW_ONLY"}:
        return "MEDIUM"
    if status in {"BLOCK", "ERROR"}:
        return "LOW"
    return "UNKNOWN"


def _skip_reason(node: Dict[str, Any]) -> str:
    reasons = node.get("downgradeReasons") or []
    if reasons:
        return str(reasons[0])
    return str(node.get("inputSummary") or "Skipped by run mode, runtime disablement, or kill switch.")


def _warnings_for_node(node: Dict[str, Any], run: Dict[str, Any]) -> List[str]:
    warnings = []
    status = _standard_agent_status(node.get("status", "WARN"))
    if status in {"WARN", "REVIEW_ONLY", "BLOCK", "ERROR"}:
        summary = node.get("outputSummary")
        if summary:
            warnings.append(str(summary))
    if node.get("id") == "data_reliability_engine" and run.get("marketData", {}).get("status") != "READY":
        warnings.append(str(run.get("marketData", {}).get("error") or "Market data is not ready."))
    return _unique(warnings)


def _build_final_context(run: Dict[str, Any], kill_switch: Dict[str, Any]) -> Dict[str, Any]:
    execution = run.get("execution", {})
    market_data = run.get("marketData", {})
    quote = market_data.get("quote", {}) if isinstance(market_data, dict) else {}
    dvg = run.get("dvg", {})
    qiam = run.get("qiam", {})
    mfe_mae_research = run.get("mfeMaeResearch", {})
    bottom_research = mfe_mae_research if isinstance(mfe_mae_research, dict) and mfe_mae_research else run.get("bottomResearch", {})
    guardrail_hub = run.get("guardrailHub", {}) if isinstance(run.get("guardrailHub"), dict) else {}
    quant_core = run.get("quantCore", {})
    market = run.get("market", {})
    technical = run.get("technicalKline", {})
    market_technical = run.get("marketTechnical", {})
    atrade = run.get("atrade", {})
    factor = run.get("factorSlicing", {})
    portfolio = run.get("portfolio", {})
    return {
        "final_writer_mode": kill_switch.get("finalWriterMode", "NORMAL"),
        "final_action": run.get("finalAction", "WAIT"),
        "final_decision_cap": _final_decision_cap(run),
        "allowed_actions": execution.get("allowedActions", kill_switch.get("allowedPaths", [])),
        "forbidden_actions": execution.get("forbiddenActions", kill_switch.get("blockedPaths", [])),
        "data_reliability": dvg.get("dataReliability", "LOW"),
        "guardrail_hub_summary": guardrail_hub,
        "risk_summary": run.get("risk", {}),
        "dvg_summary": dvg,
        "atrade_summary": atrade,
        "market_summary": market,
        "quant_core_summary": quant_core if isinstance(quant_core, dict) else {},
        "market_technical_summary": market_technical if isinstance(market_technical, dict) else {},
        "market_data": market_data,
        "factor_summary": factor,
        "mfe_mae_research_summary": bottom_research if isinstance(bottom_research, dict) else {},
        "bottom_research_summary": bottom_research if isinstance(bottom_research, dict) else {},
        "qiam_summary": qiam,
        "portfolio_summary": portfolio,
        "execution_summary": run.get("execution", {}),
        "signalops_summary": run.get("signalOps", {}),
        "missing_data": _unique(
            dvg.get("criticalMissingData", [])
            + factor.get("missingFactorData", [])
            + qiam.get("missingData", [])
        ),
        "trigger_conditions": run.get("signalOps", {}).get("triggerConditions", []),
        "invalidation_conditions": run.get("signalOps", {}).get("invalidationConditions", []),
        "conclusion_derivation_inputs": {
            "final_action": run.get("finalAction", "WAIT"),
            "quant_core_summary": quant_core if isinstance(quant_core, dict) else {},
            "qiam_final_buy_suitability": qiam.get("finalBuySuitability"),
            "qiam_model_confidence_final": qiam.get("modelConfidenceFinal"),
            "mfe_mae_path_research": _mfe_mae_conclusion_inputs(run),
            "bottom_research": {
                "bottom_repair_probability": bottom_research.get("bottomRepairProbability") if isinstance(bottom_research, dict) else None,
                "breakdown_risk_probability": bottom_research.get("breakdownRiskProbability") if isinstance(bottom_research, dict) else None,
                "regime_state": bottom_research.get("regimeState") if isinstance(bottom_research, dict) else None,
                "horizon_forecasts": bottom_research.get("horizonForecasts", []) if isinstance(bottom_research, dict) else [],
                "trend_synthesis": bottom_research.get("trendSynthesis", {}) if isinstance(bottom_research, dict) else {},
                "qiam_adjustment_preview": bottom_research.get("qiamAdjustmentPreview", {}) if isinstance(bottom_research, dict) else {},
                "qiam_adjustment": (
                    qiam.get("mfeMaePathResearchAdjustment") or qiam.get("bottomResearchAdjustment")
                    if isinstance(qiam, dict)
                    else None
                ),
                "decision_policy": "CONTROLLED_ONE_STEP_QIAM_CALIBRATION_NO_TRADE_ACTION",
            },
            "probability_band": {
                "up": qiam.get("probabilityBandUp"),
                "sideways": qiam.get("probabilityBandSideways"),
                "down": qiam.get("probabilityBandDown"),
            },
            "core_interpretation": (
                quant_core.get("coreInterpretation")
                if isinstance(quant_core, dict)
                else None
            ),
            "dvg_allowed_output_level": dvg.get("allowedOutputLevel"),
            "dvg_final_decision_cap": dvg.get("finalDecisionCap"),
            "guardrail_hub": guardrail_hub,
            "guardrail_hub_status": guardrail_hub.get("status"),
            "guardrail_hub_final_decision_cap": guardrail_hub.get("finalDecisionCap"),
            "kill_switch": kill_switch,
            "execution_reachability": execution.get("executionReachability"),
            "allowed_actions": execution.get("allowedActions", []),
            "forbidden_actions": execution.get("forbiddenActions", []),
        },
        "fundamental_review": {
            "stock_code": run.get("stockCode"),
            "stock_name": run.get("stockName"),
            "market_sentiment": market.get("marketSentiment"),
            "institutional_activity": market.get("institutionalActivity"),
            "sector_rotation": market.get("sectorRotation", []),
            "macro_indicators": market.get("macroIndicators", {}),
            "factor_mode": factor.get("mode"),
            "factor_clusters": factor.get("factorClusters", []),
            "factor_stability": factor.get("factorStability"),
            "portfolio_constraints": portfolio,
            "fundamental_missing_or_uncertain": _unique(
                dvg.get("criticalMissingData", []) + factor.get("missingFactorData", [])
            ),
        },
        "technical_review": {
            "quote": quote,
            "quote_status": market_data.get("status") if isinstance(market_data, dict) else None,
            "quote_provider": market_data.get("provider") if isinstance(market_data, dict) else None,
            "quote_fetched_at": market_data.get("fetchedAt") if isinstance(market_data, dict) else None,
            "volatility_index": market.get("volatilityIndex"),
            "liquidity_index": market.get("liquidityIndex"),
            "technical_kline": technical if isinstance(technical, dict) else {},
            "market_technical_alignment": market_technical.get("alignment") if isinstance(market_technical, dict) else None,
            "price_limit_status": atrade.get("priceLimitStatus"),
            "t1_status": atrade.get("t1Status"),
            "level2_available": atrade.get("level2Available"),
            "depth_available": atrade.get("depthAvailable"),
            "liquidity_risk": atrade.get("liquidityRisk"),
            "slippage_limit": atrade.get("slippageLimit"),
            "participation_limit": atrade.get("participationLimit"),
            "execution_reachability": atrade.get("executionReachability"),
        },
        "data_verification_checklist": {
            "source": market_data.get("provider") if isinstance(market_data, dict) else None,
            "status": market_data.get("status") if isinstance(market_data, dict) else None,
            "fetched_at": market_data.get("fetchedAt") if isinstance(market_data, dict) else None,
            "confirmed_ratio": dvg.get("confirmedRatio"),
            "inferred_ratio": dvg.get("inferredRatio"),
            "unknown_ratio": dvg.get("unknownRatio"),
            "hallucination_risk_level": dvg.get("hallucinationRiskLevel"),
            "hallucination_risk_score": dvg.get("hallucinationRiskScore"),
            "critical_missing_data": dvg.get("criticalMissingData", []),
            "data_conflicts": dvg.get("dataConflicts", []),
            "audit_id": run.get("finalWriter", {}).get("auditId", "AUD_FINAL_CONTEXT"),
        },
        "human_confirmation_required": True,
        "audit_id": run.get("finalWriter", {}).get("auditId", "AUD_FINAL_CONTEXT"),
    }


def _build_orchestrator_plan(
    run: Dict[str, Any],
    run_mode: str,
    kill_switch: Dict[str, Any],
) -> Dict[str, Any]:
    active_agents = [node["id"] for node in run.get("nodes", []) if not node.get("isSkipped")]
    skipped_agents = [node["id"] for node in run.get("nodes", []) if node.get("isSkipped")]
    mandatory_nodes = ["orchestrator", "data_reliability_engine", "guardrail_hub", "final_writer"]
    conditional_nodes = [agent["id"] for agent in AGENT_MANIFEST if agent["id"] not in mandatory_nodes]
    return {
        "node": "ORCHESTRATOR",
        "status": "HARD_RISK_FINAL_ONLY" if kill_switch.get("active") else "CONTINUE",
        "run_mode": run_mode,
        "runtime_environment": "API_ORCHESTRATED",
        "mandatory_nodes": mandatory_nodes,
        "conditional_nodes": conditional_nodes,
        "active_agents": active_agents,
        "skipped_agents": skipped_agents,
        "skipped_nodes": run.get("skippedNodes", []),
        "dag_events": run.get("dagEvents", []),
        "skip_reasons": {
            node["id"]: node.get("downgradeReasons", []) or [node.get("inputSummary", "Skipped.")]
            for node in run.get("nodes", [])
            if node.get("isSkipped")
        },
        "tool_budget": {
            **RUN_MODE_TOOL_BUDGET[run_mode],
            "used_tool_calls": len(active_agents),
        },
        "kill_switch_active": kill_switch.get("active", False),
        "kill_switch_level": kill_switch.get("level", "NONE"),
        "trigger_node": kill_switch.get("triggerNode", ""),
        "trigger_rule": kill_switch.get("triggerRule", ""),
        "blocked_paths": kill_switch.get("blockedPaths", []),
        "allowed_paths": kill_switch.get("allowedPaths", []),
        "fallback_plan": _fallback_plan(run, kill_switch),
        "final_writer_mode": kill_switch.get("finalWriterMode", "NORMAL"),
        "human_confirmation_required": True,
        "final_decision_cap": _final_decision_cap(run),
        "audit_id": "AUD_ORCHESTRATOR_PLAN",
    }


def _fallback_plan(run: Dict[str, Any], kill_switch: Dict[str, Any]) -> Dict[str, Any]:
    market_data = run.get("marketData", {})
    if kill_switch.get("active"):
        return {
            "mode": "HARD_RISK_FINAL_ONLY",
            "reason": kill_switch.get("triggerRule", "kill_switch_active"),
            "allowed_paths": kill_switch.get("allowedPaths", []),
        }
    if market_data and market_data.get("status") != "READY":
        return {
            "mode": "DATA_DEGRADED_REVIEW_ONLY",
            "reason": market_data.get("error") or market_data.get("status", "market_data_not_ready"),
            "allowed_paths": ["REVIEW_ONLY", "WAIT"],
        }
    return {
        "mode": "NORMAL",
        "reason": "",
        "allowed_paths": run.get("execution", {}).get("allowedActions", []),
    }


def _final_decision_cap(run: Dict[str, Any]) -> str:
    guardrail = run.get("guardrailHub") if isinstance(run.get("guardrailHub"), dict) else {}
    guardrail_cap = guardrail.get("finalDecisionCap")
    if guardrail_cap in {"REVIEW_ONLY", "BLOCK_BUY", "REJECT"}:
        return guardrail_cap
    dvg_cap = run.get("dvg", {}).get("finalDecisionCap")
    final_action = run.get("finalAction", "WAIT")
    if dvg_cap in {"REVIEW_ONLY", "BLOCK_BUY", "REJECT"}:
        return dvg_cap
    if final_action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        return "NO_STRONG_BUY"
    return "NO_BUY" if final_action in {"WAIT", "LIGHT_WATCH", "SIGNAL_ONLY"} else "NO_CAP"


def _unique(values: Iterable[Any]) -> List[Any]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _stream_event(
    event_type: str,
    run_id: str,
    message: str,
    node_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    audit_id: Optional[str] = None,
) -> Dict[str, Any]:
    from datetime import datetime

    return {
        "event_type": event_type,
        "run_id": run_id,
        "node_id": node_id,
        "message": message,
        "payload": payload or {},
        "audit_id": audit_id or f"AUD_STREAM_{event_type}",
        "timestamp": datetime.now().isoformat(),
    }
