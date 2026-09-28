import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, desc, delete as sa_delete

from ..db.session import AsyncSessionLocal
from ..db.models_case_library import CaseLibraryDB, ReviewTagDB, ErrorLedgerEntryDB, KnowledgePatchDB


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _first_bool(source: Dict[str, Any], *keys: str) -> Optional[bool]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            return value
    return None


def _case_evidence_strength(
    *,
    review_status: str,
    conclusion_correct: Optional[bool],
    final_action_correct: Optional[bool],
    data_sufficiency: str,
    optimism_bias: str,
    key_lessons: List[str],
    review_note: str,
) -> str:
    if review_status != "REVIEWED":
        return "PENDING"
    has_judgement = conclusion_correct is not None and final_action_correct is not None
    has_review_evidence = bool(key_lessons) and bool(review_note.strip())
    if data_sufficiency == "ADEQUATE" and optimism_bias != "SEVERE" and has_judgement and has_review_evidence:
        return "MEDIUM"
    return "LOW"


def _patch_evidence_strength(
    *,
    approval_status: str,
    backtest_required: bool,
    backtest_result: Dict[str, Any],
) -> str:
    status = (approval_status or "").upper()
    has_backtest = bool(backtest_result)

    if status in {"REJECTED", "ARCHIVED"}:
        return "LOW"
    if backtest_required and not has_backtest:
        return "PENDING"
    if not has_backtest:
        return "PENDING"

    passed = bool(
        backtest_result.get("passed")
        or backtest_result.get("ok")
        or backtest_result.get("success")
        or backtest_result.get("evaluation_id")
        or backtest_result.get("evaluationId")
        or backtest_result.get("report_id")
        or backtest_result.get("reportId")
    )
    if status == "APPROVED" and passed:
        return "MEDIUM"
    return "LOW"


def _error_ledger_evidence_strength(*, record: ErrorLedgerEntryDB, attribution: Dict[str, Any]) -> str:
    status = (record.status or "").upper()
    has_ids = bool(record.entry_id and record.run_id and record.audit_id)
    reported_simulation_only = _first_bool(attribution, "simulation_only", "simulationOnly")
    reported_is_real_trade = _first_bool(attribution, "is_real_trade", "isRealTrade")
    reported_boundary_conflict = reported_simulation_only is False or reported_is_real_trade is True

    if (
        reported_boundary_conflict
        or status == "OPEN"
        or (record.patch_required and not record.patch_candidate_id)
        or not has_ids
        or record.repeated_count > 1
    ):
        return "LOW"
    return "LOW"


