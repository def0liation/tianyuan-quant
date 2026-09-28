from fastapi import APIRouter, HTTPException, Query

from ..core.signalops_store import signalops_store
from ..models.signalops_lifecycle import (
    AgentSimulationCaseItem,
    AgentSimulationCaseRequest,
    AttachRunRequest,
    CreateSignalRequest,
    PaperFillRequest,
    PaperOrderItem,
    PaperOrderRequest,
    PaperPositionItem,
    PaperPortfolioItem,
    PaperPortfolioRequest,
    SignalDetail,
    SignalItem,
    SignalReviewItem,
    SignalReviewRequest,
    SignalTransitionItem,
    SignalTransitionRequest,
    UpdateSignalConditionsRequest,
)


router = APIRouter()
CLIENT_MANAGED_SIGNAL_GATE_FIELDS = {
    "risk_passed",
    "dvg_passed",
    "dvg_status",
    "qiam_passed",
    "qiam_status",
    "execution_reachable",
    "portfolio_allowed",
}
CLIENT_MANAGED_TRANSITION_GATES = {
    "basic_analysis_completed",
    "manual_confirmed",
    "execution_completed",
}


@router.post("/signals", response_model=SignalItem)
async def create_signal(request: CreateSignalRequest):
    try:
        return await signalops_store.create_signal(_server_managed_signal_create_payload(request.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "reason": "SIGNAL_CREATE_FAILED"}) from exc


@router.get("/signals", response_model=list[SignalItem])
async def list_signals(
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    return await signalops_store.list_signals(status=status, symbol=symbol, limit=limit)


@router.get("/signals/{signal_id}", response_model=SignalDetail)
async def get_signal(signal_id: str):
    detail = await signalops_store.get_signal_detail(signal_id)
    if not detail:
        raise HTTPException(status_code=404, detail={"message": "Signal not found", "reason": "SIGNAL_NOT_FOUND"})
    return detail


@router.post("/signals/{signal_id}/transition", response_model=SignalTransitionItem)
async def transition_signal(signal_id: str, request: SignalTransitionRequest):
    client_gates = CLIENT_MANAGED_TRANSITION_GATES.intersection(request.gate_context.keys())
    if client_gates:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Signal lifecycle gate_context contains server-managed gate evidence.",
                "reason": "SIGNAL_GATE_CONTEXT_SERVER_MANAGED",
                "server_managed_keys": sorted(client_gates),
            },
        )
    transition, error = await signalops_store.transition_signal(signal_id, request.model_dump())
    if not transition:
        raise HTTPException(status_code=404, detail={"message": error or "Signal not found", "reason": "SIGNAL_NOT_FOUND"})
    if error:
        raise HTTPException(status_code=409, detail={"message": error, "reason": "SIGNAL_GATE_BLOCKED", "transition": transition})
    return transition


@router.post("/signals/{signal_id}/attach-run", response_model=SignalItem)
async def attach_signal_run(signal_id: str, request: AttachRunRequest):
    signal = await signalops_store.attach_run(signal_id, request.run_id, request.audit_id)
    if not signal:
        raise HTTPException(status_code=404, detail={"message": "Signal not found", "reason": "SIGNAL_NOT_FOUND"})
    return signal


@router.patch("/signals/{signal_id}/conditions", response_model=SignalItem)
async def update_signal_conditions(signal_id: str, request: UpdateSignalConditionsRequest):
    signal = await signalops_store.update_signal_conditions(signal_id, request.model_dump(exclude_unset=True))
    if not signal:
        raise HTTPException(status_code=404, detail={"message": "Signal not found", "reason": "SIGNAL_NOT_FOUND"})
    return signal


@router.post("/signals/{signal_id}/review", response_model=SignalReviewItem)
async def review_signal(signal_id: str, request: SignalReviewRequest):
    review = await signalops_store.create_review(signal_id, request.model_dump())
    if not review:
        raise HTTPException(status_code=404, detail={"message": "Signal not found", "reason": "SIGNAL_NOT_FOUND"})
    return review


