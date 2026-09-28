from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
from .session import Base


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class CaseLibraryDB(Base):
    __tablename__ = "case_library"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(128), unique=True, nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    stock_name = Column(String(64), default="")
    task_type = Column(String(64), default="")
    run_mode = Column(String(32), default="STANDARD_MODE")
    final_action = Column(String(32), default="WAIT")
    final_action_correct = Column(Boolean, nullable=True)
    conclusion_correct = Column(Boolean, nullable=True)
    data_sufficiency = Column(String(16), default="ADEQUATE")
    optimism_bias = Column(String(16), default="NONE")
    key_lessons = Column(JSON, default=list)
    market_context = Column(Text, default="")
    tags = Column(JSON, default=list)
    reviewer = Column(String(64), nullable=True)
    review_note = Column(Text, default="")
    review_status = Column(String(32), default="PENDING")
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class ReviewTagDB(Base):
    __tablename__ = "review_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(String(128), unique=True, nullable=False, index=True)
    case_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    tag_type = Column(String(32), nullable=False)
    tag_value = Column(String(64), nullable=False)
    severity = Column(String(16), default="MEDIUM")
    description = Column(Text, default="")
    node = Column(String(64), nullable=True)
    reviewer = Column(String(64), nullable=True)
    created_at = Column(String(64), default=utcnow)


class ErrorLedgerEntryDB(Base):
    __tablename__ = "error_ledger_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(String(128), unique=True, nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    node = Column(String(64), nullable=True)
    error_type = Column(String(64), nullable=False)
    error_reason = Column(Text, default="")
    repeated_count = Column(Integer, default=1)
    patch_required = Column(Boolean, default=False)
    patch_candidate_id = Column(String(128), nullable=True)
    attribution = Column(JSON, default=dict)
    status = Column(String(32), default="OPEN")
    resolved_at = Column(String(64), nullable=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class KnowledgePatchDB(Base):
    __tablename__ = "knowledge_patches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patch_id = Column(String(128), unique=True, nullable=False, index=True)
    source_error_id = Column(String(128), nullable=True, index=True)
    source_case_id = Column(String(128), nullable=True, index=True)
    title = Column(String(256), nullable=False)
    reason = Column(Text, default="")
    affected_modules = Column(JSON, default=list)
    patch_content = Column(JSON, default=dict)
    risk_note = Column(Text, default="")
    rollback_plan = Column(Text, default="")
    backtest_required = Column(Boolean, default=True)
    backtest_result = Column(JSON, default=dict)
    approval_status = Column(String(32), default="CANDIDATE")
    approved_by = Column(String(64), nullable=True)
    approved_at = Column(String(64), nullable=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class EvaluationRunDB(Base):
    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    eval_id = Column(String(128), unique=True, nullable=False, index=True)
    patch_id = Column(String(128), nullable=False, index=True)
    status = Column(String(32), default="PENDING")
    total_cases = Column(Integer, default=0)
    passed_cases = Column(Integer, default=0)
    improved_cases = Column(Integer, default=0)
    regressed_cases = Column(Integer, default=0)
    unchanged_cases = Column(Integer, default=0)
    pass_rate = Column(Float, default=0.0)
    improvement_rate = Column(Float, default=0.0)
    elapsed_ms = Column(Integer, default=0)
    per_case_results = Column(JSON, default=list)
    summary = Column(Text, default="")
    error = Column(Text, nullable=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class KnowledgeVersionDB(Base):
    __tablename__ = "knowledge_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String(128), unique=True, nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    version_label = Column(String(64), default="")
    snapshot = Column(JSON, default=dict)
    active_patches = Column(JSON, default=list)
    active_rules = Column(JSON, default=list)
    patch_delta = Column(JSON, default=dict)
    source_patch_id = Column(String(128), nullable=True, index=True)
    created_by = Column(String(64), default="system")
    description = Column(Text, default="")
    created_at = Column(String(64), default=utcnow)
