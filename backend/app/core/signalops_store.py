import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, select

from ..db.models import (
    AgentSimulationCaseDB,
    PaperExecutionDB,
    PaperOrderDB,
    PaperPortfolioDB,
    PaperPositionDB,
    SignalDB,
    SignalReviewDB,
    SignalTransitionDB,
)
from ..db.session import AsyncSessionLocal


SIGNAL_STATUS_ORDER = [
    "IDEA",
    "WATCH",
    "PAPER_TEST",
    "QUALIFIED",
    "TRADE_PLAN",
    "MANUAL_CONFIRMED",
    "EXECUTION_REVIEW",
    "CLOSED",
]
SIGNAL_STATUSES = set(SIGNAL_STATUS_ORDER) | {"PATCH_REQUIRED"}
PAPER_ENABLED_STATUSES = {
    "PAPER_TEST",
    "QUALIFIED",
    "TRADE_PLAN",
    "MANUAL_CONFIRMED",
    "EXECUTION_REVIEW",
}
SIM_ACTIONS = {
    "SIM_BUY",
    "SIM_SELL",
    "SIM_HOLD",
    "SIM_REBALANCE",
    "SIM_CLOSE",
    "SIM_T_BUY",
    "SIM_T_SELL",
    "SIM_SHORT",
    "SIM_COVER",
}
NO_RISK_ACTIONS = {"SIM_HOLD", "SIM_CLOSE", "SIM_SELL", "SIM_T_SELL", "SIM_COVER"}
BOARD_LOT_SIZE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _board_lot_quantity(value: Any) -> int:
    try:
        quantity = float(value)
    except (TypeError, ValueError):
        return 0
    if quantity < BOARD_LOT_SIZE:
        return 0
    return int(quantity // BOARD_LOT_SIZE) * BOARD_LOT_SIZE


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _audit_id(prefix: str, entity_id: str) -> str:
    return f"AUD_{prefix}_{entity_id}_{uuid.uuid4().hex[:6]}"


def _status_index(status: str) -> int:
    try:
        return SIGNAL_STATUS_ORDER.index(status)
    except ValueError:
        return -1


class SignalOpsStore:
    async def create_signal(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            signal_id = _generate_id("SIG")
            source_run_id = data.get("source_run_id")
            attached_runs = [source_run_id] if source_run_id else []
            signal = SignalDB(
                signal_id=signal_id,
                symbol=data["symbol"],
                stock_name=data.get("stock_name", ""),
                status="IDEA",
                source_run_id=source_run_id,
                latest_run_id=source_run_id,
                audit_id=data.get("audit_id") or _audit_id("SIGNAL_CREATE", signal_id),
                risk_passed=bool(data.get("risk_passed", False)),
                dvg_passed=bool(data.get("dvg_passed", False)),
                dvg_status=data.get("dvg_status", ""),
                qiam_passed=bool(data.get("qiam_passed", False)),
                qiam_status=data.get("qiam_status", ""),
                execution_reachable=bool(data.get("execution_reachable", False)),
                portfolio_allowed=bool(data.get("portfolio_allowed", True)),
                trigger_conditions=data.get("trigger_conditions", []),
                invalidation_conditions=data.get("invalidation_conditions", []),
                review_fields=data.get("review_fields", []),
                attached_runs=attached_runs,
                metadata_json=data.get("metadata_json", {}),
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(signal)
            await db.commit()
            await db.refresh(signal)
            return self._signal_to_dict(signal)

    async def upsert_from_run(self, run_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        signal_data = run_data.get("signalOps") if isinstance(run_data.get("signalOps"), dict) else {}
        if not signal_data:
            return None
        symbol = str(run_data.get("stockCode") or run_data.get("symbol") or "").strip()
        if not symbol:
            return None
        run_id = str(run_data.get("runId") or "")
        target_status = str(signal_data.get("signalStatus") or "WATCH").upper()
        if target_status not in SIGNAL_STATUSES:
            target_status = "WATCH"

        payload = _signal_payload_from_run(run_data, signal_data, symbol, run_id)

        async with AsyncSessionLocal() as db:
            query = (
                select(SignalDB)
                .where(SignalDB.symbol == symbol)
                .where(SignalDB.status != "CLOSED")
                .order_by(desc(SignalDB.updated_at))
                .limit(1)
            )
            result = await db.execute(query)
            signal = result.scalar_one_or_none()
            if signal is None:
                signal = SignalDB(
                    signal_id=_generate_id("SIG"),
                    symbol=symbol,
                    stock_name=payload.get("stock_name", ""),
                    status="IDEA",
                    source_run_id=run_id or None,
                    latest_run_id=run_id or None,
                    audit_id=payload.get("audit_id") or _audit_id("SIGNAL_RUN_UPSERT", run_id or symbol),
                    created_at=_now(),
                )
                db.add(signal)
                await db.flush()

            previous_status = signal.status
            runs = list(signal.attached_runs or [])
            if run_id and run_id not in runs:
                runs.append(run_id)
            signal.attached_runs = runs
            signal.latest_run_id = run_id or signal.latest_run_id
            signal.audit_id = payload.get("audit_id") or _audit_id("SIGNAL_RUN_UPSERT", signal.signal_id)
            signal.stock_name = payload.get("stock_name", signal.stock_name)
            signal.risk_passed = payload["risk_passed"]
            signal.dvg_passed = payload["dvg_passed"]
            signal.dvg_status = payload["dvg_status"]
            signal.qiam_passed = payload["qiam_passed"]
            signal.qiam_status = payload["qiam_status"]
            signal.execution_reachable = payload["execution_reachable"]
            signal.portfolio_allowed = payload["portfolio_allowed"]
            signal.trigger_conditions = payload["trigger_conditions"]
            signal.invalidation_conditions = payload["invalidation_conditions"]
            signal.review_fields = payload["review_fields"]
            signal.blocked_reason = payload["blocked_reason"]
            signal.metadata_json = payload["metadata_json"]

            should_attempt_transition = (
                target_status == "PATCH_REQUIRED"
                or target_status == "CLOSED"
                or _status_index(target_status) > _status_index(previous_status)
            )
            if should_attempt_transition:
                checks = self._gate_checks(
                    signal,
                    target_status,
                    {
                        "basic_analysis_completed": True,
                        "manual_confirmed": False,
                        "execution_completed": False,
                    },
                )
                passed = all(check["passed"] for check in checks)
                transition = SignalTransitionDB(
                    transition_id=_generate_id("SIGTR"),
                    signal_id=signal.signal_id,
                    from_status=previous_status,
                    to_status=target_status,
                    audit_id=signal.audit_id,
                    run_id=run_id,
                    actor="agent",
                    reason="Auto-upserted from completed analysis run.",
                    gate_checks=[
                        {"key": "analysis_run_completed", "passed": True, "message": "Completed run mapped to SignalOps lifecycle."},
                        *checks,
                    ],
                    passed=passed,
                    created_at=_now(),
                )
                db.add(transition)
                if passed:
                    signal.status = target_status
                    signal.blocked_reason = ""
                else:
                    signal.blocked_reason = "; ".join(check["message"] for check in checks if not check["passed"])[:256]
            elif previous_status == "IDEA" and target_status == "WATCH":
                signal.status = "WATCH"

            signal.updated_at = _now()
            await db.commit()
            await db.refresh(signal)
            return self._signal_to_dict(signal)

    async def list_signals(
        self,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(SignalDB)
            if status:
                query = query.where(SignalDB.status == status)
            if symbol:
                query = query.where(SignalDB.symbol == symbol)
            query = query.order_by(desc(SignalDB.updated_at)).limit(limit)
            result = await db.execute(query)
            return [self._signal_to_dict(record) for record in result.scalars().all()]

    async def get_signal_detail(self, signal_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None
            transitions = await db.execute(
                select(SignalTransitionDB)
                .where(SignalTransitionDB.signal_id == signal_id)
                .order_by(SignalTransitionDB.created_at)
            )
            reviews = await db.execute(
                select(SignalReviewDB)
                .where(SignalReviewDB.signal_id == signal_id)
                .order_by(desc(SignalReviewDB.created_at))
            )
            return {
                "signal": self._signal_to_dict(signal),
                "transitions": [self._transition_to_dict(r) for r in transitions.scalars().all()],
                "reviews": [self._review_to_dict(r) for r in reviews.scalars().all()],
            }

    async def attach_run(self, signal_id: str, run_id: str, audit_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None
            runs = list(signal.attached_runs or [])
            if run_id not in runs:
                runs.append(run_id)
            signal.attached_runs = runs
            signal.latest_run_id = run_id
            signal.audit_id = audit_id or _audit_id("SIGNAL_ATTACH_RUN", signal_id)
            signal.updated_at = _now()
            await db.commit()
            await db.refresh(signal)
            return self._signal_to_dict(signal)

    async def update_signal_conditions(self, signal_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None
            if "trigger_conditions" in data:
                signal.trigger_conditions = list(data.get("trigger_conditions") or [])
            if "invalidation_conditions" in data:
                signal.invalidation_conditions = list(data.get("invalidation_conditions") or [])
            if "review_fields" in data:
                signal.review_fields = list(data.get("review_fields") or [])
            signal.audit_id = data.get("audit_id") or _audit_id("SIGNAL_CONDITIONS", signal_id)
            signal.updated_at = _now()
            await db.commit()
            await db.refresh(signal)
            return self._signal_to_dict(signal)

    async def update_signal_stock_name(self, signal_id: str, stock_name: str) -> Optional[Dict[str, Any]]:
        name = str(stock_name or "").strip()
        if not name:
            return None
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None
            if signal.stock_name == name:
                return self._signal_to_dict(signal)
            signal.stock_name = name
            signal.updated_at = _now()
            await db.commit()
            await db.refresh(signal)
            return self._signal_to_dict(signal)

    async def transition_signal(self, signal_id: str, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None, "Signal not found"
            target = str(data.get("target_status", "")).upper()
            if target not in SIGNAL_STATUSES:
                return None, f"Invalid target_status: {target}"

            checks = self._gate_checks(signal, target, data.get("gate_context", {}))
            passed = all(check["passed"] for check in checks)
            audit_id = data.get("audit_id") or _audit_id("SIGNAL_TRANSITION", signal_id)
            transition = SignalTransitionDB(
                transition_id=_generate_id("SIGTR"),
                signal_id=signal_id,
                from_status=signal.status,
                to_status=target,
                audit_id=audit_id,
                run_id=data.get("run_id") or signal.latest_run_id,
                actor=data.get("actor", "human"),
                reason=data.get("reason", ""),
                gate_checks=checks,
                passed=passed,
                created_at=_now(),
            )
            db.add(transition)
            if not passed:
                signal.blocked_reason = "; ".join(check["message"] for check in checks if not check["passed"])[:256]
                signal.audit_id = audit_id
                signal.updated_at = _now()
                await db.commit()
                return self._transition_to_dict(transition), signal.blocked_reason

            signal.status = target
            signal.audit_id = audit_id
            signal.blocked_reason = ""
            if data.get("run_id"):
                runs = list(signal.attached_runs or [])
                if data["run_id"] not in runs:
                    runs.append(data["run_id"])
                signal.attached_runs = runs
                signal.latest_run_id = data["run_id"]
            signal.updated_at = _now()
            await db.commit()
            await db.refresh(transition)
            return self._transition_to_dict(transition), None

    async def create_review(self, signal_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None
            audit_id = data.get("audit_id") or _audit_id("SIGNAL_REVIEW", signal_id)
            review = SignalReviewDB(
                review_id=_generate_id("SIGREV"),
                signal_id=signal_id,
                audit_id=audit_id,
                reviewer=data.get("reviewer", "human"),
                review_type=data.get("review_type", "MANUAL"),
                decision=data.get("decision", "PENDING"),
                note=data.get("note", ""),
                review_fields=data.get("review_fields", []),
                created_at=_now(),
            )
            signal.audit_id = audit_id
            signal.updated_at = _now()
            db.add(review)
            await db.commit()
            await db.refresh(review)
            return self._review_to_dict(review)

    async def create_paper_portfolio(self, signal_id: str, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None, "Signal not found"
            reason = self._paper_enable_reason(signal)
            if reason:
                return None, reason
            existing = await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal_id))
            record = existing.scalar_one_or_none()
            if record:
                return self._portfolio_to_dict(record), None

            portfolio_id = _generate_id("PAPERPF")
            portfolio = PaperPortfolioDB(
                portfolio_id=portfolio_id,
                signal_id=signal_id,
                audit_id=data.get("audit_id") or _audit_id("PAPER_PORTFOLIO", signal_id),
                run_id=data.get("run_id") or signal.latest_run_id,
                symbol=signal.symbol,
                initial_cash=float(data.get("initial_cash", 100000.0)),
                available_cash=float(data.get("initial_cash", 100000.0)),
                market_value=0.0,
                risk_budget=data.get("risk_budget", {}),
                created_by_agent=data.get("created_by_agent", "signalops"),
                simulation_only=True,
                is_real_trade=False,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(portfolio)
            await db.commit()
            await db.refresh(portfolio)
            return self._portfolio_to_dict(portfolio), None

    async def get_paper_portfolio(self, signal_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal_id))
            record = result.scalar_one_or_none()
            return self._portfolio_to_dict(record) if record else None

    async def sync_paper_portfolio_budget(
        self,
        signal_id: str,
        initial_cash: float,
        risk_budget: Optional[Dict[str, Any]] = None,
        *,
        preserve_available_cash: bool = False,
    ) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal_id))
            record = result.scalar_one_or_none()
            if not record:
                return None
            budget = max(float(initial_cash or 0.0), 0.0)
            market_value = float(record.market_value or 0.0)
            record.initial_cash = budget
            if not preserve_available_cash:
                if market_value >= 0:
                    record.available_cash = max(budget - market_value, 0.0)
                else:
                    record.available_cash = max(float(record.available_cash or budget), 0.0)
            if risk_budget:
                record.risk_budget = {**(record.risk_budget or {}), **risk_budget}
            record.updated_at = _now()
            await db.commit()
            await db.refresh(record)
            return self._portfolio_to_dict(record)

    async def list_paper_orders(self, signal_id: str) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PaperOrderDB)
                .where(PaperOrderDB.signal_id == signal_id)
                .order_by(desc(PaperOrderDB.created_at))
            )
            return [self._order_to_dict(record) for record in result.scalars().all()]

    async def list_paper_positions(self, signal_id: str) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            portfolio = (
                await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal_id))
            ).scalar_one_or_none()
            result = await db.execute(
                select(PaperPositionDB)
                .where(PaperPositionDB.signal_id == signal_id)
                .where(PaperPositionDB.quantity != 0)
                .order_by(desc(PaperPositionDB.updated_at))
            )
            positions = result.scalars().all()
            if portfolio and self._normalize_positions_to_board_lots(portfolio, positions):
                await db.commit()
            return [self._position_to_dict(record) for record in positions if abs(float(record.quantity or 0.0)) > 0]

    async def mark_paper_portfolio_to_market(self, signal_id: str, price: float) -> Optional[Dict[str, Any]]:
        if price <= 0:
            return await self.get_paper_portfolio(signal_id)
        async with AsyncSessionLocal() as db:
            portfolio = (
                await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal_id))
            ).scalar_one_or_none()
            if not portfolio:
                return None
            result = await db.execute(select(PaperPositionDB).where(PaperPositionDB.signal_id == signal_id))
            positions = result.scalars().all()
            self._normalize_positions_to_board_lots(portfolio, positions, mark_price=price)
            await db.commit()
            await db.refresh(portfolio)
            return self._portfolio_to_dict(portfolio)

    async def create_paper_order(self, signal_id: str, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None, "Signal not found"
            reason = self._paper_enable_reason(signal)
            if reason:
                return None, reason
            portfolio = (await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.signal_id == signal_id))).scalar_one_or_none()
            if not portfolio:
                return None, "Paper portfolio must be created before paper orders."

            action = str(data.get("action", "")).upper()
            if action not in SIM_ACTIONS:
                return None, "Paper order action must be one of SIM_BUY, SIM_SELL, SIM_HOLD, SIM_REBALANCE, SIM_CLOSE, SIM_T_BUY, SIM_T_SELL, SIM_SHORT, SIM_COVER."
            if self._must_avoid_new_risk(signal, data) and action not in NO_RISK_ACTIONS:
                return None, "Kill Switch/Risk/DVG gate only allows SIM_HOLD or risk-reducing paper actions."
            simulated_quantity = float(data.get("simulated_quantity", 0.0))
            if action in {"SIM_BUY", "SIM_SELL", "SIM_CLOSE", "SIM_T_BUY", "SIM_T_SELL", "SIM_SHORT", "SIM_COVER"}:
                simulated_quantity = _board_lot_quantity(simulated_quantity)
                if simulated_quantity <= 0:
                    return None, "Paper order quantity must be an integer board lot of 100 shares."

            risk_constraints = {
                **(data.get("risk_constraints", {}) or {}),
                "simulation_only": True,
                "is_real_trade": False,
                "paper_gate_warnings": self._paper_gate_warnings(signal),
            }

            order = PaperOrderDB(
                order_id=_generate_id("PAPERORD"),
                paper_portfolio_id=portfolio.portfolio_id,
                signal_id=signal_id,
                audit_id=data.get("audit_id") or _audit_id("PAPER_ORDER", signal_id),
                run_id=data.get("run_id") or signal.latest_run_id,
                agent_id=data.get("agent_id", "paper_trading_agent"),
                action=action,
                action_reason=data.get("action_reason", ""),
                simulated_price=float(data.get("simulated_price", 0.0)),
                simulated_quantity=simulated_quantity,
                fill_status="PENDING",
                risk_constraints=risk_constraints,
                invalidation_conditions=signal.invalidation_conditions or [],
                data_snapshot_hash=data.get("data_snapshot_hash", ""),
                simulated_fill={},
                simulation_only=True,
                is_real_trade=False,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(order)
            await db.commit()
            await db.refresh(order)
            return self._order_to_dict(order), None

    async def fill_paper_order(self, signal_id: str, order_id: str, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        async with AsyncSessionLocal() as db:
            order = (
                await db.execute(
                    select(PaperOrderDB).where(PaperOrderDB.signal_id == signal_id, PaperOrderDB.order_id == order_id)
                )
            ).scalar_one_or_none()
            if not order:
                return None, "Paper order not found"
            if order.fill_status == "FILLED":
                return self._order_to_dict(order), None
            portfolio = (
                await db.execute(select(PaperPortfolioDB).where(PaperPortfolioDB.portfolio_id == order.paper_portfolio_id))
            ).scalar_one_or_none()
            if not portfolio:
                return None, "Paper portfolio not found"

            price = float(data.get("filled_price") or order.simulated_price or 0.0)
            qty = float(data.get("filled_quantity") or order.simulated_quantity or 0.0)
            if order.action in {"SIM_BUY", "SIM_SELL", "SIM_CLOSE", "SIM_T_BUY", "SIM_T_SELL", "SIM_SHORT", "SIM_COVER"}:
                qty = _board_lot_quantity(qty)
                if qty <= 0:
                    return None, "Paper fill quantity must be an integer board lot of 100 shares."
            fees = float(data.get("fees", 0.0))
            slippage = float(data.get("slippage", 0.0))
            amount = max(price * qty, 0.0)
            order.fill_status = data.get("fill_status", "FILLED")
            order.simulated_fill = {
                "filled_price": price,
                "filled_quantity": qty,
                "fees": fees,
                "slippage": slippage,
                "fill_status": order.fill_status,
            }
            order.updated_at = _now()
            if order.fill_status == "FILLED":
                if order.action in {"SIM_BUY", "SIM_T_BUY"}:
                    portfolio.available_cash = max(float(portfolio.available_cash or 0.0) - amount - fees, 0.0)
                    portfolio.market_value = float(portfolio.market_value or 0.0) + amount
                    await self._apply_position_delta(db, portfolio.portfolio_id, signal_id, portfolio.symbol, qty, price)
                elif order.action in {"SIM_SELL", "SIM_CLOSE", "SIM_T_SELL"}:
                    portfolio.available_cash = float(portfolio.available_cash or 0.0) + amount - fees
                    portfolio.market_value = max(float(portfolio.market_value or 0.0) - amount, 0.0)
                    await self._apply_position_delta(db, portfolio.portfolio_id, signal_id, portfolio.symbol, -qty, price)
                elif order.action == "SIM_SHORT":
                    portfolio.available_cash = float(portfolio.available_cash or 0.0) + amount - fees
                    portfolio.market_value = float(portfolio.market_value or 0.0) - amount
                    await self._apply_position_delta(db, portfolio.portfolio_id, signal_id, portfolio.symbol, -qty, price)
                elif order.action == "SIM_COVER":
                    portfolio.available_cash = max(float(portfolio.available_cash or 0.0) - amount - fees, 0.0)
                    portfolio.market_value = float(portfolio.market_value or 0.0) + amount
                    await self._apply_position_delta(db, portfolio.portfolio_id, signal_id, portfolio.symbol, qty, price)
                positions_result = await db.execute(
                    select(PaperPositionDB).where(PaperPositionDB.portfolio_id == portfolio.portfolio_id)
                )
                self._normalize_positions_to_board_lots(portfolio, list(positions_result.scalars().all()), mark_price=price)
                portfolio.updated_at = _now()
            execution = PaperExecutionDB(
                execution_id=_generate_id("PAPEREXEC"),
                order_id=order.order_id,
                paper_portfolio_id=order.paper_portfolio_id,
                signal_id=signal_id,
                audit_id=data.get("audit_id") or order.audit_id,
                fill_status=order.fill_status,
                filled_price=price,
                filled_quantity=qty,
                fees=fees,
                slippage=slippage,
                rule_checks=data.get("rule_checks", []),
                created_at=_now(),
            )
            db.add(execution)
            await db.commit()
            await db.refresh(order)
            return self._order_to_dict(order), None

    async def update_paper_order_risk_constraints(
        self,
        signal_id: str,
        order_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            order = (
                await db.execute(
                    select(PaperOrderDB).where(PaperOrderDB.signal_id == signal_id, PaperOrderDB.order_id == order_id)
                )
            ).scalar_one_or_none()
            if not order:
                return None
            risk_constraints = order.risk_constraints if isinstance(order.risk_constraints, dict) else {}
            order.risk_constraints = {
                **risk_constraints,
                **updates,
                "simulation_only": True,
                "is_real_trade": False,
            }
            order.updated_at = _now()
            await db.commit()
            await db.refresh(order)
            return self._order_to_dict(order)

    async def create_agent_simulation_case(self, signal_id: str, data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        async with AsyncSessionLocal() as db:
            signal = await self._get_signal(db, signal_id)
            if not signal:
                return None, "Signal not found"
            order_id = data.get("source_paper_order_id")
            order = (
                await db.execute(
                    select(PaperOrderDB).where(PaperOrderDB.signal_id == signal_id, PaperOrderDB.order_id == order_id)
                )
            ).scalar_one_or_none()
            if not order:
                return None, "Paper order not found"
            existing = (
                await db.execute(
                    select(AgentSimulationCaseDB).where(AgentSimulationCaseDB.source_paper_order_id == order.order_id)
                )
            ).scalar_one_or_none()
            if existing:
                return self._case_to_dict(existing), None
            case = AgentSimulationCaseDB(
                case_id=_generate_id("SIMCASE"),
                case_source="AGENT_SIMULATION",
                operator_type="AGENT",
                source_signal_id=signal_id,
                source_paper_order_id=order.order_id,
                run_id=order.run_id,
                agent_id=order.agent_id,
                audit_id=data.get("audit_id") or _audit_id("SIM_CASE", signal_id),
                simulation_only=True,
                is_real_trade=False,
                outcome=data.get("outcome", {}),
                failure_tags=data.get("failure_tags", []),
                knowledge_candidate_status=data.get("knowledge_candidate_status", "REVIEWING"),
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(case)
            await db.commit()
            await db.refresh(case)
            return self._case_to_dict(case), None

    async def list_agent_simulation_cases(
        self,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(AgentSimulationCaseDB)
            if source:
                query = query.where(AgentSimulationCaseDB.case_source == source)
            query = query.order_by(desc(AgentSimulationCaseDB.created_at)).limit(limit)
            result = await db.execute(query)
            cases = [self._case_to_dict(record) for record in result.scalars().all()]

            if source in (None, "AGENT_SIMULATION"):
                existing_order_ids = {case.get("source_paper_order_id") for case in cases}
                order_result = await db.execute(
                    select(PaperOrderDB, SignalDB, PaperPortfolioDB)
                    .join(SignalDB, SignalDB.signal_id == PaperOrderDB.signal_id)
                    .outerjoin(PaperPortfolioDB, PaperPortfolioDB.portfolio_id == PaperOrderDB.paper_portfolio_id)
                    .where(PaperOrderDB.simulation_only.is_(True))
                    .order_by(desc(PaperOrderDB.created_at))
                    .limit(limit)
                )
                for order, signal, portfolio in order_result.all():
                    if order.order_id in existing_order_ids:
                        continue
                    cases.append(self._case_from_paper_order(signal, order, portfolio))

            return sorted(cases, key=lambda item: item.get("created_at") or "", reverse=True)[:limit]

    async def _get_signal(self, db, signal_id: str) -> Optional[SignalDB]:
        result = await db.execute(select(SignalDB).where(SignalDB.signal_id == signal_id))
        return result.scalar_one_or_none()

    async def _apply_position_delta(self, db, portfolio_id: str, signal_id: str, symbol: str, qty_delta: float, price: float) -> None:
        result = await db.execute(select(PaperPositionDB).where(PaperPositionDB.portfolio_id == portfolio_id, PaperPositionDB.symbol == symbol))
        position = result.scalar_one_or_none()
        if position:
            current_qty = float(position.quantity or 0.0)
            next_qty = current_qty + qty_delta
            if abs(next_qty) < 0.000001:
                position.virtual_cost = 0.0
                next_qty = 0.0
            elif current_qty == 0 or current_qty * qty_delta > 0:
                position.virtual_cost = (
                    (float(position.virtual_cost or 0.0) * abs(current_qty)) + abs(qty_delta) * price
                ) / abs(next_qty)
            elif current_qty * next_qty < 0:
                position.virtual_cost = price
            position.quantity = next_qty
            position.current_value = next_qty * price
            position.floating_pnl = position.current_value - position.virtual_cost * next_qty
            position.updated_at = _now()
        else:
            db.add(PaperPositionDB(
                position_id=_generate_id("PAPERPOS"),
                portfolio_id=portfolio_id,
                signal_id=signal_id,
                symbol=symbol,
                quantity=qty_delta,
                virtual_cost=price,
                current_value=qty_delta * price,
                floating_pnl=0.0,
                max_drawdown=0.0,
                updated_at=_now(),
            ))

    def _normalize_positions_to_board_lots(
        self,
        portfolio: PaperPortfolioDB,
        positions: List[PaperPositionDB],
        mark_price: Optional[float] = None,
    ) -> bool:
        changed = False
        market_value = 0.0
        released_cash = 0.0
        for position in positions:
            old_qty = float(position.quantity or 0.0)
            lot_qty = _board_lot_quantity(abs(old_qty))
            if old_qty < 0:
                lot_qty = -lot_qty
            cost = float(position.virtual_cost or 0.0)
            price = float(mark_price or 0.0)
            if price <= 0 and abs(old_qty) > 0 and float(position.current_value or 0.0) != 0:
                price = abs(float(position.current_value or 0.0) / old_qty)
            if price <= 0:
                price = cost

            if abs(old_qty - lot_qty) > 0.000001:
                released_cash += max(old_qty - lot_qty, 0.0) * cost
                position.quantity = lot_qty
                changed = True

            current_value = lot_qty * price
            cost_value = lot_qty * cost
            position.current_value = current_value
            position.floating_pnl = current_value - cost_value
            exposure_cost = abs(lot_qty) * cost
            if exposure_cost > 0:
                drawdown = min(0.0, position.floating_pnl / exposure_cost)
                position.max_drawdown = min(float(position.max_drawdown or 0.0), drawdown)
            if changed or mark_price:
                position.updated_at = _now()
            market_value += current_value

        if changed or mark_price:
            portfolio.available_cash = float(portfolio.available_cash or 0.0) + released_cash
            portfolio.market_value = market_value
            portfolio.updated_at = _now()
        return changed

    def _gate_checks(self, signal: SignalDB, target: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = []
        current = signal.status
        if current == "CLOSED" and target != "PATCH_REQUIRED":
            checks.append({"key": "not_closed", "passed": False, "message": "Closed signals cannot be upgraded."})
            return checks
        if target == "PATCH_REQUIRED":
            return [{"key": "patch_required_allowed", "passed": True, "message": "PATCH_REQUIRED can be entered from any active status."}]
        if target == current:
            return [{"key": "same_status", "passed": True, "message": "Signal already has this status."}]
        if target == "CLOSED":
            return [{"key": "close_allowed", "passed": True, "message": "Signal can be closed for archive."}]
        if _status_index(target) <= _status_index(current):
            checks.append({"key": "forward_only", "passed": False, "message": "Lifecycle transitions must move forward or close."})
            return checks
        if target == "WATCH":
            checks.append({
                "key": "basic_analysis_completed",
                "passed": bool(context.get("basic_analysis_completed") or signal.source_run_id or signal.attached_runs),
                "message": "WATCH requires a source run or basic_analysis_completed=true.",
            })
        if _status_index(target) >= _status_index("PAPER_TEST"):
            checks.extend([
                {
                    "key": "ai_paper_sandbox_allowed",
                    "passed": True,
                    "message": "PAPER_TEST uses AI-generated conditions and allows sandbox exploration.",
                },
                {
                    "key": "risk_advisory_only",
                    "passed": True,
                    "message": "Risk Firewall is advisory for PAPER_TEST simulation.",
                },
                {
                    "key": "dvg_advisory_only",
                    "passed": True,
                    "message": "DVG is advisory for PAPER_TEST simulation.",
                },
            ])
        if _status_index(target) >= _status_index("QUALIFIED"):
            checks.extend([
                {
                    "key": "ai_invalidation_allowed",
                    "passed": True,
                    "message": "QUALIFIED can use AI-generated invalidation conditions.",
                },
                {"key": "dvg_passed", "passed": bool(signal.dvg_passed), "message": "DVG must pass before QUALIFIED."},
                {"key": "dvg_not_review_only", "passed": str(signal.dvg_status).upper() != "REVIEW_ONLY", "message": "DVG REVIEW_ONLY cannot enter QUALIFIED."},
                {"key": "qiam_passed", "passed": bool(signal.qiam_passed), "message": "QIAM must pass before QUALIFIED."},
            ])
        if _status_index(target) >= _status_index("TRADE_PLAN"):
            checks.extend([
                {"key": "qiam_not_block_buy", "passed": str(signal.qiam_status).upper() != "BLOCK_BUY", "message": "QIAM BLOCK_BUY cannot enter TRADE_PLAN."},
                {"key": "execution_reachable", "passed": bool(signal.execution_reachable), "message": "ATrade/Execution must be reachable before TRADE_PLAN."},
                {"key": "portfolio_allowed", "passed": bool(signal.portfolio_allowed), "message": "Portfolio constraints must allow TRADE_PLAN."},
            ])
        if _status_index(target) >= _status_index("MANUAL_CONFIRMED"):
            checks.append({
                "key": "manual_confirmed",
                "passed": bool(context.get("manual_confirmed")),
                "message": "MANUAL_CONFIRMED requires explicit manual_confirmed=true.",
            })
        if _status_index(target) >= _status_index("EXECUTION_REVIEW"):
            checks.append({
                "key": "execution_completed",
                "passed": bool(context.get("execution_completed")),
                "message": "EXECUTION_REVIEW requires execution_completed=true.",
            })
        return checks or [{"key": "forward_transition", "passed": True, "message": "Forward transition allowed."}]

    def _paper_enable_reason(self, signal: SignalDB) -> str:
        if signal.status == "CLOSED":
            return "Closed signals cannot create paper portfolios."
        return ""

    def _must_avoid_new_risk(self, signal: SignalDB, data: Dict[str, Any]) -> bool:
        risk = data.get("risk_constraints", {}) or {}
        return bool(risk.get("kill_switch_active"))

    def _paper_gate_warnings(self, signal: SignalDB) -> List[str]:
        warnings: List[str] = []
        if signal.status not in PAPER_ENABLED_STATUSES:
            warnings.append("signal_not_in_paper_test")
        if not signal.risk_passed:
            warnings.append("risk_not_passed")
        if str(signal.dvg_status).upper() == "BLOCK_BUY":
            warnings.append("dvg_block_buy")
        if not signal.qiam_passed:
            warnings.append("qiam_not_passed")
        if not signal.execution_reachable:
            warnings.append("execution_not_reachable")
        return warnings

    def _signal_to_dict(self, record: SignalDB) -> Dict[str, Any]:
        return {
            "signal_id": record.signal_id,
            "symbol": record.symbol,
            "stock_name": record.stock_name,
            "status": record.status,
            "source_run_id": record.source_run_id,
            "latest_run_id": record.latest_run_id,
            "audit_id": record.audit_id,
            "risk_passed": record.risk_passed,
            "dvg_passed": record.dvg_passed,
            "dvg_status": record.dvg_status,
            "qiam_passed": record.qiam_passed,
            "qiam_status": record.qiam_status,
            "execution_reachable": record.execution_reachable,
            "portfolio_allowed": record.portfolio_allowed,
            "trigger_conditions": record.trigger_conditions or [],
            "invalidation_conditions": record.invalidation_conditions or [],
            "review_fields": record.review_fields or [],
            "attached_runs": record.attached_runs or [],
            "blocked_reason": record.blocked_reason or "",
            "metadata_json": record.metadata_json or {},
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _transition_to_dict(self, record: SignalTransitionDB) -> Dict[str, Any]:
        return {
            "transition_id": record.transition_id,
            "signal_id": record.signal_id,
            "from_status": record.from_status,
            "to_status": record.to_status,
            "audit_id": record.audit_id,
            "run_id": record.run_id,
            "actor": record.actor,
            "reason": record.reason,
            "gate_checks": record.gate_checks or [],
            "passed": record.passed,
            "simulation_only": True,
            "is_real_trade": False,
            "created_at": record.created_at,
        }

    def _review_to_dict(self, record: SignalReviewDB) -> Dict[str, Any]:
        return {
            "review_id": record.review_id,
            "signal_id": record.signal_id,
            "audit_id": record.audit_id,
            "reviewer": record.reviewer,
            "review_type": record.review_type,
            "decision": record.decision,
            "note": record.note,
            "review_fields": record.review_fields or [],
            "simulation_only": True,
            "is_real_trade": False,
            "created_at": record.created_at,
        }

    def _portfolio_to_dict(self, record: PaperPortfolioDB) -> Dict[str, Any]:
        return {
            "portfolio_id": record.portfolio_id,
            "signal_id": record.signal_id,
            "audit_id": record.audit_id,
            "run_id": record.run_id,
            "symbol": record.symbol,
            "initial_cash": record.initial_cash,
            "available_cash": record.available_cash,
            "market_value": record.market_value,
            "max_drawdown": record.max_drawdown,
            "risk_budget": record.risk_budget or {},
            "created_by_agent": record.created_by_agent,
            "simulation_only": record.simulation_only,
            "is_real_trade": record.is_real_trade,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _order_to_dict(self, record: PaperOrderDB) -> Dict[str, Any]:
        risk_constraints = record.risk_constraints or {}
        return {
            "order_id": record.order_id,
            "paper_portfolio_id": record.paper_portfolio_id,
            "signal_id": record.signal_id,
            "audit_id": record.audit_id,
            "run_id": record.run_id,
            "agent_id": record.agent_id,
            "action": record.action,
            "action_reason": record.action_reason,
            "simulated_price": record.simulated_price,
            "simulated_quantity": record.simulated_quantity,
            "fill_status": record.fill_status,
            "risk_constraints": risk_constraints,
            "decision_card": risk_constraints.get("decision_card") if isinstance(risk_constraints, dict) else None,
            "invalidation_conditions": record.invalidation_conditions or [],
            "data_snapshot_hash": record.data_snapshot_hash,
            "simulated_fill": record.simulated_fill or {},
            "simulation_only": record.simulation_only,
            "is_real_trade": record.is_real_trade,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _position_to_dict(self, record: PaperPositionDB) -> Dict[str, Any]:
        current_value = float(record.current_value or 0.0)
        virtual_cost = float(record.virtual_cost or 0.0)
        quantity = float(record.quantity or 0.0)
        return {
            "position_id": record.position_id,
            "portfolio_id": record.portfolio_id,
            "signal_id": record.signal_id,
            "symbol": record.symbol,
            "quantity": record.quantity,
            "virtual_cost": record.virtual_cost,
            "current_value": record.current_value,
            "floating_pnl": record.floating_pnl,
            "max_drawdown": record.max_drawdown,
            "capital_attribution": {
                "position_value": current_value,
                "cost_basis_value": virtual_cost * quantity,
                "floating_pnl": float(record.floating_pnl or 0.0),
                "exposure_value": abs(current_value),
            },
            "simulation_only": True,
            "is_real_trade": False,
            "updated_at": record.updated_at,
        }

    def _case_to_dict(self, record: AgentSimulationCaseDB) -> Dict[str, Any]:
        return {
            "case_id": record.case_id,
            "case_source": record.case_source,
            "operator_type": record.operator_type,
            "source_signal_id": record.source_signal_id,
            "source_paper_order_id": record.source_paper_order_id,
            "run_id": record.run_id,
            "agent_id": record.agent_id,
            "audit_id": record.audit_id,
            "simulation_only": record.simulation_only,
            "is_real_trade": record.is_real_trade,
            "outcome": record.outcome or {},
            "failure_tags": record.failure_tags or [],
            "knowledge_candidate_status": record.knowledge_candidate_status,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _case_from_paper_order(
        self,
        signal: SignalDB,
        order: PaperOrderDB,
        portfolio: Optional[PaperPortfolioDB],
    ) -> Dict[str, Any]:
        warnings = (order.risk_constraints or {}).get("paper_gate_warnings", [])
        executable_actions = {"SIM_BUY", "SIM_SELL", "SIM_CLOSE", "SIM_REBALANCE", "SIM_T_BUY", "SIM_T_SELL", "SIM_SHORT", "SIM_COVER"}
        has_trade_metrics = order.action in executable_actions
        fill = order.simulated_fill or {}
        metric_price = float(fill.get("filled_price") or order.simulated_price or 0.0) if has_trade_metrics else None
        metric_quantity = float(fill.get("filled_quantity") or order.simulated_quantity or 0.0) if has_trade_metrics else None
        simulated_value = (
            metric_price * metric_quantity
            if metric_price is not None and metric_quantity is not None
            else None
        )
        outcome = {
            "source": "paper_order",
            "review_required": True,
            "symbol": signal.symbol,
            "stock_name": signal.stock_name,
            "signal_status": signal.status,
            "paper_action": order.action,
            "action_reason": order.action_reason,
            "fill_status": order.fill_status if has_trade_metrics else "OBSERVED",
            "trade_metrics_available": has_trade_metrics,
            "metric_note": "模拟成交数据来自 paper_order/simulated_fill" if has_trade_metrics else "SIM_HOLD 是观察动作，无模拟成交价、数量或金额",
            "simulated_price": metric_price,
            "simulated_quantity": metric_quantity,
            "simulated_value": simulated_value,
            "risk_constraints": order.risk_constraints or {},
            "invalidation_conditions": order.invalidation_conditions or [],
            "data_snapshot_hash": order.data_snapshot_hash,
            "simulated_fill": order.simulated_fill or {},
            "knowledge_use": "非真实交易，仅用于知识迭代",
        }
        if portfolio:
            outcome["portfolio"] = {
                "portfolio_id": portfolio.portfolio_id,
                "initial_cash": portfolio.initial_cash,
                "available_cash": portfolio.available_cash,
                "market_value": portfolio.market_value,
                "max_drawdown": portfolio.max_drawdown,
            }
        return {
            "case_id": f"SIMCASE_DERIVED_{order.order_id}",
            "case_source": "AGENT_SIMULATION",
            "operator_type": "AGENT",
            "source_signal_id": signal.signal_id,
            "source_paper_order_id": order.order_id,
            "run_id": order.run_id,
            "agent_id": order.agent_id,
            "audit_id": order.audit_id,
            "simulation_only": True,
            "is_real_trade": False,
            "outcome": outcome,
            "failure_tags": ["PAPER_GATE_WARNING"] if warnings else [],
            "knowledge_candidate_status": "REVIEWING",
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }


signalops_store = SignalOpsStore()


def _signal_payload_from_run(
    run_data: Dict[str, Any],
    signal_data: Dict[str, Any],
    symbol: str,
    run_id: str,
) -> Dict[str, Any]:
    dvg = run_data.get("dvg") if isinstance(run_data.get("dvg"), dict) else {}
    qiam = run_data.get("qiam") if isinstance(run_data.get("qiam"), dict) else {}
    portfolio = run_data.get("portfolio") if isinstance(run_data.get("portfolio"), dict) else {}
    execution = run_data.get("execution") if isinstance(run_data.get("execution"), dict) else {}
    final_writer = run_data.get("finalWriter") if isinstance(run_data.get("finalWriter"), dict) else {}
    return {
        "stock_name": run_data.get("stockName", ""),
        "audit_id": signal_data.get("auditId") or final_writer.get("auditId") or _audit_id("SIGNAL_RUN", run_id or symbol),
        "risk_passed": bool(signal_data.get("riskPassed", False)),
        "dvg_passed": bool(signal_data.get("dvgPassed", False)),
        "dvg_status": dvg.get("allowedOutputLevel") or dvg.get("dataReliability") or "",
        "qiam_passed": bool(signal_data.get("qiamPassed", False)),
        "qiam_status": qiam.get("finalBuySuitability", ""),
        "execution_reachable": bool(signal_data.get("executionReachable", False)),
        "portfolio_allowed": bool(portfolio.get("allowAddPosition", True)),
        "trigger_conditions": list(signal_data.get("triggerConditions") or []),
        "invalidation_conditions": list(signal_data.get("invalidationConditions") or []),
        "review_fields": list(signal_data.get("reviewFields") or []),
        "blocked_reason": signal_data.get("blockedReason", ""),
        "metadata_json": {
            "source": "analysis_run_auto_upsert",
            "run_id": run_id,
            "data_mode": run_data.get("dataMode"),
            "final_action": final_writer.get("finalAction") or run_data.get("finalAction"),
            "portfolio_coverage": portfolio.get("portfolioCoverage"),
            "execution_allowed_actions": execution.get("allowedActions", []),
        },
    }
