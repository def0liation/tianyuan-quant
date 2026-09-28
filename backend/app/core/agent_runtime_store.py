import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .file_utils import atomic_replace_file
from ..models.agent_runtime import (
    AgentDeployment,
    AgentLLMProfile,
    AgentLLMProfilePublic,
    AgentRuntimeConfig,
    LLMConfigTestResult,
    LLMProfileConfig,
    MarketDataAdapterConfig,
    MarketDataConfigTestResult,
    MarketDataProfile,
    MarketDataProfilePublic,
    UpdateAgentLLMRequest,
    UpdateMarketDataAdapterConfigRequest,
    UpdateRuntimeSettingsRequest,
    UpsertMarketDataProfileRequest,
    UpsertLLMProfileRequest,
)
from .agent_framework import CONSOLIDATED_AGENT_REDIRECTS, agent_definitions, sync_agent_state
from .llm_egress_policy import (
    LLMEgressDecision,
    configured_allowlist_hosts,
    validate_llm_egress,
)
from .market_data_egress_policy import (
    MarketDataEgressDecision,
    configured_market_data_allowlist_hosts,
    validate_market_data_egress,
)
from .config_store import (
    RUNTIME_SECRET_REF_PREFIX,
    SECRET_VAULT_REFS_SNAPSHOT_KEY,
    redact_config_payload,
)
from .secret_store import (
    delete_runtime_secret,
    load_runtime_secret,
    runtime_secret_storage_status,
    store_runtime_secret,
    store_runtime_secret_version,
)


STORAGE_FILE = Path(__file__).resolve().parents[1] / "storage" / "agent_runtime.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


RUNTIME_RESTORE_KEYS = (
    "default_llm_profile_id",
    "default_market_data_profile_id",
    "max_parallel_agents",
    "llm_profiles",
    "market_data_profiles",
    "agents",
    "data_sources_config",
    "market_data_adapter_configs",
)
REDACTED_VALUE = "<redacted>"


def runtime_config_audit_snapshot(*, include_secret_versions: bool = False) -> Dict[str, Any]:
    state = _load_state()
    snapshot = redact_config_payload(
        {
            "default_llm_profile_id": state.get("default_llm_profile_id", ""),
            "default_market_data_profile_id": state.get("default_market_data_profile_id", ""),
            "max_parallel_agents": state.get("max_parallel_agents", 5),
            "llm_profiles": state.get("llm_profiles", []),
            "market_data_profiles": state.get("market_data_profiles", []),
            "agents": state.get("agents", []),
            "data_sources_config": state.get("data_sources_config", {}),
            "market_data_adapter_configs": state.get("market_data_adapter_configs", []),
            "secret_refs": state.get("secret_refs", {}),
            "updated_at": state.get("updated_at", ""),
        }
    )
    snapshot["secret_refs"] = _public_secret_refs(
        state.get("secret_refs", {}),
        include_versions=include_secret_versions,
    )
    return snapshot


def _public_secret_refs(value: Any, *, include_versions: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_secret_refs(item, include_versions=include_versions)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_public_secret_refs(item, include_versions=include_versions) for item in value]
    if isinstance(value, str) and value.startswith(RUNTIME_SECRET_REF_PREFIX):
        if include_versions:
            secret_value = load_runtime_secret(STORAGE_FILE, value)
            if secret_value is not None:
                return store_runtime_secret_version(STORAGE_FILE, value, secret_value)
        return value
    if isinstance(value, str):
        return "<redacted>" if value else value
    return value


def _base_url_security(decision: Any, allowed_hosts: Iterable[str]) -> Dict[str, Any]:
    if not decision.allowed:
        status = "BLOCKED"
    elif decision.code == "BASE_URL_MISSING":
        status = "MISSING"
    elif decision.reason == "localhost":
        status = "LOCAL"
    elif decision.reason in {"official_provider_host", "allowlist"}:
        status = "TRUSTED"
    else:
        status = "CUSTOM"
    return {
        "status": status,
        "allowed": bool(decision.allowed),
        "strict_mode_required": bool(decision.strict_mode),
        "message": decision.message,
        "code": decision.code,
        "host": decision.host,
        "reason": decision.reason,
        "allowed_hosts": list(allowed_hosts),
        "confirmed_at": None,
        "confirmed_by": None,
    }


def build_runtime_config_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    changed: Dict[str, Any] = {}
    keys = sorted(set(before) | set(after))
    for key in keys:
        if before.get(key) != after.get(key):
            changed[key] = {
                "before": before.get(key),
                "after": after.get(key),
            }
    return redact_config_payload(changed)


def restore_runtime_config_snapshot(
    snapshot: Dict[str, Any],
    *,
    approval_id: str,
    reason: str,
    restore_keys: Iterable[str] | None = None,
) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError("Runtime restore snapshot must be an object.")
    if not approval_id.strip():
        raise ValueError("Runtime restore requires an approval id.")
    if not reason.strip():
        raise ValueError("Runtime restore requires a reason.")

    state = _load_state()
    restored = json.loads(json.dumps(state))
    skipped_redacted_paths: list[str] = []
    applied_keys: list[str] = []

    requested_keys = tuple(restore_keys or RUNTIME_RESTORE_KEYS)
    unknown_keys = sorted(set(requested_keys) - set(RUNTIME_RESTORE_KEYS))
    if unknown_keys:
        raise ValueError(f"Unsupported runtime restore keys: {', '.join(unknown_keys)}.")

    for key in requested_keys:
        if key not in snapshot:
            continue
        restored[key] = _merge_snapshot_value(
            state.get(key),
            snapshot.get(key),
            path=key,
            skipped=skipped_redacted_paths,
        )
        applied_keys.append(key)

    required_secret_refs = _required_secret_refs_from_snapshot(snapshot, restore_keys=requested_keys)
    _apply_required_secret_refs(restored, required_secret_refs)
    if "data_sources_config" in requested_keys:
        config = restored.get("data_sources_config")
        if isinstance(config, dict):
            token = str(config.get("tushare_token") or "") or _load_secret_ref(
                restored,
                _config_secret_ref(restored, "tushare_token"),
            )
            if token:
                _apply_token_to_market_profiles(restored, token)
    _validate_restored_runtime_state(restored)
    restored.setdefault("runtime_restore_history", []).append(
        {
            "approval_id": approval_id.strip(),
            "reason": reason.strip(),
            "restored_at": _now(),
            "required_secret_ref_count": len(required_secret_refs),
            "applied_keys": applied_keys,
        }
    )
    _save_state(restored)
    return {
        "status": "RESTORED",
        "applied_keys": applied_keys,
        "required_secret_ref_count": len(required_secret_refs),
        "skipped_redacted_paths": skipped_redacted_paths,
    }


def _merge_snapshot_value(current: Any, snapshot: Any, *, path: str, skipped: list[str]) -> Any:
    if snapshot == REDACTED_VALUE:
        skipped.append(path)
        return current
    if isinstance(snapshot, dict):
        current_dict = current if isinstance(current, dict) else {}
        return {
            str(key): _merge_snapshot_value(
                current_dict.get(key),
                value,
                path=f"{path}.{key}",
                skipped=skipped,
            )
            for key, value in snapshot.items()
            if key != SECRET_VAULT_REFS_SNAPSHOT_KEY
        }
    if isinstance(snapshot, list):
        current_list = current if isinstance(current, list) else []
        return [
            _merge_snapshot_value(
                current_list[index] if index < len(current_list) else None,
                value,
                path=f"{path}.{index}",
                skipped=skipped,
            )
            for index, value in enumerate(snapshot)
        ]
    return snapshot


def _required_secret_refs_from_snapshot(
    snapshot: Dict[str, Any],
    *,
    restore_keys: Iterable[str] | None = None,
) -> list[Dict[str, str]]:
    refs = snapshot.get(SECRET_VAULT_REFS_SNAPSHOT_KEY, [])
    if not isinstance(refs, list):
        return []
    key_set = set(restore_keys or RUNTIME_RESTORE_KEYS)
    required_refs = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        ref = str(item.get("ref") or "")
        if path and ref and _secret_ref_matches_restore_keys(path, key_set):
            required_refs.append({"path": path, "ref": ref})
    return required_refs


