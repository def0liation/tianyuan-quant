from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, MutableMapping

logger = logging.getLogger(__name__)

SIM_ORDER_NAMESPACE = "SIM_*"
PAPER_TRADING_ACTION_KEYS = ("action", "paper_action", "latest_action")
PAPER_TRADING_NAMESPACE_KEYS = ("allowed_order_namespace", "orderNamespace", "order_namespace")

from .agent_framework import (
    apply_market_regime_data,
    apply_market_technical_data,
    apply_quant_core_data,
    apply_technical_kline_data,
    normalize_run_artifacts,
)
from .agent_node_utils import (
    NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON,
    is_non_executable_plugin_observation,
    mark_non_executable_plugin_observation,
)
from .agent_runtime_store import get_agent_execution_config, save_run
from .llm_runner import LLMRunResult, run_agent_llm
from ..modules.agent_registry import run_agent as run_agent_module


async def execute_run_with_llm(
    run_id: str,
    runs_store: MutableMapping[str, Dict[str, Any]],
    agent_timeout_seconds: int = 30,
) -> None:
    run = runs_store.get(run_id)
    if run is None:
        logger.warning("Run %s not found in runs_store, aborting execution.", run_id)
        return

    run["status"] = "RUNNING"
    run["updatedAt"] = _now()
    run.setdefault("streamEvents", [])
    run.setdefault("agentOutputs", {})
    run.setdefault("agentModuleResults", {})
    run.setdefault("llmTrace", [])
    _append_stream_event(run, "RUN_STARTED", "Analysis run started.")

    prior_outputs: Dict[str, Any] = {
        "orchestrator_output": {},
        "data_reliability_engine_output": {},
        "guardrail_hub_output": {},
    }

    try:
        active_nodes = [n for n in run.get("nodes", []) if not n.get("isSkipped")]
        retry_from_node_id = _canonical_retry_node_id(str((run.get("retry") or {}).get("from_node_id") or ""))
        if retry_from_node_id and isinstance(run.get("retry"), dict):
            run["retry"]["from_node_id"] = retry_from_node_id
        retry_started = not retry_from_node_id
        runtime_kill_switch_active = _runtime_guardrail_kill_switch_active(run)
        for node in active_nodes:
            agent_id = node["id"]
            if run.get("cancelRequested"):
                raise asyncio.CancelledError("Analysis run cancellation requested.")
            if runtime_kill_switch_active and agent_id != "final_writer":
                _record_runtime_kill_switch_skip(run, node, prior_outputs)
                _save_run_snapshot(run)
                continue
            if not retry_started:
                if agent_id != retry_from_node_id:
                    if agent_id in run.get("agentOutputs", {}):
                        prior_outputs[agent_id] = run["agentOutputs"][agent_id]
                    node["rawJson"] = {
                        **node.get("rawJson", {}),
                        "retry": {
                            "status": "PRESERVED_BEFORE_RETRY_NODE",
                            "retryFromNodeId": retry_from_node_id,
                            "preservedAt": _now(),
                        },
                    }
                    continue
                retry_started = True
                _append_stream_event(
                    run,
                    "RUN_RETRY_FROM_NODE",
                    f"Retry resumed from node {retry_from_node_id}.",
                    agent_id,
                    {"retryFromNodeId": retry_from_node_id},
                    f"AUD_RETRY_{run_id}_{retry_from_node_id}",
                )

            resolved_status = node.get("status", "PASS")
            if is_non_executable_plugin_observation(node):
                _record_non_executable_plugin_observation(run, node, prior_outputs)
                _save_run_snapshot(run)
                continue

            node["isRunning"] = True
            node["status"] = "RUNNING"
            node["rawJson"] = {
                **node.get("rawJson", {}),
                "llmRunner": {"status": "RUNNING", "startedAt": _now()},
            }
            _append_audit(
                run,
                agent_id,
                "NODE_STARTED",
                f"{node.get('name', agent_id)} started.",
                "WAIT",
                "RUNNING",
                node.get("auditId"),
            )
            _append_stream_event(
                run,
                "NODE_STARTED",
                f"{node.get('name', agent_id)} started.",
                agent_id,
                {"promptRef": node.get("rawJson", {}).get("systemPromptRef")},
                node.get("auditId"),
            )

            if agent_id == "quant_engine":
                _run_quant_engine_submodules(run, prior_outputs)

            agent_module_result = run_agent_module(agent_id, run, prior_outputs)
            run["agentModuleResults"][agent_id] = agent_module_result.to_dict()
            _apply_agent_module_output_to_run(run, agent_id, agent_module_result)
            if agent_id == "guardrail_hub":
                _sync_guardrail_hub_prior_outputs(prior_outputs, agent_module_result.data)
                resolved_status = _guardrail_node_status(run)

            provider = ""
            model = ""
            profile_id = ""
            timeout_seconds = agent_timeout_seconds
            try:
                _, profile = get_agent_execution_config(agent_id)
                provider = profile.provider
                model = profile.model
                profile_id = profile.id
                timeout_seconds = max(agent_timeout_seconds, int(profile.timeout_seconds) + 5)
            except Exception:
                logger.exception("Failed to resolve LLM profile for agent %s", agent_id)

            try:
                if agent_id == "guardrail_hub":
                    result = LLMRunResult(
                        status="SKIPPED",
                        provider=provider,
                        model=model,
                        profile_id=profile_id,
                        error="Guardrail Hub is a deterministic rule engine; LLM output is suppressed.",
                        latency_ms=0,
                    )
                else:
                    result = await asyncio.wait_for(
                        run_agent_llm(agent_id, run, prior_outputs),
                        timeout=timeout_seconds,
                    )
            except asyncio.TimeoutError:
                result = LLMRunResult(
                    status="FAILED",
                    provider=provider,
                    model=model,
                    profile_id=profile_id,
                    error=f"Agent {agent_id} timed out after {timeout_seconds}s",
                    latency_ms=timeout_seconds * 1000,
                )

            _record_result(run, node, result, resolved_status)

            if result.status == "COMPLETED":
                output = result.parsed_json if result.parsed_json is not None else result.content
                if agent_id == "market_technical_analyst":
                    output = _canonical_market_technical_output(output, agent_module_result.data)
                if agent_id == "quant_core":
                    output = _canonical_quant_core_output(output, agent_module_result.data)
                prior_outputs[agent_id] = output
                if agent_id == "data_reliability_engine":
                    _mirror_data_reliability_prior_outputs(prior_outputs, output)
                if agent_id == "quant_core":
                    _mirror_quant_core_prior_outputs(prior_outputs, output)
                run["agentOutputs"][agent_id] = output
            else:
                prior_outputs[agent_id] = agent_module_result.data
                if agent_id == "data_reliability_engine":
                    _mirror_data_reliability_prior_outputs(prior_outputs, agent_module_result.data)
                if agent_id == "quant_core":
                    _mirror_quant_core_prior_outputs(prior_outputs, agent_module_result.data)
                if agent_id == "guardrail_hub":
                    _sync_guardrail_hub_prior_outputs(prior_outputs, agent_module_result.data)
                run["agentOutputs"][agent_id] = agent_module_result.data

            _apply_llm_output_to_run(run, agent_id, result)
            normalize_run_artifacts(run)
            runtime_kill_switch_active = _runtime_guardrail_kill_switch_active(run)
            _append_audit(
                run,
                agent_id,
                "NODE_FINISHED" if result.status == "COMPLETED" else "NODE_DOWNGRADED",
                _node_finish_message(node, result),
                "RUNNING",
                node.get("status", resolved_status),
                node.get("auditId"),
            )
            _append_stream_event(
                run,
                "NODE_FINISHED" if result.status == "COMPLETED" else "NODE_DOWNGRADED",
                _node_finish_message(node, result),
                agent_id,
                {
                    "llmStatus": result.status,
                    "latencyMs": result.latency_ms,
                    "hasParsedJson": result.parsed_json is not None,
                    "error": result.error,
                },
                node.get("auditId"),
            )
            run["updatedAt"] = _now()
            _save_run_snapshot(run)

        llm_trace = run.get("llmTrace", [])
        any_llm_completed = any(t.get("status") == "COMPLETED" for t in llm_trace)
        if active_nodes and not any_llm_completed and len(llm_trace) > 0:
            run["status"] = "FAILED"
            run["failReason"] = "所有 LLM 调用均失败，大模型 API 不可用。请检查 API 密钥和网络连接后重试。当前仅显示规则引擎计算值，非大模型智能分析结果。"
            run["updatedAt"] = _now()
            if "finalWriter" in run:
                run["finalWriter"]["llmFailed"] = True
                run["finalWriter"]["finalAction"] = "FAILED"
                run["finalWriter"]["mode"] = "LLM_UNAVAILABLE"
                run["finalWriter"]["humanConfirmationRequired"] = True
                run["finalWriter"]["sections"] = [
                    {
                        "title": "LLM 调用失败",
                        "content": "大模型 API 不可用，所有 Agent 的 LLM 调用均失败。当前无法生成智能分析结论。请检查后端 LLM API 配置（密钥、端点、模型名称等）后重新运行分析。规则引擎模块已正常执行，但最终分析需要大模型参与才能提供有意义的建议和结论。",
                        "riskLevel": "HIGH",
                        "requiresConfirmation": True,
                    }
                ]
            normalize_run_artifacts(run)
            _append_stream_event(
                run,
                "RUN_FAILED",
                "所有 LLM 调用均失败，大模型 API 不可用。请检查 API 密钥配置。",
                "system",
                {"failReason": run["failReason"]},
                "AUD_LLM_ALL_FAILED",
            )
            _append_audit(
                run,
                "system",
                "RUN_FAILED",
                "所有 LLM 调用均失败，大模型 API 不可用。",
                "RUNNING",
                "FAIL",
                "AUD_LLM_ALL_FAILED",
            )
        else:
            run["status"] = "COMPLETED"
            run["updatedAt"] = _now()
            normalize_run_artifacts(run)
            _append_stream_event(run, "RUN_FINISHED", "Analysis run finished.")
            _append_audit(
                run,
                "system",
                "RUN_FINISHED",
                "Analysis run finished.",
                "RUNNING",
                "PASS",
                "AUD_RUN_FINISHED",
            )
        _save_run_snapshot(run)
    except asyncio.CancelledError:
        logger.info("Analysis run %s was cancelled.", run.get("runId"))
        for node in run.get("nodes", []):
            if node.get("isRunning"):
                node["isRunning"] = False
                node["status"] = "CANCELLED"
                node.setdefault("downgradeReasons", []).append("Analysis run was cancelled by operator request.")
        run["status"] = "CANCELLED"
        run["failReason"] = "Analysis run cancelled by operator request."
        run["updatedAt"] = _now()
        normalize_run_artifacts(run)
        _append_stream_event(
            run,
            "RUN_CANCELLED",
            run["failReason"],
            "system",
            {"cancelRequested": True},
            "AUD_RUN_CANCELLED",
        )
        _append_audit(
            run,
            "system",
            "RUN_CANCELLED",
            run["failReason"],
            "RUNNING",
            "CANCELLED",
            "AUD_RUN_CANCELLED",
        )
        _save_run_snapshot(run)
        raise
    except Exception as exc:
        logger.exception("Analysis run failed for run %s: %s", run.get("runId"), exc)
        for node in run.get("nodes", []):
            if node.get("isRunning"):
                node["isRunning"] = False
                node["status"] = "FAIL"
                node.setdefault("downgradeReasons", []).append("分析运行异常，节点未能正常收束。")
        run["status"] = "FAILED"
        run["failReason"] = "分析运行异常，后端执行链未能完整收束。已保留完成节点的结果，请刷新或重新运行。"
        run["updatedAt"] = _now()
        normalize_run_artifacts(run)
        _append_stream_event(
            run,
            "RUN_FAILED",
            run["failReason"],
            "system",
            {"error": "An unexpected error occurred during the analysis run."},
            "AUD_RUN_FAILED",
        )
        _append_audit(
            run,
            "system",
            "RUN_FAILED",
            run["failReason"],
            "RUNNING",
            "FAIL",
            "AUD_RUN_FAILED",
        )
        _save_run_snapshot(run)