class CaseLibraryStore:
    async def create_case(self, run_data: Dict[str, Any], reviewer: str = "system") -> CaseLibraryDB:
        async with AsyncSessionLocal() as db:
            case_id = _generate_id("CASE")
            run_id = run_data.get("runId", "")
            audit_id = run_data.get("auditId") or run_data.get("audit_id") or f"AUD_{run_id}"
            symbol = run_data.get("stockCode", "UNKNOWN")
            stock_name = run_data.get("stockName", "")
            task_type = run_data.get("taskType", "")
            run_mode = run_data.get("runMode", "STANDARD_MODE")
            final_action = run_data.get("finalAction", "WAIT")

            case = CaseLibraryDB(
                case_id=case_id,
                run_id=run_id,
                audit_id=audit_id,
                symbol=symbol,
                stock_name=stock_name,
                task_type=task_type,
                run_mode=run_mode,
                final_action=final_action,
                review_status="PENDING",
                reviewer=reviewer,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(case)
            await db.commit()
            await db.refresh(case)
            return case

    async def list_cases(
        self,
        symbol: Optional[str] = None,
        task_type: Optional[str] = None,
        review_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(CaseLibraryDB)
            if symbol:
                query = query.where(CaseLibraryDB.symbol == symbol)
            if task_type:
                query = query.where(CaseLibraryDB.task_type == task_type)
            if review_status:
                query = query.where(CaseLibraryDB.review_status == review_status)
            query = query.order_by(desc(CaseLibraryDB.created_at)).limit(limit).offset(offset)
            result = await db.execute(query)
            records = result.scalars().all()
            return [self._case_to_dict(r) for r in records]

    async def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(CaseLibraryDB).where(CaseLibraryDB.case_id == case_id))
            record = result.scalar_one_or_none()
            return self._case_to_dict(record) if record else None

    async def find_case_by_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(CaseLibraryDB).order_by(desc(CaseLibraryDB.created_at)))
            for record in result.scalars().all():
                if tag in (record.tags or []):
                    return self._case_to_dict(record)
            return None

    async def update_case_review(
        self,
        case_id: str,
        review_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(CaseLibraryDB).where(CaseLibraryDB.case_id == case_id))
            record = result.scalar_one_or_none()
            if not record:
                return None

            if "final_action_correct" in review_data:
                record.final_action_correct = review_data["final_action_correct"]
            if "conclusion_correct" in review_data:
                record.conclusion_correct = review_data["conclusion_correct"]
            if "data_sufficiency" in review_data:
                record.data_sufficiency = review_data["data_sufficiency"]
            if "optimism_bias" in review_data:
                record.optimism_bias = review_data["optimism_bias"]
            if "key_lessons" in review_data:
                record.key_lessons = review_data["key_lessons"]
            if "market_context" in review_data:
                record.market_context = review_data["market_context"]
            if "tags" in review_data:
                record.tags = review_data["tags"]
            if "reviewer" in review_data:
                record.reviewer = review_data["reviewer"]
            if "review_note" in review_data:
                record.review_note = review_data["review_note"]
            if "review_status" in review_data:
                record.review_status = review_data["review_status"]

            record.updated_at = _now()
            await db.commit()
            await db.refresh(record)
            return self._case_to_dict(record)

    async def get_summary(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            total = await db.execute(select(func.count()).select_from(CaseLibraryDB))
            total_count = total.scalar() or 0

            pending = await db.execute(
                select(func.count()).select_from(CaseLibraryDB).where(CaseLibraryDB.review_status == "PENDING")
            )
            pending_count = pending.scalar() or 0

            reviewed = await db.execute(
                select(func.count()).select_from(CaseLibraryDB).where(CaseLibraryDB.review_status == "REVIEWED")
            )
            reviewed_count = reviewed.scalar() or 0

            correct = await db.execute(
                select(func.count()).select_from(CaseLibraryDB).where(CaseLibraryDB.conclusion_correct == True)
            )
            correct_count = correct.scalar() or 0

            return {
                "total": total_count,
                "pending": pending_count,
                "reviewed": reviewed_count,
                "correct_conclusions": correct_count,
                "accuracy_rate": round(correct_count / reviewed_count, 2) if reviewed_count > 0 else 0.0,
            }

    def _case_to_dict(self, record: CaseLibraryDB) -> Dict[str, Any]:
        key_lessons = record.key_lessons or []
        review_note = record.review_note or ""
        return {
            "case_id": record.case_id,
            "run_id": record.run_id,
            "audit_id": record.audit_id,
            "symbol": record.symbol,
            "stock_name": record.stock_name,
            "task_type": record.task_type,
            "run_mode": record.run_mode,
            "final_action": record.final_action,
            "final_action_correct": record.final_action_correct,
            "conclusion_correct": record.conclusion_correct,
            "data_sufficiency": record.data_sufficiency,
            "optimism_bias": record.optimism_bias,
            "key_lessons": key_lessons,
            "market_context": record.market_context,
            "tags": record.tags or [],
            "reviewer": record.reviewer,
            "review_note": review_note,
            "review_status": record.review_status,
            "evidence_usage": "supporting_only",
            "evidence_strength": _case_evidence_strength(
                review_status=record.review_status,
                conclusion_correct=record.conclusion_correct,
                final_action_correct=record.final_action_correct,
                data_sufficiency=record.data_sufficiency,
                optimism_bias=record.optimism_bias,
                key_lessons=key_lessons,
                review_note=review_note,
            ),
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def delete_case(self, case_id: str) -> bool:
        async with AsyncSessionLocal() as db:
            await db.execute(sa_delete(ReviewTagDB).where(ReviewTagDB.case_id == case_id))
            result = await db.execute(sa_delete(CaseLibraryDB).where(CaseLibraryDB.case_id == case_id))
            await db.commit()
            return result.rowcount > 0


class ReviewTagStore:
    async def create_tag(self, case_id: str, run_id: str, tag_data: Dict[str, Any]) -> ReviewTagDB:
        async with AsyncSessionLocal() as db:
            tag = ReviewTagDB(
                tag_id=_generate_id("TAG"),
                case_id=case_id,
                run_id=run_id,
                tag_type=tag_data["tag_type"],
                tag_value=tag_data["tag_value"],
                severity=tag_data.get("severity", "MEDIUM"),
                description=tag_data.get("description", ""),
                node=tag_data.get("node"),
                reviewer=tag_data.get("reviewer", "human"),
                created_at=_now(),
            )
            db.add(tag)
            await db.commit()
            await db.refresh(tag)
            return tag

    async def list_tags(
        self,
        case_id: Optional[str] = None,
        tag_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(ReviewTagDB)
            if case_id:
                query = query.where(ReviewTagDB.case_id == case_id)
            if tag_type:
                query = query.where(ReviewTagDB.tag_type == tag_type)
            query = query.order_by(desc(ReviewTagDB.created_at)).limit(limit)
            result = await db.execute(query)
            records = result.scalars().all()
            return [self._tag_to_dict(r) for r in records]

    async def get_tag_summary(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            total = await db.execute(select(func.count()).select_from(ReviewTagDB))
            total_count = total.scalar() or 0

            type_counts = await db.execute(
                select(ReviewTagDB.tag_type, func.count())
                .group_by(ReviewTagDB.tag_type)
            )
            types = {row[0]: row[1] for row in type_counts.all()}

            severity_counts = await db.execute(
                select(ReviewTagDB.severity, func.count())
                .group_by(ReviewTagDB.severity)
            )
            severities = {row[0]: row[1] for row in severity_counts.all()}

            return {
                "total": total_count,
                "by_type": types,
                "by_severity": severities,
            }

    def _tag_to_dict(self, record: ReviewTagDB) -> Dict[str, Any]:
        return {
            "tag_id": record.tag_id,
            "case_id": record.case_id,
            "run_id": record.run_id,
            "tag_type": record.tag_type,
            "tag_value": record.tag_value,
            "severity": record.severity,
            "description": record.description,
            "node": record.node,
            "reviewer": record.reviewer,
            "created_at": record.created_at,
        }

    async def delete_tag(self, tag_id: str) -> bool:
        async with AsyncSessionLocal() as db:
            result = await db.execute(sa_delete(ReviewTagDB).where(ReviewTagDB.tag_id == tag_id))
            await db.commit()
            return result.rowcount > 0


class ErrorLedgerStore:
    async def create_entry(self, run_data: Dict[str, Any], error_data: Dict[str, Any]) -> ErrorLedgerEntryDB:
        async with AsyncSessionLocal() as db:
            run_id = run_data.get("runId", "")
            audit_id = run_data.get("auditId") or run_data.get("audit_id") or f"AUD_{run_id}"

            entry = ErrorLedgerEntryDB(
                entry_id=_generate_id("ERR"),
                run_id=run_id,
                audit_id=audit_id,
                node=error_data.get("node"),
                error_type=error_data["error_type"],
                error_reason=error_data.get("error_reason", ""),
                repeated_count=error_data.get("repeated_count", 1),
                patch_required=error_data.get("patch_required", False),
                attribution=error_data.get("attribution", {}),
                status="OPEN",
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
            return entry

    async def list_entries(
        self,
        status: Optional[str] = None,
        error_type: Optional[str] = None,
        node: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(ErrorLedgerEntryDB)
            if status:
                query = query.where(ErrorLedgerEntryDB.status == status)
            if error_type:
                query = query.where(ErrorLedgerEntryDB.error_type == error_type)
            if node:
                query = query.where(ErrorLedgerEntryDB.node == node)
            query = query.order_by(desc(ErrorLedgerEntryDB.created_at)).limit(limit)
            result = await db.execute(query)
            records = result.scalars().all()
            return [self._entry_to_dict(r) for r in records]

    async def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ErrorLedgerEntryDB).where(ErrorLedgerEntryDB.entry_id == entry_id))
            record = result.scalar_one_or_none()
            return self._entry_to_dict(record) if record else None

    async def find_entry_by_research_iteration(self, iteration_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ErrorLedgerEntryDB).order_by(desc(ErrorLedgerEntryDB.created_at)))
            for record in result.scalars().all():
                attribution = record.attribution or {}
                if attribution.get("iteration_id") == iteration_id:
                    return self._entry_to_dict(record)
            return None

    async def update_entry(self, entry_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ErrorLedgerEntryDB).where(ErrorLedgerEntryDB.entry_id == entry_id))
            record = result.scalar_one_or_none()
            if not record:
                return None

            if "status" in updates:
                record.status = updates["status"]
                if updates["status"] == "RESOLVED":
                    record.resolved_at = _now()
            if "patch_candidate_id" in updates:
                record.patch_candidate_id = updates["patch_candidate_id"]
            if "repeated_count" in updates:
                record.repeated_count = updates["repeated_count"]

            record.updated_at = _now()
            await db.commit()
            await db.refresh(record)
            return self._entry_to_dict(record)

    async def get_summary(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            total = await db.execute(select(func.count()).select_from(ErrorLedgerEntryDB))
            total_count = total.scalar() or 0

            open_count = await db.execute(
                select(func.count()).select_from(ErrorLedgerEntryDB).where(ErrorLedgerEntryDB.status == "OPEN")
            )
            open_c = open_count.scalar() or 0

            type_counts = await db.execute(
                select(ErrorLedgerEntryDB.error_type, func.count())
                .group_by(ErrorLedgerEntryDB.error_type)
            )
            types = {row[0]: row[1] for row in type_counts.all()}

            node_counts = await db.execute(
                select(ErrorLedgerEntryDB.node, func.count())
                .group_by(ErrorLedgerEntryDB.node)
            )
            nodes = {row[0] or "UNKNOWN": row[1] for row in node_counts.all()}

            return {
                "total": total_count,
                "open": open_c,
                "resolved": total_count - open_c,
                "by_type": types,
                "by_node": nodes,
            }

    def _entry_to_dict(self, record: ErrorLedgerEntryDB) -> Dict[str, Any]:
        attribution = record.attribution or {}
        reported_simulation_only = _first_bool(attribution, "simulation_only", "simulationOnly")
        reported_is_real_trade = _first_bool(attribution, "is_real_trade", "isRealTrade")
        return {
            "entry_id": record.entry_id,
            "run_id": record.run_id,
            "audit_id": record.audit_id,
            "node": record.node,
            "error_type": record.error_type,
            "error_reason": record.error_reason,
            "repeated_count": record.repeated_count,
            "patch_required": record.patch_required,
            "patch_candidate_id": record.patch_candidate_id,
            "attribution": attribution,
            "status": record.status,
            "evidence_usage": "review_gate_only",
            "evidence_strength": _error_ledger_evidence_strength(record=record, attribution=attribution),
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "reported_simulation_only": reported_simulation_only if reported_simulation_only is False else None,
            "reported_is_real_trade": reported_is_real_trade if reported_is_real_trade is True else None,
            "resolved_at": record.resolved_at,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def delete_entry(self, entry_id: str) -> bool:
        async with AsyncSessionLocal() as db:
            result = await db.execute(sa_delete(ErrorLedgerEntryDB).where(ErrorLedgerEntryDB.entry_id == entry_id))
            await db.commit()
            return result.rowcount > 0


class KnowledgePatchStore:
    async def create_patch(
        self,
        title: str,
        reason: str,
        affected_modules: List[str],
        patch_content: Dict[str, Any],
        source_error_id: Optional[str] = None,
        source_case_id: Optional[str] = None,
    ) -> KnowledgePatchDB:
        async with AsyncSessionLocal() as db:
            patch = KnowledgePatchDB(
                patch_id=_generate_id("PATCH"),
                source_error_id=source_error_id,
                source_case_id=source_case_id,
                title=title,
                reason=reason,
                affected_modules=affected_modules,
                patch_content=patch_content,
                risk_note=patch_content.get("risk_note", ""),
                rollback_plan=patch_content.get("rollback_plan", ""),
                backtest_required=patch_content.get("backtest_required", True),
                approval_status="CANDIDATE",
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(patch)
            await db.commit()
            await db.refresh(patch)
            return patch

    async def list_patches(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(KnowledgePatchDB)
            if status:
                query = query.where(KnowledgePatchDB.approval_status == status)
            query = query.order_by(desc(KnowledgePatchDB.created_at)).limit(limit)
            result = await db.execute(query)
            records = result.scalars().all()
            return [self._patch_to_dict(r) for r in records]

    async def get_patch(self, patch_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id))
            record = result.scalar_one_or_none()
            return self._patch_to_dict(record) if record else None

    async def find_patch_by_research_iteration(self, iteration_id: str) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(KnowledgePatchDB).order_by(desc(KnowledgePatchDB.created_at)))
            for record in result.scalars().all():
                patch_content = record.patch_content or {}
                if patch_content.get("research_iteration_id") == iteration_id:
                    return self._patch_to_dict(record)
            return None

    async def review_patch(
        self,
        patch_id: str,
        action: str,
        reviewer: str,
        note: str = "",
    ) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id))
            record = result.scalar_one_or_none()
            if not record:
                return None

            action = action.upper()
            if action == "APPROVE":
                record.approval_status = "APPROVED"
                record.approved_by = reviewer
                record.approved_at = _now()
            elif action == "REJECT":
                record.approval_status = "REJECTED"
            elif action == "ARCHIVE":
                record.approval_status = "ARCHIVED"
            else:
                raise ValueError("action must be APPROVE, REJECT, or ARCHIVE")

            record.updated_at = _now()
            await db.commit()
            await db.refresh(record)
            return self._patch_to_dict(record)

    async def update_backtest_result(
        self,
        patch_id: str,
        backtest_result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id))
            record = result.scalar_one_or_none()
            if not record:
                return None

            record.backtest_result = backtest_result
            record.updated_at = _now()
            await db.commit()
            await db.refresh(record)
            return self._patch_to_dict(record)

    async def get_summary(self) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            total = await db.execute(select(func.count()).select_from(KnowledgePatchDB))
            total_count = total.scalar() or 0

            candidate = await db.execute(
                select(func.count()).select_from(KnowledgePatchDB).where(KnowledgePatchDB.approval_status == "CANDIDATE")
            )
            candidate_count = candidate.scalar() or 0

            approved = await db.execute(
                select(func.count()).select_from(KnowledgePatchDB).where(KnowledgePatchDB.approval_status == "APPROVED")
            )
            approved_count = approved.scalar() or 0

            return {
                "total": total_count,
                "candidate": candidate_count,
                "approved": approved_count,
                "rejected": total_count - candidate_count - approved_count,
            }

    def _patch_to_dict(self, record: KnowledgePatchDB) -> Dict[str, Any]:
        backtest_result = record.backtest_result or {}
        return {
            "patch_id": record.patch_id,
            "source_error_id": record.source_error_id,
            "source_case_id": record.source_case_id,
            "title": record.title,
            "reason": record.reason,
            "affected_modules": record.affected_modules or [],
            "patch_content": record.patch_content or {},
            "risk_note": record.risk_note,
            "rollback_plan": record.rollback_plan,
            "backtest_required": record.backtest_required,
            "backtest_result": backtest_result,
            "approval_status": record.approval_status,
            "approved_by": record.approved_by,
            "approved_at": record.approved_at,
            "evidence_usage": "review_gate_only",
            "evidence_strength": _patch_evidence_strength(
                approval_status=record.approval_status,
                backtest_required=record.backtest_required,
                backtest_result=backtest_result,
            ),
            "simulation_only": True,
            "is_real_trade": False,
            "strong_conclusion_allowed": False,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    async def delete_patch(self, patch_id: str) -> bool:
        async with AsyncSessionLocal() as db:
            result = await db.execute(sa_delete(KnowledgePatchDB).where(KnowledgePatchDB.patch_id == patch_id))
            await db.commit()
            return result.rowcount > 0


case_library_store = CaseLibraryStore()
review_tag_store = ReviewTagStore()
error_ledger_store = ErrorLedgerStore()
knowledge_patch_store = KnowledgePatchStore()
