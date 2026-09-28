import asyncio
import json
import os
import sys
import time
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from .plugin_runtime import (
    build_execution_sandbox_policy,
    contains_forbidden_trade_action,
    validate_json_schema_subset,
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins"
ALLOWED_EXECUTION_KIND = "external_json_stdio"
SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "AUTH", "CREDENTIAL")
BASE_ENV_ALLOWLIST = {
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
}


class PluginSandboxError(Exception):
    def __init__(self, message: str, reason: str = "PLUGIN_SANDBOX_FAILED", payload: Dict[str, Any] | None = None):
        super().__init__(message)
        self.reason = reason
        self.payload = payload or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_id(plugin_id: str, agent_id: str) -> str:
    return f"AUD_PLUGIN_SANDBOX_{plugin_id}_{agent_id}_{uuid.uuid4().hex[:6]}"


class _SafeTemplateDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _agent_by_id(plugin: Dict[str, Any], agent_id: str) -> Dict[str, Any] | None:
    for agent in plugin.get("agents", []):
        if isinstance(agent, dict) and str(agent.get("agent_id") or "") == agent_id:
            return agent
    return None


def _execution_config(plugin: Dict[str, Any], agent: Dict[str, Any]) -> Dict[str, Any]:
    plugin_manifest = plugin.get("manifest") if isinstance(plugin.get("manifest"), dict) else {}
    agent_manifest = agent.get("manifest") if isinstance(agent.get("manifest"), dict) else {}
    plugin_execution = plugin_manifest.get("execution") if isinstance(plugin_manifest.get("execution"), dict) else {}
    agent_execution = agent_manifest.get("execution") if isinstance(agent_manifest.get("execution"), dict) else {}
    execution = {**plugin_execution, **agent_execution}
    for key in ("runtime", "entrypoint", "command", "module", "file", "timeout_seconds", "resource_limits"):
        if key in agent_manifest and key not in execution:
            execution[key] = agent_manifest[key]
        elif key in plugin_manifest and key not in execution:
            execution[key] = plugin_manifest[key]
    if "kind" not in execution:
        execution["kind"] = agent_manifest.get("runtime") or plugin_manifest.get("runtime") or "controlled_dag_plan_only"
    return execution


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _template_context(payload: Dict[str, Any], plugin: Dict[str, Any], agent: Dict[str, Any]) -> Dict[str, Any]:
    context = {
        "plugin_id": plugin.get("plugin_id", ""),
        "plugin_name": plugin.get("name", ""),
        "agent_id": agent.get("agent_id", ""),
        "agent_name": agent.get("name", ""),
    }
    context.update({key: value for key, value in payload.items() if isinstance(value, (str, int, float, bool))})
    return context


def _assert_inside(path: Path, root: Path, reason: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PluginSandboxError("Plugin sandbox path escapes the plugin directory.", reason, {"path": str(path)}) from exc
    return resolved


def _plugin_dir(plugin: Dict[str, Any]) -> Path:
    plugin_id = str(plugin.get("plugin_id") or "").strip()
    if not plugin_id:
        raise PluginSandboxError("Plugin id is required for sandbox execution.", "PLUGIN_SANDBOX_INVALID_PLUGIN")
    plugin_dir = _assert_inside(PLUGIN_ROOT / plugin_id, PLUGIN_ROOT, "PLUGIN_SANDBOX_INVALID_PLUGIN_PATH")
    if not plugin_dir.is_dir():
        raise PluginSandboxError(
            "Plugin sandbox directory was not found.",
            "PLUGIN_SANDBOX_PLUGIN_DIR_MISSING",
            {"plugin_id": plugin_id, "plugin_dir": str(plugin_dir)},
        )
    return plugin_dir


def _is_secret_env_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in SECRET_ENV_MARKERS)


def _scrubbed_env() -> Dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in BASE_ENV_ALLOWLIST and not _is_secret_env_name(key)
    }
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["TIANYUAN_PLUGIN_SANDBOX"] = "1"
    return env