def _record_non_executable_plugin_observation(
    run: Dict[str, Any],
    node: Dict[str, Any],
    prior_outputs: Dict[str, Any],
) -> None:
    agent_id = str(node.get("id") or "")
    status_before = str(node.get("status") or "WAIT")
    reason = NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON
    observation = mark_non_executable_plugin_observation(node, observed_at=_now(), reason=reason)
    output = {
        "node": agent_id,
        "status": "REVIEW_ONLY",
        "message": reason,
        "pluginObservation": observation,
    }
    prior_outputs[agent_id] = output
    run.setdefault("agentOutputs", {})[agent_id] = output
    run.setdefault("agentModuleResults", {})[agent_id] = {
        "node": agent_id,
        "name": str(node.get("name") or agent_id),
        "status": "SKIPPED",
        "data": output,
        "skipped_reason": reason,
    }
    run["updatedAt"] = _now()
    normalize_run_artifacts(run)
    _append_audit(
        run,
        agent_id,
        "NODE_SKIPPED",
        reason,
        status_before,
        "REVIEW_ONLY",
        node.get("auditId"),
    )
    _append_stream_event(
        run,
        "NODE_SKIPPED",
        reason,
        agent_id,
        {"pluginObservation": observation},
        node.get("auditId"),
    )