def _secret_ref_matches_restore_keys(path: str, restore_keys: set[str]) -> bool:
    if "secret_refs" in restore_keys:
        return True
    parts = path.split(".")
    if len(parts) < 2 or parts[0] != "secret_refs":
        return False
    section = parts[1]
    if section == "llm_profiles":
        return "llm_profiles" in restore_keys
    if section == "market_data_profiles":
        return "market_data_profiles" in restore_keys
    if section == "data_sources_config":
        return "data_sources_config" in restore_keys
    return False


def _apply_required_secret_refs(state: Dict[str, Any], required_refs: list[Dict[str, str]]) -> None:
    for item in required_refs:
        path = item["path"]
        ref = item["ref"]
        if not ref.startswith(RUNTIME_SECRET_REF_PREFIX):
            raise ValueError(f"Invalid runtime secret ref for restore: {path}.")
        if ":version:" not in ref:
            raise ValueError(f"Secret restore requires an immutable vault version ref: {path}.")
        if load_runtime_secret(STORAGE_FILE, ref) is None:
            raise ValueError(f"Secret vault version is unavailable for restore: {path}.")
        parts = path.split(".")
        if len(parts) < 3 or parts[0] != "secret_refs":
            raise ValueError(f"Invalid secret ref restore path: {path}.")
        target: Any = state.setdefault("secret_refs", {})
        for part in parts[1:-1]:
            if not isinstance(target, dict):
                raise ValueError(f"Invalid secret ref restore path: {path}.")
            target = target.setdefault(part, {})
        if not isinstance(target, dict):
            raise ValueError(f"Invalid secret ref restore path: {path}.")
        target[parts[-1]] = ref


def _validate_restored_runtime_state(state: Dict[str, Any]) -> None:
    llm_profile_ids = {
        str(profile.get("id") or "")
        for profile in state.get("llm_profiles", [])
        if isinstance(profile, dict)
    }
    market_profile_ids = {
        str(profile.get("id") or "")
        for profile in state.get("market_data_profiles", [])
        if isinstance(profile, dict)
    }
    if state.get("default_llm_profile_id") not in llm_profile_ids:
        raise ValueError("Restored runtime config has an invalid default LLM profile.")
    if state.get("default_market_data_profile_id") not in market_profile_ids:
        raise ValueError("Restored runtime config has an invalid default market data profile.")


def _mask_api_key(api_key: str) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


DEFAULT_PROFILE_ID = "default_llm"
DEFAULT_MARKET_DATA_PROFILE_ID = "default_market_data"
TUSHARE_DEFAULT_FIELDS = (
    "NAME,TS_CODE,DATE,TIME,OPEN,PRE_CLOSE,PRICE,HIGH,LOW,VOLUME,AMOUNT"
)
DEFAULT_MARKET_DATA_ADAPTER_CONFIGS = [
    {
        "adapter_id": "tushare",
        "provider": "tushare",
        "label": "Tushare",
        "enabled": True,
        "priority": 1,
        "timeout_seconds": 20,
        "requires_token": True,
        "capabilities": ["REALTIME_QUOTE", "HISTORICAL_QUOTE", "FUNDAMENTALS", "ANNOUNCEMENTS", "MONEYFLOW", "CHIP", "MACRO"],
        "note": "使用数据源配置中的 Tushare Token。",
    },
    {
        "adapter_id": "akshare",
        "provider": "akshare",
        "label": "AkShare (东方财富)",
        "enabled": True,
        "priority": 5,
        "timeout_seconds": 15,
        "requires_token": False,
        "capabilities": ["HISTORICAL_QUOTE", "FUNDAMENTALS", "MONEYFLOW"],
        "note": "本地 Python 包适配器，无需 Token。",
    },
    {
        "adapter_id": "sina",
        "provider": "sina",
        "label": "Sina Finance",
        "enabled": True,
        "priority": 6,
        "timeout_seconds": 10,
        "requires_token": False,
        "capabilities": ["REALTIME_QUOTE", "MONEYFLOW"],
        "note": "公开行情降级适配器，无需 Token。",
    },
    {
        "adapter_id": "tencent_finance",
        "provider": "tencent_finance",
        "label": "腾讯财经",
        "enabled": True,
        "priority": 2,
        "timeout_seconds": 12,
        "requires_token": False,
        "capabilities": ["REALTIME_QUOTE", "HISTORICAL_QUOTE", "ANNOUNCEMENTS", "MONEYFLOW", "INDEX"],
        "note": "授权优先接入：配置 TENCENT_FINANCE_BASE_URL 后参与行情链；如网关需要密钥，可设置 TENCENT_FINANCE_API_KEY 或 TOKEN。",
    },
    {
        "adapter_id": "tongdaxin",
        "provider": "tongdaxin",
        "label": "通达信",
        "enabled": True,
        "priority": 3,
        "timeout_seconds": 12,
        "requires_token": True,
        "capabilities": ["REALTIME_QUOTE", "HISTORICAL_QUOTE", "FUNDAMENTALS", "MONEYFLOW", "CHIP", "INDEX"],
        "note": "授权优先接入：配置 TONGDAXIN_BASE_URL 与 TONGDAXIN_API_KEY/TOKEN 后参与行情链。",
    },
    {
        "adapter_id": "ifind",
        "provider": "ifind",
        "label": "同花顺 iFinD",
        "enabled": True,
        "priority": 4,
        "timeout_seconds": 15,
        "requires_token": True,
        "capabilities": ["REALTIME_QUOTE", "HISTORICAL_QUOTE", "FUNDAMENTALS", "ANNOUNCEMENTS", "MONEYFLOW", "CHIP", "MACRO", "INDEX", "BOND", "FUTURES"],
        "note": "授权优先接入：配置 IFIND_BASE_URL 与 IFIND_API_KEY/TOKEN 后参与行情链。",
    },
]


def _default_profiles() -> List[AgentLLMProfile]:
    return [
        AgentLLMProfile(
            id=DEFAULT_PROFILE_ID,
            label="Default LLM API",
            provider="openai_compatible",
            base_url="https://api.openai.com/v1",
            model="llm-model-name",
            api_key="",
            temperature=0.2,
            max_tokens=4096,
            timeout_seconds=60,
            enabled=True,
        ),
        AgentLLMProfile(
            id="local_llm",
            label="Local compatible API",
            provider="local",
            base_url="http://localhost:11434/v1",
            model="local-model-name",
            api_key="",
            temperature=0.2,
            max_tokens=4096,
            timeout_seconds=120,
            enabled=False,
        ),
    ]


def _default_market_data_profiles() -> List[MarketDataProfile]:
    return [_default_tushare_market_data_profile()]


def _default_tushare_market_data_profile(
    profile_id: str = DEFAULT_MARKET_DATA_PROFILE_ID,
) -> MarketDataProfile:
    return MarketDataProfile(
        id=profile_id,
        label="Tushare A-share realtime",
        provider="tushare",
        base_url="https://api.tushare.pro",
        quote_path="",
        symbol_query_param="ts_code",
        auth_mode="token",
        api_key="",
        api_key_header="",
        api_key_query_param="token",
        timeout_seconds=20,
        enabled=True,
        extra_query_params={
            "api_name": "realtime_quote",
            "src": "dc",
            "fields": TUSHARE_DEFAULT_FIELDS,
        },
        price_path="price",
        name_path="name",
        change_percent_path="pct_change",
        volume_path="volume",
        timestamp_path="time",
    )


def _default_market_data_adapter_configs() -> List[Dict[str, Any]]:
    return [dict(item) for item in DEFAULT_MARKET_DATA_ADAPTER_CONFIGS]


def _default_agents() -> List[AgentDeployment]:
    return [
        AgentDeployment(**agent)
        for agent in agent_definitions(DEFAULT_PROFILE_ID)
    ]


def _default_state() -> Dict[str, Any]:
    return {
        "default_llm_profile_id": DEFAULT_PROFILE_ID,
        "default_market_data_profile_id": DEFAULT_MARKET_DATA_PROFILE_ID,
        "max_parallel_agents": 5,
        "llm_profiles": [_dump(profile) for profile in _default_profiles()],
        "market_data_profiles": [_dump(profile) for profile in _default_market_data_profiles()],
        "market_data_adapter_configs": _default_market_data_adapter_configs(),
        "llm_profile_test_results": {},
        "market_data_profile_test_results": {},
        "secret_refs": {},
        "secret_storage": {},
        "agents": [_dump(agent) for agent in _default_agents()],
        "data_sources_config": _default_data_sources_config(),
        "updated_at": _now(),
    }


