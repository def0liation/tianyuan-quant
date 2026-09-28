from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class ConfigProfile(BaseModel):
    profile_id: str
    version: int
    locked_guardrails: Dict[str, Any]
    safe_runtime_config: Dict[str, Any]
    review_required_config: Dict[str, Any]
    sandbox_config: Dict[str, Any]
    created_at: str
    updated_at: str

class ConfigSchemaItem(BaseModel):
    key: str
    label: str
    type: str
    layer: str
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[List[str]] = None
    default: Any
    current: Any
    editable: bool
    direction: str
    description: str

class ConfigDraft(BaseModel):
    draft_id: str
    status: str
    changes: Dict[str, Any]
    reason: str
    policy_check: Dict[str, Any]
    audit_id: str
    created_at: str

class PolicyCheckResult(BaseModel):
    passed: bool
    level: str
    warnings: List[str]
    blocked_reasons: List[str]
    effective_changes: Dict[str, Any]

class PatchRuntimeConfigRequest(BaseModel):
    changes: Dict[str, Any]

class PatchRuntimeConfigResponse(BaseModel):
    status: str
    profile_id: str
    version: int
    audit_id: str

class ValidateConfigRequest(BaseModel):
    changes: Dict[str, Any]

class CreateConfigDraftRequest(BaseModel):
    changes: Dict[str, Any]
    reason: str

class RollbackConfigRequest(BaseModel):
    target_version: int
    reason: str

class ExternalConfigRestoreRequest(BaseModel):
    profile_id: str
    target_version: Optional[int] = None
    audit_id: Optional[str] = None
    reason: str
    approval_id: str
    approved_by: Optional[str] = None
    confirm_secret_safe: bool = False

class RollbackConfigResponse(BaseModel):
    status: str
    current_version: int
    rollback_target_version: Optional[int] = None
    audit_id: str