def _entrypoint_from_execution(execution: Dict[str, Any]) -> list[str]:
    raw = execution.get("entrypoint") or execution.get("command")
    if raw is None and execution.get("module"):
        raw = ["{python}", "-m", str(execution["module"])]
    if raw is None and execution.get("file"):
        raw = ["{python}", str(execution["file"])]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item)]
    raise PluginSandboxError("Plugin sandbox entrypoint is required.", "PLUGIN_SANDBOX_ENTRYPOINT_REQUIRED")


def _resolve_entrypoint_arg(arg: str, plugin_dir: Path, *, executable: bool = False) -> str:
    if arg == "{python}":
        return sys.executable
    if arg.startswith("{plugin_dir}"):
        suffix = arg.removeprefix("{plugin_dir}").lstrip("/\\")
        return str(_assert_inside(plugin_dir / suffix, plugin_dir, "PLUGIN_SANDBOX_ENTRYPOINT_INVALID"))

    candidate = Path(arg)
    looks_like_file = bool(candidate.suffix) or any(separator in arg for separator in ("/", "\\"))
    if candidate.is_absolute():
        return str(_assert_inside(candidate, plugin_dir, "PLUGIN_SANDBOX_ENTRYPOINT_INVALID"))
    if looks_like_file:
        resolved = _assert_inside(plugin_dir / candidate, plugin_dir, "PLUGIN_SANDBOX_ENTRYPOINT_INVALID")
        if not resolved.exists():
            raise PluginSandboxError(
                "Plugin sandbox entrypoint file was not found.",
                "PLUGIN_SANDBOX_ENTRYPOINT_MISSING",
                {"entrypoint": arg},
            )
        return str(resolved)
    if executable and (plugin_dir / candidate).exists():
        return str(_assert_inside(plugin_dir / candidate, plugin_dir, "PLUGIN_SANDBOX_ENTRYPOINT_INVALID"))
    return arg


def _resolved_command(execution: Dict[str, Any], plugin_dir: Path) -> list[str]:
    command = _entrypoint_from_execution(execution)
    if not command:
        raise PluginSandboxError("Plugin sandbox entrypoint is empty.", "PLUGIN_SANDBOX_ENTRYPOINT_REQUIRED")
    return [
        _resolve_entrypoint_arg(item, plugin_dir, executable=index == 0)
        for index, item in enumerate(command)
    ]


def _timeout_seconds(execution: Dict[str, Any], policy: Dict[str, Any]) -> float:
    raw = execution.get("timeout_seconds")
    if raw is None:
        raw = int(policy["resource_limits"]["timeout_ms"]) / 1000
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        parsed = int(policy["resource_limits"]["timeout_ms"]) / 1000
    max_seconds = max(0.001, int(policy["resource_limits"]["timeout_ms"]) / 1000)
    return max(0.001, min(parsed, max_seconds))


def _trim_text(value: bytes, limit: int = 4096) -> str:
    text = value.decode("utf-8", errors="replace").strip()
    return text[:limit]


def _sandbox_result(
    plugin: Dict[str, Any],
    agent: Dict[str, Any],
    policy: Dict[str, Any],
    audit_id: str,
    operator: str,
    started: str,
    started_perf: float,
    output: Dict[str, Any],
    stderr: str = "",
) -> Dict[str, Any]:
    return {
        "plugin_id": plugin.get("plugin_id", ""),
        "agent_id": agent.get("agent_id", ""),
        "status": "COMPLETED",
        "audit_id": audit_id,
        "operator": operator,
        "started_at": started,
        "finished_at": _now(),
        "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 3),
        "output": output,
        "errors": [],
        "sandbox": policy,
        "stderr": stderr,
    }