def _load_state() -> Dict[str, Any]:
    if not STORAGE_FILE.exists():
        state = _default_state()
        _save_state(state)
        return state

    try:
        with STORAGE_FILE.open("r", encoding="utf-8-sig") as file:
            state = json.load(file)
    except UnicodeDecodeError:
        # Fallback to utf-8 without BOM if utf-8-sig fails
        try:
            with STORAGE_FILE.open("r", encoding="utf-8") as file:
                state = json.load(file)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _recover_corrupt_state(exc)
    except json.JSONDecodeError as exc:
        return _recover_corrupt_state(exc)

    defaults = _default_state()
    changed = False
    for key in (
        "default_llm_profile_id",
        "default_market_data_profile_id",
        "max_parallel_agents",
        "llm_profiles",
        "market_data_profiles",
        "market_data_adapter_configs",
        "llm_profile_test_results",
        "market_data_profile_test_results",
        "secret_refs",
        "secret_storage",
        "agents",
        "data_sources_config",
        "updated_at",
    ):
        if key not in state:
            state[key] = defaults.get(key, _now())
            changed = True

    synced_agents = sync_agent_state(
        state["agents"],
        state.get("default_llm_profile_id") or DEFAULT_PROFILE_ID,
    )
    if synced_agents != state["agents"]:
        state["agents"] = synced_agents
        changed = True

    if _sync_market_data_profiles(state):
        changed = True
    if _sync_market_data_adapter_configs(state):
        changed = True
    recovery = state.get("runtime_recovery")
    if isinstance(recovery, dict) and not recovery.get("restored_secret_refs_at"):
        if _restore_recovered_secret_refs(state):
            recovery["restored_secret_refs_at"] = _now()
            changed = True
    if _migrate_runtime_secrets(state):
        changed = True

    if changed:
        _save_state(state)

    return state


def _recover_corrupt_state(exc: Exception) -> Dict[str, Any]:
    state = _default_state()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = STORAGE_FILE.with_name(f"{STORAGE_FILE.name}.corrupt.{timestamp}")
    try:
        STORAGE_FILE.replace(backup)
    except OSError:
        pass
    state.setdefault("runtime_recovery", {})
    state["runtime_recovery"] = {
        "recovered_at": _now(),
        "backup_file": str(backup),
        "error": str(exc)[:300],
    }
    if _restore_recovered_secret_refs(state):
        state["runtime_recovery"]["restored_secret_refs_at"] = _now()
    _save_state(state)
    return state


def _restore_recovered_secret_refs(state: Dict[str, Any]) -> bool:
    changed = False
    for profile in state.get("llm_profiles", []):
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "")
        ref = f"runtime-secret:v1:llm_profiles:{profile_id}:api_key"
        if profile_id and not _item_secret_ref(state, "llm_profiles", profile_id, "api_key") and _load_secret_ref(state, ref):
            _set_item_secret_ref(state, "llm_profiles", profile_id, "api_key", ref)
            changed = True

    for profile in state.get("market_data_profiles", []):
        if not isinstance(profile, dict):
            continue
        profile_id = str(profile.get("id") or "")
        ref = f"runtime-secret:v1:market_data_profiles:{profile_id}:api_key"
        if profile_id and not _item_secret_ref(state, "market_data_profiles", profile_id, "api_key") and _load_secret_ref(state, ref):
            _set_item_secret_ref(state, "market_data_profiles", profile_id, "api_key", ref)
            changed = True

    config_ref = "runtime-secret:v1:data_sources_config:default:tushare_token"
    if not _config_secret_ref(state, "tushare_token") and _load_secret_ref(state, config_ref):
        _set_config_secret_ref(state, "tushare_token", config_ref)
        changed = True
    return changed


def _sync_market_data_profiles(state: Dict[str, Any]) -> bool:
    profiles = state.get("market_data_profiles") or []
    changed = False

    for index, profile in enumerate(profiles):
        if (
            profile.get("id") == DEFAULT_MARKET_DATA_PROFILE_ID
            and profile.get("provider") == "generic_rest"
            and not profile.get("base_url")
            and not profile.get("api_key")
        ):
            profiles[index] = _dump(_default_tushare_market_data_profile())
            state["default_market_data_profile_id"] = DEFAULT_MARKET_DATA_PROFILE_ID
            changed = True
            break

    if not any(profile.get("provider") == "tushare" for profile in profiles):
        profiles.append(_dump(_default_tushare_market_data_profile("tushare_market_data")))
        changed = True

    if changed:
        state["market_data_profiles"] = profiles
    return changed


def _sync_market_data_adapter_configs(state: Dict[str, Any]) -> bool:
    configs = state.get("market_data_adapter_configs") or []
    config_by_id = {config.get("adapter_id"): config for config in configs}
    merged_configs: List[Dict[str, Any]] = []
    changed = len(configs) != len(DEFAULT_MARKET_DATA_ADAPTER_CONFIGS)

    for default_config in DEFAULT_MARKET_DATA_ADAPTER_CONFIGS:
        adapter_id = default_config["adapter_id"]
        current = config_by_id.get(adapter_id, {})
        merged = dict(default_config)
        for key in ("enabled", "priority", "timeout_seconds"):
            if key in current:
                merged[key] = current[key]
        merged_configs.append(merged)
        if merged != current:
            changed = True

    if changed:
        state["market_data_adapter_configs"] = merged_configs
    return changed


def _save_state(state: Dict[str, Any]) -> None:
    STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _seal_runtime_secrets(state)
    state["updated_at"] = _now()
    tmp_file = STORAGE_FILE.with_name(
        f".{STORAGE_FILE.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    )
    try:
        with tmp_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2, ensure_ascii=False)
            file.write("\n")
        _replace_state_file(tmp_file, STORAGE_FILE)
    finally:
        if tmp_file.exists():
            tmp_file.unlink()


def _replace_state_file(tmp_file: Path, target: Path) -> None:
    atomic_replace_file(tmp_file, target)


def _secret_refs(state: Dict[str, Any]) -> Dict[str, Any]:
    refs = state.setdefault("secret_refs", {})
    refs.setdefault("llm_profiles", {})
    refs.setdefault("market_data_profiles", {})
    refs.setdefault("data_sources_config", {})
    return refs


def _item_secret_ref(state: Dict[str, Any], section: str, item_id: str, field: str) -> str:
    section_refs = _secret_refs(state).get(section, {})
    item_refs = section_refs.get(item_id, {}) if isinstance(section_refs, dict) else {}
    return str(item_refs.get(field) or "")


def _set_item_secret_ref(state: Dict[str, Any], section: str, item_id: str, field: str, ref: str) -> None:
    refs = _secret_refs(state)
    refs.setdefault(section, {}).setdefault(item_id, {})[field] = ref


def _delete_item_secret_ref(state: Dict[str, Any], section: str, item_id: str, field: str) -> None:
    refs = _secret_refs(state)
    item_refs = refs.get(section, {}).get(item_id, {})
    ref = str(item_refs.get(field) or "")
    if ref:
        delete_runtime_secret(STORAGE_FILE, ref)
    item_refs.pop(field, None)
    if not item_refs and isinstance(refs.get(section), dict):
        refs[section].pop(item_id, None)


def _config_secret_ref(state: Dict[str, Any], field: str) -> str:
    refs = _secret_refs(state).get("data_sources_config", {})
    return str(refs.get(field) or "") if isinstance(refs, dict) else ""


def _set_config_secret_ref(state: Dict[str, Any], field: str, ref: str) -> None:
    _secret_refs(state).setdefault("data_sources_config", {})[field] = ref


def _delete_config_secret_ref(state: Dict[str, Any], field: str) -> None:
    refs = _secret_refs(state).setdefault("data_sources_config", {})
    ref = str(refs.get(field) or "")
    if ref:
        delete_runtime_secret(STORAGE_FILE, ref)
    refs.pop(field, None)


