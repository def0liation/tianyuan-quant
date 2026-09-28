from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PLAN_ONLY_EXECUTION_MODE = "PLAN_ONLY_NO_EXECUTION"
READ_ONLY_PERMISSION_MODE = "READ_ONLY_NO_CODE"
PLUGIN_OBSERVATION_NODE_TYPE = "plugin_observation"
NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON = (
    "Read-only plugin observation recorded; no Agent or LLM execution required."
)


def is_non_executable_plugin_observation(node: Mapping[str, Any]) -> bool:
    raw_json = _mapping(node.get("rawJson"))
    dag_registration = _mapping(raw_json.get("dagRegistration"))
    permission_sandbox = _mapping(raw_json.get("permissionSandbox"))

    node_id = str(node.get("id") or "")
    node_type = str(raw_json.get("nodeType") or "").lower()
    execution_mode = str(dag_registration.get("execution_mode") or "").upper()
    permission_mode = str(permission_sandbox.get("mode") or "").upper()
    direct_execution = raw_json.get("directExecution") is True
    can_execute_code = raw_json.get("canExecuteCode") is True or node.get("canExecuteCode") is True

    is_plugin_observation = node_type == PLUGIN_OBSERVATION_NODE_TYPE or node_id.startswith("plugin:")
    is_review_only = execution_mode == PLAN_ONLY_EXECUTION_MODE or permission_mode == READ_ONLY_PERMISSION_MODE
    return is_plugin_observation and is_review_only and not direct_execution and not can_execute_code


def mark_non_executable_plugin_observation(
    node: dict[str, Any],
    *,
    observed_at: str,
    reason: str,
) -> dict[str, Any]:
    raw_json = dict(node.get("rawJson") or {})
    observation = {
        "status": "RECORDED_NO_EXECUTION",
        "reason": reason,
        "observedAt": observed_at,
        "executionMode": _mapping(raw_json.get("dagRegistration")).get("execution_mode") or PLAN_ONLY_EXECUTION_MODE,
    }
    raw_json["pluginObservation"] = observation

    node["status"] = "REVIEW_ONLY"
    node["isRunning"] = False
    node["isSkipped"] = True
    node["outputSummary"] = reason
    node["rawJson"] = raw_json
    return observation


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
