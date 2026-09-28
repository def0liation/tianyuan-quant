import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.api import routes_research
from app.core import research_hypothesis_store as hypothesis_module
from app.core.research_hypothesis_store import ResearchHypothesisStore
from app.core.research_store import ResearchLoopStore
from app.db.models_research import ResearchHypothesisDraftDB
from app.db.session import AsyncSessionLocal
from app.models.agent_runtime import AgentLLMProfile
from app.models.research import (
    ConfirmResearchHypothesisDraftRequest,
    CreateResearchLoopRequest,
    ResearchHypothesisDraftRequest,
)


@pytest.fixture
def research_store():
    return ResearchLoopStore()


@pytest.fixture
def hypothesis_store():
    return ResearchHypothesisStore()


def test_rule_selector_prioritizes_data_quality(hypothesis_store):
    selected = hypothesis_store.select_action_target(
        {
            "dvg_status": "FAIL",
            "slippage": 0.03,
            "max_drawdown": 0.2,
            "trigger_quality": 0.2,
            "factor_stability": 0.2,
        },
        fallback_target="signal",
    )

    assert selected.target == "data_quality_rule"
    assert selected.rule_id == "P6_DATA_QUALITY_BOTTLENECK"
    assert selected.confidence > 0.8


def test_rule_selector_maps_risk_execution_signal_factor(hypothesis_store):
    assert hypothesis_store.select_action_target({"max_drawdown": 0.12}).target == "risk_rule"
    assert hypothesis_store.select_action_target({"slippage": 0.02}).target == "execution_rule"
    assert hypothesis_store.select_action_target({"trigger_quality": 0.3}).target == "signal"
    assert hypothesis_store.select_action_target({"factor_stability": 0.4}).target == "factor"
    assert hypothesis_store.select_action_target({}, fallback_target="execution_rule").target == "execution_rule"


@pytest.mark.asyncio
async def test_generate_hypothesis_draft_is_draft_only(research_store, hypothesis_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P6 data quality",
            objective="Improve evidence quality before knowledge feedback.",
            hypothesis="Low data coverage weakens accepted knowledge.",
            action_target="factor",
        )
    )
    before = await research_store.get_loop_detail(detail.loop.loop_id)

    response = await hypothesis_store.generate_draft(
        detail.loop.loop_id,
        ResearchHypothesisDraftRequest(
            iteration_id=detail.iterations[0].iteration_id,
            context_metrics={"quality_score": 45, "dvg_status": "LOW"},
            use_llm=False,
            max_drafts=2,
        ),
    )
    after = await research_store.get_loop_detail(detail.loop.loop_id)
    drafts = await hypothesis_store.list_drafts(detail.loop.loop_id)

    assert response is not None
    assert response.draft_id.startswith("RHYP_")
    assert response.action_selection.target == "data_quality_rule"
    assert response.confirmation_required is True
    assert response.auto_run_started is False
    assert response.llm_status == "NOT_REQUESTED"
    assert len(response.drafts) == 2
    assert len(before.iterations) == len(after.iterations) == 1
    assert drafts is not None
    assert drafts[0].draft_id == response.draft_id


@pytest.mark.asyncio
async def test_generate_hypothesis_draft_rejects_unknown_requested_iteration(research_store, hypothesis_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P6 stale iteration",
            objective="A selected iteration must belong to the loop.",
            hypothesis="Initial hypothesis",
        )
    )

    with pytest.raises(ValueError) as exc:
        await hypothesis_store.generate_draft(
            detail.loop.loop_id,
            ResearchHypothesisDraftRequest(iteration_id="MISSING_ITERATION"),
        )

    assert "iteration" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_generate_hypothesis_draft_reads_nested_frontend_metrics(research_store, hypothesis_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P6 nested metrics",
            objective="Frontend verdict metrics should drive the selected action target.",
            hypothesis="Nested DVG context should be recognized.",
        )
    )

    response = await hypothesis_store.generate_draft(
        detail.loop.loop_id,
        ResearchHypothesisDraftRequest(
            iteration_id=detail.iterations[0].iteration_id,
            context_metrics={
                "current_metrics": {
                    "quality_score": 45,
                    "dvg_status": "LOW",
                },
                "comparison": [
                    {"key": "slippage", "current": 0.03, "warning": "Execution slippage is elevated."}
                ],
            },
            max_drafts=1,
        ),
    )

    assert response is not None
    assert response.action_selection.target == "data_quality_rule"
    assert "quality_score=45" in response.action_selection.evidence
    assert "dvg_status=LOW" in response.action_selection.evidence


