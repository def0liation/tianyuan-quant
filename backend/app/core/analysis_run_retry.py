from __future__ import annotations

from datetime import datetime

from .agent_node_utils import (
    NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON,
    is_non_executable_plugin_observation,
    mark_non_executable_plugin_observation,
)


class AnalysisRunRetryError(Exception):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AnalysisRunRetryBadRequest(AnalysisRunRetryError):
    status_code = 400


class AnalysisRunRetryConflict(AnalysisRunRetryError):
    status_code = 409


class AnalysisRunRetryNotFound(AnalysisRunRetryError):
    status_code = 404


def prepare_retry(run: dict, payload: dict | None, *, job: dict | None = None) -> str:
    if run.get("status") == "RUNNING":
        raise AnalysisRunRetryConflict("Run is already running")
    if job and int(job.get("attempt") or 0) >= int(job.get("max_attempts") or 3):
        raise AnalysisRunRetryConflict("Retry limit reached for this run")

    payload = payload or {}
    retry_from_node_id = str(payload.get("from_node_id") or first_failed_node_id(run) or "")
    if not retry_from_node_id:
        raise AnalysisRunRetryBadRequest("No failed node found. Provide from_node_id to retry from a specific node.")

    node_ids = {node.get("id") for node in run.get("nodes", []) if isinstance(node, dict)}
    canonical_retry_from_node_id = retry_legacy_node_id(run, retry_from_node_id)
    if retry_from_node_id and retry_from_node_id not in node_ids and canonical_retry_from_node_id not in node_ids:
        raise AnalysisRunRetryNotFound("Retry node not found")

    retry_from_node_id = coerce_retry_node_id(run, canonical_retry_from_node_id)
    if not retry_from_node_id:
        raise AnalysisRunRetryBadRequest("Selected retry node is review-only and has no downstream executable node.")

    previous_status = run.get("status")
    requested_at = datetime.now().isoformat()
    run["status"] = "CREATED"
    run["failReason"] = ""
    run["failureCategory"] = ""
    run["cancelRequested"] = False
    run["retry"] = {
        "from_node_id": retry_from_node_id,
        "same_inputs": True,
        "requested_at": requested_at,
        "previous_status": previous_status,
        "reason": payload.get("reason") or "Retry requested for the same run inputs.",
    }
    run["updatedAt"] = datetime.now().isoformat()
    normalize_non_executable_plugin_observations_for_retry(run)
    prepare_nodes_for_retry(run, retry_from_node_id)
    return retry_from_node_id


def first_failed_node_id(run: dict) -> str:
    failed_statuses = {"FAIL", "FAILED", "ERROR", "CANCELLED"}
    nodes = [node for node in run.get("nodes") or [] if isinstance(node, dict)]
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        if node.get("isRunning") or node.get("status") in failed_statuses:
            if is_non_executable_plugin_observation(node):
                return next_retryable_node_id(nodes, index + 1)
            return str(node.get("id") or "")
    return ""


def coerce_retry_node_id(run: dict, retry_from_node_id: str) -> str:
    retry_from_node_id = retry_legacy_node_id(run, retry_from_node_id)
    nodes = [node for node in run.get("nodes") or [] if isinstance(node, dict)]
    for index, node in enumerate(nodes):
        if str(node.get("id") or "") != retry_from_node_id:
            continue
        if is_non_executable_plugin_observation(node):
            return next_retryable_node_id(nodes, index + 1)
        return retry_from_node_id
    return retry_from_node_id


def retry_legacy_node_id(run: dict, node_id: str) -> str:
    node_ids = {str(node.get("id") or "") for node in run.get("nodes") or [] if isinstance(node, dict)}
    if node_id in {"data_fetch", "data_engine", "chip_kb", "memory_agent"} and "data_reliability_engine" in node_ids:
        return "data_reliability_engine"
    quant_core_legacy_ids = {
        "market_regime",
        "technical_kline_analyst",
        "market_technical_analyst",
        "bottom_research",
        "quant_engine",
        "qiam",
        "scenario_engine",
    }
    if node_id in quant_core_legacy_ids and "quant_core" in node_ids:
        return "quant_core"
    if node_id in {"market_regime", "technical_kline_analyst"} and "market_technical_analyst" in node_ids:
        return "market_technical_analyst"
    return node_id


def next_retryable_node_id(nodes: list[dict], start_index: int) -> str:
    terminal_statuses = {"PASS", "WARN", "COMPLETED", "REVIEW_ONLY", "SKIPPED"}
    for node in nodes[start_index:]:
        if node.get("isSkipped") or is_non_executable_plugin_observation(node):
            continue
        node_id = str(node.get("id") or "")
        if node_id and (node.get("isRunning") or node.get("status") not in terminal_statuses):
            return node_id
    return ""


def normalize_non_executable_plugin_observations_for_retry(run: dict) -> None:
    observed_at = datetime.now().isoformat()
    for node in run.get("nodes") or []:
        if isinstance(node, dict) and is_non_executable_plugin_observation(node):
            mark_non_executable_plugin_observation(
                node,
                observed_at=observed_at,
                reason=NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON,
            )


def prepare_nodes_for_retry(run: dict, retry_from_node_id: str) -> None:
    node_ids = [str(node.get("id") or "") for node in run.get("nodes") or [] if isinstance(node, dict)]
    if retry_from_node_id:
        try:
            start_index = node_ids.index(retry_from_node_id)
        except ValueError:
            start_index = 0
    else:
        start_index = 0
    retry_node_ids = set(node_ids[start_index:])
    requested_at = (run.get("retry") or {}).get("requested_at") or datetime.now().isoformat()

    for node in run.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("id") or "") not in retry_node_ids:
            continue
        if is_non_executable_plugin_observation(node):
            mark_non_executable_plugin_observation(
                node,
                observed_at=requested_at,
                reason=NON_EXECUTABLE_PLUGIN_OBSERVATION_REASON,
            )
            continue
        node["status"] = "WAIT"
        node["isRunning"] = False
        node["duration"] = 0
        node["outputSummary"] = ""
        raw_json = dict(node.get("rawJson") or {})
        raw_json.pop("llmRunner", None)
        raw_json.pop("llmOutput", None)
        raw_json.pop("llmOutputText", None)
        raw_json["retry"] = {
            "status": "RESET_FOR_RETRY",
            "retryFromNodeId": retry_from_node_id,
            "resetAt": requested_at,
        }
        node["rawJson"] = raw_json

    for key in ("agentOutputs", "agentModuleResults"):
        value = run.get(key)
        if isinstance(value, dict):
            for node_id in retry_node_ids:
                value.pop(node_id, None)

    if isinstance(run.get("llmTrace"), list):
        run["llmTrace"] = [
            item
            for item in run["llmTrace"]
            if not isinstance(item, dict) or str(item.get("nodeId") or "") not in retry_node_ids
        ]
    if isinstance(run.get("agentResults"), list):
        run["agentResults"] = [
            item
            for item in run["agentResults"]
            if not isinstance(item, dict) or str(item.get("node") or item.get("id") or "") not in retry_node_ids
        ]


def failed_node_from_run(run: dict) -> str:
    return first_failed_node_id(run) or str((run.get("retry") or {}).get("from_node_id") or "")
