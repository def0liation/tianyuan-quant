import pytest

from app.api.routes_plugins import execute_plugin_preview, run_plugin_sandbox
from app.core.plugin_runtime import DEFAULT_FORBIDDEN_TRADE_ACTIONS, REQUIRED_RUNTIME_GATES, plugin_runtime_planner
from app.core import plugin_sandbox
from app.core.operator_context import OperatorContext, reset_current_operator, set_current_operator
from app.core.plugin_store import plugin_store
from app.core.agent_framework import apply_agent_framework_to_run
from app.models.plugins import PluginRuntimePlan, PluginSandboxRunRequest


def _plugin_manifest(plugin_id: str, enabled: bool = True, agent_overrides=None):
    agent = {
        "agent_id": f"{plugin_id}_agent",
        "name": f"{plugin_id} Agent",
        "mode": "READ_ONLY",
        "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}},
        "output_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
        },
        "permissions": ["read:analysis_context", "read:market_data"],
        "risk_level": "LOW",
        "can_emit_trade_action": False,
    }
    if agent_overrides:
        agent.update(agent_overrides)
    return {
        "plugin_id": plugin_id,
        "version": "0.1.0",
        "name": f"{plugin_id} Plugin",
        "description": "Runtime test plugin",
        "agents": [agent],
        "permissions": ["read:analysis_context"],
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)},
        "risk_level": "LOW",
        "enabled": enabled,
        "manifest": {"runtime": "controlled_dag_plan_only"},
    }


def _declarative_agent_overrides():
    return {
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}, "analysis_context": {"type": "object"}},
            "required": ["symbol"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "signals": {"type": "array"},
                "risk_notes": {"type": "array"},
            },
            "required": ["summary"],
            "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
        },
        "manifest": {
            "execution": {
                "kind": "declarative_review_note",
                "review_note_template": "Sandbox reviewed {symbol}.",
                "resource_limits": {"timeout_ms": 500, "max_input_bytes": 4096, "max_output_bytes": 4096},
            }
        },
    }


@pytest.mark.asyncio
async def test_plugin_manifest_rejects_real_trade_action_outputs():
    unsafe_output_schema = {
        "type": "object",
        "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
        "allowed_trade_actions": ["BUY"],
    }

    with pytest.raises(ValueError) as exc:
        await plugin_store.register_plugin(
            _plugin_manifest("unsafe_runtime_trade", agent_overrides={"output_schema": unsafe_output_schema})
        )

    assert "declares forbidden trade actions: BUY" in str(exc.value)


def test_plugin_manifest_requires_agent_schema_permissions_and_risk():
    failures = plugin_store.validate_manifest(
        _plugin_manifest(
            "missing_runtime_contract",
            agent_overrides={"input_schema": {}, "output_schema": {}, "permissions": [], "risk_level": ""},
        )
    )

    assert any("input_schema" in failure for failure in failures)
    assert any("output_schema" in failure for failure in failures)
    assert any("permissions are required" in failure for failure in failures)
    assert any("risk_level is required" in failure for failure in failures)


@pytest.mark.asyncio
async def test_sandboxed_stdio_agent_plan_is_blocked_without_os_sandbox():
    await plugin_store.register_plugin(
        _plugin_manifest(
            "sandbox_plan_plugin",
            enabled=True,
            agent_overrides={
                "manifest": {
                    "runtime": "external_json_stdio",
                    "entrypoint": ["{python}", "runner.py"],
                    "timeout_seconds": 2,
                }
            },
        )
    )

    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())
    target = next(agent for agent in plan["agents"] if agent["plugin_id"] == "sandbox_plan_plugin")

    assert target["registration_status"] == "BLOCKED"
    assert target["dag_registration"]["execution_mode"] == "BLOCKED"
    assert target["permission_sandbox"]["mode"] == "READ_ONLY_NO_CODE"
    assert target["permission_sandbox"]["code_execution"] == "DISABLED"
    assert target["execution_sandbox"]["allowed"] is False
    assert any("OS-level plugin sandboxing" in reason for reason in target["execution_sandbox"]["block_reasons"])
    assert target["can_execute_code"] is False
    assert target["direct_execution"] is False


