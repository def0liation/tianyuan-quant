import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select

from ..db.models import FinalReportDB
from ..db.session import AsyncSessionLocal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


class FinalReportStore:
    async def upsert_from_run(self, run_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        final_writer = run_data.get("finalWriter") if isinstance(run_data.get("finalWriter"), dict) else {}
        run_id = str(run_data.get("runId") or run_data.get("run_id") or "").strip()
        if not run_id or not final_writer:
            return None

        payload = _report_payload_from_run(run_data, final_writer)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(FinalReportDB).where(FinalReportDB.run_id == run_id))
            report = result.scalar_one_or_none()
            if report is None:
                report = FinalReportDB(
                    report_id=_generate_id("RPT"),
                    run_id=run_id,
                    created_at=_now(),
                )
                db.add(report)

            for key, value in payload.items():
                setattr(report, key, value)
            report.updated_at = _now()
            await db.commit()
            await db.refresh(report)
            return self._report_to_dict(report)

    async def get_by_run_id(self, run_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(FinalReportDB).where(FinalReportDB.run_id == run_id))
            report = result.scalar_one_or_none()
            return self._report_to_dict(report) if report else None

    async def get_by_report_id(self, report_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(FinalReportDB).where(FinalReportDB.report_id == report_id))
            report = result.scalar_one_or_none()
            return self._report_to_dict(report) if report else None

    async def list_reports(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(FinalReportDB)
            if symbol:
                query = query.where(FinalReportDB.symbol == symbol)
            query = query.order_by(desc(FinalReportDB.updated_at)).limit(limit)
            result = await db.execute(query)
            return [self._report_to_dict(record) for record in result.scalars().all()]

    def _report_to_dict(self, record: FinalReportDB) -> Dict[str, Any]:
        return {
            "report_id": record.report_id,
            "run_id": record.run_id,
            "audit_id": record.audit_id,
            "symbol": record.symbol,
            "stock_name": record.stock_name,
            "task_type": record.task_type,
            "data_mode": record.data_mode,
            "final_action": record.final_action,
            "final_writer_mode": record.final_writer_mode,
            "human_confirmation_required": record.human_confirmation_required,
            "summary": record.summary,
            "sections": record.sections_json or [],
            "source_snapshot": record.source_snapshot_json or {},
            "metadata": record.metadata_json or {},
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }


def _report_payload_from_run(run_data: Dict[str, Any], final_writer: Dict[str, Any]) -> Dict[str, Any]:
    sections = final_writer.get("sections") if isinstance(final_writer.get("sections"), list) else []
    kill_switch = run_data.get("killSwitch") if isinstance(run_data.get("killSwitch"), dict) else {}
    signal_ops = run_data.get("signalOps") if isinstance(run_data.get("signalOps"), dict) else {}
    dvg = run_data.get("dvg") if isinstance(run_data.get("dvg"), dict) else {}
    qiam = run_data.get("qiam") if isinstance(run_data.get("qiam"), dict) else {}
    data_sources = run_data.get("dataSources") if isinstance(run_data.get("dataSources"), dict) else {}
    return {
        "audit_id": final_writer.get("auditId") or run_data.get("auditId") or f"AUD_RPT_{run_data.get('runId', '')}",
        "symbol": run_data.get("stockCode") or run_data.get("symbol") or "",
        "stock_name": run_data.get("stockName") or run_data.get("stock_name") or "",
        "task_type": run_data.get("taskType") or run_data.get("task_type") or "",
        "data_mode": run_data.get("dataMode") or run_data.get("data_mode") or "",
        "final_action": final_writer.get("finalAction") or run_data.get("finalAction") or "WAIT",
        "final_writer_mode": final_writer.get("mode") or kill_switch.get("finalWriterMode") or "",
        "human_confirmation_required": bool(final_writer.get("humanConfirmationRequired", True)),
        "summary": _summary_from_sections(sections),
        "sections_json": sections,
        "source_snapshot_json": {
            "kill_switch_level": kill_switch.get("level"),
            "kill_switch_active": kill_switch.get("active"),
            "signal_status": signal_ops.get("signalStatus"),
            "signal_blocked_reason": signal_ops.get("blockedReason"),
            "dvg_allowed_output_level": dvg.get("allowedOutputLevel") or dvg.get("dataReliability"),
            "qiam_buy_suitability": qiam.get("finalBuySuitability"),
            "data_source_summary": data_sources.get("summary", {}),
        },
        "metadata_json": {
            "source": "final_writer_auto_report",
            "run_status": run_data.get("status"),
            "compressed_summary_present": bool(run_data.get("compressedSummary")),
            "section_count": len(sections),
        },
    }


def _summary_from_sections(sections: List[Dict[str, Any]]) -> str:
    if not sections:
        return ""
    first = sections[0] if isinstance(sections[0], dict) else {}
    content = str(first.get("content") or "").strip()
    if len(content) <= 500:
        return content
    return f"{content[:497]}..."


final_report_store = FinalReportStore()