def _load_secret_ref(state: Dict[str, Any], ref: str) -> str:
    if not ref:
        return ""
    try:
        return load_runtime_secret(STORAGE_FILE, ref) or ""
    except Exception:
        state.setdefault("secret_storage_errors", []).append(
            {
                "ref": ref,
                "error": "secret_decryption_failed",
                "checked_at": _now(),
            }
        )
        return ""


def _resolve_item_secret(state: Dict[str, Any], section: str, item_id: str, field: str) -> str:
    return _load_secret_ref(state, _item_secret_ref(state, section, item_id, field))


def _resolve_config_secret(state: Dict[str, Any], field: str) -> str:
    return _load_secret_ref(state, _config_secret_ref(state, field))


def _seal_item_secret(
    state: Dict[str, Any],
    section: str,
    item_id: str,
    item: Dict[str, Any],
    field: str,
) -> bool:
    value = str(item.get(field) or "")
    if not value:
        return False
    ref = store_runtime_secret(STORAGE_FILE, section, item_id, field, value)
    _set_item_secret_ref(state, section, item_id, field, ref)
    item[field] = ""
    return True


def _seal_config_secret(state: Dict[str, Any], config: Dict[str, Any], field: str) -> bool:
    value = str(config.get(field) or "")
    if not value:
        return False
    ref = store_runtime_secret(STORAGE_FILE, "data_sources_config", "default", field, value)
    _set_config_secret_ref(state, field, ref)
    config[field] = ""
    return True


def _seal_runtime_secrets(state: Dict[str, Any]) -> None:
    for profile in state.get("llm_profiles", []):
        if isinstance(profile, dict):
            _seal_item_secret(state, "llm_profiles", str(profile.get("id") or ""), profile, "api_key")
    for profile in state.get("market_data_profiles", []):
        if isinstance(profile, dict):
            _seal_item_secret(state, "market_data_profiles", str(profile.get("id") or ""), profile, "api_key")
    config = state.get("data_sources_config")
    if isinstance(config, dict):
        _seal_config_secret(state, config, "tushare_token")
    state["secret_storage"] = runtime_secret_storage_status(STORAGE_FILE)


def _migrate_runtime_secrets(state: Dict[str, Any]) -> bool:
    before = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str)
    _seal_runtime_secrets(state)
    after = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str)
    return before != after


def _profiles_from_state(state: Dict[str, Any]) -> List[AgentLLMProfile]:
    raw_profiles = []
    for profile in state["llm_profiles"]:
        item = dict(profile)
        if not item.get("api_key"):
            item["api_key"] = _resolve_item_secret(
                state,
                "llm_profiles",
                str(item.get("id") or ""),
                "api_key",
            )
        raw_profiles.append(item)
    profiles = [AgentLLMProfile(**profile) for profile in raw_profiles]
    env_api_key = os.getenv("LLM_API_KEY", "").strip()
    if env_api_key:
        for profile in profiles:
            if not profile.api_key and _can_apply_env_llm_api_key(profile, env_api_key):
                profile.api_key = env_api_key
    return profiles


def _can_apply_env_llm_api_key(profile: AgentLLMProfile, env_api_key: str) -> bool:
    if profile.provider == "local":
        return False
    candidate = profile.model_copy(update={"api_key": env_api_key})
    return validate_llm_egress(candidate).allowed


def _market_data_profiles_from_state(state: Dict[str, Any]) -> List[MarketDataProfile]:
    raw_profiles = []
    for profile in state["market_data_profiles"]:
        item = dict(profile)
        if not item.get("api_key"):
            item["api_key"] = _resolve_item_secret(
                state,
                "market_data_profiles",
                str(item.get("id") or ""),
                "api_key",
            )
        raw_profiles.append(item)
    profiles = [MarketDataProfile(**profile) for profile in raw_profiles]
    generic_key = os.getenv("MARKET_DATA_API_KEY", "").strip()
    tushare_token = os.getenv("TUSHARE_TOKEN", "").strip()
    for profile in profiles:
        if profile.api_key:
            continue
        if profile.provider.lower() == "tushare" and tushare_token:
            profile.api_key = tushare_token
        elif generic_key:
            profile.api_key = generic_key
    return profiles


def _agents_from_state(state: Dict[str, Any]) -> List[AgentDeployment]:
    return [AgentDeployment(**agent) for agent in state["agents"]]


def _public_profile(
    profile: AgentLLMProfile,
    last_test: Dict[str, Any] | None = None,
) -> AgentLLMProfilePublic:
    egress_decision = validate_llm_egress(profile)
    health_status, health_warnings = _llm_profile_health(profile, last_test, egress_decision)
    configured = _llm_profile_configured(profile)
    auth_available = _llm_profile_auth_available(profile)
    return AgentLLMProfilePublic(
        id=profile.id,
        label=profile.label,
        provider=profile.provider,
        base_url=profile.base_url,
        model=profile.model,
        configured=configured,
        auth_available=auth_available,
        api_key_set=bool(profile.api_key),
        api_key_mask=_mask_api_key(profile.api_key),
        egress_confirmed=profile.egress_confirmed,
        egress_policy_status="ALLOWED" if egress_decision.allowed else "BLOCKED",
        egress_policy_message=egress_decision.message,
        health_status=health_status,
        health_warnings=health_warnings,
        base_url_security=_base_url_security(egress_decision, configured_allowlist_hosts()),
        last_call_success=last_test.get("last_call_success") if last_test else None,
        last_error=last_test.get("last_error", "") if last_test else "",
        last_checked_at=last_test.get("last_checked_at", "") if last_test else "",
        last_test_status=last_test.get("status", "") if last_test else "",
        last_test_message=last_test.get("message", "") if last_test else "",
        last_live_call_at=last_test.get("last_live_call_at", "") if last_test else "",
        last_latency_ms=last_test.get("latency_ms") if last_test else None,
        last_usage=last_test.get("usage", {}) if last_test else {},
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        timeout_seconds=profile.timeout_seconds,
        enabled=profile.enabled,
        extra_headers=redact_config_payload(profile.extra_headers),
    )


def _public_market_data_profile(
    profile: MarketDataProfile,
    last_test: Dict[str, Any] | None = None,
) -> MarketDataProfilePublic:
    egress_decision = validate_market_data_egress(profile)
    health_status, health_warnings = _market_data_profile_health(profile, last_test, egress_decision)
    return MarketDataProfilePublic(
        id=profile.id,
        label=profile.label,
        provider=profile.provider,
        base_url=profile.base_url,
        quote_path=profile.quote_path,
        symbol_query_param=profile.symbol_query_param,
        auth_mode=profile.auth_mode,
        api_key_set=bool(profile.api_key),
        api_key_mask=_mask_api_key(profile.api_key),
        egress_confirmed=profile.egress_confirmed,
        egress_policy_status="ALLOWED" if egress_decision.allowed else "BLOCKED",
        egress_policy_message=egress_decision.message,
        health_status=health_status,
        health_warnings=health_warnings,
        base_url_security=_base_url_security(egress_decision, configured_market_data_allowlist_hosts()),
        last_call_success=last_test.get("last_call_success") if last_test else None,
        last_error=last_test.get("last_error", "") if last_test else "",
        last_checked_at=last_test.get("last_checked_at", "") if last_test else "",
        last_test_status=last_test.get("status", "") if last_test else "",
        last_test_message=last_test.get("message", "") if last_test else "",
        last_live_call_at=last_test.get("last_live_call_at", "") if last_test else "",
        last_latency_ms=last_test.get("latency_ms") if last_test else None,
        api_key_header=profile.api_key_header,
        api_key_query_param=profile.api_key_query_param,
        timeout_seconds=profile.timeout_seconds,
        enabled=profile.enabled,
        extra_headers=redact_config_payload(profile.extra_headers),
        extra_query_params=redact_config_payload(profile.extra_query_params),
        price_path=profile.price_path,
        name_path=profile.name_path,
        change_percent_path=profile.change_percent_path,
        volume_path=profile.volume_path,
        timestamp_path=profile.timestamp_path,
    )


def _llm_profile_configured(profile: AgentLLMProfile) -> bool:
    return bool(
        profile.base_url
        and profile.model
        and _llm_profile_auth_available(profile)
        and validate_llm_egress(profile).allowed
    )


