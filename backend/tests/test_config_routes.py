from copy import deepcopy
import asyncio

import pytest
from fastapi import HTTPException

from app.api import routes_config
from app.core.config_store import CONFIG_AUDIT_RUN_ID
from app.core.operator_context import OperatorContext, reset_current_operator, set_current_operator
from app.db.repositories import AuditRepository
from app.models.config import (
    CreateConfigDraftRequest,
    PatchRuntimeConfigRequest,
    RollbackConfigRequest,
    ValidateConfigRequest,
)


@pytest.fixture(autouse=True)
def restore_config_state():
    profile_snapshot = routes_config.mock_config_profile.model_copy(deep=True)
    schema_snapshot = [item.model_copy(deep=True) for item in routes_config.mock_config_schema]
    versions_snapshot = deepcopy(routes_config.config_versions)
    drafts_snapshot = deepcopy(routes_config.config_drafts)

    yield

    routes_config.mock_config_profile = profile_snapshot
    routes_config.mock_config_schema = schema_snapshot
    routes_config.config_versions = versions_snapshot
    routes_config.config_drafts = drafts_snapshot


def reset_route_cache(profile_snapshot, schema_snapshot):
    routes_config.mock_config_profile = profile_snapshot.model_copy(deep=True)
    routes_config.mock_config_schema = [item.model_copy(deep=True) for item in schema_snapshot]
    routes_config.config_versions = []
    routes_config.config_drafts = {}


@pytest.mark.asyncio
async def test_safe_runtime_patch_validates_applies_and_versions():
    previous_version = routes_config.mock_config_profile.version

    response = await routes_config.patch_runtime_config(
        PatchRuntimeConfigRequest(changes={"run_mode_default": "DEEP_MODE"})
    )
    schema = await routes_config.get_config_schema()
    run_mode_item = next(item for item in schema if item.key == "run_mode_default")

    assert response["status"] == "APPLIED"
    assert response["version"] == previous_version + 1
    assert routes_config.mock_config_profile.safe_runtime_config["run_mode_default"] == "DEEP_MODE"
    assert run_mode_item.current == "DEEP_MODE"
    assert routes_config.config_versions[-1]["version"] == previous_version + 1


@pytest.mark.asyncio
async def test_safe_runtime_patch_persists_after_route_state_reset_and_writes_audit():
    profile_snapshot = routes_config.mock_config_profile.model_copy(deep=True)
    schema_snapshot = [item.model_copy(deep=True) for item in routes_config.mock_config_schema]

    response = await routes_config.patch_runtime_config(
        PatchRuntimeConfigRequest(changes={"run_mode_default": "FAST_MODE"})
    )
    reset_route_cache(profile_snapshot, schema_snapshot)

    persisted = await routes_config.get_current_config()
    logs = await AuditRepository().find_by_run_id(CONFIG_AUDIT_RUN_ID)
    config_audit = await routes_config.get_config_audit()

    assert persisted.version == response["version"]
    assert persisted.safe_runtime_config["run_mode_default"] == "FAST_MODE"
    assert logs[-1]["auditId"] == response["audit_id"]
    assert logs[-1]["eventType"] == "CONFIG_RUNTIME_PATCH"
    assert config_audit[0]["auditId"] == response["audit_id"]


@pytest.mark.asyncio
async def test_config_version_and_audit_include_operator_context():
    operator_token = set_current_operator(
        OperatorContext(id="admin-reviewer", role="admin", source="test")
    )
    try:
        response = await routes_config.patch_runtime_config(
            PatchRuntimeConfigRequest(changes={"run_mode_default": "FAST_MODE"})
        )
    finally:
        reset_current_operator(operator_token)

    versions = await routes_config.get_config_versions()
    config_audit = await routes_config.get_config_audit()
    changed_version = next(item for item in versions if item["version"] == response["version"])

    assert changed_version["created_by"] == "admin-reviewer"
    assert config_audit[0]["auditId"] == response["audit_id"]
    assert config_audit[0]["payload"]["operator"] == {
        "id": "admin-reviewer",
        "role": "admin",
        "source": "test",
    }