async def execute_plugin_sandbox(
    *,
    plugin: Dict[str, Any],
    agent: Dict[str, Any],
    input_payload: Dict[str, Any],
    operator: str = "human",
) -> Dict[str, Any]:
    started = _now()
    started_perf = time.perf_counter()
    execution = _execution_config(plugin, agent)
    execution_kind = str(execution.get("kind") or execution.get("runtime") or "").strip().lower()
    policy = build_execution_sandbox_policy(plugin, agent)
    audit_id = _audit_id(str(plugin.get("plugin_id") or "UNKNOWN"), str(agent.get("agent_id") or "UNKNOWN"))

    if execution_kind != ALLOWED_EXECUTION_KIND or not policy["allowed"]:
        raise PluginSandboxError(
            "Plugin sandbox execution is not allowed for this agent.",
            "PLUGIN_SANDBOX_NOT_ALLOWED",
            {"block_reasons": policy.get("block_reasons", []), "sandbox": policy},
        )

    max_input_bytes = int(policy["resource_limits"]["max_input_bytes"])
    if _json_size(input_payload) > max_input_bytes:
        raise PluginSandboxError(
            "Input payload exceeds sandbox max_input_bytes.",
            "PLUGIN_INPUT_TOO_LARGE",
            {"max_input_bytes": max_input_bytes},
        )
    input_errors = validate_json_schema_subset(input_payload, agent.get("input_schema") or {}, "input")
    if input_errors:
        raise PluginSandboxError(
            "Plugin sandbox input failed schema validation.",
            "PLUGIN_SCHEMA_VALIDATION_FAILED",
            {"errors": input_errors},
        )

    plugin_dir = _plugin_dir(plugin)
    command = _resolved_command(execution, plugin_dir)
    stdin_payload = {
        "input": input_payload,
        "plugin": {
            "plugin_id": plugin.get("plugin_id", ""),
            "name": plugin.get("name", ""),
            "version": plugin.get("version", ""),
        },
        "agent": {
            "agent_id": agent.get("agent_id", ""),
            "name": agent.get("name", ""),
        },
        "sandbox": {
            "audit_id": audit_id,
            "operator": operator,
        },
    }
    timeout = _timeout_seconds(execution, policy)

    with tempfile.TemporaryDirectory(prefix="tianyuan_plugin_") as temp_cwd:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temp_cwd,
                env=_scrubbed_env(),
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(stdin_payload, ensure_ascii=False).encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise PluginSandboxError(
                "Plugin sandbox execution timed out.",
                "PLUGIN_SANDBOX_TIMEOUT",
                {"timeout_seconds": timeout},
            ) from exc
        except OSError as exc:
            raise PluginSandboxError(
                "Plugin sandbox process could not be started.",
                "PLUGIN_SANDBOX_PROCESS_START_FAILED",
                {"error": str(exc)},
            ) from exc

    stderr_text = _trim_text(stderr)
    if process.returncode != 0:
        raise PluginSandboxError(
            "Plugin sandbox process failed.",
            "PLUGIN_SANDBOX_PROCESS_FAILED",
            {"returncode": process.returncode, "stderr": stderr_text},
        )

    max_output_bytes = int(policy["resource_limits"]["max_output_bytes"])
    if len(stdout) > max_output_bytes:
        raise PluginSandboxError(
            "Output payload exceeds sandbox max_output_bytes.",
            "PLUGIN_OUTPUT_TOO_LARGE",
            {"max_output_bytes": max_output_bytes},
        )
    try:
        parsed = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginSandboxError(
            "Plugin sandbox output must be valid JSON.",
            "PLUGIN_OUTPUT_INVALID_JSON",
            {"stdout": _trim_text(stdout)},
        ) from exc
    if not isinstance(parsed, dict):
        raise PluginSandboxError("Plugin sandbox output must be a JSON object.", "PLUGIN_OUTPUT_INVALID_JSON")

    output = parsed.get("output") if isinstance(parsed.get("output"), dict) else parsed
    output_errors = validate_json_schema_subset(output, agent.get("output_schema") or {}, "output")
    if output_errors:
        raise PluginSandboxError(
            "Plugin sandbox output failed schema validation.",
            "PLUGIN_SCHEMA_VALIDATION_FAILED",
            {"errors": output_errors},
        )
    if contains_forbidden_trade_action(output):
        raise PluginSandboxError(
            "Plugin sandbox output contains a forbidden trade action.",
            "PLUGIN_FORBIDDEN_TRADE_ACTION",
            {"forbidden_actions": policy["risk_boundary"]["forbidden_trade_actions"]},
        )

    return _sandbox_result(plugin, agent, policy, audit_id, operator, started, started_perf, output, stderr_text)


def _default_value_for_schema(field_schema: Dict[str, Any], rendered_note: str) -> Any:
    field_type = str(field_schema.get("type") or "").lower()
    if field_type == "array":
        return []
    if field_type == "object":
        return {}
    if field_type == "number":
        return 0
    if field_type == "boolean":
        return False
    return rendered_note


