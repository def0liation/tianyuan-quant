import pytest
import asyncio
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.case_library_store import (
    CaseLibraryStore,
    ReviewTagStore,
    ErrorLedgerStore,
    KnowledgePatchStore,
)
from app.api import routes_analysis, routes_case_library
from app.db.session import AsyncSessionLocal
from app.db.models_case_library import CaseLibraryDB, ReviewTagDB, ErrorLedgerEntryDB, KnowledgePatchDB
from app.models.case_library import CreateErrorEntryRequest, CreateKnowledgePatchRequest


@pytest.fixture
def sample_run_data():
    return {
        "runId": "RUN_20240101_120000_abc123",
        "auditId": "AUD_RUN_20240101_120000_abc123",
        "stockCode": "000001.SZ",
        "stockName": "平安银行",
        "taskType": "POSITION_REVIEW",
        "runMode": "STANDARD_MODE",
        "finalAction": "HOLD",
    }


@pytest.fixture
def case_store():
    return CaseLibraryStore()


@pytest.fixture
def tag_store():
    return ReviewTagStore()


@pytest.fixture
def error_store():
    return ErrorLedgerStore()


@pytest.fixture
def patch_store():
    return KnowledgePatchStore()


@pytest.mark.asyncio
async def test_create_case(case_store, sample_run_data):
    case = await case_store.create_case(sample_run_data, reviewer="test_user")
    assert case.case_id.startswith("CASE_")
    assert case.symbol == "000001.SZ"
    assert case.review_status == "PENDING"
    assert case.reviewer == "test_user"


