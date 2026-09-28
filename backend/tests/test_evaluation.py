import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.evaluation_store import EvaluationSandboxStore, KnowledgeVersionStore
from app.core.case_library_store import CaseLibraryStore, KnowledgePatchStore
from app.db.models_case_library import CaseLibraryDB, KnowledgeVersionDB
from app.db.session import AsyncSessionLocal
from app.api.routes_evaluation import approve_patch_with_evaluation, create_knowledge_version, rollback_knowledge_version
from app.models.evaluation import (
    CreateVersionRequest,
    PromotePatchRequest,
    RollbackRequest,
    StrategyExperimentReport,
    StrategyExperimentRequest,
)


@pytest.fixture
def sample_run_data():
    return {
        "runId": "RUN_M6_001",
        "auditId": "AUD_M6_001",
        "stockCode": "600001.SH",
        "stockName": "TestStock",
        "taskType": "POSITION_REVIEW",
        "runMode": "STANDARD_MODE",
        "finalAction": "HOLD",
    }


@pytest.fixture
def case_store():
    return CaseLibraryStore()


@pytest.fixture
def patch_store():
    return KnowledgePatchStore()


@pytest.fixture
def eval_store():
    return EvaluationSandboxStore()


@pytest.fixture
def ver_store():
    return KnowledgeVersionStore()


def test_strategy_experiment_report_model_defaults_to_low_evidence_strength():
    report = StrategyExperimentReport(
        experiment_id="EXP_MODEL_LOW",
        hypothesis="model default stays review-gate only",
        strategy_count=1,
        baseline_config_id="baseline",
        winner_config_id="baseline",
        created_at="2026-06-19T00:00:00Z",
    )

    assert report.evidence_usage == "review_gate_only"
    assert report.evidence_strength == "LOW"
    assert report.simulation_only is True
    assert report.is_real_trade is False
    assert report.strong_conclusion_allowed is False


def test_knowledge_version_review_gate_caps_research_grade_aliases(ver_store):
    regression = ver_store._with_post_publish_regression_boundary(
        {
            "report_id": "REG_LEGACY_RESEARCH_GRADE",
            "status": "PASS",
            "evidence_usage": "primary_evidence",
            "evidence_strength": "RESEARCH_GRADE",
            "simulation_only": False,
            "is_real_trade": True,
            "strong_conclusion_allowed": True,
        }
    )
    refs = ver_store._sanitize_approval_evidence_refs(
        [
            {
                "source_type": "evaluation",
                "source_id": "EVAL_LEGACY_PRIMARY_READY",
                "evidence_usage": "primary_evidence",
                "evidence_strength": "PRIMARY_EVIDENCE_READY",
                "simulation_only": False,
                "is_real_trade": True,
                "strong_conclusion_allowed": True,
            }
        ]
    )

    assert regression["evidence_usage"] == "review_gate_only"
    assert regression["evidence_strength"] == "MEDIUM"
    assert regression["simulation_only"] is True
    assert regression["is_real_trade"] is False
    assert regression["strong_conclusion_allowed"] is False
    assert refs == [
        {
            "source_type": "evaluation",
            "source_id": "EVAL_LEGACY_PRIMARY_READY",
            "evidence_usage": "review_gate_only",
            "evidence_strength": "MEDIUM",
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
        }
    ]


