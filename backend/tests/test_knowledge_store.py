import json

import pytest
from fastapi import HTTPException

from app.api import routes_analysis
from app.api import routes_knowledge
from app.core import knowledge_store
from app.models.knowledge import (
    ActiveKnowledgeContextItem,
    CreateKnowledgeItemRequest,
    GenerateKnowledgeFromRunRequest,
    ReviewKnowledgeItemRequest,
)


@pytest.fixture(autouse=True)
def temp_knowledge_store(monkeypatch, tmp_path):
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", tmp_path / "knowledge_iterations.json")


def sample_run(final_action: str = "BUY_CANDIDATE") -> dict:
    return {
        "runId": "RUN_TEST_001",
        "auditId": "AUD_RUN_TEST_001",
        "stockCode": "603663",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "dvg": {
            "status": "PASS",
            "dataReliability": "HIGH",
            "hallucinationRiskScore": 12,
            "criticalMissingData": [],
            "dataConflicts": [],
        },
        "qiam": {
            "finalBuySuitability": "FAVORABLE",
            "modelConfidenceFinal": 0.82,
            "downgradeReasons": [],
            "missingData": [],
        },
        "signalOps": {
            "signalStatus": "QUALIFIED",
            "blockedReason": "",
        },
        "killSwitch": {
            "active": False,
            "level": "NONE",
        },
        "execution": {
            "forbiddenActions": ["自动下单"],
        },
        "chipKb": {
            "coreMissingData": [],
        },
        "finalAction": final_action,
        "finalWriter": {
            "mode": "NORMAL",
            "finalAction": final_action,
        },
    }


def test_learning_candidate_from_run_is_idempotent_and_reviewable():
    first = knowledge_store.create_learning_candidate_from_run(sample_run())
    second = knowledge_store.create_learning_candidate_from_run(sample_run())
    summary = knowledge_store.get_knowledge_summary()

    assert first.item_id == second.item_id
    assert first.status == "PENDING_REVIEW"
    assert first.category == "POSITIVE_SIGNAL"
    assert first.source_run_verified is True
    assert first.evidence_usage == "supporting_only"
    assert first.evidence_strength == "PENDING"
    assert first.simulation_only is True
    assert first.is_real_trade is False
    assert first.strong_conclusion_allowed is False
    assert summary.pending_count == 1
    assert summary.active_count == 0

    approved = knowledge_store.review_knowledge_item(
        first.item_id,
        ReviewKnowledgeItemRequest(action="APPROVE", reviewer="tester", note="looks good"),
    )
    context = knowledge_store.get_active_knowledge_context()

    assert approved.status == "ACTIVE"
    assert approved.version == 1
    assert approved.evidence_strength == "MEDIUM"
    assert approved.evidence_usage == "supporting_only"
    assert approved.strong_conclusion_allowed is False
    assert context[0]["itemId"] == first.item_id
    assert context[0]["version"] == 1
    assert context[0]["evidenceUsage"] == "supporting_only"
    assert context[0]["evidenceStrength"] == "MEDIUM"
    assert context[0]["simulationOnly"] is True
    assert context[0]["isRealTrade"] is False
    assert context[0]["strongConclusionAllowed"] is False


def test_manual_knowledge_item_validates_required_fields():
    with pytest.raises(ValueError):
        knowledge_store.create_knowledge_item(
            CreateKnowledgeItemRequest(title="", thesis="has thesis")
        )

    item = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="RUN_REVIEW",
            title="Manual learning",
            thesis="Manual rule needs review",
            evidence=["case A"],
            tags=["manual", "review"],
        )
    )

    assert item.status == "PENDING_REVIEW"
    assert item.source_run_verified is False
    assert item.evidence == ["case A"]
    assert item.tags == ["manual", "review"]
    assert item.evidence_usage == "supporting_only"
    assert item.evidence_strength == "PENDING"
    assert item.simulation_only is True
    assert item.is_real_trade is False
    assert item.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_knowledge_routes_generate_from_run_and_reject(monkeypatch):
    monkeypatch.setattr(routes_analysis, "runs_store", {"RUN_TEST_001": sample_run("WAIT")})

    item = await routes_knowledge.create_knowledge_from_run(
        "RUN_TEST_001",
        GenerateKnowledgeFromRunRequest(force=False),
    )
    rejected = await routes_knowledge.review_knowledge_item_route(
        item.item_id,
        ReviewKnowledgeItemRequest(action="REJECT", reviewer="tester", note="not reusable"),
    )
    summary = await routes_knowledge.knowledge_summary()

    assert item.category == "DEFENSIVE_REVIEW"
    assert rejected.status == "REJECTED"
    assert rejected.evidence_usage == "supporting_only"
    assert rejected.evidence_strength == "LOW"
    assert rejected.simulation_only is True
    assert rejected.is_real_trade is False
    assert rejected.strong_conclusion_allowed is False
    assert summary.rejected_count == 1

    with pytest.raises(HTTPException) as exc_info:
        await routes_knowledge.create_knowledge_from_run("MISSING_RUN")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_manual_knowledge_route_preserves_verified_source_run(monkeypatch):
    run = sample_run("WAIT")
    monkeypatch.setattr(routes_analysis, "runs_store", {run["runId"]: run})

    item = await routes_knowledge.create_knowledge_item_route(
        CreateKnowledgeItemRequest(
            category="RUN_REVIEW",
            title="Manual run-linked learning",
            thesis="Manual notes can reference only a known analysis run.",
            evidence=["operator supplied a supporting observation"],
            guardrail_notes=["human review required"],
            source_run_id=f" {run['runId']} ",
        )
    )
    reviewed = await routes_knowledge.review_knowledge_item_route(
        item.item_id,
        ReviewKnowledgeItemRequest(action="APPROVE", reviewer="tester", note="verified source"),
    )

    assert item.source_run_id == run["runId"]
    assert item.source_run_verified is True
    assert reviewed.evidence_strength == "MEDIUM"
    assert reviewed.evidence_usage == "supporting_only"
    assert reviewed.simulation_only is True
    assert reviewed.is_real_trade is False
    assert reviewed.strong_conclusion_allowed is False