@pytest.mark.asyncio
async def test_config_versions_filter_by_actor_and_include_secret_safe_policy():
    operator_token = set_current_operator(
        OperatorContext(id="runtime-admin", role="admin", source="test")
    )
    try:
        await routes_config.patch_runtime_config(
            PatchRuntimeConfigRequest(changes={"run_mode_default": "FAST_MODE"})
        )
        external = await routes_config.config_store.record_external_change(
            scope="agent_runtime",
            surface="llm_profile",
            subject="sample_llm",
            before={"api_key": "old-secret", "base_url": "https://api.openai.com/v1"},
            after={
                "api_key": "new-secret",
                "base_url": "https://api.openai.com/v1",
                "secret_refs": {
                    "llm_profiles": {
                        "sample_llm": {
                            "api_key": "runtime-secret:v1:llm_profiles:sample_llm:api_key",
                        },
                    },
                },
            },
            diff={"api_key": {"before": "old-secret", "after": "new-secret"}},
            summary="Updated sample LLM profile",
            operator=routes_config.current_operator(),
        )
    finally:
        reset_current_operator(operator_token)

    by_actor = await routes_config.get_config_versions(include_external=True, created_by="runtime-admin")
    by_profile = await routes_config.get_config_versions(
        include_external=True,
        profile_id="agent_runtime:llm_profile",
    )

    assert all(item["created_by"] == "runtime-admin" for item in by_actor)
    version = next(item for item in by_profile if item["audit_id"] == external["audit_id"])
    assert version["snapshot_redacted"] is True
    assert version["approval_required"] is True
    policy = version["rollback_policy"]
    assert policy["supported"] is False
    assert policy["approval_required"] is True
    assert policy["secret_safe_required"] is True
    assert policy["blocked_reason"] == "secret_safe_rollback_required"
    assert policy["approval_gate"] == {
        "required": True,
        "status": "BLOCKED_PENDING_VAULT_VERSION_APPROVAL",
        "scope": "runtime_config_secret_restore",
        "approver_role": "admin",
        "secret_vault_version_required": True,
        "required_secret_refs": [
            {
                "path": "secret_refs.llm_profiles.sample_llm.api_key",
                "ref": "runtime-secret:v1:llm_profiles:sample_llm:api_key",
            },
        ],
        "restore_source": "secret_vault_version_refs",
        "reason": "External runtime config snapshots are redacted; restore requires approved matching secret vault refs.",
    }
    assert version["effective_scope"] == ["agent_runtime", "llm_profile"]
    serialized_version = str(version)
    assert "old-secret" not in serialized_version
    assert "new-secret" not in serialized_version


@pytest.mark.asyncio
async def test_runtime_patch_blocks_review_required_or_unknown_keys():
    with pytest.raises(HTTPException) as exc_info:
        await routes_config.patch_runtime_config(
            PatchRuntimeConfigRequest(changes={"hallucination_review_threshold": 70})
        )

    detail = exc_info.value.detail
    assert exc_info.value.status_code == 400
    assert detail["policy_check"]["level"] == "BLOCKED"
    assert "submit a review draft" in detail["policy_check"]["blocked_reasons"][0]

    check = await routes_config.validate_config_change(
        ValidateConfigRequest(changes={"unknown_config_key": True})
    )
    assert check.passed is False
    assert check.level == "BLOCKED"
    assert check.blocked_reasons == ["Unknown config key: unknown_config_key."]


@pytest.mark.asyncio
async def test_review_draft_apply_and_rollback_restore_snapshot():
    profile_snapshot = routes_config.mock_config_profile.model_copy(deep=True)
    schema_snapshot = [item.model_copy(deep=True) for item in routes_config.mock_config_schema]
    original_version = routes_config.mock_config_profile.version
    original_threshold = routes_config.mock_config_profile.review_required_config[
        "hallucination_review_threshold"
    ]

    draft = await routes_config.create_config_draft(
        CreateConfigDraftRequest(
            changes={"hallucination_review_threshold": original_threshold + 5},
            reason="tighten review threshold through approval",
        )
    )
    reset_route_cache(profile_snapshot, schema_snapshot)
    applied = await routes_config.apply_config_draft(draft.draft_id)

    assert routes_config.config_drafts[draft.draft_id].status == "APPLIED"
    assert applied["status"] == "APPLIED"
    assert routes_config.mock_config_profile.review_required_config[
        "hallucination_review_threshold"
    ] == original_threshold + 5

    reset_route_cache(profile_snapshot, schema_snapshot)
    rolled_back = await routes_config.rollback_config(
        RollbackConfigRequest(target_version=original_version, reason="restore baseline")
    )

    assert rolled_back["status"] == "ROLLED_BACK"
    assert rolled_back["rollback_target_version"] == original_version
    assert routes_config.mock_config_profile.version == applied["version"] + 1
    assert routes_config.mock_config_profile.review_required_config[
        "hallucination_review_threshold"
    ] == original_threshold

    patched_after_rollback = await routes_config.patch_runtime_config(
        PatchRuntimeConfigRequest(changes={"run_mode_default": "DEEP_MODE"})
    )
    versions = await routes_config.get_config_versions()
    version_numbers = [item["version"] for item in versions]

    assert patched_after_rollback["version"] == routes_config.mock_config_profile.version
    assert len(version_numbers) == len(set(version_numbers))
    assert max(version_numbers) == patched_after_rollback["version"]


@pytest.mark.asyncio
async def test_concurrent_runtime_patches_allocate_unique_versions():
    responses = await asyncio.gather(
        routes_config.patch_runtime_config(
            PatchRuntimeConfigRequest(changes={"run_mode_default": "FAST_MODE"})
        ),
        routes_config.patch_runtime_config(
            PatchRuntimeConfigRequest(changes={"run_mode_default": "DEEP_MODE"})
        ),
    )

    response_versions = {item["version"] for item in responses}
    versions = await routes_config.get_config_versions()
    runtime_versions = {item["version"] for item in versions if item["audit_id"].startswith("AUD_CFG_")}

    assert len(response_versions) == 2
    assert response_versions.issubset(runtime_versions)