def _llm_profile_auth_available(profile: AgentLLMProfile) -> bool:
    return bool(profile.api_key or profile.provider == "local")


def _llm_profile_health(
    profile: AgentLLMProfile,
    last_test: Dict[str, Any] | None = None,
    egress_decision: LLMEgressDecision | None = None,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not profile.enabled:
        warnings.append("profile_disabled")
    if not profile.base_url:
        warnings.append("base_url_missing")
    if not profile.model:
        warnings.append("model_missing")
    if profile.provider != "local" and not profile.api_key:
        warnings.append("api_key_missing")
    if warnings:
        return ("DISABLED" if warnings == ["profile_disabled"] else "INCOMPLETE", warnings)
    egress_decision = egress_decision or validate_llm_egress(profile)
    if not egress_decision.allowed:
        return "BLOCKED", ["egress_blocked"]
    if last_test and last_test.get("last_call_success") is True:
        return "READY", warnings
    if last_test and last_test.get("last_call_success") is False:
        return "FAILED", warnings
    if last_test and last_test.get("status") == "BLOCKED":
        return "BLOCKED", warnings
    if last_test and last_test.get("status") == "FAILED":
        return "FAILED", warnings
    return "CONFIGURED", warnings


def _market_data_profile_health(
    profile: MarketDataProfile,
    last_test: Dict[str, Any] | None = None,
    egress_decision: MarketDataEgressDecision | None = None,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not profile.enabled:
        warnings.append("profile_disabled")
    if not profile.base_url:
        warnings.append("base_url_missing")
    if _market_data_profile_requires_key(profile) and not profile.api_key:
        warnings.append("api_key_missing")
    if warnings:
        return ("DISABLED" if warnings == ["profile_disabled"] else "INCOMPLETE", warnings)
    egress_decision = egress_decision or validate_market_data_egress(profile)
    if not egress_decision.allowed:
        return "BLOCKED", ["egress_blocked"]
    if last_test and last_test.get("last_call_success") is True:
        return "READY", warnings
    if last_test and last_test.get("last_call_success") is False:
        return "FAILED", warnings
    return "CONFIGURED", warnings


def get_runtime_config() -> AgentRuntimeConfig:
    state = _load_state()
    llm_test_results = state.get("llm_profile_test_results", {})
    market_data_test_results = state.get("market_data_profile_test_results", {})
    return AgentRuntimeConfig(
        default_llm_profile_id=state["default_llm_profile_id"],
        default_market_data_profile_id=state["default_market_data_profile_id"],
        max_parallel_agents=state["max_parallel_agents"],
        agents=_agents_from_state(state),
        llm_profiles=[
            _public_profile(profile, llm_test_results.get(profile.id))
            for profile in _profiles_from_state(state)
        ],
        market_data_profiles=[
            _public_market_data_profile(profile, market_data_test_results.get(profile.id))
            for profile in _market_data_profiles_from_state(state)
        ],
        updated_at=state["updated_at"],
    )


def get_runtime_summary() -> Dict[str, Any]:
    config = get_runtime_config()
    profile_by_id = {profile.id: profile for profile in config.llm_profiles}
    market_profile = next(
        (
            profile
            for profile in config.market_data_profiles
            if profile.id == config.default_market_data_profile_id
        ),
        None,
    )
    return {
        "defaultLlmProfileId": config.default_llm_profile_id,
        "defaultMarketDataProfileId": config.default_market_data_profile_id,
        "maxParallelAgents": config.max_parallel_agents,
        "marketData": {
            "defaultProfileId": config.default_market_data_profile_id,
            "provider": market_profile.provider if market_profile else None,
            "enabled": bool(market_profile.enabled) if market_profile else False,
            "ready": _public_market_data_profile_ready(market_profile),
        },
        "llmProfiles": [
            {
                "id": profile.id,
                "provider": profile.provider,
                "model": profile.model,
                "configured": profile.configured,
                "authAvailable": profile.auth_available,
                "apiKeySet": profile.api_key_set,
                "status": profile.health_status,
                "lastCallSuccess": profile.last_call_success,
                "lastError": profile.last_error,
                "lastCheckedAt": profile.last_checked_at,
                "lastLiveCallAt": profile.last_live_call_at,
                "lastLatencyMs": profile.last_latency_ms,
                "lastUsage": profile.last_usage,
            }
            for profile in config.llm_profiles
        ],
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "enabled": agent.enabled,
                "llmProfileId": agent.llm_profile_id,
                "model": profile_by_id.get(agent.llm_profile_id).model if profile_by_id.get(agent.llm_profile_id) else None,
                "systemPromptRef": agent.system_prompt_ref,
                "promptFile": agent.prompt_file,
                "promptHash": agent.prompt_hash,
                "nodeType": agent.node_type,
                "runModes": agent.run_modes,
                "nextNodes": agent.next_nodes,
            }
            for agent in config.agents
        ],
    }


def get_agent_execution_config(agent_id: str) -> tuple[AgentDeployment, AgentLLMProfile]:
    state = _load_state()
    agents = _agents_from_state(state)
    profiles = _profiles_from_state(state)
    agent = next((item for item in agents if item.id == agent_id), None)
    if agent is None:
        replacement_id = CONSOLIDATED_AGENT_REDIRECTS.get(agent_id)
        agent = next((item for item in agents if item.id == replacement_id), None)
    if agent is None:
        raise KeyError(f"Unknown agent: {agent_id}")

    profile = next((item for item in profiles if item.id == agent.llm_profile_id), None)
    if profile is None:
        raise KeyError(f"Unknown LLM profile: {agent.llm_profile_id}")

    return agent, profile


def get_llm_profile(profile_id: str) -> AgentLLMProfile:
    profiles = _profiles_from_state(_load_state())
    profile = next((item for item in profiles if item.id == profile_id), None)
    if profile is None:
        raise KeyError(f"Unknown LLM profile: {profile_id}")
    return profile


def get_default_market_data_profile() -> MarketDataProfile:
    state = _load_state()
    profile_id = state.get("default_market_data_profile_id") or DEFAULT_MARKET_DATA_PROFILE_ID
    return get_market_data_profile(profile_id)


def get_market_data_profile(profile_id: str) -> MarketDataProfile:
    profiles = _market_data_profiles_from_state(_load_state())
    profile = next((item for item in profiles if item.id == profile_id), None)
    if profile is None:
        raise KeyError(f"Unknown market data profile: {profile_id}")
    return profile


def get_market_data_adapter_configs() -> List[MarketDataAdapterConfig]:
    state = _load_state()
    return [
        MarketDataAdapterConfig(**config)
        for config in state.get("market_data_adapter_configs", _default_market_data_adapter_configs())
    ]


def get_market_data_adapter_config(adapter_id: str) -> MarketDataAdapterConfig:
    configs = get_market_data_adapter_configs()
    config = next((item for item in configs if item.adapter_id == adapter_id), None)
    if config is None:
        raise KeyError(f"Unknown market data adapter: {adapter_id}")
    return config


def update_market_data_adapter_config(
    adapter_id: str,
    request: UpdateMarketDataAdapterConfigRequest,
) -> MarketDataAdapterConfig:
    state = _load_state()
    configs = [
        MarketDataAdapterConfig(**config)
        for config in state.get("market_data_adapter_configs", _default_market_data_adapter_configs())
    ]
    existing = next((config for config in configs if config.adapter_id == adapter_id), None)
    if existing is None:
        raise KeyError(f"Unknown market data adapter: {adapter_id}")

    if request.enabled is not None:
        existing.enabled = request.enabled
    if request.priority is not None:
        existing.priority = request.priority
    if request.timeout_seconds is not None:
        existing.timeout_seconds = request.timeout_seconds

    state["market_data_adapter_configs"] = [_dump(config) for config in configs]
    _save_state(state)
    return existing


