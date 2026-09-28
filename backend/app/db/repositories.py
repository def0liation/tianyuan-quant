from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from .session import AsyncSessionLocal
from . import models as m


class RunRepository:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self, run_data: dict) -> m.AnalysisRunDB:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            run_id = run_data.get("runId", run_data.get("run_id", ""))
            audit_id = run_data.get("auditId") or run_data.get("audit_id") or f"AUD_{run_id}"
            values = dict(
                audit_id=audit_id,
                run_id=run_id,
                symbol=run_data.get("stockCode", run_data.get("symbol", "")),
                stock_name=run_data.get("stockName", run_data.get("stock_name", "")),
                task_type=run_data.get("taskType", run_data.get("task_type", "")),
                run_mode=run_data.get("runMode", run_data.get("run_mode", "STANDARD_MODE")),
                runtime_environment=run_data.get("environment", run_data.get("runtime_environment", "API_ORCHESTRATED")),
                data_mode=run_data.get("dataMode", run_data.get("data_mode", "MOCK")),
                final_action=(
                    run_data.get("finalWriter", {}).get("finalAction")
                    or run_data.get("finalAction", run_data.get("final_action", "WAIT"))
                ),
                final_report=run_data.get("final_report", ""),
                success=run_data.get("success", run_data.get("status") != "FAILED"),
                created_at=run_data.get("createdAt", run_data.get("created_at", "")),
                updated_at=run_data.get("updatedAt", run_data.get("updated_at", "")),
            )

            result = await db.execute(select(m.AnalysisRunDB).where(m.AnalysisRunDB.audit_id == audit_id))
            record = result.scalar_one_or_none()
            if record is None:
                record = m.AnalysisRunDB(**values)
                db.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
            await db.commit()
            await db.refresh(record)
            return record
        finally:
            if not is_managed:
                await db.close()

    async def list_recent(self, limit: int = 50) -> list[dict]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(
                select(m.AnalysisRunDB).order_by(m.AnalysisRunDB.created_at.desc()).limit(limit)
            )
            records = result.scalars().all()
            return [
                {
                    "runId": r.run_id,
                    "auditId": r.audit_id,
                    "stockCode": r.symbol,
                    "stockName": r.stock_name,
                    "taskType": r.task_type,
                    "runMode": r.run_mode,
                    "status": "COMPLETED",
                    "finalAction": r.final_action,
                    "createdAt": r.created_at,
                    "updatedAt": r.updated_at,
                }
                for r in records
            ]
        finally:
            if not is_managed:
                await db.close()

    async def find_by_audit_id(self, audit_id: str) -> dict | None:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(select(m.AnalysisRunDB).where(m.AnalysisRunDB.audit_id == audit_id))
            record = result.scalar_one_or_none()
            if not record:
                return None
            return {
                "runId": record.run_id,
                "auditId": record.audit_id,
                "stockCode": record.symbol,
                "stockName": record.stock_name,
                "taskType": record.task_type,
                "runMode": record.run_mode,
                "finalAction": record.final_action,
                "createdAt": record.created_at,
                "updatedAt": record.updated_at,
            }
        finally:
            if not is_managed:
                await db.close()

    async def find_by_run_id(self, run_id: str) -> m.AnalysisRunDB | None:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(select(m.AnalysisRunDB).where(m.AnalysisRunDB.run_id == run_id))
            return result.scalar_one_or_none()
        finally:
            if not is_managed:
                await db.close()

    async def delete_by_run_id(self, run_id: str) -> int:
        from sqlalchemy import delete
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(delete(m.AnalysisRunDB).where(m.AnalysisRunDB.run_id == run_id))
            await db.execute(delete(m.AgentResultDB).where(m.AgentResultDB.run_id == run_id))
            await db.execute(delete(m.AuditLogDB).where(m.AuditLogDB.run_id == run_id))
            await db.execute(delete(m.KillSwitchEventDB).where(m.KillSwitchEventDB.run_id == run_id))
            await db.execute(delete(m.DVGResultDB).where(m.DVGResultDB.run_id == run_id))
            await db.execute(delete(m.DataSnapshotDB).where(m.DataSnapshotDB.run_id == run_id))
            await db.execute(delete(m.StateSnapshotDB).where(m.StateSnapshotDB.run_id == run_id))
            await db.execute(delete(m.SignalOpsRecordDB).where(m.SignalOpsRecordDB.run_id == run_id))
            await db.execute(delete(m.PaperTradeRecordDB).where(m.PaperTradeRecordDB.run_id == run_id))
            await db.execute(delete(m.FinalReportDB).where(m.FinalReportDB.run_id == run_id))
            await db.execute(delete(m.SignalTransitionDB).where(m.SignalTransitionDB.run_id == run_id))
            await db.execute(delete(m.PaperPortfolioDB).where(m.PaperPortfolioDB.run_id == run_id))
            await db.execute(delete(m.PaperOrderDB).where(m.PaperOrderDB.run_id == run_id))
            await db.execute(delete(m.AgentSimulationCaseDB).where(m.AgentSimulationCaseDB.run_id == run_id))

            signal_result = await db.execute(select(m.SignalDB))
            for signal in signal_result.scalars().all():
                runs = [item for item in (signal.attached_runs or []) if item != run_id]
                touched = len(runs) != len(signal.attached_runs or [])
                if signal.source_run_id == run_id:
                    signal.source_run_id = runs[0] if runs else None
                    touched = True
                if signal.latest_run_id == run_id:
                    signal.latest_run_id = runs[-1] if runs else None
                    touched = True
                if touched:
                    signal.attached_runs = runs
                    signal.updated_at = m.utcnow()
                if touched and not runs and not signal.source_run_id and not signal.latest_run_id:
                    signal_id = signal.signal_id
                    await db.execute(delete(m.SignalReviewDB).where(m.SignalReviewDB.signal_id == signal_id))
                    await db.execute(delete(m.SignalWatchConditionDB).where(m.SignalWatchConditionDB.signal_id == signal_id))
                    await db.execute(delete(m.PaperExecutionDB).where(m.PaperExecutionDB.signal_id == signal_id))
                    await db.execute(delete(m.PaperOrderDB).where(m.PaperOrderDB.signal_id == signal_id))
                    await db.execute(delete(m.PaperPositionDB).where(m.PaperPositionDB.signal_id == signal_id))
                    await db.execute(delete(m.PaperPortfolioDB).where(m.PaperPortfolioDB.signal_id == signal_id))
                    await db.execute(delete(m.AgentSimulationCaseDB).where(m.AgentSimulationCaseDB.source_signal_id == signal_id))
                    await db.delete(signal)
            await db.commit()
            return result.rowcount
        finally:
            if not is_managed:
                await db.close()