@pytest.mark.asyncio
async def test_generate_hypothesis_draft_llm_unavailable_returns_rule_draft(research_store, hypothesis_store, monkeypatch):
    monkeypatch.setattr(
        hypothesis_module,
        "get_llm_profile",
        lambda profile_id: AgentLLMProfile(
            id=profile_id,
            label="Disabled test profile",
            provider="openai_compatible",
            base_url="https://example.test/v1",
            model="test-model",
            api_key="",
            enabled=True,
        ),
    )
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P6 LLM unavailable",
            objective="LLM should be optional for hypothesis drafts.",
        )
    )

    response = await hypothesis_store.generate_draft(
        detail.loop.loop_id,
        ResearchHypothesisDraftRequest(
            context_metrics={"trigger_quality": 0.3},
            use_llm=True,
        ),
    )

    assert response is not None
    assert response.action_selection.target == "signal"
    assert response.llm_status == "SKIPPED"
    assert "api_key" in response.llm_error
    assert response.drafts
    assert all(draft.source == "RULE" for draft in response.drafts)


@pytest.mark.asyncio
async def test_confirm_hypothesis_draft_creates_iteration_once(research_store, hypothesis_store):
    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P6 confirmation",
            objective="Confirming a draft creates a reviewable iteration.",
        )
    )
    draft = await hypothesis_store.generate_draft(
        detail.loop.loop_id,
        ResearchHypothesisDraftRequest(context_metrics={"slippage": 0.02}, max_drafts=1),
    )

    iteration = await hypothesis_store.confirm_draft(
        draft.draft_id,
        ConfirmResearchHypothesisDraftRequest(selected_index=0, reviewer="tester", note="confirm"),
    )
    repeated = await hypothesis_store.confirm_draft(
        draft.draft_id,
        ConfirmResearchHypothesisDraftRequest(selected_index=0, reviewer="tester", note="again"),
    )
    updated_draft = await hypothesis_store.get_draft(draft.draft_id)
    detail_after = await research_store.get_loop_detail(detail.loop.loop_id)

    assert iteration is not None
    assert repeated is not None
    assert iteration.iteration_id == repeated.iteration_id
    assert updated_draft.confirmed_iteration_id == iteration.iteration_id
    assert updated_draft.confirmation_required is False
    assert len(detail_after.iterations) == 1
    assert iteration.metrics["source_draft_id"] == draft.draft_id
    assert iteration.metrics["action_target"] == "execution_rule"
    assert iteration.metrics["auto_run_started"] is False


@pytest.mark.asyncio
async def test_research_hypothesis_routes_return_404_and_409(research_store):
    with pytest.raises(HTTPException) as missing_loop:
        await routes_research.draft_research_hypothesis_route(
            "MISSING_LOOP",
            ResearchHypothesisDraftRequest(),
        )
    assert missing_loop.value.status_code == 404

    detail = await research_store.create_loop(
        CreateResearchLoopRequest(
            title="P6 route",
            objective="Route coverage for hypothesis drafts.",
        )
    )
    draft = await routes_research.create_research_hypothesis_draft_route(
        detail.loop.loop_id,
        ResearchHypothesisDraftRequest(max_drafts=1),
    )
    with pytest.raises(HTTPException) as missing_iteration:
        await routes_research.draft_research_hypothesis_route(
            detail.loop.loop_id,
            ResearchHypothesisDraftRequest(iteration_id="MISSING_ITERATION"),
        )
    assert missing_iteration.value.status_code == 404

    fetched = await routes_research.get_research_hypothesis_draft_route(draft.draft_id)
    listed = await routes_research.list_research_hypothesis_drafts_route(detail.loop.loop_id)

    assert fetched.draft_id == draft.draft_id
    assert listed[0].draft_id == draft.draft_id

    with pytest.raises(HTTPException) as out_of_range:
        await routes_research.confirm_research_hypothesis_draft_route(
            draft.draft_id,
            ConfirmResearchHypothesisDraftRequest(selected_index=3),
        )
    assert out_of_range.value.status_code == 409

    in_progress = await routes_research.create_research_hypothesis_draft_route(
        detail.loop.loop_id,
        ResearchHypothesisDraftRequest(max_drafts=1),
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ResearchHypothesisDraftDB)
            .where(ResearchHypothesisDraftDB.draft_id == in_progress.draft_id)
            .values(status="CONFIRMING")
        )
        await db.commit()

    with pytest.raises(HTTPException) as confirming:
        await routes_research.confirm_research_hypothesis_draft_route(
            in_progress.draft_id,
            ConfirmResearchHypothesisDraftRequest(selected_index=0),
        )
    assert confirming.value.status_code == 409