def update_runtime_settings(request: UpdateRuntimeSettingsRequest) -> AgentRuntimeConfig:
    state = _load_state()
    profile_ids = {profile["id"] for profile in state["llm_profiles"]}
    market_profile_ids = {profile["id"] for profile in state["market_data_profiles"]}

    if request.default_llm_profile_id is not None:
        if request.default_llm_profile_id not in profile_ids:
            raise KeyError(f"Unknown LLM profile: {request.default_llm_profile_id}")
        state["default_llm_profile_id"] = request.default_llm_profile_id

    if request.default_market_data_profile_id is not None:
        if request.default_market_data_profile_id not in market_profile_ids:
            raise KeyError(f"Unknown market data profile: {request.default_market_data_profile_id}")
        state["default_market_data_profile_id"] = request.default_market_data_profile_id

    if request.max_parallel_agents is not None:
        state["max_parallel_agents"] = request.max_parallel_agents

    if request.apply_default_to_all_agents:
        default_profile_id = state["default_llm_profile_id"]
        for agent in state["agents"]:
            agent["llm_profile_id"] = default_profile_id

    _save_state(state)
    return get_runtime_config()


def upsert_llm_profile(profile_id: str, request: UpsertLLMProfileRequest) -> AgentRuntimeConfig:
    state = _load_state()
    profiles = [AgentLLMProfile(**profile) for profile in state["llm_profiles"]]
    existing = next((profile for profile in profiles if profile.id == profile_id), None)

    if existing is None:
        existing = AgentLLMProfile(
            id=profile_id,
            label=request.label or profile_id,
            provider=request.provider or "openai_compatible",
            base_url=request.base_url or "",
            model=request.model or "",
            api_key=(request.api_key or "").strip(),
            egress_confirmed=bool(request.egress_confirmed),
        )
        profiles.append(existing)

    previous_provider = existing.provider
    previous_base_url = existing.base_url

    if request.label is not None:
        existing.label = request.label
    if request.provider is not None:
        existing.provider = request.provider
    if request.base_url is not None:
        existing.base_url = request.base_url
    if request.model is not None:
        existing.model = request.model
    if request.api_key is not None:
        existing.api_key = request.api_key.strip()
        if not existing.api_key:
            _delete_item_secret_ref(state, "llm_profiles", existing.id, "api_key")
    elif request.clear_api_key:
        existing.api_key = ""
        _delete_item_secret_ref(state, "llm_profiles", existing.id, "api_key")
    if request.temperature is not None:
        existing.temperature = request.temperature
    if request.max_tokens is not None:
        existing.max_tokens = request.max_tokens
    if request.timeout_seconds is not None:
        existing.timeout_seconds = request.timeout_seconds
    if request.enabled is not None:
        existing.enabled = request.enabled
    if request.extra_headers is not None:
        existing.extra_headers = request.extra_headers
    if request.egress_confirmed is not None:
        existing.egress_confirmed = request.egress_confirmed
    elif (
        (request.provider is not None and existing.provider != previous_provider)
        or (request.base_url is not None and existing.base_url != previous_base_url)
    ):
        existing.egress_confirmed = False

    state["llm_profiles"] = [_dump(profile) for profile in profiles]
    state.setdefault("llm_profile_test_results", {}).pop(profile_id, None)
    if not state.get("default_llm_profile_id"):
        state["default_llm_profile_id"] = profile_id
    _save_state(state)
    return get_runtime_config()


def upsert_market_data_profile(
    profile_id: str,
    request: UpsertMarketDataProfileRequest,
) -> AgentRuntimeConfig:
    state = _load_state()
    profiles = [MarketDataProfile(**profile) for profile in state["market_data_profiles"]]
    existing = next((profile for profile in profiles if profile.id == profile_id), None)

    if existing is None:
        existing = MarketDataProfile(
            id=profile_id,
            label=request.label or profile_id,
            provider=request.provider or "generic_rest",
            base_url=request.base_url or "",
            api_key=(request.api_key or "").strip(),
            egress_confirmed=bool(request.egress_confirmed),
        )
        profiles.append(existing)

    previous_provider = existing.provider
    previous_base_url = existing.base_url
    previous_quote_path = existing.quote_path

    for field in (
        "label",
        "provider",
        "base_url",
        "quote_path",
        "symbol_query_param",
        "auth_mode",
        "api_key_header",
        "api_key_query_param",
        "timeout_seconds",
        "enabled",
        "extra_headers",
        "extra_query_params",
        "price_path",
        "name_path",
        "change_percent_path",
        "volume_path",
        "timestamp_path",
    ):
        value = getattr(request, field)
        if value is not None:
            setattr(existing, field, value)

    if request.api_key is not None:
        existing.api_key = request.api_key.strip()
        if not existing.api_key:
            _delete_item_secret_ref(state, "market_data_profiles", existing.id, "api_key")
    elif request.clear_api_key:
        existing.api_key = ""
        _delete_item_secret_ref(state, "market_data_profiles", existing.id, "api_key")
    if request.egress_confirmed is not None:
        existing.egress_confirmed = request.egress_confirmed
    elif (
        (request.provider is not None and existing.provider != previous_provider)
        or (request.base_url is not None and existing.base_url != previous_base_url)
        or (request.quote_path is not None and existing.quote_path != previous_quote_path)
    ):
        existing.egress_confirmed = False

    state["market_data_profiles"] = [_dump(profile) for profile in profiles]
    state.setdefault("market_data_profile_test_results", {}).pop(profile_id, None)
    if not state.get("default_market_data_profile_id"):
        state["default_market_data_profile_id"] = profile_id
    _save_state(state)
    return get_runtime_config()


def update_agent_llm(agent_id: str, request: UpdateAgentLLMRequest) -> AgentRuntimeConfig:
    state = _load_state()
    profile_ids = {profile["id"] for profile in state["llm_profiles"]}
    agents = _agents_from_state(state)
    agent = next((item for item in agents if item.id == agent_id), None)

    if agent is None:
        raise KeyError(f"Unknown agent: {agent_id}")

    if request.llm_profile_id is not None:
        if request.llm_profile_id not in profile_ids:
            raise KeyError(f"Unknown LLM profile: {request.llm_profile_id}")
        agent.llm_profile_id = request.llm_profile_id
    if request.enabled is not None:
        agent.enabled = request.enabled
        agent.status = "READY" if request.enabled else "DISABLED"

    state["agents"] = [_dump(item) for item in agents]
    _save_state(state)
    return get_runtime_config()


def test_llm_profile_config(config: LLMProfileConfig) -> LLMConfigTestResult:
    """Validate LLM profile configuration without saving."""
    missing = []
    if not config.enabled:
        missing.append("enabled")
    if not config.base_url:
        missing.append("base_url")
    if not config.model:
        missing.append("model")
    if config.provider != "local" and not config.api_key:
        missing.append("api_key")

    if missing:
        return LLMConfigTestResult(
            profile_id="draft",
            status="INCOMPLETE",
            message="Profile configuration is incomplete.",
            details={"missing": missing},
        )

    egress_decision = validate_llm_egress(config)
    if not egress_decision.allowed:
        return LLMConfigTestResult(
            profile_id="draft",
            status="BLOCKED",
            message=egress_decision.message,
            details={
                **egress_decision.to_public_dict(),
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
                "configured": False,
                "auth_available": bool(config.api_key or config.provider == "local"),
                "live_call": False,
            },
        )

    return LLMConfigTestResult(
        profile_id="draft",
        status="CONFIGURED",
        message="Profile configuration is complete. No external LLM call was made.",
        details={
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "configured": True,
            "auth_available": bool(config.api_key or config.provider == "local"),
            "live_call": False,
        },
    )


def test_llm_profile(profile_id: str) -> LLMConfigTestResult:
    """Validate a saved LLM profile without making an external call."""
    try:
        profile = get_llm_profile(profile_id)
    except KeyError:
        return LLMConfigTestResult(
            profile_id=profile_id,
            status="NOT_FOUND",
            message="LLM profile does not exist.",
            details={"error": "profile_not_found"},
        )

    missing = []
    if not profile.enabled:
        missing.append("enabled")
    if not profile.base_url:
        missing.append("base_url")
    if not profile.model:
        missing.append("model")
    if profile.provider != "local" and not profile.api_key:
        missing.append("api_key")

    if missing:
        return LLMConfigTestResult(
            profile_id=profile_id,
            status="INCOMPLETE",
            message="Profile is saved but not ready for agent calls.",
            details={"missing": missing},
        )

    egress_decision = validate_llm_egress(profile)
    if not egress_decision.allowed:
        return LLMConfigTestResult(
            profile_id=profile_id,
            status="BLOCKED",
            message=egress_decision.message,
            details={
                **egress_decision.to_public_dict(),
                "provider": profile.provider,
                "model": profile.model,
                "base_url": profile.base_url,
                "configured": False,
                "auth_available": _llm_profile_auth_available(profile),
                "api_key_set": bool(profile.api_key),
                "live_call": False,
            },
        )

    return LLMConfigTestResult(
        profile_id=profile_id,
        status="CONFIGURED",
        message="Profile has the required fields. No external LLM call was made.",
        details={
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url,
            "configured": True,
            "auth_available": _llm_profile_auth_available(profile),
            "api_key_set": bool(profile.api_key),
            "live_call": False,
        },
    )