class AgentResultRepository:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save_batch(self, agent_results: list[dict], run_id: str) -> list[m.AgentResultDB]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            records = []
            for ar in agent_results:
                record = m.AgentResultDB(
                    audit_id=ar.get("audit_id", ""),
                    run_id=run_id,
                    agent_name=ar.get("name", ar.get("agent_name", "")),
                    node=ar.get("node", ""),
                    status=ar.get("status", "PASS"),
                    confidence=ar.get("confidence", "HIGH"),
                    hard_stop=ar.get("hard_stop", False),
                    allowed_actions=ar.get("allowed_actions", []),
                    blocked_actions=ar.get("blocked_actions", []),
                    missing_data=ar.get("missing_data", []),
                    warnings=ar.get("warnings", []),
                    reasons=ar.get("reasons", []),
                    data_json=ar.get("data", {}),
                    elapsed_ms=ar.get("elapsed_ms", 0),
                    final_decision_cap=ar.get("final_decision_cap"),
                    skipped_reason=ar.get("skipped_reason"),
                )
                records.append(record)
            db.add_all(records)
            await db.commit()
            return records
        finally:
            if not is_managed:
                await db.close()

    async def find_by_run_id(self, run_id: str) -> list[dict]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(
                select(m.AgentResultDB).where(m.AgentResultDB.run_id == run_id)
            )
            records = result.scalars().all()
            return [
                {
                    "audit_id": r.audit_id,
                    "agent_name": r.agent_name,
                    "node": r.node,
                    "status": r.status,
                    "confidence": r.confidence,
                    "hard_stop": r.hard_stop,
                    "allowed_actions": r.allowed_actions,
                    "blocked_actions": r.blocked_actions,
                    "missing_data": r.missing_data,
                    "warnings": r.warnings,
                    "reasons": r.reasons,
                    "data": r.data_json,
                    "elapsed_ms": r.elapsed_ms,
                }
                for r in records
            ]
        finally:
            if not is_managed:
                await db.close()