@pytest.mark.asyncio
async def test_manual_knowledge_route_rejects_unknown_source_run(monkeypatch):
    monkeypatch.setattr(routes_analysis, "runs_store", {})

    with pytest.raises(HTTPException) as exc_info:
        await routes_knowledge.create_knowledge_item_route(
            CreateKnowledgeItemRequest(
                category="RUN_REVIEW",
                title="Forged source",
                thesis="A missing run must not become provenance.",
                evidence=["operator supplied a supporting observation"],
                guardrail_notes=["human review required"],
                source_run_id="RUN_FORGED_SOURCE",
            )
        )

    assert exc_info.value.status_code == 400
    assert knowledge_store.get_knowledge_summary().total == 0


@pytest.mark.asyncio
async def test_manual_knowledge_route_rejects_legacy_source_run(monkeypatch):
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {"RUN_MOCK_FORGED": {**sample_run("WAIT"), "runId": "RUN_MOCK_FORGED"}},
    )

    with pytest.raises(HTTPException) as exc_info:
        await routes_knowledge.create_knowledge_item_route(
            CreateKnowledgeItemRequest(
                category="RUN_REVIEW",
                title="Legacy source",
                thesis="A legacy mock run must not become manual provenance.",
                evidence=["operator supplied a supporting observation"],
                guardrail_notes=["human review required"],
                source_run_id="RUN_MOCK_FORGED",
            )
        )

    assert exc_info.value.status_code == 400
    assert knowledge_store.get_knowledge_summary().total == 0


def test_create_knowledge_item_caps_high_confidence_for_supporting_only_context():
    item = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="RUN_REVIEW",
            title="Manual high confidence candidate",
            thesis="Manual knowledge must not become a strong conclusion.",
            evidence=["operator supplied a supporting observation"],
            decision_impact="Review only.",
            guardrail_notes=["human review required"],
            tags=["manual"],
            confidence="HIGH",
        )
    )

    assert item.confidence == "MEDIUM"
    assert item.source_run_verified is False
    assert item.evidence_usage == "supporting_only"
    assert item.simulation_only is True
    assert item.is_real_trade is False
    assert item.strong_conclusion_allowed is False

    reviewed = knowledge_store.review_knowledge_item(
        item.item_id,
        ReviewKnowledgeItemRequest(action="APPROVE", reviewer="unit", note="approve supporting only"),
    )
    context = knowledge_store.get_active_knowledge_context()

    assert reviewed.confidence == "MEDIUM"
    assert context[0]["confidence"] == "MEDIUM"
    assert context[0]["evidenceUsage"] == "supporting_only"
    assert context[0]["strongConclusionAllowed"] is False


@pytest.mark.parametrize("confidence", ["", "UNKNOWN", "PENDING", "MISSING", "WARN", "REVIEW_ONLY", "SUPPORTING_ONLY"])
def test_create_knowledge_item_keeps_weak_confidence_markers_low(confidence):
    item = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="RUN_REVIEW",
            title="Manual weak confidence candidate",
            thesis="Weak confidence markers must not become medium confidence.",
            evidence=["operator supplied a supporting observation"],
            decision_impact="Review only.",
            guardrail_notes=["human review required"],
            tags=["manual"],
            confidence=confidence,
        )
    )

    assert item.confidence == "LOW"


def test_active_knowledge_context_model_caps_polluted_boundary():
    context = ActiveKnowledgeContextItem(
        itemId="KB_POLLUTED_CONTEXT",
        version=7,
        category="RUN_REVIEW",
        title="Polluted context",
        thesis="Legacy context carried strong-trade markers.",
        decisionImpact="Review only.",
        tags=["legacy"],
        confidence="HIGH",
        evidenceUsage="primary",
        evidenceStrength="HIGH",
        simulationOnly=False,
        isRealTrade=True,
        strongConclusionAllowed=True,
    )

    assert context.confidence == "MEDIUM"
    assert context.evidenceUsage == "supporting_only"
    assert context.evidenceStrength == "MEDIUM"
    assert context.simulationOnly is True
    assert context.isRealTrade is False
    assert context.strongConclusionAllowed is False