def record_llm_profile_test_result(
    profile_id: str,
    result: LLMConfigTestResult,
    *,
    live_call: bool,
) -> None:
    state = _load_state()
    details = result.details or {}
    previous = state.setdefault("llm_profile_test_results", {}).get(profile_id, {})
    actual_live_call = bool(details.get("live_call", live_call))
    last_call_success = previous.get("last_call_success")
    if actual_live_call:
        last_call_success = result.status == "READY"
    checked_at = _now()
    last_error = ""
    if result.status not in {"READY", "CONFIGURED"}:
        last_error = str(details.get("error") or result.message)
    state["llm_profile_test_results"][profile_id] = {
        "status": result.status,
        "message": result.message,
        "last_call_success": last_call_success,
        "last_error": last_error,
        "last_checked_at": checked_at,
        "last_live_call_at": (
            checked_at if actual_live_call else previous.get("last_live_call_at", "")
        ),
        "latency_ms": (
            details.get("latency_ms")
            if actual_live_call
            else previous.get("latency_ms")
        ),
        "usage": (
            details.get("usage", {})
            if actual_live_call
            else previous.get("usage", {})
        ),
    }
    _save_state(state)


def record_market_data_profile_test_result(
    profile_id: str,
    result: MarketDataConfigTestResult,
    *,
    live_call: bool,
) -> None:
    state = _load_state()
    details = result.details or {}
    last_call_success = None
    if live_call:
        last_call_success = result.status == "READY"
    checked_at = _now()
    last_error = ""
    if result.status not in {"READY", "CONFIGURED"}:
        last_error = str(details.get("error") or result.message)
    state.setdefault("market_data_profile_test_results", {})[profile_id] = {
        "status": result.status,
        "message": result.message,
        "last_call_success": last_call_success,
        "last_error": last_error,
        "last_checked_at": checked_at,
        "last_live_call_at": checked_at if live_call else "",
        "latency_ms": details.get("latency_ms"),
    }
    _save_state(state)


def test_market_data_profile(profile_id: str) -> MarketDataConfigTestResult:
    profiles = _market_data_profiles_from_state(_load_state())
    profile = next((item for item in profiles if item.id == profile_id), None)

    if profile is None:
        return MarketDataConfigTestResult(
            profile_id=profile_id,
            status="NOT_FOUND",
            message="Market data profile does not exist.",
        )

    missing = []
    if not profile.enabled:
        missing.append("enabled")
    if not profile.base_url:
        missing.append("base_url")
    if _market_data_profile_requires_key(profile) and not profile.api_key:
        missing.append("api_key")

    if missing:
        return MarketDataConfigTestResult(
            profile_id=profile_id,
            status="INCOMPLETE",
            message="Market data profile is saved but not ready for live calls.",
            details={"missing": missing},
        )

    egress_decision = validate_market_data_egress(profile)
    if not egress_decision.allowed:
        return MarketDataConfigTestResult(
            profile_id=profile_id,
            status="BLOCKED",
            message=egress_decision.message,
            details={
                **egress_decision.to_public_dict(),
                "provider": profile.provider,
                "base_url": profile.base_url,
                "quote_path": profile.quote_path,
                "auth_mode": profile.auth_mode,
                "api_key_set": bool(profile.api_key),
                "live_call": False,
            },
        )

    return MarketDataConfigTestResult(
        profile_id=profile_id,
        status="CONFIGURED",
        message="Market data profile has the required fields. No external market data call was made.",
        details={
            "provider": profile.provider,
            "base_url": profile.base_url,
            "quote_path": profile.quote_path,
            "auth_mode": profile.auth_mode,
            "configured": True,
            "api_key_set": bool(profile.api_key),
            "live_call": False,
        },
    )


def _market_data_profile_requires_key(profile: MarketDataProfile) -> bool:
    return profile.auth_mode not in {"", "none", "no_auth"}


def _public_market_data_profile_ready(profile: MarketDataProfilePublic | None) -> bool:
    if profile is None:
        return False
    return profile.health_status == "READY" and profile.last_call_success is True


DEFAULT_DATA_SOURCE_ITEMS = [
    {"key": "stock_basic", "name": "A股基础数据", "tushare_api": "stock_basic/namechange/stock_hsgt", "enabled": True, "required_credits": 3000, "tier_label": "3000积分内", "description": "股票列表、曾用名/ST线索、沪深港通股票列表。"},
    {"key": "realtime_quote", "name": "实时行情", "tushare_api": "realtime_quote", "enabled": True, "required_credits": 0, "tier_label": "实时接口", "description": "逐笔成交/盘口/分时实时行情数据；需要 Tushare SDK 1.3.3+，具体以账号实时权限为准。"},
    {"key": "kline_quote", "name": "低频行情", "tushare_api": "daily/weekly/monthly", "enabled": True, "required_credits": 2000, "tier_label": "120/2000积分", "description": "A股日线、周线、月线 K 线；日线低积分可用，周/月线按低频行情权限配置。"},
    {"key": "etf_data", "name": "ETF列表和日线", "tushare_api": "fund_basic/fund_daily", "enabled": True, "required_credits": 5000, "tier_label": "5000/8000积分", "description": "ETF/场内基金基础列表和 ETF 日线行情，8000积分档按更高频次使用。"},
    {"key": "derivative_basic", "name": "基金期货期权基础", "tushare_api": "fund_basic/fut_basic/opt_basic", "enabled": True, "required_credits": 5000, "tier_label": "5000积分内", "description": "基金列表、期货合约列表、期权合约列表等基础信息。"},
    {"key": "cross_market_basic", "name": "港美股和外汇基础", "tushare_api": "hk_basic/us_basic/fx_obasic", "enabled": True, "required_credits": 5000, "tier_label": "5000积分内", "description": "港股列表、美股列表、外汇基础信息；港美股行情分钟等独立权限不在本档自动启用。"},
    {"key": "fundamentals", "name": "财务数据", "tushare_api": "income/balancesheet/cashflow/fina_indicator", "enabled": True, "required_credits": 5000, "tier_label": "5000积分", "description": "利润表、资产负债表、现金流量表、财务指标等三大报表和衍生指标。"},
    {"key": "announcements", "name": "财报披露", "tushare_api": "disclosure_date", "enabled": True, "required_credits": 2000, "tier_label": "2000积分", "description": "财报披露计划日期索引。"},
    {"key": "macro", "name": "宏观经济", "tushare_api": "cn_cpi/cn_gdp/shibor_lpr", "enabled": True, "required_credits": 2000, "tier_label": "2000积分", "description": "CPI、GDP、LPR/利率等宏观指标；未启用时不再显示模板数值。"},
    {"key": "reference_data", "name": "参考数据", "tushare_api": "pledge_stat/repurchase/share_float/top_list/margin_detail", "enabled": True, "required_credits": 5000, "tier_label": "5000积分内", "description": "质押、回购、解禁/流通股本、龙虎榜、融资融券等参考数据。"},
    {"key": "moneyflow", "name": "资金流向", "tushare_api": "moneyflow/moneyflow_hsgt/moneyflow_mkt_dc", "enabled": True, "required_credits": 8000, "tier_label": "8000积分", "description": "个股资金流、沪深港通资金流和大盘资金流，用于资金面验证。"},
    {"key": "chip", "name": "筹码分布", "tushare_api": "cyq_perf/cyq_chips", "enabled": True, "required_credits": 10000, "tier_label": "5000/10000积分", "description": "每日筹码及胜率 / 每日筹码分布；以账号实际特色数据权限为准。"},
    {"key": "special_data", "name": "特色数据", "tushare_api": "concept/concept_detail/broker_recommend/top_inst/stk_factor", "enabled": True, "required_credits": 8000, "tier_label": "8000积分", "description": "概念板块和成分、券商金股、龙虎榜机构明细、股票技术面量化因子。"},
]

