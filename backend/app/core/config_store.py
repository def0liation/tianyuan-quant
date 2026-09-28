from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from ..db.models import AuditLogDB, ConfigDraftDB, ConfigProfileDB, ConfigVersionDB
from ..db.session import AsyncSessionLocal
from ..models.config import ConfigDraft, ConfigProfile
from .operator_context import OperatorContext


CONFIG_PROFILE_ID = "default"
CONFIG_AUDIT_RUN_ID = "CONFIG_CENTER"
SECRET_VAULT_REFS_SNAPSHOT_KEY = "_secret_vault_refs"
RUNTIME_SECRET_REF_PREFIX = "runtime-secret:"
SENSITIVE_CONFIG_KEYS = (
    "api_key",
    "api-key",
    "x-api-key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
)


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _operator_payload(operator: OperatorContext | None) -> dict[str, str]:
    if operator is None:
        return {"id": "system", "role": "admin", "source": "system"}
    return operator.as_payload()


def _created_by(operator: OperatorContext | None) -> str:
    return _operator_payload(operator)["id"]


def redact_config_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in SENSITIVE_CONFIG_KEYS):
                redacted[key] = "<redacted>" if item else item
            else:
                redacted[key] = redact_config_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_config_payload(item) for item in value]
    return value


def _collect_secret_vault_refs(value: Any, path: tuple[str, ...] = ()) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            refs.extend(_collect_secret_vault_refs(item, (*path, str(key))))
        return refs
    if isinstance(value, list):
        for index, item in enumerate(value):
            refs.extend(_collect_secret_vault_refs(item, (*path, str(index))))
        return refs
    if isinstance(value, str) and value.startswith(RUNTIME_SECRET_REF_PREFIX):
        refs.append({"path": ".".join(path), "ref": value})
    return refs


def _dedupe_secret_vault_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for item in sorted(refs, key=lambda ref_item: (ref_item.get("path", ""), ref_item.get("ref", ""))):
        path = item.get("path", "")
        ref = item.get("ref", "")
        if not path or not ref:
            continue
        marker = (path, ref)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append({"path": path, "ref": ref})
    return deduped