@pytest.mark.asyncio
async def test_blocked_execution_kind_is_not_registered_to_dag():
    await plugin_store.register_plugin(
        _plugin_manifest(
            "blocked_execution_plugin",
            enabled=True,
            agent_overrides={
                "manifest": {
                    "runtime": "python",
                    "entrypoint": ["{python}", "runner.py"],
                }
            },
        )
    )

    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())
    target = next(agent for agent in plan["agents"] if agent["plugin_id"] == "blocked_execution_plugin")

    assert target["registration_status"] == "BLOCKED"
    assert target["dag_registration"]["registered_to_dag"] is False
    assert target["execution_sandbox"]["allowed"] is False
    assert target["can_execute_code"] is False
    assert any("python" in reason for reason in target["execution_sandbox"]["block_reasons"])


@pytest.mark.asyncio
async def test_runtime_plan_only_contains_enabled_agents_with_schema_and_sandbox():
    await plugin_store.register_plugin(_plugin_manifest("enabled_runtime_plugin", enabled=True))
    await plugin_store.register_plugin(_plugin_manifest("disabled_runtime_plugin", enabled=False))

    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())
    typed_plan = PluginRuntimePlan.model_validate(plan)
    plugin_ids = {agent["plugin_id"] for agent in plan["agents"]}

    assert typed_plan.enabled_agent_count == len(plan["agents"])
    assert "enabled_runtime_plugin" in plugin_ids
    assert "disabled_runtime_plugin" not in plugin_ids

    target = next(agent for agent in plan["agents"] if agent["plugin_id"] == "enabled_runtime_plugin")
    assert target["registration_status"] == "REGISTERED"
    assert target["dag_registration"]["registered_to_dag"] is True
    assert typed_plan.registered_dag_node_count >= 1
    assert target["eligible"] is True
    assert target["schema_status"]["valid"] is True
    assert target["permission_sandbox"]["mode"] == "READ_ONLY_NO_CODE"
    assert target["permission_sandbox"]["allowed"] is True
    assert target["permission_sandbox"]["code_execution"] == "DISABLED"
    assert target["execution_sandbox"]["mode"] == "PLAN_ONLY_NO_EXECUTION"
    assert target["execution_sandbox"]["code_execution"] == "DISABLED"
    assert target["execution_sandbox"]["network_access"] == "DENIED"
    assert target["execution_sandbox"]["filesystem_access"] == "DENIED"
    assert target["execution_sandbox"]["trade_action_hard_block"] is True
    assert target["risk_gate"]["required_gates"] == list(REQUIRED_RUNTIME_GATES)
    assert target["risk_gate"]["forbidden_trade_actions"] == list(DEFAULT_FORBIDDEN_TRADE_ACTIONS)
    assert target["risk_gate"]["trade_actions_allowed"] is False
    assert target["can_execute_code"] is False
    assert target["direct_execution"] is False


@pytest.mark.asyncio
async def test_archived_plugin_is_excluded_from_runtime_plan():
    await plugin_store.register_plugin(_plugin_manifest("archived_runtime_plugin", enabled=True))
    archived = await plugin_store.archive_plugin("archived_runtime_plugin", actor="runtime-admin", reason="retired")

    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())

    assert archived["lifecycle_status"] == "ARCHIVED"
    assert archived["enabled"] is False
    assert all(agent["plugin_id"] != "archived_runtime_plugin" for agent in plan["agents"])


@pytest.mark.asyncio
async def test_runtime_plan_caps_plugin_resource_limits_and_summarizes_quota():
    plugin_id = "resource_quota_plugin"
    agent_overrides = _declarative_agent_overrides()
    agent_overrides["manifest"]["execution"]["resource_limits"] = {
        "timeout_ms": 5000,
        "max_input_bytes": 999999,
        "max_output_bytes": 999999,
        "max_events": 100,
    }
    await plugin_store.register_plugin(_plugin_manifest(plugin_id, enabled=True, agent_overrides=agent_overrides))

    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())
    typed_plan = PluginRuntimePlan.model_validate(plan)
    target = next(agent for agent in plan["agents"] if agent["plugin_id"] == plugin_id)

    assert target["execution_sandbox"]["custom_resource_limits"] is True
    assert target["execution_sandbox"]["resource_limits"]["timeout_ms"] == 1000
    assert target["execution_sandbox"]["resource_limits"]["max_input_bytes"] == 131072
    assert target["execution_sandbox"]["resource_limits"]["max_output_bytes"] == 32768
    assert target["execution_sandbox"]["resource_limits"]["max_events"] == 20
    assert len(target["execution_sandbox"]["resource_limit_warnings"]) == 4
    assert typed_plan.resource_summary["quota_status"] == "WARN"
    assert typed_plan.resource_summary["agents_with_limit_warnings"] >= 1
    assert typed_plan.resource_summary["total_timeout_ms"] >= 1000
    assert any("Plugin resource limits were capped" in note for note in plan["notes"])


