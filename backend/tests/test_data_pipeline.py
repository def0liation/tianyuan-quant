import pytest

from app.api import routes_data_pipeline
from app.api import routes_analysis
from app.core import data_pipeline, knowledge_store
from app.models.knowledge import CreateKnowledgeItemRequest


@pytest.fixture(autouse=True)
def temp_knowledge_store(monkeypatch, tmp_path):
    monkeypatch.setattr(knowledge_store, "STORAGE_FILE", tmp_path / "knowledge_iterations.json")


def sample_run() -> dict:
    return {
        "runId": "RUN_PIPE_001",
        "auditId": "AUD_PIPE_001",
        "stockCode": "603663",
        "stockName": "测试股份",
        "taskType": "position_review",
        "runMode": "STANDARD_MODE",
        "status": "COMPLETED",
        "createdAt": "2026-05-11T10:00:00",
        "updatedAt": "2026-05-11T10:05:00",
        "dataSources": {
            "summary": {
                "availableRatio": "3/5",
            }
        },
        "nodes": [
            {"id": "dvg", "status": "PASS", "outputSummary": "DVG data passed"},
            {"id": "qiam", "status": "PASS", "outputSummary": "QIAM favorable"},
        ],
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
        "paperTrading": {
            "status": "ACTIVE",
        },
        "agentResults": [{"agent_id": "dvg", "status": "PASS"}],
        "auditLog": [{"node": "router", "message": "run created"}],
        "finalAction": "BUY_CANDIDATE",
        "finalWriter": {
            "mode": "NORMAL",
            "finalAction": "BUY_CANDIDATE",
            "sections": [{"title": "结论", "content": "保持人工确认后观察候选。"}],
        },
    }


def test_run_summary_is_stable_and_decision_focused():
    run = sample_run()
    first = data_pipeline.summarize_run(run)
    second = data_pipeline.summarize_run({**run, "streamEvents": [{"noise": True}]})

    assert first.data_fingerprint.fingerprint == second.data_fingerprint.fingerprint
    assert first.final_action == "BUY_CANDIDATE"
    assert first.quality.level in {"HIGH", "MEDIUM"}
    assert "streamEvents" not in first.keep_fields
    assert first.retention_action in {"KEEP_RAW_AND_SUMMARY", "KEEP_SUMMARY_REVIEW_RAW"}
    assert first.token_budget_estimate > 0


@pytest.mark.asyncio
async def test_compress_run_route_writes_summary(monkeypatch):
    run = sample_run()
    saved = []
    monkeypatch.setattr(routes_analysis, "runs_store", {run["runId"]: run})
    monkeypatch.setattr(routes_data_pipeline, "save_run", lambda run_data: saved.append(run_data))

    summary = await routes_data_pipeline.compress_run(run["runId"])

    assert summary.run_id == run["runId"]
    assert run["compressedSummary"]["run_id"] == run["runId"]
    assert saved and saved[0]["compressedSummary"]["quality"]["score"] == summary.quality.score


def test_knowledge_distillation_groups_similar_items():
    first = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="DVG_DATA_GATE",
            title="Missing level2 blocks buy",
            thesis="Level2 missing should keep review-only.",
            tags=["603663", "DVG", "missing-data"],
        )
    )
    second = knowledge_store.create_knowledge_item(
        CreateKnowledgeItemRequest(
            category="DVG_DATA_GATE",
            title="Level2 missing repeat",
            thesis="When level2 is missing, keep review-only.",
            tags=["603663", "DVG", "missing-data"],
        )
    )

    groups = data_pipeline.distill_knowledge_items([first, second])

    assert len(groups) == 1
    assert groups[0].duplicate_count == 1
    assert set(groups[0].item_ids) == {first.item_id, second.item_id}
