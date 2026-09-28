import asyncio
import json
from io import BytesIO
from urllib.error import HTTPError

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import routes_agents, routes_config
from app.core.agent_framework import (
    AGENT_MANIFEST,
    CONSOLIDATED_AGENT_REDIRECTS,
    RUN_MODE_NODES,
    agent_definitions,
    get_framework_payload,
    load_agent_prompt,
)
from app.core.agent_runtime_store import get_runtime_config
from app.core import agent_runtime_store, file_utils as file_utils_module, llm_profile_tester, llm_runner, market_data_runner, secret_store
from app.core.llm_egress_policy import LLMEgressBlockedError, LLMEgressDecision, validate_llm_egress
from app.core.market_data_egress_policy import (
    MarketDataEgressBlockedError,
    validate_market_data_egress,
)
from app.core.secret_store import rotate_runtime_secret_vault, verify_runtime_secret_vault
from app.core.config_store import config_store
from app.db.models import ConfigVersionDB
from app.db.session import AsyncSessionLocal
from app.models.agent_runtime import (
    AgentLLMProfile,
    LLMProfileConfig,
    MarketDataProfile,
    UpdateAgentLLMRequest,
    UpdateDataSourcesRequest,
    UpdateMarketDataAdapterConfigRequest,
    UpdateRuntimeSettingsRequest,
    UpsertLLMProfileRequest,
    UpsertMarketDataProfileRequest,
)
from app.models.config import ExternalConfigRestoreRequest
from app.models.market_data import DataSourceHealth


def _json_contains(value, needle: str) -> bool:
    return needle in json.dumps(value, ensure_ascii=False, default=str)


async def _config_version_by_audit_id(audit_id: str):
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(ConfigVersionDB).where(ConfigVersionDB.audit_id == audit_id)
            )
        ).scalar_one()