@pytest.mark.asyncio
async def test_declarative_hot_reload_sandbox_run_is_audited_and_schema_checked():
    plugin_id = "declarative_hot_reload_plugin"
    manifest = _plugin_manifest(plugin_id, enabled=True, agent_overrides=_declarative_agent_overrides())
    await plugin_store.register_plugin(manifest)

    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())
    target = next(agent for agent in plan["agents"] if agent["plugin_id"] == plugin_id)

    assert plan["sandbox_status"] == "READY"
    assert target["execution_sandbox"]["hot_reload_allowed"] is True
    assert target["execution_sandbox"]["resource_limits"]["timeout_ms"] == 500
    assert target["can_execute_code"] is False

    result = await plugin_store.run_sandbox(
        plugin_id,
        f"{plugin_id}_agent",
        {"symbol": "603663", "analysis_context": {"source": "test"}},
        actor="pytest",
    )

    assert result["status"] == "COMPLETED"
    assert result["mode"] == "DECLARATIVE_HOT_RELOAD_SANDBOX"
    assert result["output"]["summary"] == "Sandbox reviewed 603663."
    assert result["policy"]["code_execution"] == "DISABLED"
    assert result["policy"]["network_access"] == "DENIED"
    assert result["policy"]["trade_action_hard_block"] is True
    audit = await plugin_store.list_audit(plugin_id)
    assert any(entry["action"] == "SANDBOX_RUN" and entry["audit_id"] == result["audit_id"] for entry in audit)
    usage_stats = await plugin_store.list_usage_stats()
    target_usage = next(item for item in usage_stats if item["plugin_id"] == plugin_id)
    assert target_usage["sandbox_run_count"] >= 1
    assert target_usage["action_counts"]["SANDBOX_RUN"] >= 1
    assert target_usage["status_counts"]["COMPLETED"] >= 1
    assert target_usage["last_audit_id"]
    assert target_usage["last_run_at"]


@pytest.mark.asyncio
async def test_plugin_sandbox_route_ignores_client_actor_and_uses_current_operator():
    plugin_id = "declarative_hot_reload_route_actor_plugin"
    manifest = _plugin_manifest(plugin_id, enabled=True, agent_overrides=_declarative_agent_overrides())
    await plugin_store.register_plugin(manifest)

    token = set_current_operator(OperatorContext(id="api_admin", role="admin", source="api_token"))
    try:
        result = await run_plugin_sandbox(
            plugin_id,
            f"{plugin_id}_agent",
            PluginSandboxRunRequest(
                input_payload={"symbol": "603663", "analysis_context": {"source": "test"}},
                actor="forged-client-actor",
            ),
        )
    finally:
        reset_current_operator(token)

    assert result["status"] == "COMPLETED"
    assert result["actor"] == "api_admin"
    audit = await plugin_store.list_audit(plugin_id)
    sandbox_audit = next(entry for entry in audit if entry["action"] == "SANDBOX_RUN")
    assert sandbox_audit["actor"] == "api_admin"
    assert sandbox_audit["actor"] != "forged-client-actor"


def test_code_entrypoint_plugin_is_blocked_by_execution_sandbox():
    plan = plugin_runtime_planner.build_plan(
        [
            _plugin_manifest(
                "unsafe_code_plugin",
                enabled=True,
                agent_overrides={
                    "manifest": {"runtime": "python", "entrypoint": "main.py"},
                },
            )
        ]
    )
    target = plan["agents"][0]

    assert plan["sandbox_status"] == "BLOCKED"
    assert target["execution_sandbox"]["allowed"] is False
    assert target["execution_sandbox"]["mode"] == "BLOCKED"
    assert target["can_execute_code"] is False
    assert any("entrypoints are blocked" in reason for reason in target["execution_sandbox"]["block_reasons"])


