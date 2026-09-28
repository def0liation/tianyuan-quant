from copy import deepcopy
from datetime import datetime, timezone
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..core.config_store import config_store
from ..core.agent_runtime_store import (
    build_runtime_config_diff,
    restore_runtime_config_snapshot,
    runtime_config_audit_snapshot,
)
from ..core.operator_context import current_operator
from ..models.config import (
    ConfigDraft,
    ConfigProfile,
    ConfigSchemaItem,
    CreateConfigDraftRequest,
    ExternalConfigRestoreRequest,
    PatchRuntimeConfigRequest,
    PolicyCheckResult,
    RollbackConfigRequest,
    ValidateConfigRequest,
)


router = APIRouter()

logger = logging.getLogger(__name__)


mock_config_profile = ConfigProfile(
    profile_id="default",
    version=3,
    locked_guardrails={
        "dvg_block_buy_hard_stop": True,
        "kill_switch_compliance_hard": True,
        "qiam_raw_forbidden_in_final": True,
        "final_writer_no_override_block": True,
        "signalops_no_bypass_risk_dvg_qiam": True,
        "paper_trading_no_profit_claim": True,
        "no_auto_real_trading": True,
        "simulated_auto_trading_allowed": True,
        "no_profit_guarantee": True,
        "chip_kb_positive_no_position_increase": True,
    },
    safe_runtime_config={
        "run_mode_default": "STANDARD_MODE",
        "tool_budget": 1000,
        "latency_budget": 30000,
        "max_parallel_nodes": 5,
        "default_scenario": "qiam_discounted",
        "factor_slicing_default_mode": "AUTO",
        "audit_log_retention_days": 90,
        "show_raw_json": False,
        "enable_developer_panels": False,
    },
    review_required_config={
        "hallucination_warn_threshold": 40,
        "hallucination_review_threshold": 60,
        "qiam_discount_warning_threshold": 0.7,
        "portfolio_single_stock_soft_limit": 0.12,
        "portfolio_industry_soft_limit": 0.25,
        "paper_test_min_observation_days": 14,
        "signalops_min_trigger_conditions": 0,
    },
    sandbox_config={},
    created_at="2026-05-09T09:00:00Z",
    updated_at="2026-05-09T10:00:00Z",
)


mock_config_schema = [
    ConfigSchemaItem(
        key="hallucination_review_threshold",
        label="Hallucination review threshold",
        type="number",
        layer="REVIEW_REQUIRED",
        min=0,
        max=100,
        default=60,
        current=60,
        editable=True,
        direction="CONSERVATIVE_ONLY",
        description="When hallucination risk reaches this value, final action is capped at REVIEW_ONLY.",
    ),
    ConfigSchemaItem(
        key="run_mode_default",
        label="Default run mode",
        type="select",
        layer="SAFE_RUNTIME",
        options=["FAST_MODE", "STANDARD_MODE", "DEEP_MODE"],
        default="STANDARD_MODE",
        current="STANDARD_MODE",
        editable=True,
        direction="ANY",
        description="Default mode for new analysis tasks.",
    ),
]

config_versions: list[dict] = []
config_drafts: dict[str, ConfigDraft] = {}
config_mutation_lock = asyncio.Lock()