@pytest.fixture(autouse=True)
def clear_llm_env(monkeypatch):
    for name in (
        "API_AUTH_MODE",
        "APP_ENV",
        "ENVIRONMENT",
        "LLM_EGRESS_MODE",
        "LLM_BASE_URL_ALLOWLIST",
        "LLM_EGRESS_ALLOWLIST",
        "LLM_ALLOWED_HOSTS",
        "MARKET_DATA_EGRESS_MODE",
        "MARKET_DATA_BASE_URL_ALLOWLIST",
        "MARKET_DATA_EGRESS_ALLOWLIST",
        "MARKET_DATA_ALLOWED_HOSTS",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def use_temp_runtime_store(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_runtime_store, "STORAGE_FILE", tmp_path / "agent_runtime.json")
    monkeypatch.setattr(agent_runtime_store, "RUNS_DIR", tmp_path / "runs")


def test_runtime_store_recovers_corrupt_json(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    agent_runtime_store.STORAGE_FILE.write_text('{"agents": [', encoding="utf-8")
    known_refs = {
        "runtime-secret:v1:market_data_profiles:default_market_data:api_key",
        "runtime-secret:v1:data_sources_config:default:tushare_token",
    }
    monkeypatch.setattr(
        agent_runtime_store,
        "load_runtime_secret",
        lambda _storage_file, ref: "restored-secret" if ref in known_refs else "",
    )

    config = agent_runtime_store.get_runtime_config()

    assert config.default_llm_profile_id == agent_runtime_store.DEFAULT_PROFILE_ID
    backups = list(tmp_path.glob("agent_runtime.json.corrupt.*"))
    assert len(backups) == 1
    persisted = json.loads(agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8"))
    assert persisted["runtime_recovery"]["backup_file"].endswith(backups[0].name)
    assert persisted["runtime_recovery"]["restored_secret_refs_at"]
    assert persisted["secret_refs"]["market_data_profiles"]["default_market_data"]["api_key"] in known_refs
    assert persisted["secret_refs"]["data_sources_config"]["tushare_token"] in known_refs
    assert persisted["agents"]


def test_runtime_store_save_state_leaves_valid_json_without_temp_files(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    state = agent_runtime_store._default_state()

    agent_runtime_store._save_state(state)

    persisted = json.loads(agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8"))
    assert persisted["default_llm_profile_id"] == agent_runtime_store.DEFAULT_PROFILE_ID
    assert list(tmp_path.glob(".agent_runtime.json.*.tmp")) == []


def test_runtime_store_save_state_retries_transient_replace_permission_error(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    monkeypatch.setattr(file_utils_module.time, "sleep", lambda _seconds: None)
    real_replace = agent_runtime_store.os.replace
    attempts = []

    def flaky_replace(source, target):
        attempts.append((source, target))
        if len(attempts) < 3:
            raise PermissionError("target locked")
        return real_replace(source, target)

    monkeypatch.setattr(agent_runtime_store.os, "replace", flaky_replace)

    state = agent_runtime_store._default_state()
    agent_runtime_store._save_state(state)

    assert len(attempts) == 3
    persisted = json.loads(agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8"))
    assert persisted["default_llm_profile_id"] == agent_runtime_store.DEFAULT_PROFILE_ID
    assert list(tmp_path.glob(".agent_runtime.json.*.tmp")) == []


def test_runtime_secret_vault_retries_transient_replace_permission_error(monkeypatch, tmp_path):
    monkeypatch.setattr(secret_store.time, "sleep", lambda _seconds: None)
    real_replace = secret_store.os.replace
    attempts = []

    def flaky_replace(source, target):
        attempts.append((source, target))
        if len(attempts) < 3:
            raise PermissionError("vault locked")
        return real_replace(source, target)

    monkeypatch.setattr(secret_store.os, "replace", flaky_replace)

    state_file = tmp_path / "agent_runtime.json"
    ref = secret_store.store_runtime_secret(state_file, "llm_profiles", "retry_llm", "api_key", "sk-retry")

    assert len(attempts) == 3
    assert secret_store.load_runtime_secret(state_file, ref) == "sk-retry"
    assert list(tmp_path.glob("agent_runtime.secrets.json.*.tmp")) == []


def test_runtime_config_uses_consolidated_agent_manifest():
    config = get_runtime_config()
    active_ids = [agent["id"] for agent in AGENT_MANIFEST]
    runtime_ids = [agent.id for agent in config.agents]

    assert runtime_ids == active_ids
    assert len(runtime_ids) == 8
    assert "orchestrator" in runtime_ids
    assert "data_reliability_engine" in runtime_ids
    assert "data_engine" not in runtime_ids
    assert "quant_core" in runtime_ids
    assert "market_technical_analyst" not in runtime_ids
    assert "market_regime" not in runtime_ids
    assert "technical_kline_analyst" not in runtime_ids
    assert "quant_engine" not in runtime_ids
    assert "bottom_research" not in runtime_ids
    assert "signalops" in runtime_ids


def test_legacy_quant_core_execution_config_redirect(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    market_agent, market_profile = agent_runtime_store.get_agent_execution_config("market_regime")
    technical_agent, technical_profile = agent_runtime_store.get_agent_execution_config("technical_kline_analyst")
    quant_agent, quant_profile = agent_runtime_store.get_agent_execution_config("quant_engine")
    bottom_agent, bottom_profile = agent_runtime_store.get_agent_execution_config("bottom_research")
    scenario_agent, scenario_profile = agent_runtime_store.get_agent_execution_config("scenario_engine")

    assert market_agent.id == "quant_core"
    assert technical_agent.id == "quant_core"
    assert quant_agent.id == "quant_core"
    assert bottom_agent.id == "quant_core"
    assert scenario_agent.id == "quant_core"
    assert market_profile.id == agent_runtime_store.DEFAULT_PROFILE_ID
    assert technical_profile.id == agent_runtime_store.DEFAULT_PROFILE_ID
    assert quant_profile.id == agent_runtime_store.DEFAULT_PROFILE_ID
    assert bottom_profile.id == agent_runtime_store.DEFAULT_PROFILE_ID
    assert scenario_profile.id == agent_runtime_store.DEFAULT_PROFILE_ID


def test_consolidated_agent_prompt_mentions_replacement():
    prompt = load_agent_prompt("state_validation")

    assert "Legacy agent ID: state_validation" in prompt
    assert "Consolidated into: orchestrator" in prompt


def test_active_prompt_files_resolve_without_template_fallback():
    orchestrator_prompt = load_agent_prompt("orchestrator")
    quant_core_prompt = load_agent_prompt("quant_core")

    assert "ORCHESTRATOR" in orchestrator_prompt
    assert "只做路由、截断、降级和权限控制" in orchestrator_prompt
    assert "QUANT_CORE" in quant_core_prompt
    assert "This agent is implemented by backend rule/tool logic" not in orchestrator_prompt
    assert "This agent is implemented by backend rule/tool logic" not in quant_core_prompt


def test_run_mode_nodes_are_active_only():
    active_ids = {agent["id"] for agent in AGENT_MANIFEST}

    assert all(node in active_ids for nodes in RUN_MODE_NODES.values() for node in nodes)
    assert len(RUN_MODE_NODES["FAST_MODE"]) == 5
    assert len(RUN_MODE_NODES["STANDARD_MODE"]) == 8
    assert len(RUN_MODE_NODES["DEEP_MODE"]) == 8
    assert "guardrail_hub" in RUN_MODE_NODES["STANDARD_MODE"]
    assert "dvg_gate" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "risk_firewall" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "trade_micro" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "market_regime" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "technical_kline_analyst" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "market_technical_analyst" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "bottom_research" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "quant_engine" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert "scenario_engine" not in RUN_MODE_NODES["STANDARD_MODE"]
    assert RUN_MODE_NODES["STANDARD_MODE"].index("guardrail_hub") < RUN_MODE_NODES["STANDARD_MODE"].index("quant_core")
    assert RUN_MODE_NODES["STANDARD_MODE"].index("quant_core") < RUN_MODE_NODES["STANDARD_MODE"].index("execution")


def test_framework_payload_exposes_consolidation_map():
    payload = get_framework_payload()

    assert payload["active_agent_count"] == 8
    assert payload["consolidated_agents"]["state_validation"] == "orchestrator"
    assert payload["consolidated_agents"]["data_fetch"] == "data_reliability_engine"
    assert payload["consolidated_agents"]["data_engine"] == "data_reliability_engine"
    assert payload["consolidated_agents"]["dvg_gate"] == "guardrail_hub"
    assert payload["consolidated_agents"]["risk_firewall"] == "guardrail_hub"
    assert payload["consolidated_agents"]["trade_micro"] == "guardrail_hub"
    assert payload["consolidated_agents"]["market_regime"] == "quant_core"
    assert payload["consolidated_agents"]["technical_kline_analyst"] == "quant_core"
    assert payload["consolidated_agents"]["qiam"] == "quant_core"
    assert payload["consolidated_agents"]["scenario_engine"] == "quant_core"
    assert "quant_core" in {node["id"] for node in payload["nodes"]}
    assert "market_technical_analyst" not in {node["id"] for node in payload["nodes"]}
    assert "signalops" in {node["id"] for node in payload["nodes"]}
    assert "bottom_research" not in {node["id"] for node in payload["nodes"]}


def test_all_agent_definitions_have_prompt_metadata():
    definitions = agent_definitions("default_llm")

    assert all(agent["prompt_hash"] for agent in definitions)
    assert all(agent["system_prompt_excerpt"] for agent in definitions)


def test_runtime_agent_definitions_do_not_expose_direct_trade_actions():
    definitions = agent_definitions("default_llm")

    assert definitions
    assert all(agent["allow_trade_action"] is False for agent in definitions)
    assert all(agent["final_decision_cap"] == "NO_DIRECT_TRADE_ACTION" for agent in definitions)


def test_runtime_store_sync_clears_legacy_direct_trade_flags(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    state = agent_runtime_store._default_state()
    for agent in state["agents"]:
        if agent["id"] in {"execution", "final_writer"}:
            agent["allow_trade_action"] = True
            agent["final_decision_cap"] = "UPSTREAM_ONLY"
    agent_runtime_store._save_state(state)

    config = agent_runtime_store.get_runtime_config()

    assert config.agents
    assert all(agent.allow_trade_action is False for agent in config.agents)
    assert all(agent.final_decision_cap == "NO_DIRECT_TRADE_ACTION" for agent in config.agents)
    persisted = json.loads(agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8"))
    assert all(agent["allow_trade_action"] is False for agent in persisted["agents"])
    assert all(agent["final_decision_cap"] == "NO_DIRECT_TRADE_ACTION" for agent in persisted["agents"])


def test_llm_profile_upsert_accepts_flat_payload_and_preserves_api_key(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    config = agent_runtime_store.upsert_llm_profile(
        "review_llm",
        UpsertLLMProfileRequest(
            label="Review LLM",
            provider="openai_compatible",
            base_url="https://example.test/v1",
            model="review-model",
            api_key="sk-test-secret",
            temperature=0.3,
            max_tokens=2048,
            timeout_seconds=30,
            enabled=True,
        ),
    )
    profile = next(item for item in config.llm_profiles if item.id == "review_llm")
    assert profile.api_key_set is True

    persisted = json.loads(agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8"))
    raw_profile = next(item for item in persisted["llm_profiles"] if item["id"] == "review_llm")
    assert raw_profile["api_key"] == ""
    assert "sk-test-secret" not in agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8")
    secret_ref = persisted["secret_refs"]["llm_profiles"]["review_llm"]["api_key"]
    assert secret_ref.startswith("runtime-secret:v1:")
    assert "sk-test-secret" not in (tmp_path / "agent_runtime.secrets.json").read_text(encoding="utf-8")

    config = agent_runtime_store.upsert_llm_profile(
        "review_llm",
        UpsertLLMProfileRequest(label="Renamed Review LLM"),
    )
    profile = next(item for item in config.llm_profiles if item.id == "review_llm")
    assert profile.label == "Renamed Review LLM"
    assert profile.api_key_set is True
    assert agent_runtime_store.get_llm_profile("review_llm").api_key == "sk-test-secret"

    config = agent_runtime_store.upsert_llm_profile(
        "review_llm",
        UpsertLLMProfileRequest(clear_api_key=True),
    )
    profile = next(item for item in config.llm_profiles if item.id == "review_llm")
    assert profile.api_key_set is False
    persisted = json.loads(agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8"))
    assert "review_llm" not in persisted["secret_refs"].get("llm_profiles", {})


def test_runtime_public_profiles_redact_sensitive_extra_fields(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    config = agent_runtime_store.upsert_llm_profile(
        "headers_llm",
        UpsertLLMProfileRequest(
            label="Headers LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="headers-model",
            api_key="sk-profile-secret",
            extra_headers={
                "Authorization": "Bearer hidden",
                "X-API-Key": "key-hidden",
                "X-Trace-ID": "trace-visible",
            },
            enabled=True,
        ),
    )

    public_llm = next(item for item in config.llm_profiles if item.id == "headers_llm")
    assert public_llm.extra_headers["Authorization"] == "<redacted>"
    assert public_llm.extra_headers["X-API-Key"] == "<redacted>"
    assert public_llm.extra_headers["X-Trace-ID"] == "trace-visible"

    config = agent_runtime_store.upsert_market_data_profile(
        "headers_market",
        UpsertMarketDataProfileRequest(
            label="Headers Market",
            provider="generic_rest",
            base_url="https://quotes.example.test",
            api_key="market-profile-secret",
            extra_headers={
                "Authorization": "Bearer market-hidden",
                "X-Trace-ID": "market-trace-visible",
            },
            extra_query_params={
                "token": "query-hidden",
                "region": "cn",
            },
            enabled=True,
        ),
    )

    public_market = next(item for item in config.market_data_profiles if item.id == "headers_market")
    assert public_market.extra_headers["Authorization"] == "<redacted>"
    assert public_market.extra_headers["X-Trace-ID"] == "market-trace-visible"
    assert public_market.extra_query_params["token"] == "<redacted>"
    assert public_market.extra_query_params["region"] == "cn"


@pytest.mark.asyncio
async def test_llm_profile_route_writes_unified_config_audit_and_redacts_secret(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    response = await routes_agents.put_llm_profile(
        "audit_llm",
        UpsertLLMProfileRequest(
            label="Audit LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="audit-model",
            api_key="sk-audit-secret",
            enabled=True,
        ),
    )
    profile = next(item for item in response.llm_profiles if item.id == "audit_llm")
    audits = await config_store.list_audit()
    latest = audits[0]
    version = await _config_version_by_audit_id(latest["auditId"])

    assert profile.api_key_set is True
    assert latest["eventType"] == "CONFIG_EXTERNAL_CHANGE"
    assert latest["payload"]["scope"] == "agent_runtime"
    assert latest["payload"]["surface"] == "llm_profile"
    assert latest["payload"]["subject"] == "audit_llm"
    assert latest["payload"]["version_id"] == version.id
    assert latest["payload"]["operator"] == {
        "id": "local_workbench",
        "role": "admin",
        "source": "default",
    }
    assert version.profile_id == "agent_runtime:llm_profile"
    assert version.created_by == "local_workbench"
    versions = await routes_config.get_config_versions(include_external=True)
    external_version = next(
        item
        for item in versions
        if item["profile_id"] == "agent_runtime:llm_profile" and item["audit_id"] == latest["auditId"]
    )
    policy = external_version["rollback_policy"]
    assert policy["supported"] is False
    assert policy["approval_gate"]["status"] == "BLOCKED_PENDING_VAULT_VERSION_APPROVAL"
    assert policy["approval_gate"]["secret_vault_version_required"] is True
    required_secret_refs = policy["approval_gate"]["required_secret_refs"]
    assert len(required_secret_refs) == 1
    assert required_secret_refs[0]["path"] == "secret_refs.llm_profiles.audit_llm.api_key"
    assert required_secret_refs[0]["ref"].startswith("runtime-secret:v1:llm_profiles:audit_llm:api_key:version:")
    assert not _json_contains(latest["payload"], "sk-audit-secret")
    assert not _json_contains(version.snapshot_json, "sk-audit-secret")


@pytest.mark.asyncio
async def test_external_config_restore_uses_approved_vault_version_refs(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    first_response = await routes_agents.put_llm_profile(
        "restore_llm",
        UpsertLLMProfileRequest(
            label="Restore LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="old-model",
            api_key="sk-restore-old-secret",
            enabled=True,
        ),
    )
    first_audit = (await config_store.list_audit())[0]["auditId"]
    first_profile = next(item for item in first_response.llm_profiles if item.id == "restore_llm")

    await routes_agents.put_llm_profile(
        "restore_llm",
        UpsertLLMProfileRequest(
            label="Restore LLM Updated",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="new-model",
            api_key="sk-restore-new-secret",
            enabled=True,
        ),
    )

    changed_profile = agent_runtime_store.get_llm_profile("restore_llm")
    assert changed_profile.model == "new-model"
    assert changed_profile.api_key == "sk-restore-new-secret"

    with pytest.raises(HTTPException) as missing_confirm:
        await routes_config.restore_external_config(
            ExternalConfigRestoreRequest(
                profile_id="agent_runtime:llm_profile",
                audit_id=first_audit,
                reason="restore old reviewed profile",
                approval_id="APPROVAL-RESTORE-1",
                confirm_secret_safe=False,
            )
        )
    assert missing_confirm.value.status_code == 400

    result = await routes_config.restore_external_config(
        ExternalConfigRestoreRequest(
            profile_id="agent_runtime:llm_profile",
            audit_id=first_audit,
            reason="restore old reviewed profile",
            approval_id="APPROVAL-RESTORE-1",
            approved_by="admin-reviewer",
            confirm_secret_safe=True,
        )
    )
    restored_profile = agent_runtime_store.get_llm_profile("restore_llm")
    versions = await routes_config.get_config_versions(
        include_external=True,
        profile_id="agent_runtime:llm_profile",
    )
    restore_version = next(item for item in versions if item["audit_id"] == result["restore_audit_id"])

    assert first_profile.model == "old-model"
    assert result["status"] == "RESTORED"
    assert result["required_secret_ref_count"] == 1
    assert restored_profile.model == "old-model"
    assert restored_profile.api_key == "sk-restore-old-secret"
    assert restore_version["rollback_policy"]["approval_gate"]["required_secret_refs"][0]["ref"].startswith(
        "runtime-secret:v1:llm_profiles:restore_llm:api_key:version:"
    )
    serialized = json.dumps(result, ensure_ascii=False) + json.dumps(restore_version, ensure_ascii=False)
    assert "sk-restore-old-secret" not in serialized
    assert "sk-restore-new-secret" not in serialized


@pytest.mark.asyncio
async def test_external_data_sources_restore_is_surface_scoped(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    await routes_agents.put_data_sources(
        UpdateDataSourcesRequest(tushare_token="ts-old-secret", sources=None)
    )
    versions = await routes_config.get_config_versions(
        include_external=True,
        profile_id="agent_runtime:data_sources_config",
    )
    data_sources_audit = versions[0]["audit_id"]

    await routes_agents.put_llm_profile(
        "survive_llm",
        UpsertLLMProfileRequest(
            label="Survive LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="survive-model",
            api_key="sk-survive-secret",
            enabled=True,
        ),
    )
    await routes_agents.put_data_sources(
        UpdateDataSourcesRequest(tushare_token="ts-new-secret", sources=None)
    )

    result = await routes_config.restore_external_config(
        ExternalConfigRestoreRequest(
            profile_id="agent_runtime:data_sources_config",
            audit_id=data_sources_audit,
            reason="restore reviewed data source token",
            approval_id="APPROVAL-DATA-SOURCES-1",
            approved_by="admin-reviewer",
            confirm_secret_safe=True,
        )
    )

    restored_sources = agent_runtime_store.get_data_sources_config()
    restored_market_profile = agent_runtime_store.get_market_data_profile("default_market_data")
    surviving_profile = agent_runtime_store.get_llm_profile("survive_llm")
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "RESTORED"
    assert result["applied_keys"] == ["data_sources_config"]
    assert result["required_secret_ref_count"] == 1
    assert restored_sources["tushare_token"] == "ts-old-secret"
    assert restored_market_profile.api_key == "ts-old-secret"
    assert surviving_profile.model == "survive-model"
    assert surviving_profile.api_key == "sk-survive-secret"
    assert "ts-old-secret" not in serialized
    assert "ts-new-secret" not in serialized


@pytest.mark.asyncio
async def test_external_market_data_profile_restore_is_surface_scoped(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    await routes_agents.put_market_data_profile(
        "restore_market",
        UpsertMarketDataProfileRequest(
            label="Restore Market",
            provider="generic_rest",
            base_url="https://quotes-old.example.test",
            quote_path="quote.old",
            auth_mode="header",
            api_key="market-old-secret",
            api_key_header="X-Old-Key",
            enabled=True,
            egress_confirmed=True,
        ),
    )
    versions = await routes_config.get_config_versions(
        include_external=True,
        profile_id="agent_runtime:market_data_profile",
    )
    market_profile_audit = versions[0]["audit_id"]

    await routes_agents.put_llm_profile(
        "survive_market_restore_llm",
        UpsertLLMProfileRequest(
            label="Survive Market Restore LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="survive-market-model",
            api_key="sk-survive-market-secret",
            enabled=True,
        ),
    )
    await routes_agents.put_data_sources(
        UpdateDataSourcesRequest(tushare_token="ts-survive-market-restore", sources=None)
    )
    await routes_agents.put_market_data_profile(
        "restore_market",
        UpsertMarketDataProfileRequest(
            label="Restore Market Updated",
            provider="generic_rest",
            base_url="https://quotes-new.example.test",
            quote_path="quote.new",
            auth_mode="query",
            api_key="market-new-secret",
            api_key_query_param="new_token",
            enabled=False,
            egress_confirmed=True,
        ),
    )

    result = await routes_config.restore_external_config(
        ExternalConfigRestoreRequest(
            profile_id="agent_runtime:market_data_profile",
            audit_id=market_profile_audit,
            reason="restore reviewed market data profile",
            approval_id="APPROVAL-MARKET-PROFILE-1",
            approved_by="admin-reviewer",
            confirm_secret_safe=True,
        )
    )

    restored_profile = agent_runtime_store.get_market_data_profile("restore_market")
    surviving_llm = agent_runtime_store.get_llm_profile("survive_market_restore_llm")
    data_sources = agent_runtime_store.get_data_sources_config()
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "RESTORED"
    assert result["applied_keys"] == [
        "default_market_data_profile_id",
        "market_data_profiles",
    ]
    assert result["required_secret_ref_count"] == 1
    assert restored_profile.label == "Restore Market"
    assert restored_profile.base_url == "https://quotes-old.example.test"
    assert restored_profile.quote_path == "quote.old"
    assert restored_profile.auth_mode == "header"
    assert restored_profile.api_key == "market-old-secret"
    assert restored_profile.api_key_header == "X-Old-Key"
    assert restored_profile.enabled is True
    assert surviving_llm.model == "survive-market-model"
    assert surviving_llm.api_key == "sk-survive-market-secret"
    assert data_sources["tushare_token"] == "ts-survive-market-restore"
    assert "market-old-secret" not in serialized
    assert "market-new-secret" not in serialized
    assert "sk-survive-market-secret" not in serialized


@pytest.mark.asyncio
async def test_external_market_data_adapter_restore_is_surface_scoped(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    await routes_agents.put_market_data_adapter_config(
        "akshare",
        UpdateMarketDataAdapterConfigRequest(
            enabled=False,
            priority=8,
            timeout_seconds=31,
        ),
    )
    versions = await routes_config.get_config_versions(
        include_external=True,
        profile_id="agent_runtime:market_data_adapter_config",
    )
    adapter_audit = versions[0]["audit_id"]

    await routes_agents.put_llm_profile(
        "survive_adapter_restore_llm",
        UpsertLLMProfileRequest(
            label="Survive Adapter Restore LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="survive-adapter-model",
            api_key="sk-survive-adapter-secret",
            enabled=True,
        ),
    )
    await routes_agents.put_market_data_profile(
        "survive_adapter_market",
        UpsertMarketDataProfileRequest(
            label="Survive Adapter Market",
            provider="generic_rest",
            base_url="https://adapter-market.example.test",
            auth_mode="none",
            enabled=True,
            egress_confirmed=True,
        ),
    )
    await routes_agents.put_market_data_adapter_config(
        "akshare",
        UpdateMarketDataAdapterConfigRequest(
            enabled=True,
            priority=2,
            timeout_seconds=15,
        ),
    )

    result = await routes_config.restore_external_config(
        ExternalConfigRestoreRequest(
            profile_id="agent_runtime:market_data_adapter_config",
            audit_id=adapter_audit,
            reason="restore reviewed market data adapter config",
            approval_id="APPROVAL-MARKET-ADAPTER-1",
            approved_by="admin-reviewer",
            confirm_secret_safe=True,
        )
    )

    restored_adapter = agent_runtime_store.get_market_data_adapter_config("akshare")
    surviving_llm = agent_runtime_store.get_llm_profile("survive_adapter_restore_llm")
    surviving_market = agent_runtime_store.get_market_data_profile("survive_adapter_market")
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["status"] == "RESTORED"
    assert result["applied_keys"] == ["market_data_adapter_configs"]
    assert result["required_secret_ref_count"] == 0
    assert restored_adapter.enabled is False
    assert restored_adapter.priority == 8
    assert restored_adapter.timeout_seconds == 31
    assert surviving_llm.model == "survive-adapter-model"
    assert surviving_llm.api_key == "sk-survive-adapter-secret"
    assert surviving_market.base_url == "https://adapter-market.example.test"
    assert "sk-survive-adapter-secret" not in serialized


def test_runtime_store_migrates_plaintext_market_and_data_source_secrets(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    legacy_state = agent_runtime_store._default_state()
    legacy_state["llm_profiles"].append(
        {
            "id": "legacy_llm",
            "label": "Legacy LLM",
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "legacy-model",
            "api_key": "legacy-llm-secret",
            "temperature": 0.2,
            "max_tokens": 4096,
            "timeout_seconds": 60,
            "enabled": True,
            "extra_headers": {},
        }
    )
    legacy_state["market_data_profiles"].append(
        {
            "id": "legacy_market",
            "label": "Legacy Market",
            "provider": "tushare",
            "base_url": "https://api.tushare.pro",
            "quote_path": "",
            "symbol_query_param": "ts_code",
            "auth_mode": "token",
            "api_key": "legacy-market-secret",
            "api_key_header": "",
            "api_key_query_param": "token",
            "timeout_seconds": 20,
            "enabled": True,
            "extra_headers": {},
            "extra_query_params": {},
            "price_path": "price",
            "name_path": "name",
            "change_percent_path": "pct_change",
            "volume_path": "volume",
            "timestamp_path": "time",
        }
    )
    legacy_state["data_sources_config"]["tushare_token"] = "legacy-tushare-secret"
    agent_runtime_store.STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    agent_runtime_store.STORAGE_FILE.write_text(json.dumps(legacy_state), encoding="utf-8")

    config = agent_runtime_store.get_runtime_config()
    assert next(item for item in config.llm_profiles if item.id == "legacy_llm").api_key_set is True
    assert next(item for item in config.market_data_profiles if item.id == "legacy_market").api_key_set is True
    assert agent_runtime_store.get_llm_profile("legacy_llm").api_key == "legacy-llm-secret"
    assert agent_runtime_store.get_market_data_profile("legacy_market").api_key == "legacy-market-secret"
    assert agent_runtime_store.get_data_sources_config()["tushare_token"] == "legacy-tushare-secret"

    runtime_text = agent_runtime_store.STORAGE_FILE.read_text(encoding="utf-8")
    vault_text = (tmp_path / "agent_runtime.secrets.json").read_text(encoding="utf-8")
    assert "legacy-llm-secret" not in runtime_text
    assert "legacy-market-secret" not in runtime_text
    assert "legacy-tushare-secret" not in runtime_text
    assert "legacy-llm-secret" not in vault_text
    assert "legacy-market-secret" not in vault_text
    assert "legacy-tushare-secret" not in vault_text


def test_runtime_secret_vault_rotates_local_key_without_losing_profiles(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.upsert_llm_profile(
        "rotate_llm",
        UpsertLLMProfileRequest(
            label="Rotate LLM",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="rotate-model",
            api_key="rotate-secret",
            enabled=True,
        ),
    )
    key_path = tmp_path / "agent_runtime.secret.key"
    vault_path = tmp_path / "agent_runtime.secrets.json"
    before_key = key_path.read_text(encoding="utf-8")
    before_vault = vault_path.read_text(encoding="utf-8")

    result = rotate_runtime_secret_vault(agent_runtime_store.STORAGE_FILE)

    assert result["rotated"] is True
    assert result["secret_count"] >= 1
    assert key_path.read_text(encoding="utf-8") != before_key
    assert vault_path.read_text(encoding="utf-8") != before_vault
    assert verify_runtime_secret_vault(agent_runtime_store.STORAGE_FILE)["ok"] is True
    assert agent_runtime_store.get_llm_profile("rotate_llm").api_key == "rotate-secret"


def test_strict_llm_egress_blocks_custom_base_url_with_api_key(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = AgentLLMProfile(
        id="evil",
        label="Evil",
        provider="openai_compatible",
        base_url="https://metadata.attacker.test/v1",
        model="model",
        api_key="sk-secret",
    )

    decision = validate_llm_egress(profile)

    assert decision.allowed is False
    assert decision.code == "LLM_EGRESS_BLOCKED"
    assert "LLM_BASE_URL_ALLOWLIST" in decision.message
    assert "egress_confirmed cannot approve" in decision.message
    assert llm_runner._validate_profile(profile) == decision.message
    with pytest.raises(LLMEgressBlockedError):
        llm_runner._call_profile_chat(profile, [])

    result = agent_runtime_store.test_llm_profile_config(
        LLMProfileConfig(
            provider=profile.provider,
            base_url=profile.base_url,
            model=profile.model,
            api_key=profile.api_key,
        )
    )
    assert result.status == "BLOCKED"
    assert result.details["code"] == "LLM_EGRESS_BLOCKED"
    assert result.details["host"] == "metadata.attacker.test"


def test_strict_llm_egress_allows_official_provider_base_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    profile = AgentLLMProfile(
        id="official",
        label="Official",
        provider="openai_compatible",
        base_url="https://api.openai.com/v1",
        model="model",
        api_key="sk-secret",
    )

    decision = validate_llm_egress(profile)

    assert decision.allowed is True
    assert decision.code == "OFFICIAL_HOST_ALLOWED"
    assert llm_runner._validate_profile(profile) == ""


def test_strict_llm_egress_allows_localhost_and_allowlist(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("LLM_BASE_URL_ALLOWLIST", "https://llm-allow.example.test/v1")
    local_profile = AgentLLMProfile(
        id="local-debug",
        label="Local Debug",
        provider="openai_compatible",
        base_url="http://127.0.0.1:11434/v1",
        model="model",
        api_key="",
    )
    allowlisted_profile = AgentLLMProfile(
        id="allowlisted",
        label="Allowlisted",
        provider="openai_compatible",
        base_url="https://llm-allow.example.test/v1",
        model="model",
        api_key="sk-secret",
    )

    local_decision = validate_llm_egress(local_profile)
    allowlisted_decision = validate_llm_egress(allowlisted_profile)

    assert local_decision.allowed is True
    assert local_decision.code == "LOCALHOST_ALLOWED"
    assert llm_runner._validate_profile(local_profile) == ""
    assert allowlisted_decision.allowed is True
    assert allowlisted_decision.code == "ALLOWLIST_ALLOWED"


def test_strict_llm_egress_confirmation_does_not_bypass_server_allowlist(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = AgentLLMProfile(
        id="confirmed",
        label="Confirmed",
        provider="openai_compatible",
        base_url="https://llm-gateway.example.test/v1",
        model="model",
        api_key="sk-secret",
        egress_confirmed=True,
    )

    decision = validate_llm_egress(profile)

    assert decision.allowed is False
    assert decision.reason == "custom_base_url_requires_allowlist"
    assert "egress_confirmed cannot approve" in decision.message


def test_env_llm_api_key_does_not_attach_to_unallowlisted_custom_profile(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-secret")
    agent_runtime_store.upsert_llm_profile(
        "custom_gateway",
        UpsertLLMProfileRequest(
            label="Custom Gateway",
            provider="openai_compatible",
            base_url="https://metadata.attacker.test/v1",
            model="model",
            enabled=True,
        ),
    )

    config = get_runtime_config()
    profile = next(item for item in config.llm_profiles if item.id == "custom_gateway")

    assert profile.api_key_set is False
    assert profile.auth_available is False
    assert profile.egress_policy_status == "BLOCKED"


def test_strict_llm_egress_blocks_unspecified_bind_address(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = AgentLLMProfile(
        id="bind-address",
        label="Bind Address",
        provider="openai_compatible",
        base_url="http://0.0.0.0:11434/v1",
        model="model",
        api_key="sk-secret",
    )

    decision = validate_llm_egress(profile)

    assert decision.allowed is False
    assert decision.reason == "custom_base_url_requires_allowlist"


def test_strict_llm_egress_blocks_remote_local_provider_without_api_key(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = AgentLLMProfile(
        id="remote-local",
        label="Remote Local",
        provider="local",
        base_url="http://metadata.attacker.test:11434/v1",
        model="model",
        api_key="",
    )

    decision = validate_llm_egress(profile)

    assert decision.allowed is False
    assert decision.reason == "custom_base_url_requires_allowlist"
    assert "server-side approval" in decision.message
    assert llm_runner._validate_profile(profile) == decision.message
    with pytest.raises(LLMEgressBlockedError):
        llm_runner._call_profile_chat(profile, [])

    result = agent_runtime_store.test_llm_profile_config(
        LLMProfileConfig(
            provider=profile.provider,
            base_url=profile.base_url,
            model=profile.model,
            api_key=profile.api_key,
        )
    )
    assert result.status == "BLOCKED"
    assert result.details["auth_available"] is True
    assert result.details["live_call"] is False


def test_runtime_settings_and_agent_update_accept_flat_payload(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.upsert_llm_profile(
        "review_llm",
        UpsertLLMProfileRequest(
            label="Review LLM",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
        ),
    )

    config = agent_runtime_store.update_runtime_settings(
        UpdateRuntimeSettingsRequest(
            default_llm_profile_id="review_llm",
            apply_default_to_all_agents=True,
        )
    )
    assert all(agent.llm_profile_id == "review_llm" for agent in config.agents)

    first_agent = config.agents[0]
    config = agent_runtime_store.update_agent_llm(
        first_agent.id,
        UpdateAgentLLMRequest(llm_profile_id="default_llm", enabled=False),
    )
    updated_agent = next(agent for agent in config.agents if agent.id == first_agent.id)
    assert updated_agent.llm_profile_id == "default_llm"
    assert updated_agent.enabled is False


def test_market_data_profile_upsert_accepts_flat_payload_and_returns_auth_fields(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    config = agent_runtime_store.upsert_market_data_profile(
        "tushare_live",
        UpsertMarketDataProfileRequest(
            label="Tushare Live",
            provider="tushare",
            base_url="https://api.tushare.pro",
            auth_mode="token",
            api_key="ts-token",
            api_key_header="",
            api_key_query_param="token",
            extra_query_params={"api_name": "realtime_quote"},
            enabled=True,
        ),
    )
    profile = next(item for item in config.market_data_profiles if item.id == "tushare_live")

    assert profile.api_key_set is True
    assert profile.api_key_query_param == "token"
    assert profile.extra_query_params["api_name"] == "realtime_quote"


def test_strict_market_data_egress_blocks_custom_base_url_with_api_key(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = MarketDataProfile(
        id="evil-market",
        label="Evil Market",
        provider="generic_rest",
        base_url="https://metadata.attacker.test/quote",
        auth_mode="bearer",
        api_key="market-secret",
        enabled=True,
    )

    decision = validate_market_data_egress(profile)

    assert decision.allowed is False
    assert decision.code == "MARKET_DATA_EGRESS_BLOCKED"
    assert "MARKET_DATA_BASE_URL_ALLOWLIST" in decision.message
    with pytest.raises(MarketDataEgressBlockedError):
        market_data_runner._call_market_data_profile(profile, "603663")

    agent_runtime_store.upsert_market_data_profile(
        profile.id,
        UpsertMarketDataProfileRequest(
            label=profile.label,
            provider=profile.provider,
            base_url=profile.base_url,
            auth_mode=profile.auth_mode,
            api_key=profile.api_key,
            enabled=True,
        ),
    )
    result = agent_runtime_store.test_market_data_profile(profile.id)
    assert result.status == "BLOCKED"
    assert result.details["code"] == "MARKET_DATA_EGRESS_BLOCKED"
    assert result.details["host"] == "metadata.attacker.test"


def test_strict_market_data_egress_allows_official_and_allowlist(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("MARKET_DATA_BASE_URL_ALLOWLIST", "https://quotes-allow.example.test/api")
    official_profile = MarketDataProfile(
        id="tushare-official",
        label="Tushare Official",
        provider="tushare",
        base_url="https://api.tushare.pro",
        auth_mode="token",
        api_key="ts-token",
        enabled=True,
    )
    allowlisted_profile = MarketDataProfile(
        id="allowlisted-market",
        label="Allowlisted Market",
        provider="generic_rest",
        base_url="https://quotes-allow.example.test/api",
        auth_mode="query",
        api_key="quote-key",
        enabled=True,
    )

    official_decision = validate_market_data_egress(official_profile)
    allowlisted_decision = validate_market_data_egress(allowlisted_profile)

    assert official_decision.allowed is True
    assert official_decision.code == "OFFICIAL_HOST_ALLOWED"
    assert allowlisted_decision.allowed is True
    assert allowlisted_decision.code == "ALLOWLIST_ALLOWED"


def test_strict_market_data_egress_blocks_plaintext_tushare_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = MarketDataProfile(
        id="tushare-http",
        label="Tushare HTTP",
        provider="tushare",
        base_url="http://api.tushare.pro",
        auth_mode="token",
        api_key="ts-token",
        enabled=True,
    )

    decision = validate_market_data_egress(profile)

    assert decision.allowed is False
    assert decision.reason == "tushare_requires_https"


def test_market_data_egress_confirmation_does_not_bypass_service_allowlist(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = MarketDataProfile(
        id="confirmed-market",
        label="Confirmed Market",
        provider="generic_rest",
        base_url="https://quotes-gateway.example.test/api",
        auth_mode="none",
        api_key="",
        egress_confirmed=True,
        enabled=True,
    )

    decision = validate_market_data_egress(profile)

    assert decision.allowed is False
    assert decision.reason == "custom_base_url_requires_allowlist_or_confirmation"


def test_strict_market_data_egress_blocks_localhost_unless_allowlisted(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = MarketDataProfile(
        id="local-market",
        label="Local Market",
        provider="generic_rest",
        base_url="http://localhost:9090/quote",
        auth_mode="none",
        enabled=True,
    )

    blocked_decision = validate_market_data_egress(profile)
    assert blocked_decision.allowed is False
    assert blocked_decision.host == "localhost"

    monkeypatch.setenv("MARKET_DATA_BASE_URL_ALLOWLIST", "localhost")
    allowed_decision = validate_market_data_egress(profile)
    assert allowed_decision.allowed is True
    assert allowed_decision.code == "ALLOWLIST_ALLOWED"


def test_market_data_egress_validates_absolute_quote_path(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = MarketDataProfile(
        id="absolute-quote-path",
        label="Absolute Quote Path",
        provider="generic_rest",
        base_url="https://www.alphavantage.co/query",
        quote_path="https://metadata.attacker.test/quote",
        auth_mode="query",
        api_key="quote-key",
        enabled=True,
    )

    decision = validate_market_data_egress(profile)

    assert decision.allowed is False
    assert decision.host == "metadata.attacker.test"
    with pytest.raises(MarketDataEgressBlockedError):
        market_data_runner._call_market_data_profile(profile, "603663")


def test_tushare_http_helpers_block_custom_base_url_with_token(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    profile = MarketDataProfile(
        id="evil-tushare",
        label="Evil Tushare",
        provider="tushare",
        base_url="https://metadata.attacker.test/tushare",
        auth_mode="token",
        api_key="ts-token",
        enabled=True,
    )

    with pytest.raises(MarketDataEgressBlockedError):
        market_data_runner._call_tushare_http_api_raw(profile, "daily", {"ts_code": "603663.SH"})

    from app.core.adapters.tushare_adapter import _call_tushare_http_api_sync

    with pytest.raises(MarketDataEgressBlockedError):
        _call_tushare_http_api_sync(profile, "daily", {"ts_code": "603663.SH"})


def test_market_data_cache_does_not_mask_endpoint_policy_changes(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("MARKET_DATA_BASE_URL_ALLOWLIST", "quotes-allow.example.test")
    market_data_runner._MARKET_DATA_CACHE.clear()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"name":"Safe Quote","price":10.0,"volume":1000}'

    monkeypatch.setattr(market_data_runner, "urlopen", lambda request, timeout: FakeResponse())
    allowed_profile = MarketDataProfile(
        id="cache-profile",
        label="Cache Profile",
        provider="generic_rest",
        base_url="https://quotes-allow.example.test/api",
        auth_mode="none",
        enabled=True,
    )
    blocked_profile = MarketDataProfile(
        id="cache-profile",
        label="Cache Profile",
        provider="generic_rest",
        base_url="https://metadata.attacker.test/api",
        auth_mode="none",
        enabled=True,
    )

    first_result = asyncio.run(market_data_runner.fetch_market_data(allowed_profile, "603663"))
    second_result = asyncio.run(market_data_runner.fetch_market_data(blocked_profile, "603663"))

    assert first_result.status == "READY"
    assert second_result.status == "BLOCKED"
    assert "MARKET_DATA_BASE_URL_ALLOWLIST" in second_result.error


def test_runtime_profiles_expose_base_url_security(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    monkeypatch.setenv("API_AUTH_MODE", "strict")
    monkeypatch.setenv("LLM_BASE_URL_ALLOWLIST", "https://llm-allow.example.test/v1")
    monkeypatch.setenv(
        "MARKET_DATA_BASE_URL_ALLOWLIST",
        "https://quotes-allow.example.test/api",
    )

    agent_runtime_store.upsert_llm_profile(
        "blocked_llm",
        UpsertLLMProfileRequest(
            label="Blocked LLM",
            provider="openai_compatible",
            base_url="https://metadata.attacker.test/v1",
            model="model",
            api_key="sk-secret",
            enabled=True,
        ),
    )
    agent_runtime_store.upsert_llm_profile(
        "allowlisted_llm",
        UpsertLLMProfileRequest(
            label="Allowlisted LLM",
            provider="openai_compatible",
            base_url="https://llm-allow.example.test/v1",
            model="model",
            api_key="sk-secret",
            enabled=True,
        ),
    )
    config = agent_runtime_store.upsert_market_data_profile(
        "allowlisted_market",
        UpsertMarketDataProfileRequest(
            label="Allowlisted Market",
            provider="generic_rest",
            base_url="https://quotes-allow.example.test/api",
            auth_mode="none",
            enabled=True,
        ),
    )

    blocked = next(profile for profile in config.llm_profiles if profile.id == "blocked_llm")
    allowlisted = next(
        profile for profile in config.llm_profiles if profile.id == "allowlisted_llm"
    )
    market = next(
        profile
        for profile in config.market_data_profiles
        if profile.id == "allowlisted_market"
    )

    assert blocked.base_url_security.status == "BLOCKED"
    assert blocked.base_url_security.allowed is False
    assert blocked.base_url_security.strict_mode_required is True
    assert blocked.base_url_security.code == "LLM_EGRESS_BLOCKED"
    assert blocked.base_url_security.host == "metadata.attacker.test"
    assert blocked.base_url_security.reason == "custom_base_url_requires_allowlist"
    assert "llm-allow.example.test" in blocked.base_url_security.allowed_hosts
    assert "sk-secret" not in blocked.base_url_security.message

    assert allowlisted.base_url_security.status == "TRUSTED"
    assert allowlisted.base_url_security.allowed is True
    assert allowlisted.base_url_security.strict_mode_required is True
    assert allowlisted.base_url_security.code == "ALLOWLIST_ALLOWED"
    assert allowlisted.base_url_security.reason == "allowlist"
    assert allowlisted.base_url_security.host == "llm-allow.example.test"

    assert market.base_url_security.status == "TRUSTED"
    assert market.base_url_security.allowed is True
    assert market.base_url_security.strict_mode_required is True
    assert market.base_url_security.code == "ALLOWLIST_ALLOWED"
    assert market.base_url_security.reason == "allowlist"
    assert market.base_url_security.host == "quotes-allow.example.test"
    assert "quotes-allow.example.test" in market.base_url_security.allowed_hosts


def test_runtime_profiles_report_health_status(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    config = get_runtime_config()
    default_llm = next(profile for profile in config.llm_profiles if profile.id == "default_llm")
    default_market = next(
        profile
        for profile in config.market_data_profiles
        if profile.id == "default_market_data"
    )

    assert default_llm.health_status == "INCOMPLETE"
    assert "api_key_missing" in default_llm.health_warnings
    assert default_market.health_status == "INCOMPLETE"
    assert "api_key_missing" in default_market.health_warnings

    config = agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )
    local_profile = next(profile for profile in config.llm_profiles if profile.id == "local_ready")
    assert local_profile.health_status == "CONFIGURED"
    assert local_profile.health_warnings == []

    config = agent_runtime_store.upsert_market_data_profile(
        "public_quote",
        UpsertMarketDataProfileRequest(
            label="Public Quote",
            provider="generic_rest",
            base_url="https://quotes.example.test",
            auth_mode="none",
            enabled=True,
        ),
    )
    market_profile = next(
        profile for profile in config.market_data_profiles if profile.id == "public_quote"
    )
    assert market_profile.health_status == "CONFIGURED"
    assert market_profile.health_warnings == []


def test_market_data_profile_live_test_result_is_visible_in_runtime(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_market_data_profile(
        "public_quote",
        UpsertMarketDataProfileRequest(
            label="Public Quote",
            provider="generic_rest",
            base_url="https://quotes.example.test",
            auth_mode="none",
            enabled=True,
        ),
    )

    field_result = agent_runtime_store.test_market_data_profile("public_quote")
    assert field_result.status == "CONFIGURED"
    assert field_result.details["live_call"] is False

    agent_runtime_store.record_market_data_profile_test_result(
        "public_quote",
        agent_runtime_store.MarketDataConfigTestResult(
            profile_id="public_quote",
            status="READY",
            message="Live market data connection succeeded.",
            details={"latency_ms": 12, "live_call": True},
        ),
        live_call=True,
    )

    config = agent_runtime_store.get_runtime_config()
    profile = next(item for item in config.market_data_profiles if item.id == "public_quote")
    assert profile.health_status == "READY"
    assert profile.last_call_success is True
    assert profile.last_latency_ms == 12


def test_market_data_runtime_ready_requires_persisted_live_success(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    market_data_runner._MARKET_DATA_CACHE.clear()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"name":"Sample Quote","price":12.3,"volume":1000,"timestamp":"2026-05-20T10:00:00Z"}'

    monkeypatch.setattr(market_data_runner, "urlopen", lambda request, timeout: FakeResponse())
    agent_runtime_store.upsert_market_data_profile(
        "public_quote",
        UpsertMarketDataProfileRequest(
            label="Public Quote",
            provider="generic_rest",
            base_url="https://quotes.example.test",
            auth_mode="none",
            enabled=True,
        ),
    )
    agent_runtime_store.update_runtime_settings(
        UpdateRuntimeSettingsRequest(default_market_data_profile_id="public_quote")
    )

    summary_before = agent_runtime_store.get_runtime_summary()
    assert summary_before["marketData"]["ready"] is False

    profile = agent_runtime_store.get_market_data_profile("public_quote")
    result = asyncio.run(market_data_runner.fetch_market_data(profile, "603663"))

    assert result.status == "READY"
    config = agent_runtime_store.get_runtime_config()
    public_profile = next(item for item in config.market_data_profiles if item.id == "public_quote")
    assert public_profile.health_status == "READY"
    assert public_profile.last_call_success is True
    assert public_profile.last_test_status == "READY"
    summary_after = agent_runtime_store.get_runtime_summary()
    assert summary_after["marketData"]["ready"] is True


def test_llm_profile_test_result_is_visible_in_runtime(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )

    field_result = agent_runtime_store.test_llm_profile("local_ready")
    assert field_result.status == "CONFIGURED"
    assert field_result.details["live_call"] is False

    monkeypatch.setattr(
        llm_profile_tester,
        "_call_profile_chat",
        lambda profile, messages: {"usage": {"total_tokens": 3}},
    )
    live_result = asyncio.run(
        llm_profile_tester.test_llm_profile_connection("local_ready", live_call=True)
    )
    assert live_result.status == "READY"

    config = agent_runtime_store.get_runtime_config()
    profile = next(item for item in config.llm_profiles if item.id == "local_ready")
    assert profile.health_status == "READY"
    assert profile.configured is True
    assert profile.auth_available is True
    assert profile.last_call_success is True
    assert isinstance(profile.last_latency_ms, int)
    assert profile.last_usage["total_tokens"] == 3

    summary_profile = next(
        item for item in agent_runtime_store.get_runtime_summary()["llmProfiles"]
        if item["id"] == "local_ready"
    )
    assert summary_profile["lastCallSuccess"] is True
    assert isinstance(summary_profile["lastLatencyMs"], int)


def test_llm_profile_live_test_uses_short_probe_limits(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_llm_profile(
        "slow_upstream",
        UpsertLLMProfileRequest(
            label="Slow Upstream",
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-flash",
            api_key="sk-test-secret",
            max_tokens=4096,
            timeout_seconds=120,
            enabled=True,
        ),
    )

    captured = {}

    def fake_call(profile, messages):
        captured["timeout_seconds"] = profile.timeout_seconds
        captured["max_tokens"] = profile.max_tokens
        captured["disable_thinking"] = getattr(profile, "live_test_disable_thinking", False)
        return {"usage": {"total_tokens": 3}}

    monkeypatch.setattr(llm_profile_tester, "_call_profile_chat", fake_call)

    result = asyncio.run(
        llm_profile_tester.test_llm_profile_connection("slow_upstream", live_call=True)
    )

    assert result.status == "READY"
    assert captured["timeout_seconds"] == llm_profile_tester.LIVE_TEST_TIMEOUT_SECONDS
    assert captured["max_tokens"] == llm_profile_tester.LIVE_TEST_MAX_RESPONSE_TOKENS
    assert captured["disable_thinking"] is True
    assert result.details["timeout_seconds"] == llm_profile_tester.LIVE_TEST_TIMEOUT_SECONDS
    assert agent_runtime_store.get_llm_profile("slow_upstream").timeout_seconds == 120


def test_openai_compatible_probe_disables_deepseek_v4_thinking(monkeypatch):
    profile = AgentLLMProfile(
        id="deepseek_probe",
        label="DeepSeek Probe",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        api_key="sk-test-secret",
    ).model_copy(update={"live_test_disable_thinking": True})
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"OK"}}]}'

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(llm_runner, "urlopen", fake_urlopen)

    response = llm_runner._call_openai_compatible_chat(
        profile,
        [{"role": "user", "content": "Reply OK"}],
    )

    assert response["choices"][0]["message"]["content"] == "OK"
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_llm_profile_static_check_preserves_last_live_call_metadata(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )
    monkeypatch.setattr(
        llm_profile_tester,
        "_call_profile_chat",
        lambda profile, messages: {"usage": {"total_tokens": 3}},
    )
    asyncio.run(llm_profile_tester.test_llm_profile_connection("local_ready", live_call=True))
    ready_profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "local_ready"
    )

    static_result = asyncio.run(
        llm_profile_tester.test_llm_profile_connection("local_ready", live_call=False)
    )

    assert static_result.status == "CONFIGURED"
    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "local_ready"
    )
    assert profile.health_status == "READY"
    assert profile.last_call_success is True
    assert profile.last_live_call_at == ready_profile.last_live_call_at
    assert profile.last_usage["total_tokens"] == 3
    assert profile.last_checked_at != ready_profile.last_checked_at


def test_llm_profile_live_test_precheck_failure_does_not_set_live_call_at(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_llm_profile(
        "missing_key",
        UpsertLLMProfileRequest(
            label="Missing Key",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="model",
            enabled=True,
        ),
    )

    result = asyncio.run(
        llm_profile_tester.test_llm_profile_connection("missing_key", live_call=True)
    )

    assert result.status == "INCOMPLETE"
    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "missing_key"
    )
    assert profile.health_status == "INCOMPLETE"
    assert profile.last_call_success is None
    assert profile.last_live_call_at == ""
    assert profile.last_latency_ms is None


def test_llm_profile_live_test_failure_records_latency(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )

    def raise_timeout(profile, messages):
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_profile_tester, "_call_profile_chat", raise_timeout)
    result = asyncio.run(
        llm_profile_tester.test_llm_profile_connection("local_ready", live_call=True)
    )

    assert result.status == "FAILED"
    assert result.message == "Live LLM connection timed out after 15 seconds."
    assert result.details["error"] == "live_call_timeout"
    assert result.details["timeout_seconds"] == llm_profile_tester.LIVE_TEST_TIMEOUT_SECONDS
    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "local_ready"
    )
    assert profile.health_status == "FAILED"
    assert profile.last_call_success is False
    assert profile.last_live_call_at == profile.last_checked_at
    assert isinstance(profile.last_latency_ms, int)


def test_llm_profile_live_test_reports_provider_http_error(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    agent_runtime_store.upsert_llm_profile(
        "bad_model",
        UpsertLLMProfileRequest(
            label="Bad Model",
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="missing-model",
            api_key="sk-test-secret",
            enabled=True,
        ),
    )

    def raise_http_error(profile, messages):
        body = b'{"error":{"message":"Model Not Exist","code":"invalid_request_error"}}'
        raise HTTPError(profile.base_url, 400, "Bad Request", {}, BytesIO(body))

    monkeypatch.setattr(llm_profile_tester, "_call_profile_chat", raise_http_error)

    result = asyncio.run(
        llm_profile_tester.test_llm_profile_connection("bad_model", live_call=True)
    )

    assert result.status == "FAILED"
    assert result.message == (
        "LLM service rejected the test request (HTTP 400): Model Not Exist "
        "Check the model ID and OpenAI-compatible request format."
    )
    assert result.details["error"] == result.message
    assert result.details["error_type"] == "HTTPError"

    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "bad_model"
    )
    assert profile.health_status == "FAILED"
    assert profile.last_call_success is False
    assert profile.last_error == result.message
    assert "sk-test-secret" not in profile.last_error


def test_run_agent_llm_persists_success_to_profile_health(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )
    agent_runtime_store.update_runtime_settings(
        UpdateRuntimeSettingsRequest(
            default_llm_profile_id="local_ready",
            apply_default_to_all_agents=True,
        )
    )
    monkeypatch.setattr(
        llm_runner,
        "_call_profile_chat",
        lambda profile, messages: {
            "choices": [
                {
                    "message": {"content": '{"status":"PASS"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 7},
        },
    )

    result = asyncio.run(llm_runner.run_agent_llm("orchestrator", {"runId": "RUN_LLM_OK"}, {}))

    assert result.status == "COMPLETED"
    config = agent_runtime_store.get_runtime_config()
    profile = next(item for item in config.llm_profiles if item.id == "local_ready")
    assert profile.health_status == "READY"
    assert profile.last_call_success is True
    assert profile.last_test_status == "READY"
    assert profile.last_test_message == "Live agent LLM call succeeded for orchestrator."
    assert profile.last_checked_at
    assert profile.last_live_call_at == profile.last_checked_at
    assert isinstance(profile.last_latency_ms, int)
    assert profile.last_usage["total_tokens"] == 7

    summary_profile = next(
        item for item in agent_runtime_store.get_runtime_summary()["llmProfiles"]
        if item["id"] == "local_ready"
    )
    assert summary_profile["status"] == "READY"
    assert summary_profile["lastCallSuccess"] is True


def test_run_agent_llm_persists_failure_and_downgrades_ready(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )
    agent_runtime_store.update_runtime_settings(
        UpdateRuntimeSettingsRequest(
            default_llm_profile_id="local_ready",
            apply_default_to_all_agents=True,
        )
    )
    monkeypatch.setattr(
        llm_runner,
        "_call_profile_chat",
        lambda profile, messages: {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"total_tokens": 3},
        },
    )
    asyncio.run(llm_runner.run_agent_llm("orchestrator", {"runId": "RUN_LLM_READY"}, {}))
    ready_profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "local_ready"
    )
    assert ready_profile.health_status == "READY"

    def raise_timeout(profile, messages):
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm_runner, "_call_profile_chat", raise_timeout)
    result = asyncio.run(llm_runner.run_agent_llm("orchestrator", {"runId": "RUN_LLM_FAIL"}, {}))

    assert result.status == "FAILED"
    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "local_ready"
    )
    assert profile.health_status == "FAILED"
    assert profile.last_call_success is False
    assert profile.last_test_status == "FAILED"
    assert "network or transport" in profile.last_error
    assert profile.last_checked_at
    assert profile.last_live_call_at == profile.last_checked_at
    assert isinstance(profile.last_latency_ms, int)


def test_run_agent_llm_persists_provider_http_error_reason(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.upsert_llm_profile(
        "bad_model",
        UpsertLLMProfileRequest(
            label="Bad Model",
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="missing-model",
            api_key="sk-test-secret",
            enabled=True,
        ),
    )
    agent_runtime_store.update_runtime_settings(
        UpdateRuntimeSettingsRequest(
            default_llm_profile_id="bad_model",
            apply_default_to_all_agents=True,
        )
    )

    def raise_http_error(profile, messages):
        body = (
            b'{"error":{"message":"Model Not Exist for key sk-test-secret",'
            b'"code":"invalid_request_error"}}'
        )
        raise HTTPError(profile.base_url, 400, "Bad Request", {}, BytesIO(body))

    monkeypatch.setattr(llm_runner, "_call_profile_chat", raise_http_error)

    result = asyncio.run(llm_runner.run_agent_llm("orchestrator", {"runId": "RUN_LLM_BAD_MODEL"}, {}))

    assert result.status == "FAILED"
    assert result.error == (
        "LLM service rejected the request (HTTP 400): Model Not Exist for key sk-... "
        "Check the model ID and OpenAI-compatible request format."
    )
    assert "sk-test-secret" not in result.error

    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "bad_model"
    )
    assert profile.health_status == "FAILED"
    assert profile.last_call_success is False
    assert profile.last_error == result.error
    assert profile.last_test_message == result.error


def test_run_agent_llm_persists_skipped_live_call_attempt(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.upsert_llm_profile(
        "local_ready",
        UpsertLLMProfileRequest(
            label="Local Ready",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model",
            enabled=True,
        ),
    )
    agent_runtime_store.update_runtime_settings(
        UpdateRuntimeSettingsRequest(
            default_llm_profile_id="local_ready",
            apply_default_to_all_agents=True,
        )
    )
    decision = LLMEgressDecision(
        allowed=False,
        code="LLM_EGRESS_BLOCKED",
        message="blocked by test policy",
        strict_mode=True,
        host="localhost",
        reason="test_policy",
    )

    def raise_blocked(profile, messages):
        raise LLMEgressBlockedError(decision)

    monkeypatch.setattr(llm_runner, "_call_profile_chat", raise_blocked)
    result = asyncio.run(llm_runner.run_agent_llm("orchestrator", {"runId": "RUN_LLM_SKIP"}, {}))

    assert result.status == "SKIPPED"
    profile = next(
        item for item in agent_runtime_store.get_runtime_config().llm_profiles
        if item.id == "local_ready"
    )
    assert profile.health_status == "CONFIGURED"
    assert profile.last_call_success is None
    assert profile.last_test_status == "SKIPPED"
    assert profile.last_error == "blocked by test policy"
    assert profile.last_checked_at
    assert profile.last_live_call_at == ""
    assert profile.last_latency_ms is None


def test_market_data_adapter_config_is_persisted(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    configs = agent_runtime_store.get_market_data_adapter_configs()
    akshare = next(config for config in configs if config.adapter_id == "akshare")
    tencent = next(config for config in configs if config.adapter_id == "tencent_finance")
    tongdaxin = next(config for config in configs if config.adapter_id == "tongdaxin")
    ifind = next(config for config in configs if config.adapter_id == "ifind")

    assert akshare.label == "AkShare (东方财富)"
    assert akshare.enabled is True
    assert akshare.priority == 5
    assert akshare.timeout_seconds == 15
    assert tencent.label == "腾讯财经"
    assert tencent.priority == 2
    assert tencent.requires_token is False
    assert "REALTIME_QUOTE" in tencent.capabilities
    assert tongdaxin.requires_token is True
    assert "CHIP" in tongdaxin.capabilities
    assert ifind.label == "同花顺 iFinD"
    assert "MACRO" in ifind.capabilities

    updated = agent_runtime_store.update_market_data_adapter_config(
        "akshare",
        UpdateMarketDataAdapterConfigRequest(
            enabled=False,
            priority=8,
            timeout_seconds=30,
        ),
    )

    assert updated.enabled is False
    assert updated.priority == 8
    assert updated.timeout_seconds == 30

    reloaded = agent_runtime_store.get_market_data_adapter_config("akshare")
    assert reloaded.enabled is False
    assert reloaded.priority == 8
    assert reloaded.timeout_seconds == 30


def test_market_data_adapter_config_routes(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    response = asyncio.run(routes_agents.get_market_data_adapters_config())
    assert any(item["adapter_id"] == "akshare" for item in response)
    assert any(item["adapter_id"] == "tencent_finance" for item in response)
    assert any(item["adapter_id"] == "tongdaxin" for item in response)
    assert any(item["adapter_id"] == "ifind" for item in response)

    response = asyncio.run(
        routes_agents.put_market_data_adapter_config(
            "sina",
            UpdateMarketDataAdapterConfigRequest(
                enabled=False,
                priority=7,
                timeout_seconds=22,
            ),
        )
    )
    assert response["adapter_id"] == "sina"
    assert response["enabled"] is False
    assert response["priority"] == 7
    assert response["timeout_seconds"] == 22


def test_default_data_sources_match_tushare_8000_tier(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)

    config = agent_runtime_store.get_data_sources_config()
    sources = {item["key"]: item for item in config["sources"]}

    expected_keys = {
        "stock_basic",
        "realtime_quote",
        "kline_quote",
        "etf_data",
        "derivative_basic",
        "cross_market_basic",
        "fundamentals",
        "announcements",
        "macro",
        "reference_data",
        "moneyflow",
        "chip",
        "special_data",
    }
    assert expected_keys.issubset(sources)
    assert all(sources[key]["enabled"] is True for key in expected_keys)
    assert sources["moneyflow"]["required_credits"] == 8000
    assert sources["special_data"]["tushare_api"] == "concept/concept_detail/broker_recommend/top_inst/stk_factor"
    assert sources["realtime_quote"]["provider_apis"]["tencent_finance"] == "authorized quote gateway"
    assert sources["kline_quote"]["providers"] == ["tushare", "tencent_finance", "tongdaxin", "ifind"]
    assert "ifind" in sources["macro"]["provider_apis"]


def test_data_source_group_test_uses_each_tushare_api(monkeypatch, tmp_path):
    use_temp_runtime_store(monkeypatch, tmp_path)
    agent_runtime_store.save_data_sources_config(
        "test-token",
        [
            {
                "key": "special_data",
                "name": "特色数据",
                "tushare_api": "concept/broker_recommend/stk_factor",
                "enabled": True,
                "description": "test",
            }
        ],
    )

    from app.core import market_data_runner

    calls = []

    def fake_call(profile, api_name, params):
        calls.append((api_name, params))
        return {"records": [{"api": api_name}]}

    monkeypatch.setattr(market_data_runner, "_call_tushare_http_api_raw", fake_call)

    response = asyncio.run(routes_agents.post_data_source_test("special_data"))

    assert response["status"] == "READY"
    assert response["record_count"] == 5
    assert [api for api, _params in calls] == [
        "concept",
        "concept_detail",
        "broker_recommend",
        "top_inst",
        "stk_factor",
    ]
    assert calls[2][1]["month"]
    assert calls[4][1]["ts_code"] == "603663.SH"


def test_market_data_adapters_route_is_metadata_by_default(monkeypatch):
    from app.core import market_data_adapter

    class FakeRegistry:
        def list_adapters(self):
            return [
                DataSourceHealth(
                    adapter_id="fake",
                    provider="fake",
                    label="Fake adapter",
                    enabled=True,
                    installed=True,
                )
            ]

        async def health_check_all(self):
            raise AssertionError("GET /agents/market-data/adapters should not run live checks by default")

    monkeypatch.setattr(market_data_adapter, "register_default_market_data_adapters", lambda: FakeRegistry())

    response = asyncio.run(routes_agents.get_market_data_adapters())

    assert response[0]["adapterId"] == "fake"
    assert response[0]["healthCheckMode"] == "metadata"
    assert "metadata" in response[0]["message"]


def test_market_data_adapters_route_can_run_explicit_live_check(monkeypatch):
    from app.core import market_data_adapter

    class FakeRegistry:
        def list_adapters(self):
            raise AssertionError("live_check=True should use health_check_all")

        async def health_check_all(self):
            return [
                DataSourceHealth(
                    adapter_id="fake",
                    provider="fake",
                    label="Fake adapter",
                    healthy=True,
                    upstream_healthy=True,
                    live_data_usable=True,
                )
            ]

    monkeypatch.setattr(market_data_adapter, "register_default_market_data_adapters", lambda: FakeRegistry())

    response = asyncio.run(routes_agents.get_market_data_adapters(live_check=True))

    assert response[0]["adapterId"] == "fake"
    assert response[0]["healthy"] is True