@pytest.mark.asyncio
async def test_registered_plugin_agent_is_added_to_runtime_dag():
    await plugin_store.register_plugin(_plugin_manifest("dag_runtime_plugin", enabled=True))
    plan = plugin_runtime_planner.build_plan(await plugin_store.list_plugins())
    runtime_summary = {
        "agents": [],
        "pluginRuntimePlan": plan,
    }

    run = apply_agent_framework_to_run(
        {
            "runId": "RUN_PLUGIN_DAG_001",
            "stockCode": "603663",
            "status": "CREATED",
            "dvg": {"status": "PASS"},
            "qiam": {},
            "risk": {},
            "killSwitch": {"active": False, "level": "NONE"},
        },
        {"symbol": "603663", "run_mode": "STANDARD_MODE"},
        runtime_summary,
    )

    plugin_node = next(node for node in run["nodes"] if node["id"].startswith("plugin:dag_runtime_plugin:"))
    quant_core_index = next(index for index, node in enumerate(run["nodes"]) if node["id"] == "quant_core")
    plugin_index = next(index for index, node in enumerate(run["nodes"]) if node["id"] == plugin_node["id"])
    execution_index = next(index for index, node in enumerate(run["nodes"]) if node["id"] == "execution")
    quant_core_node = run["nodes"][quant_core_index]
    node_by_id = {node["id"]: node for node in run["nodes"]}
    chain = []
    next_ids = list(quant_core_node["allowedNextActions"])
    while next_ids:
        current = next_ids[0]
        chain.append(current)
        if current == "execution":
            break
        next_ids = list(node_by_id[current]["allowedNextActions"])

    assert quant_core_index < plugin_index < execution_index
    assert plugin_node["id"] in chain
    assert chain[-1] == "execution"
    assert plugin_node["status"] == "REVIEW_ONLY"
    assert plugin_node["rawJson"]["canExecuteCode"] is False
    assert plugin_node["rawJson"]["riskGate"]["trade_actions_allowed"] is False
    assert any(event["node"] == plugin_node["id"] for event in run["dagEvents"])


@pytest.mark.asyncio
async def test_plugin_sandbox_execute_preview_blocks_external_stdio_and_audits(monkeypatch, tmp_path):
    plugin_id = "sandbox_execute_plugin"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "runner.py").write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "print(json.dumps({'summary': 'checked ' + payload['input']['symbol'], 'risk_notes': []}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugin_sandbox, "PLUGIN_ROOT", tmp_path)

    await plugin_store.register_plugin(
        _plugin_manifest(
            plugin_id,
            enabled=True,
            agent_overrides={
                "agent_id": "sandbox_agent",
                "input_schema": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}, "risk_notes": {"type": "array"}},
                    "required": ["summary"],
                    "forbidden_actions": list(DEFAULT_FORBIDDEN_TRADE_ACTIONS),
                },
                "manifest": {
                    "runtime": "external_json_stdio",
                    "entrypoint": ["{python}", "runner.py"],
                    "timeout_seconds": 2,
                },
            },
        )
    )

    token = set_current_operator(OperatorContext(id="api_admin", role="admin", source="api_token"))
    try:
        with pytest.raises(Exception) as exc:
            await execute_plugin_preview(
                plugin_id,
                "sandbox_agent",
                {"input": {"symbol": "603663"}, "operator": "forged-preview-operator"},
            )
    finally:
        reset_current_operator(token)
    audit = await plugin_store.list_audit(plugin_id)

    assert "PLUGIN_SANDBOX_NOT_ALLOWED" in str(exc.value.detail)
    failed_audit = next(item for item in audit if item["action"] == "EXECUTE_PREVIEW_FAILED")
    assert failed_audit["actor"] == "api_admin"
    assert failed_audit["actor"] != "forged-preview-operator"


@pytest.mark.asyncio
async def test_plugin_sandbox_blocks_forbidden_trade_actions(monkeypatch, tmp_path):
    plugin_id = "sandbox_trade_block_plugin"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir()
    (plugin_dir / "runner.py").write_text(
        "import json\nprint(json.dumps({'summary': 'unsafe', 'action': 'BUY'}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugin_sandbox, "PLUGIN_ROOT", tmp_path)

    await plugin_store.register_plugin(
        _plugin_manifest(
            plugin_id,
            enabled=True,
            agent_overrides={
                "agent_id": "sandbox_agent",
                "manifest": {
                    "runtime": "external_json_stdio",
                    "entrypoint": ["{python}", "runner.py"],
                    "timeout_seconds": 2,
                },
            },
        )
    )

    with pytest.raises(Exception) as exc:
        await execute_plugin_preview(plugin_id, "sandbox_agent", {"input": {"symbol": "603663"}})

    assert "PLUGIN_SANDBOX_NOT_ALLOWED" in str(exc.value.detail)