class AuditRepository:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save_logs(self, audit_logs: list[dict]) -> list[m.AuditLogDB]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            records = []
            for al in audit_logs:
                record = m.AuditLogDB(
                    audit_id=al.get("auditId", al.get("audit_id", "")),
                    run_id=al.get("runId", al.get("run_id", "")),
                    event_type=al.get("eventType", al.get("event_type", "")),
                    node=al.get("node"),
                    message=al.get("message", ""),
                    status_before=al.get("statusBefore"),
                    status_after=al.get("statusAfter"),
                    input_hash=al.get("inputHash"),
                    output_hash=al.get("outputHash"),
                    payload_json=al,
                )
                records.append(record)
            db.add_all(records)
            await db.commit()
            return records
        finally:
            if not is_managed:
                await db.close()

    async def find_by_run_id(self, run_id: str) -> list[dict]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(
                select(m.AuditLogDB).where(m.AuditLogDB.run_id == run_id).order_by(m.AuditLogDB.created_at.asc())
            )
            records = result.scalars().all()
            return [
                {
                    "auditId": r.audit_id,
                    "runId": r.run_id,
                    "eventType": r.event_type,
                    "node": r.node,
                    "message": r.message,
                    "statusBefore": r.status_before,
                    "statusAfter": r.status_after,
                    "inputHash": r.input_hash,
                    "outputHash": r.output_hash,
                    "payload": r.payload_json,
                    "createdAt": r.created_at,
                }
                for r in records
            ]
        finally:
            if not is_managed:
                await db.close()


class KillSwitchRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self, kill_switch: dict, run_id: str) -> m.KillSwitchEventDB:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            record = m.KillSwitchEventDB(
                audit_id=kill_switch.get("auditId", kill_switch.get("audit_id", "")),
                run_id=run_id,
                active=kill_switch.get("active", False),
                level=kill_switch.get("level", "NONE"),
                trigger_node=kill_switch.get("triggerNode"),
                trigger_rule=kill_switch.get("triggerRule"),
                blocked_paths=kill_switch.get("blockedPaths", kill_switch.get("blocked_paths", [])),
                allowed_paths=kill_switch.get("allowedPaths", kill_switch.get("allowed_paths", [])),
                final_writer_mode=kill_switch.get("finalWriterMode", kill_switch.get("final_writer_mode", "CONSERVATIVE")),
                payload_json=kill_switch,
            )
            db.add(record)
            await db.commit()
            return record
        finally:
            if not is_managed:
                await db.close()


class DVGResultRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self, dvg: dict, run_id: str) -> m.DVGResultDB:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            record = m.DVGResultDB(
                audit_id=dvg.get("auditId", dvg.get("audit_id", "")),
                run_id=run_id,
                status=dvg.get("status", "PASS"),
                data_reliability=dvg.get("dataReliability", dvg.get("data_reliability", "HIGH")),
                confirmed_ratio=dvg.get("confirmedRatio", dvg.get("confirmed_ratio", 0.0)),
                inferred_ratio=dvg.get("inferredRatio", dvg.get("inferred_ratio", 0.0)),
                unknown_ratio=dvg.get("unknownRatio", dvg.get("unknown_ratio", 0.0)),
                core_unknown_count=dvg.get("coreUnknownCount", dvg.get("core_unknown_count", 0)),
                freshness_status=dvg.get("freshnessStatus", dvg.get("freshness_status", "UNKNOWN")),
                source_integrity=dvg.get("sourceIntegrity", dvg.get("source_integrity", "UNKNOWN")),
                qiam_permission=dvg.get("qiamPermission", dvg.get("qiam_permission", "ALLOW")),
                scenario_permission=dvg.get("scenarioPermission", dvg.get("scenario_permission", "ALLOW")),
                execution_permission=dvg.get("executionPermission", dvg.get("execution_permission", "ALLOW")),
                final_decision_cap=dvg.get("finalDecisionCap", dvg.get("final_decision_cap", "")),
                hallucination_risk_score=dvg.get("hallucinationRiskScore", dvg.get("hallucination_risk_score", 0)),
                hallucination_risk_level=dvg.get("hallucinationRiskLevel", dvg.get("hallucination_risk_level", "LOW")),
                hard_stop=dvg.get("hardStop", dvg.get("hard_stop", False)),
                critical_missing_data=dvg.get("criticalMissingData", dvg.get("critical_missing_data", [])),
                data_conflicts=dvg.get("dataConflicts", dvg.get("data_conflicts", [])),
                allowed_output_level=dvg.get("allowedOutputLevel", dvg.get("allowed_output_level", "FULL")),
                data_json=dvg,
            )
            db.add(record)
            await db.commit()
            return record
        finally:
            if not is_managed:
                await db.close()


class DataSnapshotRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save_snapshots(self, run_data: dict, run_id: str, audit_id: str, symbol: str) -> list[m.DataSnapshotDB]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            records = []
            for source_name in ["market", "finance", "announcement", "moneyflow", "chip"]:
                record = m.DataSnapshotDB(
                    audit_id=audit_id,
                    run_id=run_id,
                    symbol=symbol,
                    data_mode=run_data.get("data_mode", "MOCK"),
                    source_name=source_name,
                    adapter=f"{source_name}_adapter",
                    provider="mock",
                    success=True,
                    evidence_tag="I",
                    freshness_status="MOCK",
                    timestamp=run_data.get("createdAt", ""),
                    data_json={},
                )
                records.append(record)
            db.add_all(records)
            await db.commit()
            return records
        finally:
            if not is_managed:
                await db.close()


class StateSnapshotRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self, state: dict, run_id: str, audit_id: str) -> m.StateSnapshotDB:
        import hashlib, json
        state_str = json.dumps(state, sort_keys=True, default=str)
        checksum = hashlib.sha256(state_str.encode()).hexdigest()
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            record = m.StateSnapshotDB(
                audit_id=audit_id,
                run_id=run_id,
                snapshot_type="FULL",
                state_json=state,
                schema_version="10.2",
                checksum=checksum,
            )
            db.add(record)
            await db.commit()
            return record
        finally:
            if not is_managed:
                await db.close()

    async def find_by_run_id(self, run_id: str) -> list[dict]:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            result = await db.execute(select(m.StateSnapshotDB).where(m.StateSnapshotDB.run_id == run_id))
            records = result.scalars().all()
            return [
                {
                    "auditId": r.audit_id,
                    "runId": r.run_id,
                    "snapshot_type": r.snapshot_type,
                    "state_json": r.state_json,
                    "schema_version": r.schema_version,
                    "checksum": r.checksum,
                    "createdAt": r.created_at,
                }
                for r in records
            ]
        finally:
            if not is_managed:
                await db.close()


class SignalOpsRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self, signal: dict, run_id: str, symbol: str) -> m.SignalOpsRecordDB:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            record = m.SignalOpsRecordDB(
                audit_id=signal.get("auditId", signal.get("audit_id", "")),
                run_id=run_id,
                symbol=symbol,
                signal_status=signal.get("signalStatus", signal.get("signal_status", "WATCH")),
                risk_passed=signal.get("riskPassed", signal.get("risk_passed", False)),
                dvg_passed=signal.get("dvgPassed", signal.get("dvg_passed", False)),
                qiam_passed=signal.get("qiamPassed", signal.get("qiam_passed", False)),
                execution_reachable=signal.get("executionReachable", signal.get("execution_reachable", False)),
                trigger_conditions=signal.get("triggerConditions", signal.get("trigger_conditions", [])),
                invalidation_conditions=signal.get("invalidationConditions", signal.get("invalidation_conditions", [])),
                review_fields=signal.get("reviewFields", signal.get("review_fields", [])),
                blocked_reason=signal.get("blockedReason", signal.get("blocked_reason")),
            )
            db.add(record)
            await db.commit()
            return record
        finally:
            if not is_managed:
                await db.close()


class PaperTradeRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self, paper: dict, run_id: str, symbol: str) -> m.PaperTradeRecordDB:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            record = m.PaperTradeRecordDB(
                audit_id=paper.get("auditId", ""),
                run_id=run_id,
                symbol=symbol,
                status=paper.get("status", "ACTIVE"),
                observation_period=paper.get("observationPeriod", 14),
                entry_assumptions=paper.get("entryAssumptions", paper.get("entry_assumptions", [])),
                invalidation_conditions=paper.get("invalidationConditions", paper.get("invalidation_conditions", [])),
                simulated_profit=paper.get("simulatedProfit", 0.0),
                max_drawdown=paper.get("maxDrawdown", 0.0),
                triggered_invalidation=paper.get("triggeredInvalidation", False),
                written_to_ledger=paper.get("writtenToLedger", False),
                triggered_error_ledger=paper.get("triggeredErrorLedger", False),
                slippage_assumption=0.005,
            )
            db.add(record)
            await db.commit()
            return record
        finally:
            if not is_managed:
                await db.close()


class SystemVersionRepo:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_db(self):
        if self._session is not None:
            return self._session
        return AsyncSessionLocal()

    async def save(self) -> m.SystemVersionDB:
        db = await self._get_db()
        is_managed = self._session is not None
        try:
            record = m.SystemVersionDB(
                version="10.2",
                rule_version="10.2",
                agent_version="10.2",
                schema_version="10.2",
                prompt_version="10.2",
                data_adapter_version="1.0",
                frontend_version="1.0",
                backend_version="1.0",
            )
            db.add(record)
            await db.commit()
            return record
        finally:
            if not is_managed:
                await db.close()
