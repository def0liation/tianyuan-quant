from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence


DEFAULT_FORBIDDEN_TRADE_ACTIONS = ("BUY", "SELL", "ADD", "REDUCE", "CHASE", "AUTO_ORDER")
REQUIRED_RUNTIME_GATES = ("Risk", "DVG", "Execution", "Anti-Conclusion")
VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
RUNTIME_ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM"}
ALLOWED_PLUGIN_PERMISSIONS = {
    "read:analysis_context",
    "read:market_data",
    "read:technical_indicators",
    "read:plugin_context",
    "emit:review_note",
    "emit:dag_observation",
}
TRADE_ACTION_SCHEMA_FIELDS = (
    "action",
    "actions",
    "trade_action",
    "trade_actions",
    "allowed_actions",
    "allowed_trade_actions",
    "order_action",
    "order_actions",
)
ALLOWED_DECLARATIVE_EXECUTION_KINDS = {"declarative_review_note"}
ALLOWED_SANDBOX_EXECUTION_KINDS: set[str] = set()
PLAN_ONLY_EXECUTION_KINDS = {"controlled_dag_plan_only", "read_only_observation", ""}
BLOCKED_CODE_EXECUTION_KINDS = {"python", "node", "shell", "subprocess", "http", "container", "wasm"}
DEFAULT_SANDBOX_LIMITS = {
    "timeout_ms": 250,
    "max_input_bytes": 65536,
    "max_output_bytes": 16384,
    "max_events": 8,
}
MAX_SANDBOX_LIMITS = {
    "timeout_ms": 1000,
    "max_input_bytes": 131072,
    "max_output_bytes": 32768,
    "max_events": 20,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plugin_archived(plugin: Dict[str, Any]) -> bool:
    status = str(plugin.get("lifecycle_status") or "").upper()
    if status == "ARCHIVED":
        return True
    manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
    lifecycle = manifest.get("lifecycle") if isinstance(manifest.get("lifecycle"), dict) else {}
    return str(lifecycle.get("status") or "").upper() == "ARCHIVED" or manifest.get("archived") is True


def _agent_id(agent: Dict[str, Any], index: int) -> str:
    raw = agent.get("agent_id") or agent.get("id") or agent.get("name")
    return str(raw or f"agent_{index + 1}").strip()


def _schema_declared(schema: Any) -> bool:
    return isinstance(schema, dict) and bool(schema) and bool(str(schema.get("type", "")).strip())


def _as_upper_action_set(values: Any) -> set[str]:
    if isinstance(values, str):
        return {values.upper()}
    if isinstance(values, list):
        return {str(item).upper() for item in values}
    return set()


def _permission_values(agent: Dict[str, Any]) -> List[str]:
    permissions = agent.get("permissions")
    if not isinstance(permissions, list):
        return []
    return [str(item).strip() for item in permissions if str(item).strip()]


def _schema_failures(agent: Dict[str, Any], agent_label: str) -> List[str]:
    failures: List[str] = []
    if not _schema_declared(agent.get("input_schema")):
        failures.append(f"Plugin agent {agent_label} input_schema with a type is required.")
    if not _schema_declared(agent.get("output_schema")):
        failures.append(f"Plugin agent {agent_label} output_schema with a type is required.")
    return failures


def _permission_failures(agent: Dict[str, Any], agent_label: str) -> List[str]:
    permissions = agent.get("permissions")
    if not isinstance(permissions, list) or not _permission_values(agent):
        return [f"Plugin agent {agent_label} permissions are required."]
    blocked = [permission for permission in _permission_values(agent) if permission not in ALLOWED_PLUGIN_PERMISSIONS]
    if blocked:
        return [
            f"Plugin agent {agent_label} permission {permission} is outside the read-only plugin sandbox."
            for permission in blocked
        ]
    return []


def _risk_failures(agent: Dict[str, Any], agent_label: str) -> List[str]:
    risk_level = agent.get("risk_level")
    if not isinstance(risk_level, str) or not risk_level.strip():
        return [f"Plugin agent {agent_label} risk_level is required."]
    if risk_level.upper() not in VALID_RISK_LEVELS:
        return [f"Plugin agent {agent_label} risk_level must be LOW, MEDIUM, or HIGH."]
    return []


def _trade_failures(agent: Dict[str, Any], agent_label: str) -> List[str]:
    failures: List[str] = []
    if agent.get("can_emit_trade_action") is True:
        failures.append(f"Plugin agent {agent_label} cannot emit trade actions by default.")

    output_schema = agent.get("output_schema") if isinstance(agent.get("output_schema"), dict) else {}
    forbidden = _as_upper_action_set(output_schema.get("forbidden_actions"))
    missing = [action for action in DEFAULT_FORBIDDEN_TRADE_ACTIONS if action not in forbidden]
    if missing:
        failures.append(
            f"Plugin agent {agent_label} output_schema.forbidden_actions must include "
            f"{', '.join(DEFAULT_FORBIDDEN_TRADE_ACTIONS)}."
        )

    declared_trade_actions: set[str] = set()
    for field in TRADE_ACTION_SCHEMA_FIELDS:
        declared_trade_actions.update(_as_upper_action_set(output_schema.get(field)))
    illegal = sorted(declared_trade_actions.intersection(DEFAULT_FORBIDDEN_TRADE_ACTIONS))
    if illegal:
        failures.append(f"Plugin agent {agent_label} output_schema declares forbidden trade actions: {', '.join(illegal)}.")
    return failures


def validate_plugin_manifest(data: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    if not str(data.get("plugin_id", "")).strip():
        failures.append("plugin_id is required.")
    if not str(data.get("version", "")).strip():
        failures.append("version is required.")

    agents = data.get("agents", [])
    if not isinstance(agents, list):
        failures.append("agents must be a list.")
        return failures
    if not agents:
        failures.append("at least one plugin agent is required.")
        return failures

    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            failures.append(f"Plugin agent at index {index} must be an object.")
            continue
        agent_label = _agent_id(agent, index)
        if not str(agent.get("agent_id", "")).strip():
            failures.append(f"Plugin agent {agent_label} agent_id is required.")
        failures.extend(_schema_failures(agent, agent_label))
        failures.extend(_permission_failures(agent, agent_label))
        failures.extend(_risk_failures(agent, agent_label))
        failures.extend(_trade_failures(agent, agent_label))
    return failures


def _schema_status(agent: Dict[str, Any], agent_label: str) -> Dict[str, Any]:
    failures = _schema_failures(agent, agent_label)
    input_declared = _schema_declared(agent.get("input_schema"))
    output_declared = _schema_declared(agent.get("output_schema"))
    return {
        "valid": not failures,
        "input_schema_declared": input_declared,
        "output_schema_declared": output_declared,
        "failures": failures,
    }


def _agent_runtime_mode(agent: Dict[str, Any]) -> str:
    manifest = agent.get("manifest") if isinstance(agent.get("manifest"), dict) else {}
    return str(manifest.get("runtime") or "controlled_dag_plan_only")


def _permission_sandbox(agent: Dict[str, Any], *, sandbox_execution: bool = False) -> Dict[str, Any]:
    permissions = _permission_values(agent)
    blocked = [permission for permission in permissions if permission not in ALLOWED_PLUGIN_PERMISSIONS]
    allowed = [permission for permission in permissions if permission in ALLOWED_PLUGIN_PERMISSIONS]
    return {
        "mode": "SANDBOXED_JSON_STDIO" if sandbox_execution else "READ_ONLY_NO_CODE",
        "allowed": bool(permissions) and not blocked,
        "allowed_permissions": allowed,
        "blocked_permissions": blocked,
        "code_execution": "SUBPROCESS_JSON_STDIO" if sandbox_execution else "DISABLED",
        "filesystem_access": "TEMP_CWD_ONLY" if sandbox_execution else "DENIED",
        "network_access": "DENIED_BY_CONTRACT" if sandbox_execution else "DENIED",
    }


def _risk_gate(agent: Dict[str, Any]) -> Dict[str, Any]:
    risk_level = str(agent.get("risk_level", "")).upper()
    block_reasons: List[str] = []
    if risk_level not in VALID_RISK_LEVELS:
        block_reasons.append("risk_level is missing or invalid.")
    elif risk_level not in RUNTIME_ALLOWED_RISK_LEVELS:
        block_reasons.append("HIGH risk plugin agents require manual review before runtime registration.")
    if agent.get("can_emit_trade_action") is True:
        block_reasons.append("trade action emission is disabled for plugin agents.")
    return {
        "risk_level": risk_level or "UNKNOWN",
        "allowed": not block_reasons,
        "required_gates": list(REQUIRED_RUNTIME_GATES),
        "forbidden_trade_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
        "trade_actions_allowed": False,
        "block_reasons": block_reasons,
    }


def _agent_contract_failures(agent: Dict[str, Any], agent_label: str) -> List[str]:
    failures: List[str] = []
    failures.extend(_schema_failures(agent, agent_label))
    failures.extend(_permission_failures(agent, agent_label))
    failures.extend(_risk_failures(agent, agent_label))
    failures.extend(_trade_failures(agent, agent_label))
    risk_gate = _risk_gate(agent)
    failures.extend(risk_gate["block_reasons"])
    return failures


def _execution_manifest(plugin: Dict[str, Any], agent: Dict[str, Any]) -> Dict[str, Any]:
    plugin_manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
    agent_manifest = agent.get("manifest") if isinstance(agent.get("manifest"), dict) else {}
    plugin_execution = plugin_manifest.get("execution") if isinstance(plugin_manifest.get("execution"), dict) else {}
    agent_execution = agent_manifest.get("execution") if isinstance(agent_manifest.get("execution"), dict) else {}
    execution = {**plugin_execution, **agent_execution}
    for key in ("runtime", "entrypoint", "command", "module", "file"):
        if key in agent_manifest and key not in execution:
            execution[key] = agent_manifest[key]
        elif key in plugin_manifest and key not in execution:
            execution[key] = plugin_manifest[key]
    if "kind" not in execution:
        execution["kind"] = agent_manifest.get("runtime") or plugin_manifest.get("runtime") or "controlled_dag_plan_only"
    return execution


def _raw_resource_limits(execution: Dict[str, Any]) -> Dict[str, Any]:
    return execution.get("resource_limits") if isinstance(execution.get("resource_limits"), dict) else {}


def _bounded_limit(execution: Dict[str, Any], key: str) -> int:
    raw_limits = _raw_resource_limits(execution)
    value = raw_limits.get(key, DEFAULT_SANDBOX_LIMITS[key])
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_SANDBOX_LIMITS[key]
    return max(1, min(parsed, MAX_SANDBOX_LIMITS[key]))


def _resource_limit_warnings(execution: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    raw_limits = _raw_resource_limits(execution)
    for key, default_value in DEFAULT_SANDBOX_LIMITS.items():
        if key not in raw_limits:
            continue
        try:
            parsed = int(raw_limits[key])
        except (TypeError, ValueError):
            warnings.append(f"resource_limits.{key} is invalid; default {default_value} is applied.")
            continue
        if parsed < 1:
            warnings.append(f"resource_limits.{key} must be positive; minimum 1 is applied.")
        elif parsed > MAX_SANDBOX_LIMITS[key]:
            warnings.append(f"resource_limits.{key} exceeds max {MAX_SANDBOX_LIMITS[key]}; capped for runtime safety.")
    return warnings


def _runtime_resource_summary(agents: List[Dict[str, Any]]) -> Dict[str, Any]:
    limits = [
        agent["execution_sandbox"]["resource_limits"]
        for agent in agents
        if isinstance(agent.get("execution_sandbox"), dict)
    ]
    if not limits:
        return {
            "quota_status": "EMPTY",
            "enabled_agent_count": 0,
            "agents_with_custom_limits": 0,
            "agents_with_limit_warnings": 0,
            "total_timeout_ms": 0,
            "total_max_input_bytes": 0,
            "total_max_output_bytes": 0,
            "total_max_events": 0,
            "max_per_agent": dict(MAX_SANDBOX_LIMITS),
            "warnings": [],
        }

    warnings = [
        warning
        for agent in agents
        for warning in agent.get("execution_sandbox", {}).get("resource_limit_warnings", [])
    ]
    return {
        "quota_status": "WARN" if warnings else "OK",
        "enabled_agent_count": len(limits),
        "agents_with_custom_limits": len(
            [
                agent
                for agent in agents
                if agent.get("execution_sandbox", {}).get("custom_resource_limits") is True
            ]
        ),
        "agents_with_limit_warnings": len(
            [
                agent
                for agent in agents
                if agent.get("execution_sandbox", {}).get("resource_limit_warnings")
            ]
        ),
        "total_timeout_ms": sum(int(limit.get("timeout_ms", 0)) for limit in limits),
        "total_max_input_bytes": sum(int(limit.get("max_input_bytes", 0)) for limit in limits),
        "total_max_output_bytes": sum(int(limit.get("max_output_bytes", 0)) for limit in limits),
        "total_max_events": sum(int(limit.get("max_events", 0)) for limit in limits),
        "max_per_agent": dict(MAX_SANDBOX_LIMITS),
        "warnings": warnings,
    }


def build_execution_sandbox_policy(plugin: Dict[str, Any], agent: Dict[str, Any]) -> Dict[str, Any]:
    plugin_id = str(plugin.get("plugin_id") or "UNKNOWN")
    agent_id = _agent_id(agent, 0)
    execution = _execution_manifest(plugin, agent)
    execution_kind = str(execution.get("kind") or "").strip().lower()
    block_reasons = _agent_contract_failures(agent, agent_id)

    has_entrypoint = bool(execution.get("entrypoint") or execution.get("command") or execution.get("module") or execution.get("file"))
    if execution_kind == "external_json_stdio":
        block_reasons.append("External JSON stdio execution is disabled until OS-level plugin sandboxing is available.")
    if has_entrypoint and execution_kind not in ALLOWED_SANDBOX_EXECUTION_KINDS:
        block_reasons.append("Arbitrary plugin entrypoints are blocked by the hot-reload sandbox.")
    if execution_kind in BLOCKED_CODE_EXECUTION_KINDS:
        block_reasons.append(f"Execution kind {execution_kind} requires an external sandbox and is currently blocked.")
    elif (
        execution_kind not in ALLOWED_DECLARATIVE_EXECUTION_KINDS
        and execution_kind not in ALLOWED_SANDBOX_EXECUTION_KINDS
        and execution_kind not in PLAN_ONLY_EXECUTION_KINDS
    ):
        block_reasons.append(f"Execution kind {execution_kind or 'UNKNOWN'} is not allowed.")
    if execution_kind in ALLOWED_SANDBOX_EXECUTION_KINDS and not has_entrypoint:
        block_reasons.append(f"Execution kind {execution_kind} requires an entrypoint or command.")

    hot_reload_allowed = execution_kind in ALLOWED_DECLARATIVE_EXECUTION_KINDS and not block_reasons
    sandbox_execution_allowed = execution_kind in ALLOWED_SANDBOX_EXECUTION_KINDS and not block_reasons
    plan_only = execution_kind in PLAN_ONLY_EXECUTION_KINDS and not hot_reload_allowed
    resource_limits = {key: _bounded_limit(execution, key) for key in DEFAULT_SANDBOX_LIMITS}
    resource_limit_warnings = _resource_limit_warnings(execution)
    schema_status = _schema_status(agent, agent_id)
    permission_sandbox = _permission_sandbox(agent, sandbox_execution=sandbox_execution_allowed)
    risk_gate = _risk_gate(agent)

    return {
        "plugin_id": plugin_id,
        "agent_id": agent_id,
        "mode": (
            "DECLARATIVE_HOT_RELOAD_SANDBOX"
            if hot_reload_allowed
            else "SANDBOXED_JSON_STDIO"
            if sandbox_execution_allowed
            else "PLAN_ONLY_NO_EXECUTION"
            if plan_only
            else "BLOCKED"
        ),
        "allowed": not block_reasons,
        "hot_reload_allowed": hot_reload_allowed,
        "execution_kind": execution_kind or "controlled_dag_plan_only",
        "code_execution": "SUBPROCESS_JSON_STDIO" if sandbox_execution_allowed else "DISABLED",
        "direct_code_execution": False,
        "filesystem_access": "TEMP_CWD_ONLY" if sandbox_execution_allowed else "DENIED",
        "network_access": "DENIED_BY_ENV_CONTRACT" if sandbox_execution_allowed else "DENIED",
        "resource_limits": resource_limits,
        "custom_resource_limits": bool(_raw_resource_limits(execution)),
        "resource_limit_warnings": resource_limit_warnings,
        "schema_validation": {
            "input_schema_required": True,
            "output_schema_required": True,
            "input_schema_declared": schema_status["input_schema_declared"],
            "output_schema_declared": schema_status["output_schema_declared"],
            "strict_output_trade_action_scan": True,
        },
        "permission_boundary": {
            "allowed_permissions": permission_sandbox["allowed_permissions"],
            "blocked_permissions": permission_sandbox["blocked_permissions"],
        },
        "risk_boundary": {
            "risk_level": risk_gate["risk_level"],
            "required_gates": risk_gate["required_gates"],
            "forbidden_trade_actions": risk_gate["forbidden_trade_actions"],
            "trade_actions_allowed": False,
        },
        "audit_required": True,
        "rollback_supported": True,
        "trade_action_hard_block": True,
        "block_reasons": block_reasons,
    }


def validate_json_schema_subset(value: Any, schema: Dict[str, Any], label: str) -> List[str]:
    failures: List[str] = []
    schema_type = str(schema.get("type") or "").lower()
    if schema_type == "object" and not isinstance(value, dict):
        return [f"{label} must be an object."]
    if schema_type == "array" and not isinstance(value, list):
        return [f"{label} must be an array."]
    if schema_type == "string" and not isinstance(value, str):
        return [f"{label} must be a string."]
    if schema_type == "number" and not isinstance(value, (int, float)):
        return [f"{label} must be a number."]
    if schema_type == "boolean" and not isinstance(value, bool):
        return [f"{label} must be a boolean."]
    if isinstance(value, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if key not in value:
                failures.append(f"{label}.{key} is required.")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, field_schema in properties.items():
            if key in value and isinstance(field_schema, dict):
                failures.extend(validate_json_schema_subset(value[key], field_schema, f"{label}.{key}"))
    return failures


def contains_forbidden_trade_action(value: Any) -> bool:
    if isinstance(value, str):
        return value.upper() in DEFAULT_FORBIDDEN_TRADE_ACTIONS
    if isinstance(value, list):
        return any(contains_forbidden_trade_action(item) for item in value)
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in TRADE_ACTION_SCHEMA_FIELDS and contains_forbidden_trade_action(item):
                return True
            if contains_forbidden_trade_action(item):
                return True
    return False


class PluginRuntimePlanner:
    def build_plan(self, plugins: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        enabled_plugins = [plugin for plugin in plugins if plugin.get("enabled") is True and not _plugin_archived(plugin)]
        agents: List[Dict[str, Any]] = []
        notes: List[str] = []
        plan_step = 1

        for plugin in enabled_plugins:
            plugin_id = str(plugin.get("plugin_id", "")).strip()
            plugin_name = str(plugin.get("name") or plugin_id)
            declared_agents = plugin.get("agents", [])
            if not isinstance(declared_agents, list) or not declared_agents:
                notes.append(f"Enabled plugin {plugin_id or 'UNKNOWN'} has no runtime agents.")
                continue

            for index, agent in enumerate(declared_agents):
                if not isinstance(agent, dict):
                    notes.append(f"Enabled plugin {plugin_id or 'UNKNOWN'} contains a non-object agent declaration.")
                    continue
                agent_id = _agent_id(agent, index)
                schema_status = _schema_status(agent, agent_id)
                execution_sandbox = build_execution_sandbox_policy(plugin, agent)
                sandbox_execution_allowed = execution_sandbox["execution_kind"] in ALLOWED_SANDBOX_EXECUTION_KINDS and execution_sandbox["allowed"]
                permission_sandbox = _permission_sandbox(agent, sandbox_execution=sandbox_execution_allowed)
                risk_gate = _risk_gate(agent)
                validation_failures = _agent_contract_failures(agent, agent_id)
                eligible = (
                    not validation_failures
                    and permission_sandbox["allowed"]
                    and risk_gate["allowed"]
                    and execution_sandbox["allowed"]
                )
                dag_registration = {
                    "registered_to_dag": eligible,
                    "node_type": "plugin_observation",
                    "insertion_after": "market_technical_analyst",
                    "execution_mode": execution_sandbox["mode"],
                    "output_channel": "review_note",
                    "required_gates": list(REQUIRED_RUNTIME_GATES),
                }
                agents.append(
                    {
                        "plugin_id": plugin_id,
                        "plugin_name": plugin_name,
                        "agent_id": agent_id,
                        "agent_name": str(agent.get("name") or agent_id),
                        "dag_node_id": f"plugin:{plugin_id}:{agent_id}",
                        "plan_step": plan_step,
                        "enabled": True,
                        "eligible": eligible,
                        "registration_status": "REGISTERED" if eligible else "BLOCKED",
                        "dag_registration": dag_registration,
                        "input_schema": agent.get("input_schema") if isinstance(agent.get("input_schema"), dict) else {},
                        "output_schema": agent.get("output_schema") if isinstance(agent.get("output_schema"), dict) else {},
                        "permissions": _permission_values(agent),
                        "schema_status": schema_status,
                        "permission_sandbox": permission_sandbox,
                        "risk_gate": risk_gate,
                        "execution_sandbox": execution_sandbox,
                        "validation_failures": validation_failures,
                        "can_execute_code": sandbox_execution_allowed,
                        "direct_execution": False,
                    }
                )
                plan_step += 1

        resource_summary = _runtime_resource_summary(agents)
        if resource_summary["agents_with_limit_warnings"]:
            notes.append(
                f"Plugin resource limits were capped or defaulted for "
                f"{resource_summary['agents_with_limit_warnings']} runtime agent(s)."
            )
        status = "READY" if all(agent["eligible"] for agent in agents) else "BLOCKED"
        if not agents:
            status = "EMPTY"
        sandbox_blocked = [agent for agent in agents if not agent["execution_sandbox"]["allowed"]]
        return {
            "generated_at": _now(),
            "status": status,
            "sandbox_status": "EMPTY" if not agents else "BLOCKED" if sandbox_blocked else "READY",
            "enabled_plugin_count": len(enabled_plugins),
            "enabled_agent_count": len(agents),
            "registered_dag_node_count": len([agent for agent in agents if agent["eligible"]]),
            "hot_reload_agent_count": len([agent for agent in agents if agent["execution_sandbox"]["hot_reload_allowed"]]),
            "resource_summary": resource_summary,
            "agents": agents,
            "forbidden_trade_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
            "required_gates": list(REQUIRED_RUNTIME_GATES),
            "notes": notes,
        }


plugin_runtime_planner = PluginRuntimePlanner()