DEFAULT_DATA_SOURCE_PROVIDER_APIS = {
    "stock_basic": {
        "tushare": "stock_basic/namechange/stock_hsgt",
        "ifind": "iFinD security master/namechange",
    },
    "realtime_quote": {
        "tushare": "realtime_quote",
        "tencent_finance": "authorized quote gateway",
        "tongdaxin": "authorized quote gateway",
        "ifind": "iFinD quote",
    },
    "kline_quote": {
        "tushare": "daily/weekly/monthly",
        "tencent_finance": "authorized kline gateway",
        "tongdaxin": "authorized kline gateway",
        "ifind": "iFinD kline",
    },
    "etf_data": {
        "tushare": "fund_basic/fund_daily",
        "tongdaxin": "authorized ETF quote gateway",
        "ifind": "iFinD fund/ETF",
    },
    "derivative_basic": {
        "tushare": "fund_basic/fut_basic/opt_basic",
        "ifind": "iFinD futures/options master",
    },
    "cross_market_basic": {
        "tushare": "hk_basic/us_basic/fx_obasic",
        "ifind": "iFinD cross-market master",
    },
    "fundamentals": {
        "tushare": "income/balancesheet/cashflow/fina_indicator",
        "tongdaxin": "authorized fundamentals gateway",
        "ifind": "iFinD fundamentals",
    },
    "announcements": {
        "tushare": "disclosure_date",
        "tencent_finance": "authorized news/announcement gateway",
        "ifind": "iFinD announcements/news",
    },
    "macro": {
        "tushare": "cn_cpi/cn_gdp/shibor_lpr",
        "ifind": "iFinD macro",
    },
    "reference_data": {
        "tushare": "pledge_stat/repurchase/share_float/top_list/margin_detail",
        "tongdaxin": "authorized reference gateway",
        "ifind": "iFinD reference data",
    },
    "moneyflow": {
        "tushare": "moneyflow/moneyflow_hsgt/moneyflow_mkt_dc",
        "tencent_finance": "authorized moneyflow gateway",
        "tongdaxin": "authorized moneyflow gateway",
        "ifind": "iFinD moneyflow",
    },
    "chip": {
        "tushare": "cyq_perf/cyq_chips",
        "tongdaxin": "authorized chip gateway",
        "ifind": "iFinD chip/factor data",
    },
    "special_data": {
        "tushare": "concept/concept_detail/broker_recommend/top_inst/stk_factor",
        "tencent_finance": "authorized sector/index gateway",
        "tongdaxin": "authorized sector/factor gateway",
        "ifind": "iFinD concept/factor data",
    },
}


def _data_source_item_with_provider_apis(item: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(item)
    provider_apis = dict(DEFAULT_DATA_SOURCE_PROVIDER_APIS.get(str(item.get("key") or ""), {}))
    if not provider_apis and item.get("tushare_api"):
        provider_apis["tushare"] = str(item.get("tushare_api") or "")
    enriched["provider_apis"] = provider_apis
    enriched["providers"] = list(provider_apis)
    return enriched


def _default_data_source_items() -> List[Dict[str, Any]]:
    return [_data_source_item_with_provider_apis(item) for item in DEFAULT_DATA_SOURCE_ITEMS]


def _default_data_sources_config() -> Dict[str, Any]:
    return {
        "tushare_token": "",
        "sources": _default_data_source_items(),
    }


def get_data_sources_config() -> Dict[str, Any]:
    state = _load_state()
    config = state.get("data_sources_config", _default_data_sources_config())
    _merge_default_data_source_items(config)
    token = config.get("tushare_token", "")
    if not token:
        token = _resolve_config_secret(state, "tushare_token")
        if token:
            config["tushare_token"] = token
    if not token:
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if token and not config.get("tushare_token"):
            config["tushare_token"] = token
    _sync_data_sources_config_with_market_profile(state, config)
    return config


def _merge_default_data_source_items(config: Dict[str, Any]) -> None:
    existing = {item.get("key"): item for item in config.get("sources", []) if isinstance(item, dict)}
    merged = []
    for default_item in DEFAULT_DATA_SOURCE_ITEMS:
        default_item = _data_source_item_with_provider_apis(default_item)
        current = dict(existing.get(default_item["key"], {}))
        merged_item = {**default_item, **current}
        for field in ("name", "tushare_api", "description", "required_credits", "tier_label", "provider_apis", "providers"):
            merged_item[field] = default_item[field]
        if "enabled" in current:
            merged_item["enabled"] = current["enabled"]
        merged.append(merged_item)
    config["sources"] = merged


def public_data_sources_config(config: Dict[str, Any]) -> Dict[str, Any]:
    token = str(config.get("tushare_token") or "")
    return {
        "tushare_token": "",
        "tushare_token_set": bool(token),
        "tushare_token_mask": _mask_api_key(token),
        "sources": config.get("sources", []),
    }


def save_data_sources_config(tushare_token: str | None, sources: list[Dict[str, Any]] | None) -> Dict[str, Any]:
    state = _load_state()
    config = state.get("data_sources_config", _default_data_sources_config())
    if not config.get("tushare_token"):
        stored_token = _resolve_config_secret(state, "tushare_token")
        if stored_token:
            config["tushare_token"] = stored_token
    if tushare_token is not None:
        config["tushare_token"] = tushare_token.strip()
        if not config["tushare_token"]:
            _delete_config_secret_ref(state, "tushare_token")
            _clear_tushare_token_from_market_profiles(state)
    if sources is not None:
        config["sources"] = sources
    state["data_sources_config"] = config
    _apply_token_to_market_profiles(state, config.get("tushare_token", ""))
    _save_state(state)
    return get_data_sources_config()


def _sync_data_sources_config_with_market_profile(state: Dict[str, Any], config: Dict[str, Any]) -> None:
    token = config.get("tushare_token", "")
    if not token:
        for profile in state.get("market_data_profiles", []):
            if profile.get("provider") != "tushare":
                continue
            profile_token = profile.get("api_key") or _resolve_item_secret(
                state,
                "market_data_profiles",
                str(profile.get("id") or ""),
                "api_key",
            )
            if profile_token:
                config["tushare_token"] = profile_token
                break


def _apply_token_to_market_profiles(state: Dict[str, Any], token: str) -> None:
    if not token:
        return
    for profile in state.get("market_data_profiles", []):
        if profile.get("provider") == "tushare":
            profile["api_key"] = token
    state["market_data_profiles"] = state.get("market_data_profiles", [])


def _clear_tushare_token_from_market_profiles(state: Dict[str, Any]) -> None:
    for profile in state.get("market_data_profiles", []):
        if profile.get("provider") == "tushare":
            profile["api_key"] = ""
            _delete_item_secret_ref(
                state,
                "market_data_profiles",
                str(profile.get("id") or ""),
                "api_key",
            )


RUNS_DIR = STORAGE_FILE.parent / "runs"


def _runs_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR


def save_run(run_data: Dict[str, Any]) -> None:
    run_id = run_data.get("runId", "")
    if not run_id:
        return
    run_path = _runs_dir() / f"{run_id}.json"
    run_path.write_text(
        json.dumps(run_data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def get_run(run_id: str) -> Dict[str, Any] | None:
    run_path = _runs_dir() / f"{run_id}.json"
    if not run_path.exists():
        return None
    with run_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_runs() -> list[Dict[str, Any]]:
    result = []
    runs_dir = _runs_dir()
    for f in sorted(runs_dir.glob("RUN_*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return result


def load_persisted_runs() -> Dict[str, Dict[str, Any]]:
    store: Dict[str, Dict[str, Any]] = {}
    for run_data in list_runs():
        run_id = run_data.get("runId")
        if run_id:
            store[run_id] = run_data
    return store


def delete_run(run_id: str) -> bool:
    run_path = _runs_dir() / f"{run_id}.json"
    if run_path.exists():
        try:
            run_path.unlink()
            return True
        except OSError:
            return False
    return False