@pytest.mark.parametrize("strength", ["UNKNOWN", "SUPPORTING_ONLY", "WARN", "REVIEW_ONLY"])
def test_knowledge_version_review_gate_keeps_weak_aliases_low(ver_store, strength):
    regression = ver_store._with_post_publish_regression_boundary(
        {
            "report_id": "REG_LEGACY_WEAK_ALIAS",
            "status": "PASS",
            "evidence_usage": "review_gate_only",
            "evidence_strength": strength,
        }
    )
    refs = ver_store._sanitize_approval_evidence_refs(
        [
            {
                "source_type": "evaluation",
                "source_id": "EVAL_LEGACY_WEAK_ALIAS",
                "evidence_usage": "review_gate_only",
                "evidence_strength": strength,
                "simulation_only": False,
                "is_real_trade": True,
                "strong_conclusion_allowed": True,
            }
        ]
    )

    assert regression["evidence_usage"] == "review_gate_only"
    assert regression["evidence_strength"] == "LOW"
    assert regression["simulation_only"] is True
    assert regression["is_real_trade"] is False
    assert regression["strong_conclusion_allowed"] is False
    assert refs[0]["evidence_usage"] == "review_gate_only"
    assert refs[0]["evidence_strength"] == "LOW"
    assert refs[0]["simulation_only"] is True
    assert refs[0]["is_real_trade"] is False
    assert refs[0]["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_create_version(ver_store):
    v = await ver_store.create_version(description="Initial version")
    assert v["version_number"] >= 1
    assert v["description"] == "Initial version"
    assert v["evidence_usage"] == "review_gate_only"
    assert v["evidence_strength"] == "LOW"
    assert v["simulation_only"] is True
    assert v["is_real_trade"] is False
    assert v["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_create_knowledge_version_route_is_draft_only():
    version = await create_knowledge_version(
        CreateVersionRequest(
            description="Manual draft snapshot",
            approval_record={"reviewer": "human", "decision": "MANUAL_DRAFT"},
        )
    )

    assert version.status == "draft"
    assert version.evidence_strength == "PENDING"
    assert version.source_run_id is None
    assert version.source_case_id is None
    assert version.source_patch_id is None
    assert version.source_evaluation_id is None
    assert version.approval_record["decision"] == "MANUAL_DRAFT"
    assert version.simulation_only is True
    assert version.is_real_trade is False
    assert version.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_create_knowledge_version_route_rejects_direct_published_status():
    with pytest.raises(HTTPException) as exc_info:
        await create_knowledge_version(
            CreateVersionRequest(
                description="Unsafe active snapshot",
                status="active",
            )
        )

    assert exc_info.value.status_code == 400
    assert "draft-only" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_knowledge_version_route_rejects_unvalidated_sources_and_refs():
    with pytest.raises(HTTPException) as source_exc:
        await create_knowledge_version(
            CreateVersionRequest(
                description="Unsafe sourced draft",
                source_run_id="RUN_DIRECT_UNVERIFIED",
            )
        )

    assert source_exc.value.status_code == 400
    assert "unvalidated source field" in source_exc.value.detail
    assert "source_run_id" in source_exc.value.detail

    with pytest.raises(HTTPException) as refs_exc:
        await create_knowledge_version(
            CreateVersionRequest(
                description="Unsafe ref draft",
                approval_record={
                    "evidence_refs": [
                        {"source_type": "primary_evidence", "source_id": "RUN_DIRECT_STRONG"}
                    ]
                },
            )
        )

    assert refs_exc.value.status_code == 400
    assert "approval_record.evidence_refs" in refs_exc.value.detail


@pytest.mark.asyncio
async def test_list_versions(ver_store):
    await ver_store.create_version(description="v1")
    await ver_store.create_version(description="v2")
    versions = await ver_store.list_versions()
    assert len(versions) >= 2
    assert versions[0]["version_number"] >= versions[1]["version_number"]
    assert versions[0]["evidence_usage"] == "review_gate_only"
    assert versions[0]["simulation_only"] is True
    assert versions[0]["is_real_trade"] is False
    assert versions[0]["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_diff_versions(ver_store, patch_store):
    v1 = await ver_store.create_version(description="base")

    patch = await patch_store.create_patch(
        title="Test patch for diff",
        reason="Testing diff",
        affected_modules=["test"],
        patch_content={},
    )
    await patch_store.review_patch(patch.patch_id, "APPROVE", "test")

    v2 = await ver_store.create_version(
        description="version with patch",
        source_patch_id=patch.patch_id,
    )

    diff = await ver_store.diff_versions(v1["version_id"], v2["version_id"])
    assert "patches_added" in diff
    assert diff["patch_count_diff"] >= 0


@pytest.mark.asyncio
async def test_rollback(ver_store, patch_store):
    await ver_store.create_version(description="initial")

    patch = await patch_store.create_patch(
        title="Rollback test",
        reason="Testing rollback",
        affected_modules=["test"],
        patch_content={},
    )
    await patch_store.review_patch(patch.patch_id, "APPROVE", "test")
    v_before = await ver_store.create_version(description="before rollback")

    result = await ver_store.rollback_to(v_before["version_id"], "test_user")
    assert "rollback_target" in result
    assert "new_version" in result
    assert result["new_version"]["version_number"] > v_before["version_number"]
    assert result["rollback_target"]["strong_conclusion_allowed"] is False
    assert result["new_version"]["evidence_usage"] == "review_gate_only"
    assert result["new_version"]["evidence_strength"] in {"LOW", "MEDIUM"}
    assert result["new_version"]["simulation_only"] is True
    assert result["new_version"]["is_real_trade"] is False
    assert result["new_version"]["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_rollback_route_validates_nested_knowledge_version_boundaries(ver_store):
    version = await ver_store.create_version(
        description="route rollback target",
        source_run_id="RUN_ROLLBACK_ROUTE_001",
        status="review",
    )

    response = await rollback_knowledge_version(
        version["version_id"],
        RollbackRequest(performed_by="route_user"),
    )

    assert response.rollback_target.version_id == version["version_id"]
    assert response.rollback_target.evidence_usage == "review_gate_only"
    assert response.rollback_target.simulation_only is True
    assert response.rollback_target.is_real_trade is False
    assert response.rollback_target.strong_conclusion_allowed is False
    assert response.new_version.status == "rolled_back"
    assert response.new_version.evidence_usage == "review_gate_only"
    assert response.new_version.evidence_strength in {"LOW", "MEDIUM"}
    assert response.new_version.simulation_only is True
    assert response.new_version.is_real_trade is False
    assert response.new_version.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_rollback_route_rejects_draft_target():
    draft = await create_knowledge_version(
        CreateVersionRequest(description="Draft cannot be rollback target")
    )

    with pytest.raises(HTTPException) as exc_info:
        await rollback_knowledge_version(
            draft.version_id,
            RollbackRequest(performed_by="rollback_user"),
        )

    assert exc_info.value.status_code == 400
    assert "draft versions cannot be rollback targets" in exc_info.value.detail


@pytest.mark.asyncio
async def test_rollback_sanitizes_request_controlled_metadata(ver_store):
    version = await ver_store.create_version(
        description="rollback metadata target",
        source_run_id="RUN_ROLLBACK_META_001",
        status="review",
    )

    response = await rollback_knowledge_version(
        version["version_id"],
        RollbackRequest(
            performed_by="rollback_admin",
            approval_record={
                "action": "PROMOTE",
                "performed_by": "spoofed_user",
                "performed_at": "2000-01-01T00:00:00",
                "reason": "restore reviewed policy",
                "evidence_refs": [
                    {
                        "source_type": "primary_evidence",
                        "source_id": "FORGED_ROLLBACK_REF",
                    }
                ],
            },
            rollback_impact={
                "target_version_id": "KBVER_FORGED",
                "target_version_number": -1,
                "restored_patch_count": 999,
                "operator_note": "preserve caller note",
            },
        ),
    )

    approval = response.new_version.approval_record
    assert approval["action"] == "ROLLBACK"
    assert approval["performed_by"] == "rollback_admin"
    assert approval["performed_at"] != "2000-01-01T00:00:00"
    assert approval["reason"] == "restore reviewed policy"
    assert "evidence_refs" not in approval

    impact = response.new_version.rollback_impact
    assert impact["target_version_id"] == version["version_id"]
    assert impact["target_version_number"] == version["version_number"]
    assert impact["restored_patch_count"] == response.restored_patches
    assert impact["operator_note"] == "preserve caller note"
    assert response.new_version.evidence_usage == "review_gate_only"
    assert response.new_version.simulation_only is True
    assert response.new_version.is_real_trade is False
    assert response.new_version.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_evaluation_runs_on_patch(patch_store, eval_store):
    patch = await patch_store.create_patch(
        title="Eval test patch",
        reason="Testing evaluation",
        affected_modules=["dvg_gate"],
        patch_content={"tag_fix": "DATA_INSUFFICIENT"},
    )

    result = await eval_store.run_evaluation(patch.patch_id)
    assert result["status"] in ("COMPLETED", "RUNNING")
    assert result["patch_id"] == patch.patch_id
    assert result["simulation_only"] is True
    assert result["is_real_trade"] is False
    assert result["evidence_usage"] == "review_gate_only"
    assert result["evidence_strength"] in {"MEDIUM", "LOW", "MISSING", "PENDING"}
    assert result["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_evaluation_is_idempotent(patch_store, eval_store):
    patch = await patch_store.create_patch(
        title="Idempotent test",
        reason="Testing idempotency",
        affected_modules=["test"],
        patch_content={},
    )

    r1 = await eval_store.run_evaluation(patch.patch_id)
    r2 = await eval_store.run_evaluation(patch.patch_id)
    assert r1["eval_id"] == r2["eval_id"]


@pytest.mark.asyncio
async def test_list_evaluations(patch_store, eval_store):
    patch = await patch_store.create_patch(
        title="List eval test",
        reason="Testing list",
        affected_modules=["test"],
        patch_content={},
    )
    await eval_store.run_evaluation(patch.patch_id)

    evals = await eval_store.list_evaluations(patch_id=patch.patch_id)
    assert len(evals) >= 1
    assert evals[0]["patch_id"] == patch.patch_id
    assert evals[0]["simulation_only"] is True
    assert evals[0]["is_real_trade"] is False
    assert evals[0]["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_get_evaluation(patch_store, eval_store):
    patch = await patch_store.create_patch(
        title="Get eval test",
        reason="Testing get",
        affected_modules=["test"],
        patch_content={},
    )
    result = await eval_store.run_evaluation(patch.patch_id)

    ev = await eval_store.get_evaluation(result["eval_id"])
    assert ev is not None
    assert ev["status"] == "COMPLETED"
    assert ev["evidence_usage"] == "review_gate_only"
    assert ev["evidence_strength"] == result["evidence_strength"]


@pytest.mark.asyncio
async def test_evaluation_with_cases(case_store, patch_store, eval_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": False, "optimism_bias": "SEVERE"}
    )

    patch = await patch_store.create_patch(
        title="Case eval test",
        reason="Testing with reviewed cases",
        affected_modules=["risk_firewall"],
        patch_content={"rule_change": "strict_optimism_check"},
    )

    result = await eval_store.run_evaluation(patch.patch_id, force=True)
    assert result["status"] == "COMPLETED"
    assert "total_cases" in result
    assert "pass_rate" in result
    assert "improvement_rate" in result


@pytest.mark.asyncio
async def test_strategy_experiment_report_compares_configs(patch_store, eval_store):
    patch = await patch_store.create_patch(
        title="A/B strategy patch",
        reason="Testing strategy experiment",
        affected_modules=["strategy"],
        patch_content={"hypothesis": "Tighter risk gate improves decision quality"},
    )

    report = await eval_store.run_strategy_experiment(
        patch_id=patch.patch_id,
        hypothesis="Tighter risk gate improves decision quality",
        sample_window={"start": "2026-01-01", "end": "2026-03-31"},
        strategy_configs=[
            {
                "config_id": "control",
                "metrics": {
                    "win_rate": 0.55,
                    "max_drawdown": 0.12,
                    "misjudge_rate": 0.18,
                    "manual_review_pass_rate": 0.72,
                    "risk_trigger_rate": 0.2,
                },
            },
            {
                "config_id": "candidate",
                "metrics": {
                    "win_rate": 0.64,
                    "max_drawdown": 0.09,
                    "misjudge_rate": 0.11,
                    "manual_review_pass_rate": 0.82,
                    "risk_trigger_rate": 0.14,
                },
            },
        ],
    )

    assert report["hypothesis"] == "Tighter risk gate improves decision quality"
    assert report["strategy_count"] == 2
    assert report["winner_config_id"] == "candidate"
    assert report["sample_window"]["start"] == "2026-01-01"
    assert report["evidence_usage"] == "review_gate_only"
    assert report["evidence_strength"] == "LOW"
    assert report["simulation_only"] is True
    assert report["is_real_trade"] is False
    assert report["strong_conclusion_allowed"] is False
    for key in (
        "win_rate",
        "max_drawdown",
        "misjudge_rate",
        "manual_review_pass_rate",
        "risk_trigger_rate",
        "sample_window",
    ):
        assert key in report["metrics_by_strategy"]["candidate"]

    stored_patch = await patch_store.get_patch(patch.patch_id)
    stored_report = stored_patch["backtest_result"]["strategy_experiment_report"]
    assert stored_report["experiment_id"] == report["experiment_id"]
    assert stored_report["evidence_usage"] == "review_gate_only"
    assert stored_report["evidence_strength"] == "LOW"
    assert stored_report["simulation_only"] is True
    assert stored_report["is_real_trade"] is False
    assert stored_report["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_strategy_experiment_request_preserves_aliases_and_nested_metrics(patch_store, eval_store):
    patch = await patch_store.create_patch(
        title="A/B strategy alias patch",
        reason="Testing request preservation",
        affected_modules=["strategy"],
        patch_content={"hypothesis": "Nested report metrics are accepted"},
    )
    request = StrategyExperimentRequest(
        hypothesis="Nested report metrics are accepted",
        strategy_configs=[
            {
                "id": "control_alias",
                "report": {
                    "win_rate": 0.45,
                    "max_drawdown": 0.18,
                    "misjudge_rate": 0.22,
                    "manual_review_pass_rate": 0.6,
                    "risk_trigger_rate": 0.2,
                },
            },
            {
                "id": "candidate_alias",
                "report": {
                    "win_rate": 0.71,
                    "max_drawdown": 0.08,
                    "misjudge_rate": 0.09,
                    "manual_review_pass_rate": 0.86,
                    "risk_trigger_rate": 0.12,
                },
            },
        ],
    )

    report = await eval_store.run_strategy_experiment(
        patch_id=patch.patch_id,
        hypothesis=request.hypothesis,
        strategy_configs=[cfg.model_dump() for cfg in request.strategy_configs],
    )

    assert report["baseline_config_id"] == "control_alias"
    assert report["winner_config_id"] == "candidate_alias"
    assert report["metrics_by_strategy"]["candidate_alias"]["win_rate"] == 0.71
    assert report["evidence_usage"] == "review_gate_only"
    assert report["evidence_strength"] == "LOW"
    assert report["simulation_only"] is True
    assert report["is_real_trade"] is False
    assert report["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_promote_rejects_missing_evidence(patch_store):
    patch = await patch_store.create_patch(
        title="Missing evidence patch",
        reason="Testing promotion gate",
        affected_modules=["risk"],
        patch_content={},
    )

    with pytest.raises(HTTPException) as exc_info:
        await approve_patch_with_evaluation(patch.patch_id, None)

    assert exc_info.value.status_code == 400
    assert "evidence reference" in exc_info.value.detail


@pytest.mark.asyncio
async def test_promote_with_evaluation_evidence_creates_governed_version(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )

    patch = await patch_store.create_patch(
        title="Promotion evidence patch",
        reason="Testing governed promotion",
        affected_modules=["orchestrator"],
        patch_content={"risk_note": "Only affects orchestrator gate"},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    version = await approve_patch_with_evaluation(
        patch.patch_id,
        PromotePatchRequest(
            performed_by="reviewer_a",
            evaluation_id=eval_result["eval_id"],
            source_run_id=sample_run_data["runId"],
            source_case_id=case.case_id,
            risk_boundary="Only affects orchestrator gate",
        ),
    )

    assert version.source_patch_id == patch.patch_id
    assert version.source_evaluation_id == eval_result["eval_id"]
    assert version.source_run_id == sample_run_data["runId"]
    assert version.source_case_id == case.case_id
    assert version.status == "active"
    assert version.approval_record["reviewer"] == "reviewer_a"
    assert version.approval_record["evidence_refs"][0]["source_type"] == "evaluation"


@pytest.mark.asyncio
async def test_promote_derives_source_run_from_patch_source_case(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )
    patch = await patch_store.create_patch(
        title="Promotion derives canonical run",
        reason="Promotion should use the patch source case as canonical provenance",
        affected_modules=["orchestrator"],
        patch_content={"risk_note": "derive run id from source case"},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    version = await approve_patch_with_evaluation(
        patch.patch_id,
        PromotePatchRequest(
            performed_by="reviewer_canonical",
            evaluation_id=eval_result["eval_id"],
        ),
    )

    assert version.source_patch_id == patch.patch_id
    assert version.source_evaluation_id == eval_result["eval_id"]
    assert version.source_case_id == case.case_id
    assert version.source_run_id == sample_run_data["runId"]
    assert version.evidence_usage == "review_gate_only"
    assert version.simulation_only is True
    assert version.is_real_trade is False
    assert version.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_promote_rejects_source_case_override(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    canonical_case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        canonical_case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )
    other_run_data = {
        **sample_run_data,
        "runId": "RUN_M6_OTHER",
        "auditId": "AUD_M6_OTHER",
        "stockCode": "600002.SH",
    }
    other_case = await case_store.create_case(other_run_data)
    await case_store.update_case_review(
        other_case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )
    patch = await patch_store.create_patch(
        title="Promotion rejects case override",
        reason="Promotion must not let request payload override patch provenance",
        affected_modules=["risk"],
        patch_content={"risk_note": "case source is canonical"},
        source_case_id=canonical_case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    with pytest.raises(HTTPException) as exc_info:
        await approve_patch_with_evaluation(
            patch.patch_id,
            PromotePatchRequest(
                performed_by="reviewer_override",
                evaluation_id=eval_result["eval_id"],
                source_case_id=other_case.case_id,
            ),
        )

    assert exc_info.value.status_code == 400
    assert "source_case_id" in exc_info.value.detail
    assert "patch source_case_id" in exc_info.value.detail


@pytest.mark.asyncio
async def test_promote_rejects_source_run_override(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )
    patch = await patch_store.create_patch(
        title="Promotion rejects run override",
        reason="Promotion run source must match canonical source case",
        affected_modules=["risk"],
        patch_content={"risk_note": "run source is canonical"},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    with pytest.raises(HTTPException) as exc_info:
        await approve_patch_with_evaluation(
            patch.patch_id,
            PromotePatchRequest(
                performed_by="reviewer_override",
                evaluation_id=eval_result["eval_id"],
                source_run_id="RUN_M6_WRONG",
            ),
        )

    assert exc_info.value.status_code == 400
    assert "source_run_id" in exc_info.value.detail
    assert "source case run_id" in exc_info.value.detail


@pytest.mark.asyncio
async def test_promote_merges_validated_evidence_refs_when_approval_record_is_empty(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )
    patch = await patch_store.create_patch(
        title="Promotion evidence merge patch",
        reason="Testing evidence ref merge",
        affected_modules=["risk"],
        patch_content={"risk_note": "merge evidence refs"},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    version = await approve_patch_with_evaluation(
        patch.patch_id,
        PromotePatchRequest(
            performed_by="reviewer_b",
            evaluation_id=eval_result["eval_id"],
            approval_record={"evidence_refs": []},
        ),
    )

    evidence_refs = version.approval_record["evidence_refs"]
    assert evidence_refs
    assert evidence_refs[0]["source_type"] == "evaluation"
    assert evidence_refs[0]["source_id"] == eval_result["eval_id"]


@pytest.mark.asyncio
async def test_promote_discards_unvalidated_approval_record_evidence_refs(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": True},
    )
    patch = await patch_store.create_patch(
        title="Promotion evidence ref pollution patch",
        reason="Testing promotion evidence refs cannot be supplied by request payload",
        affected_modules=["risk"],
        patch_content={"risk_note": "only validated refs can enter the approval record"},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    version = await approve_patch_with_evaluation(
        patch.patch_id,
        PromotePatchRequest(
            performed_by="reviewer_refs",
            evaluation_id=eval_result["eval_id"],
            approval_record={
                "reviewer": "reviewer_refs",
                "decision": "PROMOTE_AFTER_EVALUATION",
                "evidence_refs": [
                    {
                        "source_type": "primary_evidence",
                        "source_id": "RUN_FORGED_STRONG_001",
                        "summary": "forged strong evidence should not be retained",
                    },
                ],
            },
        ),
    )

    evidence_refs = version.approval_record["evidence_refs"]
    assert evidence_refs == [
        {
            "source_type": "evaluation",
            "source_id": eval_result["eval_id"],
            "summary": eval_result["summary"],
            "metrics": {
                "pass_rate": eval_result["pass_rate"],
                "improvement_rate": eval_result["improvement_rate"],
                "regressed_cases": eval_result["regressed_cases"],
            },
        }
    ]
    assert version.approval_record["decision"] == "PROMOTE_AFTER_EVALUATION"
    assert version.evidence_usage == "review_gate_only"
    assert version.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_promote_rejects_regressed_evaluation_evidence(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {
            "review_status": "REVIEWED",
            "conclusion_correct": False,
            "optimism_bias": "SEVERE",
            "tags": ["CONCLUSION_INCORRECT"],
        },
    )
    patch = await patch_store.create_patch(
        title="Regressed promotion patch",
        reason="Promotion gate must block regressed evaluation evidence",
        affected_modules=["risk_firewall"],
        patch_content={"regression_tags": ["CONCLUSION_INCORRECT"]},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    assert eval_result["regressed_cases"] >= 1

    with pytest.raises(HTTPException) as exc_info:
        await approve_patch_with_evaluation(
            patch.patch_id,
            PromotePatchRequest(
                performed_by="reviewer_c",
                evaluation_id=eval_result["eval_id"],
                source_case_id=case.case_id,
            ),
        )

    assert exc_info.value.status_code == 400
    assert "regressed case" in exc_info.value.detail
    assert "regression waiver" in exc_info.value.detail


@pytest.mark.asyncio
async def test_promote_rejects_incomplete_regression_waiver(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {
            "review_status": "REVIEWED",
            "conclusion_correct": False,
            "optimism_bias": "SEVERE",
            "tags": ["CONCLUSION_INCORRECT"],
        },
    )
    patch = await patch_store.create_patch(
        title="Incomplete waiver patch",
        reason="Promotion gate must reject incomplete regression waivers",
        affected_modules=["risk_firewall"],
        patch_content={"regression_tags": ["CONCLUSION_INCORRECT"]},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)

    with pytest.raises(HTTPException) as exc_info:
        await approve_patch_with_evaluation(
            patch.patch_id,
            PromotePatchRequest(
                performed_by="reviewer_d",
                evaluation_id=eval_result["eval_id"],
                source_case_id=case.case_id,
                allow_regression_override=True,
                regression_override_reason="too short",
                regression_override_approval_id="WAIVER_INCOMPLETE",
                regression_override_approver_role="researcher",
            ),
        )

    assert exc_info.value.status_code == 400
    assert "approver_role=admin" in exc_info.value.detail


@pytest.mark.asyncio
async def test_promote_regressed_evaluation_with_audited_waiver_records_governance(
    case_store,
    patch_store,
    eval_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {
            "review_status": "REVIEWED",
            "conclusion_correct": False,
            "optimism_bias": "SEVERE",
            "tags": ["CONCLUSION_INCORRECT"],
        },
    )
    patch = await patch_store.create_patch(
        title="Audited waiver patch",
        reason="Promotion gate allows only audited regression waivers",
        affected_modules=["risk_firewall"],
        patch_content={"regression_tags": ["CONCLUSION_INCORRECT"]},
        source_case_id=case.case_id,
    )
    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)
    assert eval_result["regressed_cases"] >= 1

    version = await approve_patch_with_evaluation(
        patch.patch_id,
        PromotePatchRequest(
            performed_by="risk_admin",
            evaluation_id=eval_result["eval_id"],
            source_case_id=case.case_id,
            risk_boundary="Research sandbox waiver only; manual review remains required.",
            allow_regression_override=True,
            regression_override_reason="Approved for bounded research sandbox validation after documented regression review.",
            regression_override_approval_id="WAIVER-20260601-001",
            regression_override_approver_role="admin",
        ),
    )

    waiver = version.approval_record["regression_waiver"]
    assert waiver["policy_id"] == "knowledge_promotion_regression_waiver_v1"
    assert waiver["status"] == "APPROVED"
    assert waiver["approval_id"] == "WAIVER-20260601-001"
    assert waiver["evaluation_id"] == eval_result["eval_id"]
    assert waiver["regressed_cases"] == eval_result["regressed_cases"]
    evidence_refs = version.approval_record["evidence_refs"]
    assert any(ref["source_type"] == "evaluation" for ref in evidence_refs)
    waiver_refs = [ref for ref in evidence_refs if ref["source_type"] == "regression_waiver"]
    assert waiver_refs
    assert waiver_refs[0]["source_id"] == "WAIVER-20260601-001"


@pytest.mark.asyncio
async def test_version_governance_metadata_and_rollback(ver_store):
    version = await ver_store.create_version(
        description="Governed review version",
        source_run_id="RUN_GOV_001",
        source_case_id="CASE_GOV_001",
        source_patch_id="PATCH_GOV_001",
        source_evaluation_id="EVAL_GOV_001",
        source_verdict_id="VERDICT_GOV_001",
        scope="risk_rule",
        risk_boundary="Only applies to risk_rule module",
        approval_record={"reviewer": "lead", "decision": "review"},
        rollback_impact={"expected": "restore prior risk rule"},
        status="review",
    )

    assert version["source_run_id"] == "RUN_GOV_001"
    assert version["source_case_id"] == "CASE_GOV_001"
    assert version["source_patch_id"] == "PATCH_GOV_001"
    assert version["source_evaluation_id"] == "EVAL_GOV_001"
    assert version["source_verdict_id"] == "VERDICT_GOV_001"
    assert version["scope"] == "risk_rule"
    assert version["risk_boundary"] == "Only applies to risk_rule module"
    assert version["approval_record"]["decision"] == "review"
    assert version["rollback_impact"]["expected"] == "restore prior risk rule"
    assert version["status"] == "review"
    assert version["evidence_usage"] == "review_gate_only"
    assert version["evidence_strength"] in {"LOW", "MEDIUM"}
    assert version["simulation_only"] is True
    assert version["is_real_trade"] is False
    assert version["strong_conclusion_allowed"] is False

    rollback = await ver_store.rollback_to(version["version_id"], "rollback_user")
    rolled = rollback["new_version"]
    assert rolled["status"] == "rolled_back"
    assert rolled["rollback_impact"]["target_version_id"] == version["version_id"]
    assert rolled["approval_record"]["action"] == "ROLLBACK"
    assert rolled["approval_record"]["performed_by"] == "rollback_user"
    assert rolled["evidence_usage"] == "review_gate_only"
    assert rolled["evidence_strength"] in {"LOW", "MEDIUM"}
    assert rolled["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_full_m6_workflow(case_store, patch_store, eval_store, ver_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {"review_status": "REVIEWED", "conclusion_correct": False}
    )

    patch = await patch_store.create_patch(
        title="M6 workflow patch",
        reason="Testing full M6 workflow",
        affected_modules=["orchestrator"],
        patch_content={"tag_fix": "FALSE"},
    )

    eval_result = await eval_store.run_evaluation(patch.patch_id, force=True)
    assert eval_result["status"] == "COMPLETED"

    await patch_store.review_patch(patch.patch_id, "APPROVE", "human")

    version = await ver_store.create_version(
        description="Approved after evaluation",
        source_patch_id=patch.patch_id,
    )
    assert version["source_patch_id"] == patch.patch_id
    assert len(version["active_patches"]) >= 1

    diff = await ver_store.diff_versions(
        version["version_id"],
        version["version_id"],
    )
    assert diff["patch_count_diff"] == 0


@pytest.mark.asyncio
async def test_knowledge_version_runs_post_publish_regression(
    case_store,
    patch_store,
    ver_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {
            "review_status": "REVIEWED",
            "conclusion_correct": False,
            "optimism_bias": "SEVERE",
        },
    )
    patch = await patch_store.create_patch(
        title="Post publish regression patch",
        reason="Testing version regression report",
        affected_modules=["risk_firewall"],
        patch_content={"rule_change": "strict_optimism_check"},
    )
    await patch_store.review_patch(patch.patch_id, "APPROVE", "human")

    version = await ver_store.create_version(
        description="Active version with auto regression",
        source_patch_id=patch.patch_id,
        status="active",
    )

    report = version["post_publish_regression"]
    assert report["status"] in {"PASS", "REVIEW"}
    assert report["evidence_usage"] == "review_gate_only"
    assert report["evidence_strength"] == "LOW"
    assert report["simulation_only"] is True
    assert report["is_real_trade"] is False
    assert report["strong_conclusion_allowed"] is False
    assert report["active_patch_count"] >= 1
    assert report["representative_case_count"] >= 1
    impact = report["knowledge_impact"]
    assert impact["policy_id"] == "knowledge_post_publish_impact_summary_v1"
    assert impact["mode"] == "OBSERVATION_ONLY"
    assert impact["auto_blocks_promotion"] is False
    assert impact["source_status"] == report["status"]
    assert impact["risk_level"] in {"MEDIUM", "LOW"}
    assert impact["requires_human_review"] is (impact["risk_level"] in {"HIGH", "MEDIUM"})
    assert impact["affected_module_count"] == len(report["affected_modules"])
    assert impact["net_improvement_cases"] == report["improved_cases"] - report["regressed_cases"]
    assert report["case_set_quality"]["reviewed_case_count"] >= 1
    assert "low_representative_case_count" in report["quality_warnings"]
    assert report["case_set_quality_policy"]["policy_id"] == "knowledge_regression_case_set_quality_v1"
    assert report["case_set_quality_policy"]["mode"] == "WARN_ONLY"
    assert report["case_set_quality_policy"]["action"] == "WARN_ONLY"
    assert report["case_set_quality_policy"]["blocking"] is False
    assert report["case_set_quality_policy"]["override_required"] is False
    remediation = report["case_set_quality_policy"]["remediation"]
    assert remediation["status"] == "ACTION_REQUIRED"
    assert remediation["owner"] == "case_library_reviewer"
    assert "add_reviewed_cases" in remediation["required_actions"]
    assert remediation["required_reviewed_case_delta"] >= 1
    assert remediation["target_case_mix"]["requires_failure_or_boundary_case"] is True
    assert any("representative case" in action for action in remediation["next_actions"])
    assert report["improvement_rate"] > 0
    assert "risk_firewall" in report["affected_modules"]
    assert version["snapshot"]["post_publish_regression"]["report_id"] == report["report_id"]
    assert version["snapshot"]["post_publish_regression"]["evidence_usage"] == "review_gate_only"
    assert version["snapshot"]["post_publish_regression"]["simulation_only"] is True
    assert version["snapshot"]["post_publish_regression"]["is_real_trade"] is False
    assert version["snapshot"]["post_publish_regression"]["strong_conclusion_allowed"] is False
    assert version["patch_delta"]["governance"]["post_publish_regression"]["report_id"] == report["report_id"]
    assert version["patch_delta"]["governance"]["post_publish_regression"]["evidence_usage"] == "review_gate_only"
    assert version["patch_delta"]["governance"]["post_publish_regression"]["evidence_strength"] == "LOW"
    assert version["patch_delta"]["governance"]["post_publish_regression"]["simulation_only"] is True
    assert version["patch_delta"]["governance"]["post_publish_regression"]["is_real_trade"] is False
    assert version["patch_delta"]["governance"]["post_publish_regression"]["strong_conclusion_allowed"] is False
    assert version["patch_delta"]["governance"]["post_publish_regression"]["case_set_quality"]["status"] == "LOW_COVERAGE"
    assert version["patch_delta"]["governance"]["post_publish_regression"]["case_set_quality_policy"]["mode"] == "WARN_ONLY"
    assert version["evidence_usage"] == "review_gate_only"
    assert version["evidence_strength"] == "LOW"
    assert version["simulation_only"] is True
    assert version["is_real_trade"] is False
    assert version["strong_conclusion_allowed"] is False

    rerun = await ver_store.run_post_publish_regression(version["version_id"], performed_by="tester")
    assert rerun["post_publish_regression"]["trigger"] == "manual_rerun"
    assert rerun["post_publish_regression"]["performed_by"] == "tester"
    assert rerun["post_publish_regression"]["evidence_usage"] == "review_gate_only"
    assert rerun["post_publish_regression"]["evidence_strength"] == "LOW"
    assert rerun["post_publish_regression"]["simulation_only"] is True
    assert rerun["post_publish_regression"]["is_real_trade"] is False
    assert rerun["post_publish_regression"]["strong_conclusion_allowed"] is False
    assert rerun["evidence_strength"] == "LOW"
    assert rerun["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_knowledge_version_sanitizes_legacy_regression_boundary_on_read(ver_store):
    version = await ver_store.create_version(
        description="Legacy regression boundary",
        status="active",
    )
    legacy_report = {
        "report_id": "REG_LEGACY_BOUNDARY",
        "status": "PASS",
        "evidence_usage": "primary_evidence",
        "evidence_strength": "HIGH",
        "simulation_only": False,
        "is_real_trade": True,
        "strong_conclusion_allowed": True,
        "knowledge_impact": {"risk_level": "LOW", "status": "IMPROVING"},
    }

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(KnowledgeVersionDB).where(KnowledgeVersionDB.version_id == version["version_id"])
        )
        record = result.scalar_one()
        snapshot = dict(record.snapshot or {})
        patch_delta = dict(record.patch_delta or {})
        snapshot_governance = dict(snapshot.get("governance") or {})
        patch_delta_governance = dict(patch_delta.get("governance") or {})
        snapshot["post_publish_regression"] = legacy_report
        patch_delta["post_publish_regression"] = legacy_report
        snapshot_governance["post_publish_regression"] = legacy_report
        patch_delta_governance["post_publish_regression"] = legacy_report
        snapshot["governance"] = snapshot_governance
        patch_delta["governance"] = patch_delta_governance
        record.snapshot = snapshot
        record.patch_delta = patch_delta
        await db.commit()

    sanitized = await ver_store.get_version(version["version_id"])
    assert sanitized is not None
    report = sanitized["post_publish_regression"]
    assert report["evidence_usage"] == "review_gate_only"
    assert report["evidence_strength"] == "MEDIUM"
    assert report["simulation_only"] is True
    assert report["is_real_trade"] is False
    assert report["strong_conclusion_allowed"] is False
    assert sanitized["snapshot"]["post_publish_regression"]["evidence_usage"] == "review_gate_only"
    assert sanitized["snapshot"]["post_publish_regression"]["evidence_strength"] == "MEDIUM"
    assert sanitized["snapshot"]["post_publish_regression"]["simulation_only"] is True
    assert sanitized["snapshot"]["post_publish_regression"]["is_real_trade"] is False
    assert sanitized["patch_delta"]["governance"]["post_publish_regression"]["evidence_usage"] == "review_gate_only"
    assert sanitized["patch_delta"]["governance"]["post_publish_regression"]["evidence_strength"] == "MEDIUM"
    assert sanitized["patch_delta"]["governance"]["post_publish_regression"]["simulation_only"] is True
    assert sanitized["patch_delta"]["governance"]["post_publish_regression"]["is_real_trade"] is False
    assert sanitized["evidence_usage"] == "review_gate_only"
    assert sanitized["evidence_strength"] == "LOW"
    assert sanitized["simulation_only"] is True
    assert sanitized["is_real_trade"] is False
    assert sanitized["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_knowledge_version_sanitizes_legacy_approval_refs_on_read(ver_store):
    version = await ver_store.create_version(
        description="Legacy approval refs",
        status="draft",
    )
    legacy_refs = [
        {
            "source_type": "primary_evidence",
            "source_id": "RUN_FORGED_STRONG_001",
            "summary": "forged strong run evidence",
        },
        {
            "source_type": "case",
            "source_id": "CASE_FORGED_STRONG_001",
            "summary": "case metadata is not approval evidence",
        },
        {
            "source_type": "Evaluation",
            "source_id": "EVAL_LEGACY_APPROVAL_001",
            "summary": "legacy evaluation approval evidence",
            "evidence_usage": "primary_evidence",
            "evidence_strength": "HIGH",
            "simulation_only": False,
            "is_real_trade": True,
            "strong_conclusion_allowed": True,
        },
        {
            "source_type": "evaluation",
            "source_id": "EVAL_LEGACY_APPROVAL_001",
            "summary": "duplicate evaluation evidence",
        },
    ]

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(KnowledgeVersionDB).where(KnowledgeVersionDB.version_id == version["version_id"])
        )
        record = result.scalar_one()
        snapshot = dict(record.snapshot or {})
        patch_delta = dict(record.patch_delta or {})
        snapshot_governance = dict(snapshot.get("governance") or {})
        patch_delta_governance = dict(patch_delta.get("governance") or {})
        snapshot_approval = dict(snapshot_governance.get("approval_record") or {})
        patch_delta_approval = dict(patch_delta_governance.get("approval_record") or {})
        snapshot_approval["evidence_refs"] = legacy_refs
        patch_delta_approval["evidence_refs"] = legacy_refs
        snapshot_governance["approval_record"] = snapshot_approval
        patch_delta_governance["approval_record"] = patch_delta_approval
        snapshot["governance"] = snapshot_governance
        patch_delta["governance"] = patch_delta_governance
        record.snapshot = snapshot
        record.patch_delta = patch_delta
        await db.commit()

    sanitized = await ver_store.get_version(version["version_id"])
    assert sanitized is not None
    refs = sanitized["approval_record"]["evidence_refs"]
    assert len(refs) == 1
    assert refs[0]["source_type"] == "evaluation"
    assert refs[0]["source_id"] == "EVAL_LEGACY_APPROVAL_001"
    assert refs[0]["evidence_usage"] == "review_gate_only"
    assert refs[0]["evidence_strength"] == "MEDIUM"
    assert refs[0]["simulation_only"] is True
    assert refs[0]["is_real_trade"] is False
    assert refs[0]["strong_conclusion_allowed"] is False
    assert sanitized["snapshot"]["governance"]["approval_record"]["evidence_refs"] == refs
    assert sanitized["patch_delta"]["governance"]["approval_record"]["evidence_refs"] == refs
    assert sanitized["evidence_strength"] == "PENDING"
    assert sanitized["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_knowledge_version_source_context_alone_does_not_upgrade_strength(ver_store):
    version = await ver_store.create_version(
        description="Legacy source context only",
        source_run_id="RUN_SOURCE_ONLY_001",
        source_case_id="CASE_SOURCE_ONLY_001",
        status="active",
    )
    legacy_pass_report = {
        "report_id": "REG_SOURCE_ONLY_PASS",
        "status": "PASS",
        "knowledge_impact": {"risk_level": "LOW", "status": "STABLE"},
        "case_set_quality_policy": {"blocking": False},
        "quality_warnings": [],
    }

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(KnowledgeVersionDB).where(KnowledgeVersionDB.version_id == version["version_id"])
        )
        record = result.scalar_one()
        snapshot = dict(record.snapshot or {})
        patch_delta = dict(record.patch_delta or {})
        snapshot_governance = dict(snapshot.get("governance") or {})
        patch_delta_governance = dict(patch_delta.get("governance") or {})
        snapshot["post_publish_regression"] = legacy_pass_report
        patch_delta["post_publish_regression"] = legacy_pass_report
        snapshot_governance["post_publish_regression"] = legacy_pass_report
        patch_delta_governance["post_publish_regression"] = legacy_pass_report
        snapshot["governance"] = snapshot_governance
        patch_delta["governance"] = patch_delta_governance
        record.snapshot = snapshot
        record.patch_delta = patch_delta
        await db.commit()

    sanitized = await ver_store.get_version(version["version_id"])
    assert sanitized is not None
    assert sanitized["source_run_id"] == "RUN_SOURCE_ONLY_001"
    assert sanitized["source_case_id"] == "CASE_SOURCE_ONLY_001"
    assert sanitized["post_publish_regression"]["status"] == "PASS"
    assert sanitized["evidence_usage"] == "review_gate_only"
    assert sanitized["evidence_strength"] == "LOW"
    assert sanitized["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_post_publish_regression_detects_regressed_cases(
    case_store,
    patch_store,
    ver_store,
    sample_run_data,
):
    case = await case_store.create_case(sample_run_data)
    await case_store.update_case_review(
        case.case_id,
        {
            "review_status": "REVIEWED",
            "conclusion_correct": False,
            "optimism_bias": "SEVERE",
            "tags": ["CONCLUSION_INCORRECT"],
        },
    )
    patch = await patch_store.create_patch(
        title="Loosen optimism guardrail",
        reason="Regression detection should catch weakened controls",
        affected_modules=["risk_firewall"],
        patch_content={"rule_change": "loosen_optimism_check"},
    )
    await patch_store.review_patch(patch.patch_id, "APPROVE", "human")

    version = await ver_store.create_version(
        description="Active version with regression risk",
        source_patch_id=patch.patch_id,
        status="active",
    )

    report = version["post_publish_regression"]
    assert report["status"] == "REGRESSION"
    assert report["evidence_usage"] == "review_gate_only"
    assert report["evidence_strength"] == "LOW"
    assert report["simulation_only"] is True
    assert report["is_real_trade"] is False
    assert report["strong_conclusion_allowed"] is False
    assert report["regressed_cases"] >= 1
    assert report["regression_rate"] > 0
    assert report["knowledge_impact"]["status"] == "REGRESSION_ATTENTION"
    assert report["knowledge_impact"]["risk_level"] == "HIGH"
    assert report["knowledge_impact"]["action"] == "review_regressions_before_policy_trust"
    assert report["knowledge_impact"]["requires_human_review"] is True
    assert report["knowledge_impact"]["top_affected_modules"] == report["affected_modules"][:5]
    assert report["per_patch"][0]["regressed_cases"] >= 1
    assert version["evidence_usage"] == "review_gate_only"
    assert version["evidence_strength"] == "LOW"
    assert version["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_draft_version_has_no_post_publish_regression_and_cannot_rerun(ver_store):
    draft = await ver_store.create_version(
        description="Draft should not run post-publish regression",
        status="draft",
    )

    assert draft["post_publish_regression"] is None
    assert draft["evidence_usage"] == "review_gate_only"
    assert draft["evidence_strength"] == "PENDING"
    assert draft["simulation_only"] is True
    assert draft["is_real_trade"] is False
    assert draft["strong_conclusion_allowed"] is False

    with pytest.raises(ValueError, match="Draft versions cannot run post-publish regression"):
        await ver_store.run_post_publish_regression(draft["version_id"], performed_by="tester")