AGENT_RUNTIME_RESTORE_KEYS_BY_SURFACE = {
    "runtime_settings": (
        "default_llm_profile_id",
        "default_market_data_profile_id",
        "max_parallel_agents",
        "agents",
    ),
    "llm_profile": ("default_llm_profile_id", "llm_profiles"),
    "market_data_profile": ("default_market_data_profile_id", "market_data_profiles"),
    "agent_llm_assignment": ("agents",),
    "data_sources_config": ("data_sources_config",),
    "market_data_adapter_config": ("market_data_adapter_configs",),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _schema_by_key() -> dict[str, ConfigSchemaItem]:
    return {item.key: item for item in mock_config_schema}


def _config_layer_for_item(item: ConfigSchemaItem) -> dict:
    if item.layer == "SAFE_RUNTIME":
        return mock_config_profile.safe_runtime_config
    if item.layer == "REVIEW_REQUIRED":
        return mock_config_profile.review_required_config
    if item.layer == "SANDBOX":
        return mock_config_profile.sandbox_config
    return mock_config_profile.locked_guardrails


def _coerce_and_validate_value(item: ConfigSchemaItem, value):
    if item.type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{item.key} must be a number.")
        if item.min is not None and value < item.min:
            raise ValueError(f"{item.key} must be >= {item.min}.")
        if item.max is not None and value > item.max:
            raise ValueError(f"{item.key} must be <= {item.max}.")
    elif item.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{item.key} must be a boolean.")
    elif item.type == "select":
        if item.options and value not in item.options:
            raise ValueError(f"{item.key} must be one of: {', '.join(item.options)}.")
    elif item.type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{item.key} must be a string.")


def _validate_changes(changes: dict, *, safe_runtime_only: bool = False) -> PolicyCheckResult:
    schema = _schema_by_key()
    warnings: list[str] = []
    blocked_reasons: list[str] = []
    effective_changes: dict = {}
    requires_review = False

    for key, value in changes.items():
        item = schema.get(key)
        if item is None:
            blocked_reasons.append(f"Unknown config key: {key}.")
            continue
        if not item.editable or item.layer == "LOCKED":
            blocked_reasons.append(f"{key} is locked and cannot be changed.")
            continue
        if safe_runtime_only and item.layer != "SAFE_RUNTIME":
            blocked_reasons.append(f"{key} belongs to {item.layer}; submit a review draft instead.")
            continue

        try:
            _coerce_and_validate_value(item, value)
        except ValueError as exc:
            logger.exception("Config validation failed for key %s: %s", key, exc)
            blocked_reasons.append("Invalid value provided. Please check the configuration requirements.")
            continue

        current = _config_layer_for_item(item).get(key, item.current)
        if item.direction == "CONSERVATIVE_ONLY" and isinstance(value, (int, float)) and not isinstance(value, bool) and value < current:
            requires_review = True
            warnings.append(f"{key} relaxes a conservative guardrail and requires review.")
        if item.layer == "REVIEW_REQUIRED":
            requires_review = True
            warnings.append(f"{key} requires review before it can become active.")
        effective_changes[key] = value

    level = "BLOCKED" if blocked_reasons else "REVIEW_REQUIRED" if requires_review else "SAFE"
    return PolicyCheckResult(
        passed=not blocked_reasons and not requires_review,
        level=level,
        warnings=warnings,
        blocked_reasons=blocked_reasons,
        effective_changes=effective_changes,
    )


def _apply_changes(changes: dict) -> None:
    schema = _schema_by_key()
    for key, value in changes.items():
        item = schema[key]
        _config_layer_for_item(item)[key] = value
        item.current = value


def _sync_schema_current_values() -> None:
    for item in mock_config_schema:
        item.current = _config_layer_for_item(item).get(item.key, item.current)


async def _load_config_state() -> ConfigProfile:
    global mock_config_profile, config_versions, config_drafts

    profile, versions, drafts = await config_store.load_state(mock_config_profile)
    mock_config_profile = profile
    config_versions = versions
    config_drafts = drafts
    _sync_schema_current_values()
    return mock_config_profile


def _version_audit_id(version: int) -> str:
    return f"AUD_CFG_{version}"


def _next_config_version() -> int:
    versions = [mock_config_profile.version]
    versions.extend(int(version.get("version") or 0) for version in config_versions)
    return max(versions) + 1


@router.get("/config/current", response_model=ConfigProfile)
async def get_current_config():
    await _load_config_state()
    return mock_config_profile


@router.get("/config/schema", response_model=list[ConfigSchemaItem])
async def get_config_schema():
    await _load_config_state()
    return mock_config_schema


@router.patch("/config/runtime")
async def patch_runtime_config(request: PatchRuntimeConfigRequest):
    async with config_mutation_lock:
        await _load_config_state()
        check = _validate_changes(request.changes, safe_runtime_only=True)
        if not check.passed:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Runtime config change failed policy validation.",
                    "policy_check": check.model_dump(),
                },
            )

        previous_version = mock_config_profile.version
        _apply_changes(check.effective_changes)
        mock_config_profile.version = _next_config_version()
        mock_config_profile.updated_at = _now()
        audit_id = _version_audit_id(mock_config_profile.version)
        change_summary = "Runtime config changed: " + ", ".join(sorted(check.effective_changes.keys()))
        await config_store.record_runtime_change(
            mock_config_profile,
            change_summary=change_summary,
            audit_id=audit_id,
            changes=check.effective_changes,
            previous_version=previous_version,
            operator=current_operator(),
        )
        await _load_config_state()

        return {
            "status": "APPLIED",
            "profile_id": mock_config_profile.profile_id,
            "version": mock_config_profile.version,
            "audit_id": audit_id,
        }