@router.post("/signalops/{signal_id}/paper-portfolio", response_model=PaperPortfolioItem)
async def create_paper_portfolio(signal_id: str, request: PaperPortfolioRequest):
    portfolio, error = await signalops_store.create_paper_portfolio(signal_id, request.model_dump())
    if error:
        status_code = 404 if error == "Signal not found" else 409
        raise HTTPException(status_code=status_code, detail={"message": error, "reason": "PAPER_PORTFOLIO_BLOCKED"})
    return portfolio


@router.get("/signalops/{signal_id}/paper-portfolio", response_model=PaperPortfolioItem | None)
async def get_paper_portfolio(signal_id: str, allow_missing: bool = Query(default=False)):
    portfolio = await signalops_store.get_paper_portfolio(signal_id)
    if not portfolio:
        if allow_missing:
            return None
        raise HTTPException(status_code=404, detail={"message": "Paper portfolio not found", "reason": "PAPER_PORTFOLIO_NOT_FOUND"})
    return portfolio


@router.get("/signalops/{signal_id}/paper-orders", response_model=list[PaperOrderItem])
async def list_paper_orders(signal_id: str):
    return await signalops_store.list_paper_orders(signal_id)


@router.get("/signalops/{signal_id}/paper-positions", response_model=list[PaperPositionItem])
async def list_paper_positions(signal_id: str):
    return await signalops_store.list_paper_positions(signal_id)


@router.post("/signalops/{signal_id}/paper-orders", response_model=PaperOrderItem)
async def create_paper_order(signal_id: str, request: PaperOrderRequest):
    order, error = await signalops_store.create_paper_order(signal_id, request.model_dump())
    if error:
        status_code = 404 if "not found" in error.lower() else 409
        raise HTTPException(status_code=status_code, detail={"message": error, "reason": "PAPER_ORDER_BLOCKED"})
    return order


@router.post("/signalops/{signal_id}/paper-orders/{order_id}/fill", response_model=PaperOrderItem)
async def fill_paper_order(signal_id: str, order_id: str, request: PaperFillRequest):
    order, error = await signalops_store.fill_paper_order(signal_id, order_id, request.model_dump())
    if error:
        status_code = 404 if "not found" in error.lower() else 409
        raise HTTPException(status_code=status_code, detail={"message": error, "reason": "PAPER_FILL_BLOCKED"})
    return order


@router.post("/signalops/{signal_id}/paper-cases", response_model=AgentSimulationCaseItem)
async def create_agent_simulation_case(signal_id: str, request: AgentSimulationCaseRequest):
    case, error = await signalops_store.create_agent_simulation_case(signal_id, request.model_dump())
    if error:
        status_code = 404 if "not found" in error.lower() else 409
        raise HTTPException(status_code=status_code, detail={"message": error, "reason": "SIM_CASE_BLOCKED"})
    return case


@router.get("/knowledge/cases", response_model=list[AgentSimulationCaseItem])
async def list_knowledge_cases(
    source: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    return await signalops_store.list_agent_simulation_cases(source=source, limit=limit)


def _server_managed_signal_create_payload(data: dict) -> dict:
    sanitized = dict(data)
    ignored = [key for key in CLIENT_MANAGED_SIGNAL_GATE_FIELDS if sanitized.get(key) not in (None, "", False)]
    sanitized.update(
        {
            "risk_passed": False,
            "dvg_passed": False,
            "dvg_status": "",
            "qiam_passed": False,
            "qiam_status": "",
            "execution_reachable": False,
            "portfolio_allowed": False,
        }
    )
    if ignored:
        metadata = dict(sanitized.get("metadata_json") or {})
        metadata["client_gate_fields_ignored"] = sorted(ignored)
        sanitized["metadata_json"] = metadata
    return sanitized