@pytest.mark.parametrize("confidence", ["", "UNKNOWN", "PENDING", "MISSING", "WARN", "REVIEW_ONLY", "SUPPORTING_ONLY"])
def test_active_knowledge_context_model_keeps_weak_confidence_markers_low(confidence):
    context = ActiveKnowledgeContextItem(
        itemId="KB_WEAK_CONFIDENCE_CONTEXT",
        version=7,
        category="RUN_REVIEW",
        title="Weak confidence context",
        thesis="Legacy weak confidence must not become medium confidence.",
        decisionImpact="Review only.",
        tags=["legacy"],
        confidence=confidence,
        evidenceUsage="supporting_only",
        evidenceStrength="LOW",
        simulationOnly=False,
        isRealTrade=True,
        strongConclusionAllowed=True,
    )

    assert context.confidence == "LOW"
    assert context.evidenceUsage == "supporting_only"
    assert context.evidenceStrength == "LOW"
    assert context.simulationOnly is True
    assert context.isRealTrade is False
    assert context.strongConclusionAllowed is False


@pytest.mark.asyncio
async def test_knowledge_context_route_returns_typed_boundary_response():
    item = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="RUN_REVIEW",
            title="Context response",
            thesis="Typed context must preserve review-only boundaries.",
            evidence=["case A"],
            guardrail_notes=["manual review required"],
            source_run_id="RUN_CONTEXT_ROUTE_001",
        )
    )
    knowledge_store.review_knowledge_item(
        item.item_id,
        ReviewKnowledgeItemRequest(action="APPROVE", reviewer="unit", note="approve for context"),
    )

    response = await routes_knowledge.knowledge_context(limit=8)

    assert response.items[0].itemId == item.item_id
    assert response.items[0].evidenceUsage == "supporting_only"
    assert response.items[0].evidenceStrength == "LOW"
    assert response.items[0].simulationOnly is True
    assert response.items[0].isRealTrade is False
    assert response.items[0].strongConclusionAllowed is False


def test_learning_candidate_from_run_caps_high_qiam_confidence():
    item = knowledge_store.create_learning_candidate_from_run(
        {
            "runId": "RUN_KNOWLEDGE_HIGH_CONFIDENCE",
            "auditId": "AUD_KNOWLEDGE_HIGH_CONFIDENCE",
            "stockCode": "603663",
            "taskType": "research",
            "runMode": "STANDARD_MODE",
            "finalAction": "BUY_CANDIDATE",
            "finalWriter": {"finalAction": "BUY_CANDIDATE", "humanConfirmationRequired": True},
            "qiam": {"modelConfidenceFinal": 0.95, "finalBuySuitability": "REVIEW_ONLY"},
            "dvg": {"status": "PASS"},
            "signalOps": {"signalStatus": "PAPER_TEST"},
            "killSwitch": {"active": False, "level": "NONE"},
            "execution": {"forbiddenActions": []},
            "chipKb": {"coreMissingData": []},
        },
        force=True,
    )

    assert item.confidence == "MEDIUM"
    assert item.source_run_verified is True
    assert item.evidence_usage == "supporting_only"
    assert item.evidence_strength == "PENDING"
    assert item.simulation_only is True
    assert item.is_real_trade is False
    assert item.strong_conclusion_allowed is False


def test_legacy_loaded_high_confidence_is_capped_before_active_context(tmp_path):
    storage_file = tmp_path / "knowledge_iterations.json"
    storage_file.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "item_id": "KB_LEGACY_HIGH",
                        "version": 1,
                        "status": "ACTIVE",
                        "category": "RUN_REVIEW",
                        "source_run_id": "RUN_LEGACY_HIGH",
                        "source_audit_id": "AUD_LEGACY_HIGH",
                        "title": "Legacy high confidence",
                        "thesis": "Legacy state must be normalized before reuse.",
                        "evidence": ["legacy evidence"],
                        "decision_impact": "Review only.",
                        "guardrail_notes": ["legacy guardrail"],
                        "tags": ["legacy"],
                        "confidence": "HIGH",
                        "evidence_usage": "primary",
                        "evidence_strength": "HIGH",
                        "simulation_only": False,
                        "is_real_trade": True,
                        "strong_conclusion_allowed": True,
                        "created_at": "2026-06-01T00:00:00+00:00",
                        "updated_at": "2026-06-01T00:00:00+00:00",
                    }
                ],
                "updated_at": "2026-06-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    item = knowledge_store.list_knowledge_items(status="ACTIVE")[0]
    context = knowledge_store.get_active_knowledge_context()

    assert item.confidence == "MEDIUM"
    assert item.evidence_usage == "supporting_only"
    assert item.source_run_verified is False
    assert item.evidence_strength == "LOW"
    assert item.simulation_only is True
    assert item.is_real_trade is False
    assert item.strong_conclusion_allowed is False
    assert context[0]["confidence"] == "MEDIUM"
    assert context[0]["simulationOnly"] is True
    assert context[0]["isRealTrade"] is False
