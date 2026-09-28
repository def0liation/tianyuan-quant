from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .atrade import ATradeAgent
from .base_agent import AgentResult, BaseAgent
from .dvg_evidence_gate import DvgEvidenceGateAgent
from .risk_firewall import RiskFirewallAgent


KILL_SWITCH_RULES: Dict[str, Dict[str, Any]] = {
    "compliance_violation": {
        "level": "COMPLIANCE",
        "blocked_paths": ["ALL_TRADE_RELATED"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY"],
        "final_writer_mode": "COMPLIANCE_ONLY",
    },
    "risk_hard_reject": {
        "level": "HARD",
        "blocked_paths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "CHASE", "EXECUTION_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY", "HOLD"],
        "final_writer_mode": "HARD_RISK_FINAL_ONLY",
    },
    "dvg_block_buy": {
        "level": "HARD",
        "blocked_paths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "EXECUTION_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY"],
        "final_writer_mode": "DATA_VERIFICATION_BLOCK",
    },
    "atrade_not_reachable": {
        "level": "HARD",
        "blocked_paths": ["BUY_CANDIDATE", "ADD_CANDIDATE", "EXECUTION_BUY"],
        "allowed_paths": ["WAIT", "REVIEW_ONLY", "HOLD"],
        "final_writer_mode": "EXECUTION_UNREACHABLE",
    },
}


class GuardrailHubAgent(BaseAgent):
    node = "guardrail_hub"
    name = "Guardrail Hub"
    stage = "guardrail"
    rule_engine_only = True

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        dvg_result = DvgEvidenceGateAgent().process(run_context, prior_outputs)
        dvg_payload = _merge_dict(run_context.get("dvg"), dvg_result.data)

        context_after_dvg = {**run_context, "dvg": dvg_payload}
        guardrail_priors = dict(prior_outputs)
        guardrail_priors["dvg_gate"] = dvg_payload
        guardrail_priors["dvg_evidence_gate"] = dvg_payload

        risk_result = RiskFirewallAgent().process(context_after_dvg, guardrail_priors)
        risk_payload = _merge_dict(
            run_context.get("risk"),
            risk_result.data,
            {
                "status": risk_result.status,
                "hardStop": risk_result.hard_stop,
                "finalDecisionCap": risk_result.final_decision_cap,
                "auditId": risk_result.audit_id,
            },
        )
        guardrail_priors["risk_firewall"] = risk_payload

        context_after_risk = {**context_after_dvg, "risk": risk_payload}
        atrade_result = ATradeAgent().process(context_after_risk, guardrail_priors)
        atrade_payload = _merge_dict(
            run_context.get("atrade"),
            atrade_result.data,
            {
                "status": atrade_result.status,
                "hardStop": atrade_result.hard_stop,
                "finalDecisionCap": atrade_result.final_decision_cap,
                "auditId": atrade_result.audit_id,
            },
        )

        kill_switch = _infer_kill_switch(dvg_payload, risk_payload, atrade_payload)
        status = _aggregate_status(dvg_result, risk_result, atrade_result, kill_switch)
        final_decision_cap = _final_decision_cap(dvg_payload, kill_switch)
        allowed_actions = _aggregate_allowed_actions(
            [dvg_result, risk_result, atrade_result],
            kill_switch,
        )
        blocked_actions = _aggregate_blocked_actions(
            [dvg_result, risk_result, atrade_result],
            kill_switch,
        )
        warnings = _unique(
            list(dvg_result.warnings)
            + list(risk_result.warnings)
            + list(atrade_result.warnings)
            + (["Guardrail Hub activated kill switch."] if kill_switch.get("active") else [])
        )
        gate_results = {
            "dvg": _result_summary(dvg_result),
            "risk": _result_summary(risk_result),
            "atrade": _result_summary(atrade_result),
        }
        legacy_module_results = {
            "dvg_gate": _alias_result_dict(dvg_result, "dvg_gate", dvg_payload),
            "dvg_evidence_gate": _alias_result_dict(dvg_result, "dvg_evidence_gate", dvg_payload),
            "risk_firewall": _alias_result_dict(risk_result, "risk_firewall", risk_payload),
            "trade_micro": _alias_result_dict(atrade_result, "trade_micro", atrade_payload),
            "atrade": _alias_result_dict(atrade_result, "atrade", atrade_payload),
        }
        legacy_agent_outputs = {
            "dvg_gate": _legacy_compatibility_payload("dvg_gate", dvg_payload),
            "dvg_evidence_gate": _legacy_compatibility_payload("dvg_evidence_gate", dvg_payload),
            "risk_firewall": _legacy_compatibility_payload("risk_firewall", risk_payload),
            "trade_micro": _legacy_compatibility_payload("trade_micro", atrade_payload),
            "atrade": _legacy_compatibility_payload("atrade", atrade_payload),
        }
        audit_id = kill_switch.get("auditId") if kill_switch.get("active") else self._audit()
        data = {
            "status": status,
            "finalDecisionCap": final_decision_cap,
            "killSwitch": kill_switch,
            "dvg": dvg_payload,
            "risk": risk_payload,
            "atrade": atrade_payload,
            "gateResults": gate_results,
            "warnings": warnings,
            "auditId": audit_id,
            "legacyModuleResults": legacy_module_results,
            "legacyAgentOutputs": legacy_agent_outputs,
        }

        return AgentResult(
            node=self.node,
            status=status,
            allowed_actions=allowed_actions,
            blocked_actions=blocked_actions,
            hard_stop=bool(kill_switch.get("active") and kill_switch.get("level") in {"HARD", "COMPLIANCE"}),
            final_decision_cap=final_decision_cap,
            confidence=_aggregate_confidence([dvg_result, risk_result, atrade_result], kill_switch),
            reasons=_unique(list(dvg_result.reasons) + list(risk_result.reasons) + list(atrade_result.reasons)),
            missing_data=_unique(list(dvg_result.missing_data) + list(atrade_result.missing_data)),
            warnings=warnings,
            data=data,
            audit_id=audit_id,
        )


def _merge_dict(*values: Any) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for value in values:
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _aggregate_status(
    dvg_result: AgentResult,
    risk_result: AgentResult,
    atrade_result: AgentResult,
    kill_switch: Dict[str, Any],
) -> str:
    if kill_switch.get("level") == "COMPLIANCE" or risk_result.status == "BLOCK":
        return "BLOCK"
    statuses = [dvg_result.status, risk_result.status, atrade_result.status]
    if kill_switch.get("active") or "BLOCK_BUY" in statuses:
        return "BLOCK_BUY"
    dvg_level = str(dvg_result.data.get("allowedOutputLevel") or "")
    if "REVIEW_ONLY" in statuses or dvg_level == "REVIEW_ONLY":
        return "REVIEW_ONLY"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _final_decision_cap(dvg: Dict[str, Any], kill_switch: Dict[str, Any]) -> str:
    if kill_switch.get("active"):
        return "REJECT" if kill_switch.get("level") == "COMPLIANCE" else "BLOCK_BUY"
    cap = dvg.get("finalDecisionCap")
    if isinstance(cap, str) and cap:
        return cap
    allowed_output = dvg.get("allowedOutputLevel")
    if allowed_output == "REVIEW_ONLY":
        return "REVIEW_ONLY"
    return "NO_CAP"


def _infer_kill_switch(dvg: Dict[str, Any], risk: Dict[str, Any], atrade: Dict[str, Any]) -> Dict[str, Any]:
    if risk.get("complianceRedLines"):
        return _kill_switch("compliance_violation", "AUD_KS_COMPLIANCE")

    hard_risk_keys = [
        "f0IndividualHardRisks",
        "f1ExtremeChipCollapse",
        "f4ThreePartyFundResonanceOutflow",
        "l0AbsoluteLiquidityRedLine",
        "m0SystemicRisk",
        "portfolioRiskOverLimit",
        "executionUnreachable",
    ]
    if any(_has_items(risk.get(key)) for key in hard_risk_keys) or risk.get("hardStop"):
        return _kill_switch("risk_hard_reject", "AUD_KS_RISK")

    if dvg.get("hardStop") or dvg.get("status") == "BLOCK_BUY" or dvg.get("finalDecisionCap") == "BLOCK_BUY":
        return _kill_switch("dvg_block_buy", "AUD_KS_DVG")

    if atrade.get("executionReachability") == "NOT_REACHABLE" or atrade.get("flashCrashVacuumStatus"):
        return _kill_switch("atrade_not_reachable", "AUD_KS_ATRADE")

    return {
        "active": False,
        "level": "NONE",
        "triggerNode": "",
        "triggerRule": "",
        "blockedPaths": [],
        "allowedPaths": ["WAIT", "REVIEW_ONLY", "HOLD", "LIGHT_WATCH", "BUY_CANDIDATE", "ADD_CANDIDATE"],
        "finalWriterMode": "NORMAL",
        "auditId": "AUD_KS_NONE",
    }


def _kill_switch(rule_id: str, audit_id: str) -> Dict[str, Any]:
    rule = KILL_SWITCH_RULES[rule_id]
    return {
        "active": True,
        "level": rule["level"],
        "triggerNode": "guardrail_hub",
        "triggerRule": rule_id,
        "blockedPaths": list(rule["blocked_paths"]),
        "allowedPaths": list(rule["allowed_paths"]),
        "finalWriterMode": rule["final_writer_mode"],
        "auditId": audit_id,
    }


def _aggregate_allowed_actions(results: Iterable[AgentResult], kill_switch: Dict[str, Any]) -> List[str]:
    if kill_switch.get("active"):
        return list(kill_switch.get("allowedPaths") or [])
    allowed = _unique(action for result in results for action in result.allowed_actions)
    return allowed or ["WAIT", "REVIEW_ONLY", "HOLD", "LIGHT_WATCH"]


def _aggregate_blocked_actions(results: Iterable[AgentResult], kill_switch: Dict[str, Any]) -> List[str]:
    blocked = _unique(action for result in results for action in result.blocked_actions)
    if kill_switch.get("active"):
        blocked = _unique(blocked + list(kill_switch.get("blockedPaths") or []))
    return blocked


def _aggregate_confidence(results: Iterable[AgentResult], kill_switch: Dict[str, Any]) -> str:
    if kill_switch.get("active"):
        return "HIGH"
    ranks = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    confidences = [result.confidence for result in results]
    lowest = min(confidences, key=lambda item: ranks.get(item, 1), default="MEDIUM")
    return lowest


def _result_summary(result: AgentResult) -> Dict[str, Any]:
    return {
        "node": result.node,
        "status": result.status,
        "hardStop": result.hard_stop,
        "finalDecisionCap": result.final_decision_cap,
        "allowedActions": list(result.allowed_actions),
        "blockedActions": list(result.blocked_actions),
        "auditId": result.audit_id,
    }


def _alias_result_dict(result: AgentResult, node: str, data: Dict[str, Any]) -> Dict[str, Any]:
    output = result.to_dict()
    output["node"] = node
    output["data"] = data
    return _legacy_compatibility_payload(node, output)


def _legacy_compatibility_payload(node: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(payload)
    output["node"] = node
    output["legacyCompatibilityOnly"] = True
    output["canonicalNode"] = "guardrail_hub"
    output["activeNode"] = False
    return output


def _has_items(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return bool(value)
    return bool(value)


def _unique(values: Iterable[Any]) -> List[Any]:
    result: List[Any] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