@router.post("/config/validate", response_model=PolicyCheckResult)
async def validate_config_change(request: ValidateConfigRequest):
    await _load_config_state()
    return _validate_changes(request.changes)


@router.post("/config/drafts", response_model=ConfigDraft)
async def create_config_draft(request: CreateConfigDraftRequest):
    async with config_mutation_lock:
        await _load_config_state()
        check = _validate_changes(request.changes)
        if check.level == "BLOCKED":
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Draft contains blocked config changes.",
                    "policy_check": check.model_dump(),
                },
            )

        draft_version = _next_config_version()
        draft = ConfigDraft(
            draft_id=f"CFG_DRAFT_{draft_version}",
            status="PENDING_REVIEW",
            changes=check.effective_changes,
            reason=request.reason,
            policy_check=check.model_dump(),
            audit_id=f"AUD_CFG_DRAFT_{draft_version}",
            created_at=_now(),
        )
        draft = await config_store.create_draft(mock_config_profile, draft, operator=current_operator())
        config_drafts[draft.draft_id] = draft
        return draft


@router.post("/config/drafts/{draft_id}/apply")
async def apply_config_draft(draft_id: str):
    async with config_mutation_lock:
        await _load_config_state()
        draft = config_drafts.get(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Config draft not found")
        if draft.status != "PENDING_REVIEW":
            raise HTTPException(status_code=409, detail="Config draft is not pending review")

        previous_version = mock_config_profile.version
        _apply_changes(draft.changes)
        draft.status = "APPLIED"
        mock_config_profile.version = _next_config_version()
        mock_config_profile.updated_at = _now()
        audit_id = f"AUD_CFG_APPLY_{draft_id}_{mock_config_profile.version}"
        change_summary = "Applied review draft: " + ", ".join(sorted(draft.changes.keys()))
        await config_store.apply_draft(
            mock_config_profile,
            draft,
            change_summary=change_summary,
            audit_id=audit_id,
            previous_version=previous_version,
            operator=current_operator(),
        )
        await _load_config_state()
        return {
            "status": "APPLIED",
            "version": mock_config_profile.version,
            "rollback_version": previous_version,
            "audit_id": audit_id,
        }


@router.post("/config/rollback")
async def rollback_config(request: RollbackConfigRequest):
    async with config_mutation_lock:
        await _load_config_state()
        snapshot = next(
            (
                version.get("snapshot")
                for version in reversed(config_versions)
                if version.get("version") == request.target_version
            ),
            None,
        )
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Config version not found")

        mock_config_profile.locked_guardrails = deepcopy(snapshot["locked_guardrails"])
        mock_config_profile.safe_runtime_config = deepcopy(snapshot["safe_runtime_config"])
        mock_config_profile.review_required_config = deepcopy(snapshot["review_required_config"])
        mock_config_profile.sandbox_config = deepcopy(snapshot["sandbox_config"])
        mock_config_profile.version = _next_config_version()
        mock_config_profile.updated_at = _now()
        _sync_schema_current_values()
        audit_id = f"AUD_CFG_ROLLBACK_{request.target_version}_AS_{mock_config_profile.version}"
        await config_store.rollback(
            mock_config_profile,
            target_version=request.target_version,
            reason=request.reason,
            audit_id=audit_id,
            operator=current_operator(),
        )
        await _load_config_state()
        return {
            "status": "ROLLED_BACK",
            "current_version": mock_config_profile.version,
            "rollback_target_version": request.target_version,
            "audit_id": audit_id,
        }


@router.post("/config/external-restore")
async def restore_external_config(request: ExternalConfigRestoreRequest):
    if not request.confirm_secret_safe:
        raise HTTPException(
            status_code=400,
            detail="External config restore requires confirm_secret_safe=true.",
        )
    if not request.target_version and not request.audit_id:
        raise HTTPException(
            status_code=400,
            detail="External config restore requires target_version or audit_id.",
        )
    scope_parts = request.profile_id.split(":", 1)
    scope = scope_parts[0] if scope_parts else ""
    surface = scope_parts[1] if len(scope_parts) > 1 else ""
    if scope != "agent_runtime" or not surface:
        raise HTTPException(
            status_code=400,
            detail="Only agent_runtime external config restore is supported.",
        )
    restore_keys = AGENT_RUNTIME_RESTORE_KEYS_BY_SURFACE.get(surface)
    if restore_keys is None:
        raise HTTPException(
            status_code=400,
            detail=f"External config restore is not supported for surface: {surface}.",
        )

    target = await config_store.get_version(
        profile_id=request.profile_id,
        version=request.target_version,
        audit_id=request.audit_id,
        include_snapshot=True,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="External config version not found")

    policy = target.get("rollback_policy") or {}
    approval_gate = policy.get("approval_gate") or {}
    if approval_gate.get("secret_vault_version_required") is not True:
        raise HTTPException(
            status_code=409,
            detail="External config version is missing a vault-version approval gate.",
        )

    before = runtime_config_audit_snapshot(include_secret_versions=True)
    try:
        restore_result = restore_runtime_config_snapshot(
            target.get("snapshot") or {},
            approval_id=request.approval_id,
            reason=request.reason,
            restore_keys=restore_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    after = runtime_config_audit_snapshot(include_secret_versions=True)
    restore_audit = await config_store.record_external_change(
        scope="agent_runtime",
        surface=surface,
        subject=f"restore:{target.get('audit_id')}",
        before=before,
        after=after,
        diff=build_runtime_config_diff(before, after),
        summary=f"Approved external config restore to {request.profile_id} v{target.get('version')}.",
        operator=current_operator(),
    )
    return {
        "status": "RESTORED",
        "profile_id": request.profile_id,
        "target_version": target.get("version"),
        "target_audit_id": target.get("audit_id"),
        "restore_audit_id": restore_audit["audit_id"] if restore_audit else None,
        "approval_id": request.approval_id,
        "approved_by": request.approved_by or current_operator().id,
        **restore_result,
    }


def _matches_optional_filter(item: dict, key: str, value: str | None) -> bool:
    return not value or str(item.get(key) or "") == value


@router.get("/config/versions")
async def get_config_versions(
    include_external: bool = False,
    profile_id: str | None = None,
    created_by: str | None = None,
    status: str | None = None,
    limit: int = 200,
):
    limit = min(max(int(limit or 200), 1), 1000)
    if include_external:
        return await config_store.list_versions(
            limit=limit,
            include_snapshot=False,
            profile_id=profile_id,
            created_by=created_by,
            status=status,
        )

    await _load_config_state()
    versions = [
        {key: deepcopy(value) for key, value in version.items() if key != "snapshot"}
        for version in sorted(config_versions, key=lambda item: item["created_at"], reverse=True)
    ]
    return [
        version
        for version in versions
        if _matches_optional_filter(version, "profile_id", profile_id)
        and _matches_optional_filter(version, "created_by", created_by)
        and _matches_optional_filter(version, "status", status)
    ][:limit]


@router.get("/config/audit")
async def get_config_audit():
    return await config_store.list_audit()