class ConfigStore:
    async def load_state(
        self,
        default_profile: ConfigProfile,
    ) -> tuple[ConfigProfile, list[dict[str, Any]], dict[str, ConfigDraft]]:
        async with AsyncSessionLocal() as db:
            await self._ensure_seeded(db, default_profile)
            profile_record = (
                await db.execute(
                    select(ConfigProfileDB).where(ConfigProfileDB.profile_id == default_profile.profile_id)
                )
            ).scalar_one()
            version_records = (
                await db.execute(
                    select(ConfigVersionDB)
                    .where(ConfigVersionDB.profile_id == default_profile.profile_id)
                    .order_by(ConfigVersionDB.id.asc())
                )
            ).scalars().all()
            draft_records = (
                await db.execute(
                    select(ConfigDraftDB)
                    .where(ConfigDraftDB.profile_id == default_profile.profile_id)
                    .order_by(ConfigDraftDB.created_at.asc())
                )
            ).scalars().all()
            return (
                self._profile_to_model(profile_record),
                [self._version_to_dict(record) for record in version_records],
                {record.draft_id: self._draft_to_model(record) for record in draft_records},
            )

    async def record_runtime_change(
        self,
        profile: ConfigProfile,
        *,
        change_summary: str,
        audit_id: str,
        changes: dict[str, Any],
        previous_version: int,
        operator: OperatorContext | None = None,
    ) -> None:
        await self._save_profile_version_and_audit(
            profile,
            change_summary=change_summary,
            audit_id=audit_id,
            event_type="CONFIG_RUNTIME_PATCH",
            message=change_summary,
            operator=operator,
            payload={
                "profile_id": profile.profile_id,
                "previous_version": previous_version,
                "version": profile.version,
                "changes": deepcopy(changes),
                "operator": _operator_payload(operator),
            },
        )

    async def create_draft(
        self,
        default_profile: ConfigProfile,
        draft: ConfigDraft,
        *,
        operator: OperatorContext | None = None,
    ) -> ConfigDraft:
        async with AsyncSessionLocal() as db:
            await self._ensure_seeded(db, default_profile)
            draft = draft.model_copy(deep=True)
            requested_draft_id = draft.draft_id
            requested_audit_id = draft.audit_id
            draft.draft_id = await self._unique_draft_id(db, requested_draft_id)
            if draft.draft_id != requested_draft_id:
                draft.audit_id = f"{requested_audit_id}_{draft.draft_id.rsplit('_', 1)[-1]}"
            record = ConfigDraftDB(
                draft_id=draft.draft_id,
                profile_id=default_profile.profile_id,
                status=draft.status,
                changes_json=deepcopy(draft.changes),
                reason=draft.reason,
                policy_check_json=deepcopy(draft.policy_check),
                audit_id=draft.audit_id,
                created_at=draft.created_at,
                updated_at=draft.created_at,
            )
            db.add(record)
            db.add(
                self._audit_log(
                    audit_id=draft.audit_id,
                    event_type="CONFIG_DRAFT_CREATED",
                    message="Config review draft created.",
                    payload={
                        "profile_id": default_profile.profile_id,
                        "draft_id": draft.draft_id,
                        "status_after": draft.status,
                        "changes": deepcopy(draft.changes),
                        "reason": draft.reason,
                        "policy_check": deepcopy(draft.policy_check),
                        "operator": _operator_payload(operator),
                    },
                )
            )
            await db.commit()
            return draft

    async def apply_draft(
        self,
        profile: ConfigProfile,
        draft: ConfigDraft,
        *,
        change_summary: str,
        audit_id: str,
        previous_version: int,
        operator: OperatorContext | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            await self._ensure_seeded(db, profile)
            draft_record = (
                await db.execute(select(ConfigDraftDB).where(ConfigDraftDB.draft_id == draft.draft_id))
            ).scalar_one_or_none()
            if draft_record:
                draft_record.status = draft.status
                draft_record.updated_at = profile.updated_at

            await self._upsert_profile_record(db, profile)
            await self._supersede_active_versions(db, profile.profile_id)
            db.add(
                self._version_record(
                    profile,
                    change_summary=change_summary,
                    audit_id=audit_id,
                    status="active",
                    operator=operator,
                )
            )
            db.add(
                self._audit_log(
                    audit_id=audit_id,
                    event_type="CONFIG_DRAFT_APPLIED",
                    message=change_summary,
                    payload={
                        "profile_id": profile.profile_id,
                        "draft_id": draft.draft_id,
                        "draft_audit_id": draft.audit_id,
                        "previous_version": previous_version,
                        "version": profile.version,
                        "status_after": "APPLIED",
                        "changes": deepcopy(draft.changes),
                        "operator": _operator_payload(operator),
                    },
                )
            )
            await db.commit()

    async def rollback(
        self,
        profile: ConfigProfile,
        *,
        target_version: int,
        reason: str,
        audit_id: str,
        operator: OperatorContext | None = None,
    ) -> None:
        change_summary = f"Rolled back to version {target_version}"
        await self._save_profile_version_and_audit(
            profile,
            change_summary=change_summary,
            audit_id=audit_id,
            event_type="CONFIG_ROLLBACK",
            message=change_summary,
            operator=operator,
            payload={
                "profile_id": profile.profile_id,
                "target_version": target_version,
                "reason": reason,
                "version": profile.version,
                "status_after": "ROLLED_BACK",
                "operator": _operator_payload(operator),
            },
        )

    async def list_audit(self) -> list[dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AuditLogDB)
                .where(AuditLogDB.run_id == CONFIG_AUDIT_RUN_ID)
                .order_by(desc(AuditLogDB.created_at))
                .limit(100)
            )
            return [self._audit_to_dict(record) for record in result.scalars().all()]

    async def list_versions(
        self,
        *,
        limit: int = 200,
        include_snapshot: bool = False,
        profile_id: str | None = None,
        created_by: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            query = select(ConfigVersionDB)
            if profile_id:
                query = query.where(ConfigVersionDB.profile_id == profile_id)
            if created_by:
                query = query.where(ConfigVersionDB.created_by == created_by)
            if status:
                query = query.where(ConfigVersionDB.status == status)
            result = await db.execute(
                query.order_by(desc(ConfigVersionDB.created_at), desc(ConfigVersionDB.id)).limit(limit)
            )
            return [
                self._version_to_dict(record, include_snapshot=include_snapshot)
                for record in result.scalars().all()
            ]

    async def get_version(
        self,
        *,
        profile_id: str,
        version: int | None = None,
        audit_id: str | None = None,
        include_snapshot: bool = True,
    ) -> dict[str, Any] | None:
        async with AsyncSessionLocal() as db:
            query = select(ConfigVersionDB).where(ConfigVersionDB.profile_id == profile_id)
            if audit_id:
                query = query.where(ConfigVersionDB.audit_id == audit_id)
            if version is not None:
                query = query.where(ConfigVersionDB.version == version)
            record = (
                await db.execute(
                    query.order_by(desc(ConfigVersionDB.created_at), desc(ConfigVersionDB.id)).limit(1)
                )
            ).scalar_one_or_none()
            if record is None:
                return None
            return self._version_to_dict(record, include_snapshot=include_snapshot)

    async def record_external_change(
        self,
        *,
        scope: str,
        surface: str,
        subject: str,
        before: dict[str, Any],
        after: dict[str, Any],
        diff: dict[str, Any],
        summary: str,
        operator: OperatorContext | None = None,
    ) -> dict[str, Any]:
        profile_id = f"{scope}:{surface}"
        audit_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        async with AsyncSessionLocal() as db:
            latest = (
                await db.execute(
                    select(ConfigVersionDB)
                    .where(ConfigVersionDB.profile_id == profile_id)
                    .order_by(desc(ConfigVersionDB.version), desc(ConfigVersionDB.id))
                    .limit(1)
                )
            ).scalar_one_or_none()
            version = (latest.version if latest else 0) + 1
            audit_id = f"AUD_CFG_{scope.upper()}_{surface.upper()}_{version}_{audit_timestamp}"
            await self._supersede_active_versions(db, profile_id)
            snapshot = redact_config_payload(after)
            secret_vault_refs = _dedupe_secret_vault_refs(_collect_secret_vault_refs(after))
            if secret_vault_refs:
                snapshot[SECRET_VAULT_REFS_SNAPSHOT_KEY] = secret_vault_refs

            version_record = ConfigVersionDB(
                profile_id=profile_id,
                version=version,
                created_at=datetime.now(timezone.utc).isoformat(),
                created_by=_created_by(operator),
                change_summary=summary,
                audit_id=audit_id,
                status="active",
                rollback_available=False,
                snapshot_json=snapshot,
            )
            db.add(version_record)
            await db.flush()
            db.add(
                self._audit_log(
                    audit_id=audit_id,
                    event_type="CONFIG_EXTERNAL_CHANGE",
                    message=summary,
                    payload={
                        "profile_id": profile_id,
                        "scope": scope,
                        "surface": surface,
                        "subject": subject,
                        "version": version,
                        "version_id": version_record.id,
                        "summary": summary,
                        "diff": redact_config_payload(diff),
                        "before": redact_config_payload(before),
                        "after": redact_config_payload(after),
                        "operator": _operator_payload(operator),
                    },
                )
            )
            await db.commit()
            return {
                "audit_id": audit_id,
                "version_id": version_record.id,
                "version": version,
                "scope": scope,
                "surface": surface,
                "subject": subject,
            }

    async def _save_profile_version_and_audit(
        self,
        profile: ConfigProfile,
        *,
        change_summary: str,
        audit_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        operator: OperatorContext | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            await self._ensure_seeded(db, profile)
            await self._upsert_profile_record(db, profile)
            await self._supersede_active_versions(db, profile.profile_id)
            db.add(
                self._version_record(
                    profile,
                    change_summary=change_summary,
                    audit_id=audit_id,
                    status="active",
                    operator=operator,
                )
            )
            db.add(
                self._audit_log(
                    audit_id=audit_id,
                    event_type=event_type,
                    message=message,
                    payload=payload,
                )
            )
            await db.commit()

    async def _ensure_seeded(self, db, default_profile: ConfigProfile) -> None:
        profile_record = (
            await db.execute(
                select(ConfigProfileDB).where(ConfigProfileDB.profile_id == default_profile.profile_id)
            )
        ).scalar_one_or_none()
        if profile_record is None:
            db.add(self._profile_record(default_profile))
            db.add(
                self._version_record(
                    default_profile,
                    change_summary="Initial runtime configuration",
                    audit_id=f"AUD_CFG_{default_profile.version}",
                    status="active",
                )
            )
            await db.commit()
            return

        version_record = (
            await db.execute(
                select(ConfigVersionDB).where(ConfigVersionDB.profile_id == default_profile.profile_id).limit(1)
            )
        ).scalar_one_or_none()
        if version_record is None:
            db.add(
                self._version_record(
                    self._profile_to_model(profile_record),
                    change_summary="Initial runtime configuration",
                    audit_id=f"AUD_CFG_{profile_record.version}",
                    status="active",
                )
            )
            await db.commit()

    async def _supersede_active_versions(self, db, profile_id: str) -> None:
        result = await db.execute(
            select(ConfigVersionDB).where(
                ConfigVersionDB.profile_id == profile_id,
                ConfigVersionDB.status == "active",
            )
        )
        for record in result.scalars().all():
            record.status = "superseded"
            record.rollback_available = True

    async def _upsert_profile_record(self, db, profile: ConfigProfile) -> None:
        record = (
            await db.execute(select(ConfigProfileDB).where(ConfigProfileDB.profile_id == profile.profile_id))
        ).scalar_one_or_none()
        if record is None:
            db.add(self._profile_record(profile))
            return

        record.version = profile.version
        record.locked_guardrails_json = deepcopy(profile.locked_guardrails)
        record.safe_runtime_config_json = deepcopy(profile.safe_runtime_config)
        record.review_required_config_json = deepcopy(profile.review_required_config)
        record.sandbox_config_json = deepcopy(profile.sandbox_config)
        record.created_at = profile.created_at
        record.updated_at = profile.updated_at

    async def _unique_draft_id(self, db, requested_id: str) -> str:
        draft_id = requested_id
        suffix = 2
        while True:
            existing = (
                await db.execute(select(ConfigDraftDB).where(ConfigDraftDB.draft_id == draft_id))
            ).scalar_one_or_none()
            if existing is None:
                return draft_id
            draft_id = f"{requested_id}_{suffix}"
            suffix += 1

    def _profile_record(self, profile: ConfigProfile) -> ConfigProfileDB:
        return ConfigProfileDB(
            profile_id=profile.profile_id,
            version=profile.version,
            locked_guardrails_json=deepcopy(profile.locked_guardrails),
            safe_runtime_config_json=deepcopy(profile.safe_runtime_config),
            review_required_config_json=deepcopy(profile.review_required_config),
            sandbox_config_json=deepcopy(profile.sandbox_config),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def _version_record(
        self,
        profile: ConfigProfile,
        *,
        change_summary: str,
        audit_id: str,
        status: str,
        operator: OperatorContext | None = None,
    ) -> ConfigVersionDB:
        return ConfigVersionDB(
            profile_id=profile.profile_id,
            version=profile.version,
            created_at=profile.updated_at,
            created_by=_created_by(operator),
            change_summary=change_summary,
            audit_id=audit_id,
            status=status,
            rollback_available=False,
            snapshot_json=_model_dump(profile),
        )

    def _audit_log(
        self,
        *,
        audit_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any],
    ) -> AuditLogDB:
        return AuditLogDB(
            audit_id=audit_id,
            run_id=CONFIG_AUDIT_RUN_ID,
            event_type=event_type,
            node="config_center",
            message=message,
            status_before=payload.get("status_before"),
            status_after=payload.get("status_after") or "APPLIED",
            payload_json={
                "auditId": audit_id,
                "runId": CONFIG_AUDIT_RUN_ID,
                "eventType": event_type,
                "node": "config_center",
                "message": message,
                **deepcopy(payload),
            },
        )

    def _profile_to_model(self, record: ConfigProfileDB) -> ConfigProfile:
        return ConfigProfile(
            profile_id=record.profile_id,
            version=record.version,
            locked_guardrails=deepcopy(record.locked_guardrails_json or {}),
            safe_runtime_config=deepcopy(record.safe_runtime_config_json or {}),
            review_required_config=deepcopy(record.review_required_config_json or {}),
            sandbox_config=deepcopy(record.sandbox_config_json or {}),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _version_to_dict(self, record: ConfigVersionDB, *, include_snapshot: bool = True) -> dict[str, Any]:
        is_external = record.profile_id != CONFIG_PROFILE_ID
        snapshot = record.snapshot_json or {}
        secret_vault_refs = []
        if isinstance(snapshot, dict):
            raw_refs = snapshot.get(SECRET_VAULT_REFS_SNAPSHOT_KEY, [])
            if isinstance(raw_refs, list):
                secret_vault_refs = [
                    {"path": str(item.get("path", "")), "ref": str(item.get("ref", ""))}
                    for item in raw_refs
                    if isinstance(item, dict) and item.get("path") and item.get("ref")
                ]
        gate_required = bool(is_external or record.rollback_available)
        approval_gate = {
            "required": gate_required,
            "status": "BLOCKED_PENDING_VAULT_VERSION_APPROVAL"
            if is_external
            else ("REQUIRES_ADMIN_APPROVAL" if record.rollback_available else "NOT_REQUIRED"),
            "scope": "runtime_config_secret_restore"
            if is_external
            else ("config_rollback" if record.rollback_available else ""),
            "approver_role": "admin" if gate_required else "",
            "secret_vault_version_required": bool(is_external),
            "required_secret_refs": secret_vault_refs,
            "restore_source": "secret_vault_version_refs"
            if is_external
            else ("config_version_snapshot" if record.rollback_available else ""),
            "reason": (
                "External runtime config snapshots are redacted; restore requires approved matching secret vault refs."
                if is_external
                else ""
            ),
        }
        rollback_policy = {
            "supported": bool(record.rollback_available and not is_external),
            "approval_required": bool(is_external or record.rollback_available),
            "secret_safe_required": bool(is_external),
            "blocked_reason": "secret_safe_rollback_required" if is_external else "",
            "approval_gate": approval_gate,
        }
        scope_parts = record.profile_id.split(":", 1)
        payload = {
            "profile_id": record.profile_id,
            "version": record.version,
            "created_at": record.created_at,
            "created_by": record.created_by,
            "change_summary": record.change_summary,
            "audit_id": record.audit_id,
            "status": record.status,
            "rollback_available": record.rollback_available,
            "approval_required": rollback_policy["approval_required"],
            "effective_scope": scope_parts,
            "snapshot_redacted": is_external,
            "rollback_policy": rollback_policy,
        }
        if include_snapshot:
            payload["snapshot"] = deepcopy(record.snapshot_json or {})
        return payload

    def _draft_to_model(self, record: ConfigDraftDB) -> ConfigDraft:
        return ConfigDraft(
            draft_id=record.draft_id,
            status=record.status,
            changes=deepcopy(record.changes_json or {}),
            reason=record.reason,
            policy_check=deepcopy(record.policy_check_json or {}),
            audit_id=record.audit_id,
            created_at=record.created_at,
        )

    def _audit_to_dict(self, record: AuditLogDB) -> dict[str, Any]:
        return {
            "auditId": record.audit_id,
            "runId": record.run_id,
            "eventType": record.event_type,
            "node": record.node,
            "message": record.message,
            "statusBefore": record.status_before,
            "statusAfter": record.status_after,
            "inputHash": record.input_hash,
            "outputHash": record.output_hash,
            "payload": record.payload_json or {},
            "createdAt": record.created_at,
        }


config_store = ConfigStore()