@pytest.mark.asyncio
async def test_list_and_get_case(case_store, sample_run_data):
    await case_store.create_case(sample_run_data, reviewer="test_user")

    cases = await case_store.list_cases(symbol="000001.SZ")
    assert len(cases) >= 1
    assert cases[0]["symbol"] == "000001.SZ"
    assert cases[0]["evidence_usage"] == "supporting_only"
    assert cases[0]["evidence_strength"] == "PENDING"
    assert cases[0]["simulation_only"] is True
    assert cases[0]["is_real_trade"] is False
    assert cases[0]["strong_conclusion_allowed"] is False

    case_id = cases[0]["case_id"]
    case = await case_store.get_case(case_id)
    assert case is not None
    assert case["case_id"] == case_id
    assert case["evidence_usage"] == "supporting_only"
    assert case["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_update_case_review(case_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    case_id = case.case_id

    updated = await case_store.update_case_review(
        case_id,
        {
            "conclusion_correct": True,
            "final_action_correct": True,
            "data_sufficiency": "ADEQUATE",
            "optimism_bias": "SLIGHT",
            "key_lessons": ["lesson1", "lesson2"],
            "review_note": "reviewed with sufficient simulation evidence",
            "review_status": "REVIEWED",
            "reviewer": "human_reviewer",
        }
    )
    assert updated is not None
    assert updated["conclusion_correct"] is True
    assert updated["data_sufficiency"] == "ADEQUATE"
    assert updated["optimism_bias"] == "SLIGHT"
    assert updated["review_status"] == "REVIEWED"
    assert updated["reviewer"] == "human_reviewer"
    assert len(updated["key_lessons"]) == 2
    assert updated["evidence_usage"] == "supporting_only"
    assert updated["evidence_strength"] == "MEDIUM"
    assert updated["simulation_only"] is True
    assert updated["is_real_trade"] is False
    assert updated["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_case_summary(case_store, sample_run_data):
    await case_store.create_case(sample_run_data)
    summary = await case_store.get_summary()
    assert summary["total"] >= 1
    assert "pending" in summary
    assert "reviewed" in summary
    assert "accuracy_rate" in summary


@pytest.mark.asyncio
async def test_create_review_tag(tag_store, case_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    case_id = case.case_id
    run_id = case.run_id

    tag = await tag_store.create_tag(
        case_id=case_id,
        run_id=run_id,
        tag_data={
            "tag_type": "CONCLUSION_CORRECT",
            "tag_value": "TRUE",
            "severity": "LOW",
            "description": "结论正确",
            "node": "final_writer",
        }
    )
    assert tag.tag_id.startswith("TAG_")
    assert tag.tag_type == "CONCLUSION_CORRECT"


@pytest.mark.asyncio
async def test_list_review_tags(tag_store, case_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    await tag_store.create_tag(
        case_id=case.case_id,
        run_id=case.run_id,
        tag_data={"tag_type": "TEST_TAG", "tag_value": "VALUE1"}
    )

    tags = await tag_store.list_tags(case_id=case.case_id)
    assert len(tags) >= 1
    assert tags[0]["case_id"] == case.case_id


@pytest.mark.asyncio
async def test_tag_summary(tag_store, case_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    await tag_store.create_tag(
        case_id=case.case_id,
        run_id=case.run_id,
        tag_data={"tag_type": "TEST_TAG", "tag_value": "VALUE1", "severity": "HIGH"}
    )

    summary = await tag_store.get_tag_summary()
    assert summary["total"] >= 1
    assert "by_type" in summary
    assert "by_severity" in summary


@pytest.mark.asyncio
async def test_create_error_entry(error_store, sample_run_data):
    entry = await error_store.create_entry(
        sample_run_data,
        error_data={
            "node": "dvg_gate",
            "error_type": "DATA_MISSING",
            "error_reason": "关键财务数据缺失",
            "repeated_count": 1,
            "patch_required": True,
        }
    )
    assert entry.entry_id.startswith("ERR_")
    assert entry.error_type == "DATA_MISSING"
    assert entry.status == "OPEN"
    saved = await error_store.get_entry(entry.entry_id)
    assert saved is not None
    assert saved["evidence_usage"] == "review_gate_only"
    assert saved["evidence_strength"] == "LOW"
    assert saved["simulation_only"] is True
    assert saved["is_real_trade"] is False
    assert saved["strong_conclusion_allowed"] is False
    assert saved["reported_simulation_only"] is None
    assert saved["reported_is_real_trade"] is None


@pytest.mark.asyncio
async def test_error_entry_caps_polluted_simulation_attribution(error_store, sample_run_data):
    entry = await error_store.create_entry(
        sample_run_data,
        error_data={
            "node": "research_lab",
            "error_type": "BOUNDARY_POLLUTION",
            "error_reason": "legacy payload carried live-trade flags",
            "attribution": {
                "simulation_only": False,
                "is_real_trade": True,
            },
        }
    )

    saved = await error_store.get_entry(entry.entry_id)
    assert saved is not None
    assert saved["attribution"]["simulation_only"] is False
    assert saved["attribution"]["is_real_trade"] is True
    assert saved["evidence_usage"] == "review_gate_only"
    assert saved["evidence_strength"] == "LOW"
    assert saved["simulation_only"] is True
    assert saved["is_real_trade"] is False
    assert saved["strong_conclusion_allowed"] is False
    assert saved["reported_simulation_only"] is False
    assert saved["reported_is_real_trade"] is True


@pytest.mark.asyncio
async def test_error_ledger_route_exposes_review_gate_boundary_fields(
    error_store, monkeypatch, sample_run_data
):
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {sample_run_data["runId"]: sample_run_data},
    )

    response = await routes_case_library.create_error_entry(
        CreateErrorEntryRequest(
            node="research_lab",
            error_type="BOUNDARY_POLLUTION",
            error_reason="legacy payload carried live-trade flags",
            attribution={
                "run_id": f" {sample_run_data['runId']} ",
                "simulation_only": False,
                "is_real_trade": True,
            },
        )
    )

    try:
        assert response.run_id == sample_run_data["runId"]
        assert response.audit_id == sample_run_data["auditId"]
        assert response.attribution["run_id"] == sample_run_data["runId"]
        assert response.evidence_usage == "review_gate_only"
        assert response.evidence_strength == "LOW"
        assert response.simulation_only is True
        assert response.is_real_trade is False
        assert response.strong_conclusion_allowed is False
        assert response.reported_simulation_only is False
        assert response.reported_is_real_trade is True
    finally:
        await error_store.delete_entry(response.entry_id)


@pytest.mark.asyncio
async def test_error_ledger_route_rejects_missing_run_id():
    with pytest.raises(HTTPException) as exc_info:
        await routes_case_library.create_error_entry(
            CreateErrorEntryRequest(
                node="research_lab",
                error_type="BOUNDARY_POLLUTION",
                error_reason="missing run provenance",
                attribution={},
            )
        )

    assert exc_info.value.status_code == 400
    assert "attribution.run_id" in exc_info.value.detail


@pytest.mark.asyncio
async def test_error_ledger_route_rejects_unknown_and_legacy_runs(
    monkeypatch, sample_run_data
):
    monkeypatch.setattr(routes_analysis, "runs_store", {})

    with pytest.raises(HTTPException) as unknown_exc:
        await routes_case_library.create_error_entry(
            CreateErrorEntryRequest(
                node="research_lab",
                error_type="BOUNDARY_POLLUTION",
                error_reason="unknown run provenance",
                attribution={"run_id": "RUN_FORGED_001"},
            )
        )

    assert unknown_exc.value.status_code == 404

    legacy_run = {
        **sample_run_data,
        "runId": "RUN_MOCK_FORGED_001",
        "auditId": "AUD_RUN_MOCK_FORGED_001",
    }
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {legacy_run["runId"]: legacy_run},
    )

    with pytest.raises(HTTPException) as legacy_exc:
        await routes_case_library.create_error_entry(
            CreateErrorEntryRequest(
                node="research_lab",
                error_type="BOUNDARY_POLLUTION",
                error_reason="legacy run provenance",
                attribution={"run_id": legacy_run["runId"]},
            )
        )

    assert legacy_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_error_entries(error_store, sample_run_data):
    await error_store.create_entry(
        sample_run_data,
        error_data={"error_type": "TEST_ERROR", "error_reason": "test"}
    )

    entries = await error_store.list_entries()
    assert len(entries) >= 1


@pytest.mark.asyncio
async def test_update_error_entry(error_store, sample_run_data):
    entry = await error_store.create_entry(
        sample_run_data,
        error_data={"error_type": "TEST_ERROR", "error_reason": "test"}
    )

    updated = await error_store.update_entry(
        entry.entry_id,
        {"status": "RESOLVED", "patch_candidate_id": "PATCH_001"}
    )
    assert updated is not None
    assert updated["status"] == "RESOLVED"
    assert updated["evidence_usage"] == "review_gate_only"
    assert updated["evidence_strength"] == "LOW"
    assert updated["simulation_only"] is True
    assert updated["is_real_trade"] is False
    assert updated["strong_conclusion_allowed"] is False
    assert updated["resolved_at"] is not None
    assert updated["patch_candidate_id"] == "PATCH_001"


@pytest.mark.asyncio
async def test_error_summary(error_store, sample_run_data):
    await error_store.create_entry(
        sample_run_data,
        error_data={"error_type": "TEST_ERROR", "error_reason": "test"}
    )
    summary = await error_store.get_summary()
    assert summary["total"] >= 1
    assert "open" in summary
    assert "by_type" in summary
    assert "by_node" in summary


@pytest.mark.asyncio
async def test_create_knowledge_patch(patch_store):
    patch = await patch_store.create_patch(
        title="修复 DVG 数据缺失处理",
        reason="当核心财务数据缺失时，DVG Gate 未正确降级",
        affected_modules=["dvg_gate", "data_reliability_engine"],
        patch_content={
            "risk_note": "可能影响数据覆盖率",
            "rollback_plan": "恢复默认配置",
            "backtest_required": True,
        },
        source_error_id="ERR_001",
    )
    assert patch.patch_id.startswith("PATCH_")
    assert patch.approval_status == "CANDIDATE"
    assert patch.backtest_required is True
    saved = await patch_store.get_patch(patch.patch_id)
    assert saved is not None
    assert saved["evidence_usage"] == "review_gate_only"
    assert saved["evidence_strength"] == "PENDING"
    assert saved["simulation_only"] is True
    assert saved["is_real_trade"] is False
    assert saved["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_knowledge_patch_route_uses_verified_source_records(
    case_store, error_store, patch_store, sample_run_data
):
    case = await case_store.create_case(sample_run_data)
    error = await error_store.create_entry(
        sample_run_data,
        error_data={
            "node": "research_lab",
            "error_type": "MODULE_FAILURE",
            "error_reason": "route verified source",
            "patch_required": True,
        },
    )

    response = await routes_case_library.create_knowledge_patch(
        CreateKnowledgePatchRequest(
            title="Verified source patch",
            reason="Only existing source ids can enter the patch ledger",
            affected_modules=["research_lab"],
            patch_content={"risk_note": "review gate only", "backtest_required": True},
            source_error_id=f" {error.entry_id} ",
            source_case_id=f" {case.case_id} ",
        )
    )

    try:
        assert response.source_error_id == error.entry_id
        assert response.source_case_id == case.case_id
        assert response.evidence_usage == "review_gate_only"
        assert response.evidence_strength == "PENDING"
        assert response.simulation_only is True
        assert response.is_real_trade is False
        assert response.strong_conclusion_allowed is False
    finally:
        await patch_store.delete_patch(response.patch_id)


@pytest.mark.asyncio
async def test_knowledge_patch_route_rejects_unknown_sources():
    with pytest.raises(HTTPException) as error_exc:
        await routes_case_library.create_knowledge_patch(
            CreateKnowledgePatchRequest(
                title="Forged source error patch",
                reason="forged error id must not enter the patch ledger",
                affected_modules=["research_lab"],
                patch_content={"risk_note": "review gate only"},
                source_error_id="ERR_FORGED_001",
            )
        )

    assert error_exc.value.status_code == 404
    assert "Source error entry" in error_exc.value.detail

    with pytest.raises(HTTPException) as case_exc:
        await routes_case_library.create_knowledge_patch(
            CreateKnowledgePatchRequest(
                title="Forged source case patch",
                reason="forged case id must not enter the patch ledger",
                affected_modules=["research_lab"],
                patch_content={"risk_note": "review gate only"},
                source_case_id="CASE_FORGED_001",
            )
        )

    assert case_exc.value.status_code == 404
    assert "Source case" in case_exc.value.detail


@pytest.mark.asyncio
async def test_knowledge_patch_route_rejects_cross_run_source_pair(
    case_store, error_store, sample_run_data
):
    case = await case_store.create_case(sample_run_data)
    other_run_data = {
        **sample_run_data,
        "runId": "RUN_ROUTE_PATCH_OTHER",
        "auditId": "AUD_ROUTE_PATCH_OTHER",
        "stockCode": "000002.SZ",
    }
    error = await error_store.create_entry(
        other_run_data,
        error_data={
            "node": "research_lab",
            "error_type": "MODULE_FAILURE",
            "error_reason": "cross run source",
            "patch_required": True,
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_case_library.create_knowledge_patch(
            CreateKnowledgePatchRequest(
                title="Cross run source patch",
                reason="case and error provenance must agree",
                affected_modules=["research_lab"],
                patch_content={"risk_note": "review gate only"},
                source_error_id=error.entry_id,
                source_case_id=case.case_id,
            )
        )

    assert exc_info.value.status_code == 400
    assert "same run" in exc_info.value.detail


@pytest.mark.asyncio
async def test_review_patch(patch_store):
    patch = await patch_store.create_patch(
        title="测试补丁",
        reason="测试",
        affected_modules=["test"],
        patch_content={},
    )

    reviewed = await patch_store.review_patch(
        patch.patch_id, action="APPROVE", reviewer="test_user"
    )
    assert reviewed is not None
    assert reviewed["approval_status"] == "APPROVED"
    assert reviewed["approved_by"] == "test_user"
    assert reviewed["approved_at"] is not None
    assert reviewed["evidence_usage"] == "review_gate_only"
    assert reviewed["evidence_strength"] == "PENDING"
    assert reviewed["simulation_only"] is True
    assert reviewed["is_real_trade"] is False
    assert reviewed["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_patch_backtest(patch_store):
    patch = await patch_store.create_patch(
        title="测试补丁",
        reason="测试",
        affected_modules=["test"],
        patch_content={},
    )

    updated = await patch_store.update_backtest_result(
        patch.patch_id,
        {"passed": True, "cases_tested": 10, "success_rate": 0.9}
    )
    assert updated is not None
    assert updated["backtest_result"]["passed"] is True
    assert updated["evidence_usage"] == "review_gate_only"
    assert updated["evidence_strength"] == "LOW"
    assert updated["simulation_only"] is True
    assert updated["is_real_trade"] is False
    assert updated["strong_conclusion_allowed"] is False

    reviewed = await patch_store.review_patch(
        patch.patch_id, action="APPROVE", reviewer="test_user"
    )
    assert reviewed is not None
    assert reviewed["evidence_strength"] == "MEDIUM"
    assert reviewed["strong_conclusion_allowed"] is False


@pytest.mark.asyncio
async def test_patch_summary(patch_store):
    await patch_store.create_patch(
        title="测试补丁",
        reason="测试",
        affected_modules=["test"],
        patch_content={},
    )
    summary = await patch_store.get_summary()
    assert summary["total"] >= 1
    assert "candidate" in summary
    assert "approved" in summary


@pytest.mark.asyncio
async def test_end_to_end_workflow(case_store, tag_store, error_store, patch_store, sample_run_data):
    case = await case_store.create_case(sample_run_data)
    case_id = case.case_id
    run_id = case.run_id

    tag = await tag_store.create_tag(
        case_id=case_id,
        run_id=run_id,
        tag_data={"tag_type": "CONCLUSION_INCORRECT", "tag_value": "FALSE", "severity": "HIGH"}
    )

    error = await error_store.create_entry(
        sample_run_data,
        error_data={
            "error_type": "MODULE_FAILURE",
            "error_reason": "模块处理异常",
            "patch_required": True,
        }
    )

    patch = await patch_store.create_patch(
        title="修复模块异常",
        reason="解决模块处理异常问题",
        affected_modules=["test_module"],
        patch_content={},
        source_error_id=error.entry_id,
        source_case_id=case_id,
    )

    await error_store.update_entry(
        error.entry_id,
        {"patch_candidate_id": patch.patch_id}
    )

    await case_store.update_case_review(
        case_id,
        {"review_status": "REVIEWED", "conclusion_correct": False}
    )

    final_case = await case_store.get_case(case_id)
    assert final_case["review_status"] == "REVIEWED"
    assert final_case["conclusion_correct"] is False
    assert final_case["evidence_usage"] == "supporting_only"
    assert final_case["evidence_strength"] == "LOW"
    assert final_case["strong_conclusion_allowed"] is False

    final_error = await error_store.list_entries()
    assert any(e["patch_candidate_id"] == patch.patch_id for e in final_error)
