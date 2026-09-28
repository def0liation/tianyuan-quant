from __future__ import annotations

from collections.abc import Callable
import logging

from ..db.repositories import (
    AgentResultRepository,
    AuditRepository,
    DVGResultRepo,
    DataSnapshotRepo,
    KillSwitchRepo,
    PaperTradeRepo,
    RunRepository,
    SignalOpsRepo,
    StateSnapshotRepo,
    SystemVersionRepo,
)
from .final_report_store import final_report_store
from .signalops_store import signalops_store

SaveRun = Callable[[dict], None]


async def persist_run(
    run_data: dict,
    run_id: str,
    symbol: str,
    *,
    save_run: SaveRun,
    logger: logging.Logger | None = None,
) -> None:
    audit_id = run_data.get("auditId") or run_data.get("audit_id") or f"AUD_{run_id}"
    save_run(run_data)
    try:
        run_repo = RunRepository()
        await run_repo.save(run_data)

        agent_results = run_data.get("agentResults", [])
        if agent_results:
            ar_repo = AgentResultRepository()
            await ar_repo.save_batch(agent_results, run_id)

        audit_logs = run_data.get("auditLog", [])
        if audit_logs:
            audit_repo = AuditRepository()
            await audit_repo.save_logs(audit_logs)

        ks = run_data.get("killSwitch", {})
        if ks:
            ks_repo = KillSwitchRepo()
            await ks_repo.save(ks, run_id)

        dvg = run_data.get("dvg", {})
        if dvg:
            dvg_repo = DVGResultRepo()
            await dvg_repo.save(dvg, run_id)

        data_repo = DataSnapshotRepo()
        await data_repo.save_snapshots(run_data, run_id, audit_id, symbol)

        state_repo = StateSnapshotRepo()
        await state_repo.save(run_data, run_id, audit_id)

        final_report = await final_report_store.upsert_from_run(run_data)
        if final_report:
            run_data["finalReportAsset"] = {
                "reportId": final_report["report_id"],
                "auditId": final_report["audit_id"],
                "updatedAt": final_report["updated_at"],
            }
            save_run(run_data)

        signal = run_data.get("signalOps", {})
        if signal:
            sig_repo = SignalOpsRepo()
            await sig_repo.save(signal, run_id, symbol)
            lifecycle_signal = await signalops_store.upsert_from_run(run_data)
            if lifecycle_signal:
                run_data["signalOpsLifecycle"] = {
                    "signalId": lifecycle_signal["signal_id"],
                    "status": lifecycle_signal["status"],
                    "latestRunId": lifecycle_signal.get("latest_run_id"),
                    "autoLinked": True,
                    "updatedAt": lifecycle_signal.get("updated_at"),
                }
                save_run(run_data)

        paper = run_data.get("paperTrading", {})
        if paper:
            pt_repo = PaperTradeRepo()
            await pt_repo.save(paper, run_id, symbol)

        ver_repo = SystemVersionRepo()
        await ver_repo.save()
    except Exception:
        if logger:
            logger.exception("Failed to persist run %s", run_id)