def _declarative_output(plugin: Dict[str, Any], agent: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    execution = _execution_config(plugin, agent)
    context = _SafeTemplateDict(_template_context(payload, plugin, agent))
    template = str(
        execution.get("review_note_template")
        or "{agent_name} reviewed {symbol} in a no-code hot-reload sandbox."
    )
    rendered_note = template.format_map(context)
    configured_output = execution.get("output") if isinstance(execution.get("output"), dict) else {}
    output_schema = agent.get("output_schema") if isinstance(agent.get("output_schema"), dict) else {}
    properties = output_schema.get("properties") if isinstance(output_schema.get("properties"), dict) else {}

    output: Dict[str, Any] = {}
    for key in properties:
        if key in configured_output:
            output[key] = configured_output[key]
        elif key in {"summary", "review_note", "note"}:
            output[key] = rendered_note
        elif key in {"signals", "risk_notes", "warnings"}:
            output[key] = []
        else:
            field_schema = properties.get(key) if isinstance(properties.get(key), dict) else {}
            output[key] = _default_value_for_schema(field_schema, rendered_note)
    if not output:
        output = {"summary": rendered_note, "signals": [], "risk_notes": []}
    for key in output_schema.get("required", []) if isinstance(output_schema.get("required"), list) else []:
        if key not in output:
            field_schema = properties.get(key) if isinstance(properties.get(key), dict) else {}
            output[key] = _default_value_for_schema(field_schema, rendered_note)
    return output


def run_declarative_plugin_sandbox(
    plugin: Dict[str, Any],
    agent_id: str,
    input_payload: Dict[str, Any],
    *,
    actor: str = "human",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    agent = _agent_by_id(plugin, agent_id)
    if not agent:
        raise ValueError("Plugin agent not found")

    started = _now()
    started_perf = time.perf_counter()
    policy = build_execution_sandbox_policy(plugin, agent)
    audit_id = _audit_id(str(plugin.get("plugin_id") or "UNKNOWN"), agent_id)
    errors: list[str] = []

    if not policy["hot_reload_allowed"]:
        errors.extend(policy.get("block_reasons") or ["Plugin hot reload is not allowed by sandbox policy."])
        return _result(plugin, agent, policy, audit_id, actor, started, started_perf, "BLOCKED", {}, errors), policy

    if _json_size(input_payload) > int(policy["resource_limits"]["max_input_bytes"]):
        errors.append("Input payload exceeds sandbox max_input_bytes.")
    errors.extend(validate_json_schema_subset(input_payload, agent.get("input_schema") or {}, "input"))
    if errors:
        return _result(plugin, agent, policy, audit_id, actor, started, started_perf, "FAILED", {}, errors), policy

    output = _declarative_output(plugin, agent, input_payload)
    if _json_size(output) > int(policy["resource_limits"]["max_output_bytes"]):
        errors.append("Output payload exceeds sandbox max_output_bytes.")
    errors.extend(validate_json_schema_subset(output, agent.get("output_schema") or {}, "output"))
    if contains_forbidden_trade_action(output):
        errors.append("Output contains a forbidden trade action.")

    status = "COMPLETED" if not errors else "BLOCKED"
    return _result(plugin, agent, policy, audit_id, actor, started, started_perf, status, output, errors), policy


def _result(
    plugin: Dict[str, Any],
    agent: Dict[str, Any],
    policy: Dict[str, Any],
    audit_id: str,
    actor: str,
    started: str,
    started_perf: float,
    status: str,
    output: Dict[str, Any],
    errors: list[str],
) -> Dict[str, Any]:
    finished = _now()
    return {
        "plugin_id": plugin.get("plugin_id", ""),
        "agent_id": agent.get("agent_id", ""),
        "status": status,
        "mode": policy["mode"],
        "audit_id": audit_id,
        "actor": actor,
        "started_at": started,
        "finished_at": finished,
        "elapsed_ms": round((time.perf_counter() - started_perf) * 1000, 3),
        "output": output,
        "errors": errors,
        "policy": policy,
    }