def _canonical_retry_node_id(node_id: str) -> str:
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
    return node_id


def _guardrail_legacy_module_result(legacy_id: str, legacy_result: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(legacy_result)
    result.setdefault("node", legacy_id)
    result["legacyCompatibilityOnly"] = True
    result["canonicalNode"] = "guardrail_hub"
    result["activeNode"] = False
    return result


def _runtime_guardrail_kill_switch_active(run: Dict[str, Any]) -> bool:
    kill_switch = run.get("killSwitch") if isinstance(run.get("killSwitch"), dict) else {}
    return bool(
        kill_switch.get("active")
        and kill_switch.get("level") in {"HARD", "COMPLIANCE"}
        and str(kill_switch.get("triggerNode") or "") == "guardrail_hub"
    )


def _record_runtime_kill_switch_skip(
    run: Dict[str, Any],
    node: Dict[str, Any],
    prior_outputs: Dict[str, Any],
) -> None:
    agent_id = str(node.get("id") or "")
    kill_switch = run.get("killSwitch") if isinstance(run.get("killSwitch"), dict) else {}
    reason = f"Guardrail Hub kill switch {kill_switch.get('level', 'HARD')} routed remaining path to Final Writer."
    status_before = str(node.get("status") or "WAIT")
    node["isRunning"] = False
    node["isSkipped"] = True
    node["isBlocked"] = True
    node["status"] = "SKIPPED"
    node["duration"] = 0
    node["allowedNextActions"] = []
    node["blockedPaths"] = list(kill_switch.get("blockedPaths") or [])
    node["downgradeReasons"] = [reason]
    node["rawJson"] = {
        **(node.get("rawJson") if isinstance(node.get("rawJson"), dict) else {}),
        "runtimeKillSwitch": kill_switch,
    }
    output = {
        "node": agent_id,
        "status": "SKIPPED",
        "skippedReason": reason,
        "killSwitch": kill_switch,
    }
    prior_outputs[agent_id] = output
    run.setdefault("agentOutputs", {})[agent_id] = output
    run.setdefault("agentModuleResults", {})[agent_id] = {
        "node": agent_id,
        "name": str(node.get("name") or agent_id),
        "status": "SKIPPED",
        "allowed_actions": [],
        "blocked_actions": list(kill_switch.get("blockedPaths") or []),
        "hard_stop": False,
        "final_decision_cap": kill_switch.get("finalDecisionCap") or "BLOCK_BUY",
        "confidence": "HIGH",
        "reasons": [reason],
        "missing_data": [],
        "warnings": [reason],
        "data": output,
        "audit_id": node.get("auditId") or f"AUD_{agent_id.upper()}_SKIPPED",
        "elapsed_ms": 0,
        "skipped_reason": reason,
    }
    run["updatedAt"] = _now()
    normalize_run_artifacts(run)
    _append_audit(
        run,
        agent_id,
        "NODE_SKIPPED",
        reason,
        status_before,
        "SKIPPED",
        node.get("auditId"),
    )
    _append_stream_event(
        run,
        "NODE_SKIPPED",
        reason,
        agent_id,
        {"killSwitch": kill_switch},
        node.get("auditId"),
    )


def _sync_guardrail_hub_prior_outputs(prior_outputs: Dict[str, Any], output: Any) -> None:
    if not isinstance(output, dict):
        return
    prior_outputs["guardrail_hub"] = output
    prior_outputs["guardrail_hub_output"] = output
    legacy_outputs = output.get("legacyAgentOutputs")
    if isinstance(legacy_outputs, dict):
        for key, value in legacy_outputs.items():
            if isinstance(value, dict):
                marked_value = _guardrail_legacy_module_result(key, value)
                prior_outputs[key] = marked_value
                prior_outputs[f"{key}_output"] = marked_value
    for child_key, legacy_key in (("dvg", "dvg_gate"), ("risk", "risk_firewall"), ("atrade", "trade_micro")):
        child = output.get(child_key)
        if isinstance(child, dict):
            marked_child = _guardrail_legacy_module_result(legacy_key, child)
            prior_outputs[legacy_key] = marked_child
            prior_outputs[f"{legacy_key}_output"] = marked_child
            if legacy_key == "dvg_gate":
                marked_dvg_alias = _guardrail_legacy_module_result("dvg_evidence_gate", child)
                prior_outputs["dvg_evidence_gate"] = marked_dvg_alias
                prior_outputs["dvg_evidence_gate_output"] = marked_dvg_alias
            if legacy_key == "trade_micro":
                marked_atrade_alias = _guardrail_legacy_module_result("atrade", child)
                prior_outputs["atrade"] = marked_atrade_alias
                prior_outputs["atrade_output"] = marked_atrade_alias


def _guardrail_node_status(run: Dict[str, Any]) -> str:
    guardrail = run.get("guardrailHub") if isinstance(run.get("guardrailHub"), dict) else {}
    kill_switch = guardrail.get("killSwitch") if isinstance(guardrail.get("killSwitch"), dict) else run.get("killSwitch", {})
    if isinstance(kill_switch, dict) and kill_switch.get("active"):
        return "FAIL" if kill_switch.get("level") == "COMPLIANCE" else "BLOCK_BUY"
    status = str(guardrail.get("status") or "WARN")
    if status == "BLOCK":
        return "BLOCK_BUY"
    if status in {"PASS", "WARN", "REVIEW_ONLY", "BLOCK_BUY", "FAIL"}:
        return status
    return "WARN"


def _record_result(
    run: Dict[str, Any],
    node: Dict[str, Any],
    result: LLMRunResult,
    resolved_status: str,
) -> None:
    node["isRunning"] = False
    if result.status == "FAILED":
        node["status"] = "WARN" if resolved_status == "PASS" else resolved_status
        node.setdefault("downgradeReasons", []).append(result.error or "LLM runner failed.")
    else:
        node["status"] = resolved_status

    node["duration"] = max(node.get("duration", 0), result.latency_ms)
    node["rawJson"] = {
        **node.get("rawJson", {}),
        "llmRunner": result.to_public_dict(),
    }
    if result.parsed_json is not None:
        node["rawJson"]["llmOutput"] = result.parsed_json
    elif result.content:
        node["rawJson"]["llmOutputText"] = result.content

    if result.status == "COMPLETED":
        node["outputSummary"] = _summary_from_result(node["id"], result, node.get("outputSummary", ""))
    elif result.status == "SKIPPED":
        node["outputSummary"] = f"{node.get('outputSummary', '')} LLM skipped: {result.error}".strip()
    else:
        node["outputSummary"] = f"{node.get('outputSummary', '')} LLM failed: {result.error}".strip()

    run["llmTrace"].append(
        {
            "nodeId": node["id"],
            "status": result.status,
            "profileId": result.profile_id,
            "model": result.model,
            "latencyMs": result.latency_ms,
            "usage": result.usage or {},
            "promptTokens": _usage_value(result.usage, "prompt_tokens", "input_tokens", "promptTokens", "inputTokens"),
            "completionTokens": _usage_value(result.usage, "completion_tokens", "output_tokens", "completionTokens", "outputTokens"),
            "totalTokens": _usage_value(result.usage, "total_tokens", "totalTokens"),
            "error": result.error,
            "timestamp": _now(),
        }
    )


def _summary_from_result(agent_id: str, result: LLMRunResult, fallback: str) -> str:
    if isinstance(result.parsed_json, dict):
        status = result.parsed_json.get("status")
        audit_id = result.parsed_json.get("audit_id") or result.parsed_json.get("auditId")
        if status:
            return f"LLM completed for {agent_id}: status={status}; audit={audit_id or 'N/A'}."
    if result.content:
        compact = " ".join(result.content.split())
        return compact[:240]
    return fallback or f"LLM completed for {agent_id}."


def _ensure_quant_engine_dict(run: Dict[str, Any]) -> Dict[str, Any]:
    quant_engine = run.get("quantEngine")
    if isinstance(quant_engine, dict):
        return quant_engine
    quant_engine = {}
    run["quantEngine"] = quant_engine
    return quant_engine


def _canonical_paper_trading_output(value: Any) -> Dict[str, Any]:
    output = dict(value) if isinstance(value, dict) else {}
    raw_warnings = output.get("warnings")
    if isinstance(raw_warnings, list):
        warnings = list(raw_warnings)
    elif raw_warnings:
        warnings = [str(raw_warnings)]
    else:
        warnings = []

    def add_warning(warning: str) -> None:
        if warning not in warnings:
            warnings.append(warning)

    def normalize_action(item: Any) -> Any:
        if not isinstance(item, str):
            return item
        action = item.strip().upper()
        if not action:
            return item
        if action.startswith("SIM_"):
            return action
        add_warning("non_sim_paper_action_suppressed")
        return "SIM_HOLD"

    if output.get("simulation_only") is False or output.get("simulationOnly") is False:
        add_warning("simulation_only_boundary_restored")
    if output.get("is_real_trade") is True or output.get("isRealTrade") is True:
        add_warning("real_trade_boundary_suppressed")

    for key in PAPER_TRADING_ACTION_KEYS:
        if key in output:
            output[key] = normalize_action(output.get(key))

    for key in PAPER_TRADING_NAMESPACE_KEYS:
        namespace = output.get(key)
        if isinstance(namespace, str) and namespace.strip() and namespace.strip() != SIM_ORDER_NAMESPACE:
            add_warning("non_sim_order_namespace_suppressed")
        if key in output:
            output[key] = SIM_ORDER_NAMESPACE

    for list_key in ("simulationActions", "simulation_actions"):
        actions = output.get(list_key)
        if not isinstance(actions, list):
            continue
        normalized_actions = []
        for item in actions:
            if not isinstance(item, dict):
                normalized_actions.append(item)
                continue
            normalized_item = dict(item)
            for key in PAPER_TRADING_ACTION_KEYS:
                if key in normalized_item:
                    normalized_item[key] = normalize_action(normalized_item.get(key))
            for key in PAPER_TRADING_NAMESPACE_KEYS:
                namespace = normalized_item.get(key)
                if isinstance(namespace, str) and namespace.strip() and namespace.strip() != SIM_ORDER_NAMESPACE:
                    add_warning("non_sim_order_namespace_suppressed")
                if key in normalized_item:
                    normalized_item[key] = SIM_ORDER_NAMESPACE
            normalized_actions.append(normalized_item)
        output[list_key] = normalized_actions

    output["simulation_only"] = True
    output["is_real_trade"] = False
    output["simulationOnly"] = True
    output["isRealTrade"] = False
    output["allowed_order_namespace"] = SIM_ORDER_NAMESPACE
    if warnings:
        output["warnings"] = warnings
    return output


def _apply_agent_module_output_to_run(
    run: Dict[str, Any],
    agent_id: str,
    agent_result: Any,
) -> None:
    result = agent_result.to_dict()
    if agent_id == "guardrail_hub":
        data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
        run["guardrailHub"] = {**(run.get("guardrailHub") if isinstance(run.get("guardrailHub"), dict) else {}), **data}
        dvg_data = data.get("dvg") if isinstance(data.get("dvg"), dict) else {}
        risk_data = data.get("risk") if isinstance(data.get("risk"), dict) else {}
        atrade_data = data.get("atrade") if isinstance(data.get("atrade"), dict) else {}
        if dvg_data:
            run["dvg"] = {**(run.get("dvg") if isinstance(run.get("dvg"), dict) else {}), **dvg_data}
            quant_engine = _ensure_quant_engine_dict(run)
            if dvg_data.get("quantEngineMode"):
                quant_engine["mode"] = dvg_data["quantEngineMode"]
            if dvg_data.get("parameterProfile"):
                quant_engine["parameterProfile"] = dvg_data["parameterProfile"]
            if "ignoredMissingData" in dvg_data:
                quant_engine["ignoredMissingData"] = list(dvg_data.get("ignoredMissingData") or [])
        if risk_data:
            run["risk"] = {**(run.get("risk") if isinstance(run.get("risk"), dict) else {}), **risk_data}
        if atrade_data:
            run["atrade"] = {**(run.get("atrade") if isinstance(run.get("atrade"), dict) else {}), **atrade_data}
            run["portfolio"] = {**(run.get("portfolio") if isinstance(run.get("portfolio"), dict) else {}), **atrade_data}
        kill_switch = data.get("killSwitch")
        if isinstance(kill_switch, dict):
            run["killSwitch"] = kill_switch
        legacy_results = data.get("legacyModuleResults")
        if isinstance(legacy_results, dict):
            module_results = run.setdefault("agentModuleResults", {})
            for legacy_id, legacy_result in legacy_results.items():
                if isinstance(legacy_result, dict):
                    module_results[legacy_id] = _guardrail_legacy_module_result(legacy_id, legacy_result)
    elif agent_id in ("dvg_evidence_gate", "dvg_gate"):
        data = result.get("data", {})
        run["dvg"] = {**run.get("dvg", {}), **data}
        if isinstance(data, dict):
            quant_engine = _ensure_quant_engine_dict(run)
            if data.get("quantEngineMode"):
                quant_engine["mode"] = data["quantEngineMode"]
            if data.get("parameterProfile"):
                quant_engine["parameterProfile"] = data["parameterProfile"]
            if "ignoredMissingData" in data:
                quant_engine["ignoredMissingData"] = list(data.get("ignoredMissingData") or [])
    elif agent_id == "hallucination_guardrail":
        run["hallucinationGuardrail"] = {**run.get("hallucinationGuardrail", {}), **result.get("data", {})}
    elif agent_id == "risk_firewall" and result.get("hard_stop"):
        run["risk"] = {**run.get("risk", {}), "hardStop": True}
    elif agent_id == "flash_crash":
        run["flashCrash"] = {**run.get("flashCrash", {}), **result.get("data", {})}
    elif agent_id == "market_regime":
        apply_market_regime_data(run, result.get("data", {}))
    elif agent_id == "market_technical_analyst":
        apply_market_technical_data(run, result.get("data", {}))
    elif agent_id == "quant_core":
        apply_quant_core_data(run, result.get("data", {}))
    elif agent_id == "sector_rotation":
        run["sectorRotation"] = {**run.get("sectorRotation", {}), **result.get("data", {})}
    elif agent_id == "technical_kline_analyst":
        apply_technical_kline_data(run, result.get("data", {}))
    elif agent_id == "bottom_research":
        data = result.get("data", {})
        current_mfe = run.get("mfeMaeResearch") if isinstance(run.get("mfeMaeResearch"), dict) else {}
        merged = {**current_mfe, **data} if isinstance(data, dict) else current_mfe
        run["mfeMaeResearch"] = merged
        current = run.get("bottomResearch") if isinstance(run.get("bottomResearch"), dict) else {}
        run["bottomResearch"] = {**current, **merged}
    elif agent_id == "factor_slicing":
        data = result.get("data", {})
        run["factorSlicing"] = {**run.get("factorSlicing", {}), **data}
        if isinstance(data, dict) and data.get("quantEngineMode"):
            quant_engine = _ensure_quant_engine_dict(run)
            quant_engine["mode"] = data["quantEngineMode"]
            if data.get("parameterProfile"):
                quant_engine["parameterProfile"] = data["parameterProfile"]
    elif agent_id == "factor_engine":
        data = result.get("data", {})
        run["factorEngine"] = {**run.get("factorEngine", {}), **data}
        if isinstance(data, dict) and data.get("quantEngineMode"):
            quant_engine = _ensure_quant_engine_dict(run)
            quant_engine["mode"] = data["quantEngineMode"]
            if data.get("parameterProfile"):
                quant_engine["parameterProfile"] = data["parameterProfile"]
    elif agent_id == "calculation_authority":
        run["calculationAuthority"] = {**run.get("calculationAuthority", {}), **result.get("data", {})}
    elif agent_id in ("qiam", "quant_engine"):
        data = result.get("data", {})
        run["qiam"] = {**run.get("qiam", {}), **data}
        if isinstance(data, dict):
            quant_engine = _ensure_quant_engine_dict(run)
            if data.get("quantEngineMode"):
                quant_engine["mode"] = data["quantEngineMode"]
            if data.get("parameterProfile"):
                quant_engine["parameterProfile"] = data["parameterProfile"]
            if "ignoredMissingData" in data:
                quant_engine["ignoredMissingData"] = list(data.get("ignoredMissingData") or [])
    elif agent_id == "simulation_agent":
        run["simulationAgent"] = {**run.get("simulationAgent", {}), **result.get("data", {})}
    elif agent_id == "portfolio":
        run["portfolio"] = {**run.get("portfolio", {}), **result.get("data", {})}
    elif agent_id in ("atrade", "trade_micro"):
        run["atrade"] = {**run.get("atrade", {}), **result.get("data", {})}
        run["portfolio"] = {**run.get("portfolio", {}), **result.get("data", {})}
    elif agent_id == "execution":
        run["execution"] = {**run.get("execution", {}), **result.get("data", {})}
    elif agent_id == "signalops":
        run["signalOps"] = {**run.get("signalOps", {}), **result.get("data", {})}
    elif agent_id == "paper_trading_agent":
        current = run.get("paperTrading") if isinstance(run.get("paperTrading"), dict) else {}
        data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
        run["paperTrading"] = _canonical_paper_trading_output({**current, **data})
    elif agent_id == "review_agent":
        run["reviewAgent"] = {**run.get("reviewAgent", {}), **result.get("data", {})}
    elif agent_id == "error_ledger":
        run["errorLedger"] = {**run.get("errorLedger", {}), **result.get("data", {})}
    elif agent_id in ("meta_agent", "meta_review"):
        run["metaAgent"] = {**run.get("metaAgent", {}), **result.get("data", {})}
    elif agent_id == "state_serialization":
        run["stateSnapshot"] = {**run.get("stateSnapshot", {}), **result.get("data", {})}
    elif agent_id == "final_writer":
        run["finalWriter"] = {**run.get("finalWriter", {}), **result.get("data", {})}
    elif agent_id in ("data_fetch", "data_engine", "data_reliability_engine"):
        data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
        current = run.get("dataReliabilityEngine") if isinstance(run.get("dataReliabilityEngine"), dict) else {}
        run["dataReliabilityEngine"] = {**current, **data}
        if isinstance(data.get("dataSources"), dict):
            run["dataSources"] = data["dataSources"]


def _canonical_market_technical_output(output: Any, module_data: Any) -> Any:
    if (
        isinstance(output, dict)
        and isinstance(output.get("market"), dict)
        and isinstance(output.get("technicalKline"), dict)
    ):
        return output
    return module_data


def _canonical_quant_core_output(output: Any, module_data: Any) -> Any:
    # Quant Core is a rule-engine orchestration node. LLM output may be useful
    # as trace text, but it must not override deterministic guardrail fields.
    return module_data


def _quant_core_legacy_prior_output(value: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(value)
    result["legacyCompatibilityOnly"] = True
    result["canonicalNode"] = "quant_core"
    result["activeNode"] = False
    return result


def _mirror_quant_core_prior_outputs(prior_outputs: Dict[str, Any], output: Any) -> None:
    if not isinstance(output, dict):
        return
    legacy_outputs = output.get("legacyAgentOutputs")
    if not isinstance(legacy_outputs, dict):
        legacy_outputs = {}
    for key, value in legacy_outputs.items():
        if isinstance(value, dict):
            prior_outputs[key] = _quant_core_legacy_prior_output(value)
    if isinstance(output.get("marketTechnical"), dict):
        prior_outputs["market_technical_analyst"] = _quant_core_legacy_prior_output(output["marketTechnical"])
    mfe_mae_research = output.get("mfeMaeResearch") if isinstance(output.get("mfeMaeResearch"), dict) else output.get("bottomResearch")
    if isinstance(mfe_mae_research, dict):
        mirrored_mfe_mae_research = _quant_core_legacy_prior_output(mfe_mae_research)
        prior_outputs["mfe_mae_path_research"] = mirrored_mfe_mae_research
        prior_outputs["bottom_research"] = mirrored_mfe_mae_research
    if isinstance(output.get("qiam"), dict):
        mirrored_qiam = _quant_core_legacy_prior_output(output["qiam"])
        prior_outputs["quant_engine"] = mirrored_qiam
        prior_outputs["qiam"] = mirrored_qiam
    if isinstance(output.get("scenario"), dict):
        prior_outputs["scenario_engine"] = _quant_core_legacy_prior_output(output["scenario"])


def _mirror_data_reliability_prior_outputs(prior_outputs: Dict[str, Any], output: Any) -> None:
    if not isinstance(output, dict):
        return
    prior_outputs["data_reliability_engine"] = output
    prior_outputs["data_reliability_engine_output"] = output


def _run_quant_engine_submodules(run: Dict[str, Any], prior_outputs: Dict[str, Any]) -> None:
    for sub_agent_id in ("factor_slicing", "factor_engine", "calculation_authority"):
        sub_result = run_agent_module(sub_agent_id, run, prior_outputs)
        result_dict = sub_result.to_dict()
        run.setdefault("agentModuleResults", {})[sub_agent_id] = result_dict
        _apply_agent_module_output_to_run(run, sub_agent_id, sub_result)
        data = result_dict.get("data")
        if isinstance(data, dict):
            prior_outputs[sub_agent_id] = data


def _apply_llm_output_to_run(
    run: Dict[str, Any],
    agent_id: str,
    result: LLMRunResult,
) -> None:
    output = result.parsed_json
    if result.status != "COMPLETED":
        return

    if agent_id == "orchestrator" and isinstance(output, dict):
        run.setdefault("orchestratorPlan", {})["llmOutput"] = output
        return

    if agent_id in {"qiam", "quant_engine"} and isinstance(output, dict):
        _apply_qiam_output(run, output)
        return

    if agent_id == "final_writer":
        _apply_final_writer_output(run, output, result.content)


def _apply_qiam_output(
    run: Dict[str, Any],
    output: Dict[str, Any],
) -> None:
    qiam = run.setdefault("qiam", {})

    direct_fields = {
        "calculationMode": ("calculation_mode", "calculationMode"),
        "discountFactor": ("discount_factor", "discountFactor"),
        "missingData": ("missing_data", "missingData"),
        "downgradeReasons": ("downgrade_reasons", "downgradeReasons"),
    }
    for target, source_keys in direct_fields.items():
        value = _first_present(output, source_keys)
        if value is not None:
            qiam[target] = value

    dvg_permission = _first_present(output, ("dvg_permission", "dvgPermission"))
    if dvg_permission is not None:
        qiam["dvgPermission"] = dvg_permission in {"ALLOW", "ALLOW_WITH_DISCOUNT", True}

    raw_suitability = _normalize_suitability(_first_present(output, ("raw_buy_suitability", "rawBuySuitability")))
    final_suitability = _normalize_suitability(_first_present(output, ("final_buy_suitability", "finalBuySuitability")))
    if raw_suitability:
        qiam["rawBuySuitability"] = raw_suitability
    if final_suitability:
        qiam["finalBuySuitability"] = final_suitability

    up, sideways, down = _normalize_probability_bands(
        _first_present(output, ("probability_band_up", "probabilityBandUp")),
        _first_present(output, ("probability_band_sideways", "probabilityBandSideways")),
        _first_present(output, ("probability_band_down", "probabilityBandDown")),
        qiam,
    )
    qiam["probabilityBandUp"] = up
    qiam["probabilityBandSideways"] = sideways
    qiam["probabilityBandDown"] = down

    qiam["expectedPayoffQuality"] = _score_value(
        _first_present(output, ("expected_payoff_quality", "expectedPayoffQuality")),
        {"POSITIVE": 0.75, "NEUTRAL": 0.5, "NEGATIVE": 0.2, "UNKNOWN": 0.0},
        qiam.get("expectedPayoffQuality", 0),
    )
    qiam["regimeFit"] = _score_value(
        _first_present(output, ("regime_fit", "regimeFit")),
        {"MATCH": 0.75, "MISMATCH": 0.25, "UNKNOWN": 0.0},
        qiam.get("regimeFit", 0),
    )
    qiam["momentumQuality"] = _score_value(
        _first_present(output, ("momentum_quality", "momentumQuality")),
        {"CLEAN": 0.75, "CROWDED": 0.45, "FAKE_BREAKOUT": 0.25, "EXHAUSTED": 0.2, "UNKNOWN": 0.0},
        qiam.get("momentumQuality", 0),
    )
    qiam["volatilityCondition"] = _score_value(
        _first_present(output, ("volatility_condition", "volatilityCondition")),
        {"SUPPORTIVE": 0.75, "NEUTRAL": 0.5, "DANGEROUS": 0.15, "UNKNOWN": 0.0},
        qiam.get("volatilityCondition", 0),
    )
    qiam["liquidityAdjustedSignal"] = _score_value(
        _first_present(output, ("liquidity_adjusted_signal", "liquidityAdjustedSignal")),
        {"PASS": 0.75, "WEAK": 0.4, "FAIL": 0.15, "UNKNOWN": 0.0},
        qiam.get("liquidityAdjustedSignal", 0),
    )
    qiam["modelConfidenceRaw"] = _confidence_score(
        _first_present(output, ("model_confidence_raw", "modelConfidenceRaw")),
        qiam.get("modelConfidenceRaw", 0),
    )
    qiam["modelConfidenceFinal"] = _confidence_score(
        _first_present(output, ("model_confidence_final", "modelConfidenceFinal")),
        qiam.get("modelConfidenceFinal", 0),
    )
    qiam["overfitRisk"] = _score_value(
        _first_present(output, ("overfit_risk", "overfitRisk")),
        {"LOW": 0.2, "MEDIUM": 0.5, "HIGH": 0.85, "UNKNOWN": 0.0},
        qiam.get("overfitRisk", 0),
    )
    qiam["distributionDrift"] = _score_value(
        _first_present(output, ("distribution_drift", "distributionDrift")),
        {"NONE": 0.1, "MILD": 0.4, "SEVERE": 0.85, "UNKNOWN": 0.0},
        qiam.get("distributionDrift", 0),
    )
    qiam["decisionEffect"] = _score_value(
        _first_present(output, ("decision_effect", "decisionEffect")),
        {"UPGRADE_CONFIDENCE": 0.75, "KEEP": 0.5, "DOWNGRADE": 0.25, "BLOCK_BUY": 0.0},
        qiam.get("decisionEffect", 0),
    )
    qiam["llmOutput"] = output


def _first_present(source: Dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in source:
            return source[key]
    return None


def _normalize_suitability(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.upper()
    if normalized == "UNFAVORABLE":
        return "REVIEW_ONLY"
    if normalized in {"FAVORABLE", "NEUTRAL", "REVIEW_ONLY", "BLOCK_BUY"}:
        return normalized
    return None


def _normalize_probability_bands(
    up_value: Any,
    sideways_value: Any,
    down_value: Any,
    fallback: Dict[str, Any],
) -> tuple[float, float, float]:
    values = [
        _band_score(up_value, fallback.get("probabilityBandUp", 0)),
        _band_score(sideways_value, fallback.get("probabilityBandSideways", 0)),
        _band_score(down_value, fallback.get("probabilityBandDown", 0)),
    ]
    total = sum(values)
    if total <= 0:
        return 0.0, 0.0, 0.0
    return tuple(round(value / total, 4) for value in values)  # type: ignore[return-value]


def _band_score(value: Any, fallback: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, float(value))
    if isinstance(value, str):
        normalized = value.upper()
        if normalized == "UNKNOWN":
            if isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
                return max(0.0, float(fallback))
            return 0.0
        if normalized in {"HIGH", "MEDIUM", "LOW"}:
            return {"HIGH": 0.65, "MEDIUM": 0.35, "LOW": 0.15}[normalized]
        try:
            return max(0.0, float(normalized))
        except ValueError:
            pass
    if isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
        return max(0.0, float(fallback))
    return 0.0


def _confidence_score(value: Any, fallback: Any) -> float:
    return _score_value(value, {"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.25, "UNKNOWN": 0.0}, fallback)


def _score_value(value: Any, mapping: Dict[str, float], fallback: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        normalized = value.upper()
        if normalized == "UNKNOWN":
            return _score_fallback(fallback)
        if normalized in mapping:
            return mapping[normalized]
        try:
            return max(0.0, min(1.0, float(normalized)))
        except ValueError:
            pass
    return _score_fallback(fallback)


def _score_fallback(fallback: Any) -> float:
    if isinstance(fallback, (int, float)) and not isinstance(fallback, bool):
        return max(0.0, min(1.0, float(fallback)))
    return 0.0


def _apply_final_writer_output(
    run: Dict[str, Any],
    output: Any,
    content: str,
) -> None:
    final_writer = run.setdefault(
        "finalWriter",
        {
            "mode": run.get("killSwitch", {}).get("finalWriterMode", "NORMAL"),
            "sections": [],
            "finalAction": run.get("finalAction", "WAIT"),
            "humanConfirmationRequired": True,
            "auditId": "AUD_FINAL_WRITER_LLM",
        },
    )

    proposed_action = _extract_final_action(output, content, run.get("finalAction", "WAIT"))
    safe_action = _safe_final_action(run, proposed_action)

    if isinstance(output, dict):
        display_output = _display_final_writer_output(output, safe_action, proposed_action)
        if isinstance(display_output.get("sections"), list) and display_output["sections"]:
            sections = _normalize_final_sections(display_output["sections"], safe_action)
        else:
            sections = _sections_from_final_writer_dict(display_output, safe_action)
        if proposed_action != safe_action:
            sections.insert(
                0,
                {
                    "title": "动作校验",
                    "content": f"LLM 曾输出 {proposed_action}，但上游门禁和执行权限只允许 {safe_action}；页面最终动作已按规则降级。",
                    "riskLevel": "HIGH",
                    "requiresConfirmation": True,
                },
            )
        final_writer["sections"] = sections
        final_writer["finalAction"] = safe_action
        run["finalAction"] = safe_action
        if proposed_action != safe_action:
            final_writer["llmProposedAction"] = proposed_action
            final_writer["actionDowngradeReason"] = "LLM 输出动作超过上游门禁或执行权限，已按规则降级。"
        final_writer["llmOutput"] = output
        return

    if content:
        parsed = _json_from_fenced_text(content)
        if isinstance(parsed, dict):
            _apply_final_writer_output(run, parsed, "")
            final_writer["llmRawText"] = content
            return
        final_writer["finalAction"] = safe_action
        run["finalAction"] = safe_action
        final_writer["sections"] = _fallback_final_sections(run, safe_action)
        final_writer["llmRawText"] = content


def _extract_final_action(output: Any, content: str, fallback: str) -> str:
    if isinstance(output, dict):
        direct = output.get("final_action") or output.get("finalAction") or output.get("当前动作")
        if direct:
            return _normalize_final_action(str(direct), fallback)
        conclusion = output.get("结论")
        if isinstance(conclusion, dict):
            nested = conclusion.get("当前动作") or conclusion.get("finalAction") or conclusion.get("final_action")
            if nested:
                return _normalize_final_action(str(nested), fallback)
    if content:
        match = re.search(r'"(?:当前动作|finalAction|final_action)"\s*:\s*"([^"]+)"', content)
        if match:
            return _normalize_final_action(match.group(1), fallback)
    return fallback or "WAIT"


def _normalize_final_action(value: str, fallback: str) -> str:
    normalized = value.strip().upper()
    aliases = {
        "等待": "WAIT",
        "观察": "WAIT",
        "继续持有": "HOLD",
        "持有": "HOLD",
        "仅复核": "REVIEW_ONLY",
        "仅审查": "REVIEW_ONLY",
        "买入候选": "BUY_CANDIDATE",
        "加仓候选": "ADD_CANDIDATE",
    }
    allowed = {
        "REJECT",
        "REVIEW_ONLY",
        "WAIT",
        "HOLD",
        "REDUCE",
        "LIGHT_WATCH",
        "BUY_CANDIDATE",
        "ADD_CANDIDATE",
        "DEFENSIVE",
        "SIGNAL_ONLY",
        "PAPER_TEST_ONLY",
        "FAILED",
    }
    return aliases.get(value.strip(), normalized if normalized in allowed else fallback or "WAIT")


def _safe_final_action(run: Dict[str, Any], proposed_action: str) -> str:
    if run.get("status") == "FAILED":
        return "FAILED"

    action = _normalize_final_action(proposed_action, run.get("finalAction", "WAIT"))
    execution = run.get("execution", {}) if isinstance(run.get("execution"), dict) else {}
    dvg = run.get("dvg", {}) if isinstance(run.get("dvg"), dict) else {}
    qiam = run.get("qiam", {}) if isinstance(run.get("qiam"), dict) else {}
    portfolio = run.get("portfolio", {}) if isinstance(run.get("portfolio"), dict) else {}
    kill_switch = run.get("killSwitch", {}) if isinstance(run.get("killSwitch"), dict) else {}

    allowed = set(execution.get("allowedActions") or [])
    blocked = set(execution.get("prohibitedActions") or [])
    blocked.update(execution.get("forbiddenActions") or [])
    blocked.update(kill_switch.get("blockedPaths") or [])

    if kill_switch.get("active") and action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        return "WAIT"
    if action in blocked:
        return "WAIT"
    if action in {"BUY_CANDIDATE", "ADD_CANDIDATE"}:
        if action not in allowed:
            return "WAIT"
        if qiam.get("finalBuySuitability") != "FAVORABLE":
            return "WAIT"
        if dvg.get("allowedOutputLevel") != "FULL" or dvg.get("finalDecisionCap") in {"WAIT", "REVIEW_ONLY", "BLOCK_BUY", "REJECT"}:
            return "WAIT"
        if execution.get("executionReachability") != "REACHABLE":
            return "WAIT"
        if not portfolio.get("allowAddPosition", False):
            return "WAIT"
    return action


def _normalize_final_sections(sections: List[Any], safe_action: str) -> List[Dict[str, Any]]:
    normalized = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("标题") or "结论分项")
        content = item.get("content") or item.get("正文") or item.get("summary") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        normalized.append(
            {
                "title": title,
                "content": content,
                "riskLevel": item.get("riskLevel") or item.get("risk_level") or "MEDIUM",
                "requiresConfirmation": item.get("requiresConfirmation", True),
            }
        )
    return normalized or _fallback_final_sections({}, safe_action)


def _sections_from_final_writer_dict(output: Dict[str, Any], safe_action: str) -> List[Dict[str, Any]]:
    sections = []
    skipped = {"final_action", "finalAction", "sections"}
    for key, value in output.items():
        if key in skipped:
            continue
        if isinstance(value, (dict, list)):
            content = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            content = str(value)
        sections.append(
            {
                "title": str(key),
                "content": content,
                "riskLevel": "MEDIUM",
                "requiresConfirmation": True,
            }
        )
    if not sections:
        sections = _fallback_final_sections({}, safe_action)
    return sections


def _display_final_writer_output(output: Dict[str, Any], safe_action: str, proposed_action: str) -> Dict[str, Any]:
    try:
        display_output = json.loads(json.dumps(output, ensure_ascii=False, default=str))
    except Exception:
        display_output = dict(output)
    if proposed_action == safe_action:
        return display_output
    conclusion = display_output.get("结论")
    if isinstance(conclusion, dict):
        conclusion["LLM原始动作"] = proposed_action
        conclusion["当前动作"] = safe_action
        conclusion["动作校验"] = "已按上游门禁和执行权限降级，原始动作不作为最终结论。"
    elif "finalAction" in display_output or "final_action" in display_output:
        display_output["llmProposedAction"] = proposed_action
        display_output["finalAction"] = safe_action
        display_output["final_action"] = safe_action
    return display_output


def _fallback_final_sections(run: Dict[str, Any], safe_action: str) -> List[Dict[str, Any]]:
    qiam = run.get("qiam", {}) if isinstance(run.get("qiam"), dict) else {}
    dvg = run.get("dvg", {}) if isinstance(run.get("dvg"), dict) else {}
    execution = run.get("execution", {}) if isinstance(run.get("execution"), dict) else {}
    return [
        {
            "title": "最终动作",
            "content": f"最终动作按上游门禁校验为 {safe_action}。该动作不是自动下单指令，必须人工确认。",
            "riskLevel": "MEDIUM",
            "requiresConfirmation": True,
        },
        {
            "title": "上游依据",
            "content": "DVG 可靠性: {}; QIAM 最终适宜性: {}; 执行可达性: {}; 允许动作: {}。".format(
                dvg.get("dataReliability", "UNKNOWN"),
                qiam.get("finalBuySuitability", "UNKNOWN"),
                execution.get("executionReachability", "UNKNOWN"),
                execution.get("allowedActions", []),
            ),
            "riskLevel": "MEDIUM",
            "requiresConfirmation": True,
        },
    ]


def _json_from_fenced_text(content: str) -> Any:
    compact = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", compact, re.S | re.I)
    if fenced:
        compact = fenced.group(1).strip()
    try:
        return json.loads(compact)
    except Exception:
        return None


def _node_finish_message(node: Dict[str, Any], result: LLMRunResult) -> str:
    name = node.get("name", node.get("id", "agent"))
    if result.status == "COMPLETED":
        return f"{name} LLM runner completed."
    if result.status == "SKIPPED":
        return f"{name} LLM runner skipped: {result.error}"
    return f"{name} LLM runner failed: {result.error}"


def _usage_value(usage: Dict[str, Any] | None, *keys: str) -> int:
    if not usage:
        return 0
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return 0


def _append_stream_event(
    run: Dict[str, Any],
    event_type: str,
    message: str,
    node_id: str | None = None,
    payload: Dict[str, Any] | None = None,
    audit_id: str | None = None,
) -> None:
    run.setdefault("streamEvents", []).append(
        {
            "event_type": event_type,
            "run_id": run.get("runId", ""),
            "node_id": node_id,
            "message": message,
            "payload": payload or {},
            "audit_id": audit_id or f"AUD_{event_type}",
            "timestamp": _now(),
        }
    )


def _append_audit(
    run: Dict[str, Any],
    node: str,
    event_type: str,
    message: str,
    status_before: str,
    status_after: str,
    audit_id: str | None,
) -> None:
    run.setdefault("auditLog", []).append(
        {
            "timestamp": _now(),
            "runId": run.get("runId", ""),
            "node": node,
            "eventType": event_type,
            "message": message,
            "statusBefore": status_before,
            "statusAfter": status_after,
            "inputHash": f"hash-input-{node}",
            "outputHash": f"hash-output-{node}-{event_type}",
            "auditId": audit_id or f"AUD_{node}_{event_type}",
        }
    )


def _save_run_snapshot(run: Dict[str, Any]) -> None:
    try:
        save_run(run)
    except Exception:
        pass


def _now() -> str:
    return datetime.now().isoformat()
