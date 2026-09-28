from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship
from .session import Base


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class AnalysisRunDB(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), unique=True, nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    stock_name = Column(String(64), default="")
    task_type = Column(String(64), default="")
    run_mode = Column(String(32), default="STANDARD_MODE")
    runtime_environment = Column(String(32), default="API_ORCHESTRATED")
    data_mode = Column(String(16), default="MOCK")
    final_action = Column(String(32), default="WAIT")
    final_report = Column(Text, default="")
    success = Column(Boolean, default=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class AnalysisJobDB(Base):
    __tablename__ = "analysis_jobs"

    run_id = Column(String(128), primary_key=True, index=True)
    job_id = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    attempt = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    queue_name = Column(String(64), default="analysis", index=True)
    priority = Column(Integer, default=0)
    concurrency_group = Column(String(64), default="analysis", index=True)
    concurrency_limit = Column(Integer, default=1)
    worker_id = Column(String(128), default="", index=True)
    worker_heartbeat_at = Column(String(64), default="", index=True)
    operator = Column(String(80), default="local_workbench")
    last_operator = Column(String(80), default="local_workbench")
    last_error = Column(Text, default="")
    failed_node_id = Column(String(128), default="")
    retry_from_node_id = Column(String(128), default="")
    resume_from_node_id = Column(String(128), default="")
    retry_of_job_id = Column(String(128), default="")
    same_input_retry = Column(Boolean, default=False)
    stale_reason = Column(Text, default="")
    created_at = Column(String(64), default=utcnow, index=True)
    updated_at = Column(String(64), default=utcnow, index=True)
    queued_at = Column(String(64), default="", index=True)
    started_at = Column(String(64), default="", index=True)
    finished_at = Column(String(64), default="", index=True)
    cancel_requested_at = Column(String(64), default="", index=True)
    history_json = Column(JSON, default=list)
    recovery_json = Column(JSON, default=dict)
    payload_json = Column(JSON, default=dict)


class FinalReportDB(Base):
    __tablename__ = "final_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(128), unique=True, nullable=False, index=True)
    run_id = Column(String(128), unique=True, nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    stock_name = Column(String(64), default="")
    task_type = Column(String(64), default="")
    data_mode = Column(String(16), default="")
    final_action = Column(String(32), default="WAIT")
    final_writer_mode = Column(String(64), default="")
    human_confirmation_required = Column(Boolean, default=True)
    summary = Column(Text, default="")
    sections_json = Column(JSON, default=list)
    source_snapshot_json = Column(JSON, default=dict)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class AgentResultDB(Base):
    __tablename__ = "agent_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    agent_name = Column(String(64), nullable=False)
    node = Column(String(64), nullable=False)
    status = Column(String(16), default="PASS")
    confidence = Column(String(8), default="HIGH")
    hard_stop = Column(Boolean, default=False)
    allowed_actions = Column(JSON, default=list)
    blocked_actions = Column(JSON, default=list)
    missing_data = Column(JSON, default=list)
    warnings = Column(JSON, default=list)
    reasons = Column(JSON, default=list)
    data_json = Column(JSON, default=dict)
    elapsed_ms = Column(Integer, default=0)
    final_decision_cap = Column(String(32), nullable=True)
    skipped_reason = Column(String(256), nullable=True)
    created_at = Column(String(64), default=utcnow)


class AuditLogDB(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    node = Column(String(64), nullable=True)
    message = Column(Text, default="")
    status_before = Column(String(16), nullable=True)
    status_after = Column(String(16), nullable=True)
    input_hash = Column(String(64), nullable=True)
    output_hash = Column(String(64), nullable=True)
    payload_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class ConfigProfileDB(Base):
    __tablename__ = "config_profiles"

    profile_id = Column(String(64), primary_key=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    locked_guardrails_json = Column(JSON, default=dict)
    safe_runtime_config_json = Column(JSON, default=dict)
    review_required_config_json = Column(JSON, default=dict)
    sandbox_config_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class ConfigVersionDB(Base):
    __tablename__ = "config_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False, index=True)
    created_at = Column(String(64), default=utcnow)
    created_by = Column(String(64), default="system")
    change_summary = Column(Text, default="")
    audit_id = Column(String(128), nullable=False, index=True)
    status = Column(String(32), default="active")
    rollback_available = Column(Boolean, default=False)
    snapshot_json = Column(JSON, default=dict)


class ConfigDraftDB(Base):
    __tablename__ = "config_drafts"

    draft_id = Column(String(128), primary_key=True, index=True)
    profile_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), default="PENDING_REVIEW")
    changes_json = Column(JSON, default=dict)
    reason = Column(Text, default="")
    policy_check_json = Column(JSON, default=dict)
    audit_id = Column(String(128), nullable=False, index=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class DataSnapshotDB(Base):
    __tablename__ = "data_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    data_mode = Column(String(16), default="MOCK")
    source_name = Column(String(32), nullable=False)
    adapter = Column(String(32), default="")
    provider = Column(String(32), default="")
    success = Column(Boolean, default=True)
    evidence_tag = Column(String(4), default="I")
    freshness_status = Column(String(16), default="UNKNOWN")
    timestamp = Column(String(64), nullable=True)
    data_json = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    created_at = Column(String(64), default=utcnow)


class DVGResultDB(Base):
    __tablename__ = "dvg_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    status = Column(String(16), default="PASS")
    data_reliability = Column(String(8), default="HIGH")
    confirmed_ratio = Column(Float, default=0.0)
    inferred_ratio = Column(Float, default=0.0)
    unknown_ratio = Column(Float, default=0.0)
    core_unknown_count = Column(Integer, default=0)
    freshness_status = Column(String(16), default="UNKNOWN")
    source_integrity = Column(String(16), default="UNKNOWN")
    qiam_permission = Column(String(32), default="ALLOW")
    scenario_permission = Column(String(32), default="ALLOW")
    execution_permission = Column(String(32), default="ALLOW")
    final_decision_cap = Column(String(32), default="")
    hallucination_risk_score = Column(Integer, default=0)
    hallucination_risk_level = Column(String(8), default="LOW")
    hard_stop = Column(Boolean, default=False)
    critical_missing_data = Column(JSON, default=list)
    data_conflicts = Column(JSON, default=list)
    allowed_output_level = Column(String(32), default="FULL")
    data_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class KillSwitchEventDB(Base):
    __tablename__ = "kill_switch_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    active = Column(Boolean, default=False)
    level = Column(String(16), default="NONE")
    trigger_node = Column(String(64), nullable=True)
    trigger_rule = Column(String(256), nullable=True)
    blocked_paths = Column(JSON, default=list)
    allowed_paths = Column(JSON, default=list)
    final_writer_mode = Column(String(32), default="CONSERVATIVE")
    payload_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class SignalOpsRecordDB(Base):
    __tablename__ = "signalops_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    signal_status = Column(String(32), default="IDEA")
    risk_passed = Column(Boolean, default=False)
    dvg_passed = Column(Boolean, default=False)
    qiam_passed = Column(Boolean, default=False)
    execution_reachable = Column(Boolean, default=False)
    trigger_conditions = Column(JSON, default=list)
    invalidation_conditions = Column(JSON, default=list)
    review_fields = Column(JSON, default=list)
    blocked_reason = Column(String(256), nullable=True)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class PaperTradeRecordDB(Base):
    __tablename__ = "paper_trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, nullable=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False)
    status = Column(String(32), default="ACTIVE")
    observation_period = Column(Integer, default=14)
    entry_assumptions = Column(JSON, default=list)
    invalidation_conditions = Column(JSON, default=list)
    assumed_entry_price = Column(Float, nullable=True)
    assumed_exit_price = Column(Float, nullable=True)
    slippage_assumption = Column(Float, default=0.005)
    simulated_profit = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    triggered_invalidation = Column(Boolean, default=False)
    written_to_ledger = Column(Boolean, default=False)
    triggered_error_ledger = Column(Boolean, default=False)
    result_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class ReviewRecordDB(Base):
    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    signal_id = Column(Integer, nullable=True)
    symbol = Column(String(32), nullable=False)
    review_type = Column(String(32), default="TRADE")
    conclusion = Column(Text, default="")
    attribution_json = Column(JSON, default=dict)
    mistake_tags = Column(JSON, default=list)
    created_at = Column(String(64), default=utcnow)


class ErrorLedgerRecordDB(Base):
    __tablename__ = "error_ledger_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    node = Column(String(64), nullable=True)
    error_type = Column(String(64), nullable=False)
    error_reason = Column(Text, default="")
    repeated_count = Column(Integer, default=1)
    patch_required = Column(Boolean, default=False)
    meta_patch_id = Column(Integer, nullable=True)
    created_at = Column(String(64), default=utcnow)


class MetaPatchCandidateDB(Base):
    __tablename__ = "meta_patch_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    patch_id = Column(String(64), unique=True, nullable=False, index=True)
    source_error_id = Column(Integer, nullable=True)
    title = Column(String(256), nullable=False)
    reason = Column(Text, default="")
    affected_modules = Column(JSON, default=list)
    patch_content = Column(JSON, default=dict)
    risk_note = Column(Text, default="")
    rollback_plan = Column(Text, default="")
    backtest_required = Column(Boolean, default=True)
    approval_status = Column(String(32), default="CANDIDATE")
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class StateSnapshotDB(Base):
    __tablename__ = "state_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    snapshot_type = Column(String(32), default="FULL")
    state_json = Column(JSON, default=dict)
    schema_version = Column(String(16), default="10.2")
    checksum = Column(String(64), nullable=True)
    created_at = Column(String(64), default=utcnow)


class SystemVersionDB(Base):
    __tablename__ = "system_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(16), nullable=False)
    rule_version = Column(String(16), default="10.2")
    agent_version = Column(String(16), default="10.2")
    schema_version = Column(String(16), default="10.2")
    prompt_version = Column(String(16), default="10.2")
    data_adapter_version = Column(String(16), default="1.0")
    frontend_version = Column(String(16), default="1.0")
    backend_version = Column(String(16), default="1.0")
    created_at = Column(String(64), default=utcnow)


class PortfolioSnapshotDB(Base):
    __tablename__ = "portfolio_snapshots"

    snapshot_id = Column(String(64), primary_key=True, index=True)
    source_type = Column(String(32), default="MANUAL")
    source_name = Column(String(128), default="")
    account_name = Column(String(128), default="")
    total_assets = Column(Float, default=0.0)
    cash = Column(Float, default=0.0)
    stock_market_value = Column(Float, default=0.0)
    available_cash = Column(Float, default=0.0)
    total_position_ratio = Column(Float, default=0.0)
    max_single_position_ratio = Column(Float, default=0.0)
    position_count = Column(Integer, default=0)
    quality_status = Column(String(32), default="OK")
    issue_count = Column(Integer, default=0)
    imported_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)
    raw_json = Column(JSON, default=dict)


class HoldingPositionDB(Base):
    __tablename__ = "holding_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(String(64), ForeignKey("portfolio_snapshots.snapshot_id"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    name = Column(String(128), default="")
    shares = Column(Float, default=0.0)
    available_shares = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    market_value = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    industry = Column(String(64), default="")
    style = Column(String(64), default="")
    theme = Column(String(64), default="")
    risk_factor = Column(String(64), default="")
    weight = Column(Float, default=0.0)
    updated_at = Column(String(64), default=utcnow)
    raw_json = Column(JSON, default=dict)


class HoldingImportJobDB(Base):
    __tablename__ = "holding_import_jobs"

    job_id = Column(String(64), primary_key=True, index=True)
    snapshot_id = Column(String(64), nullable=True, index=True)
    filename = Column(String(256), default="")
    source_type = Column(String(32), default="CSV")
    status = Column(String(32), default="COMPLETED")
    rows_total = Column(Integer, default=0)
    rows_imported = Column(Integer, default=0)
    issue_count = Column(Integer, default=0)
    message = Column(Text, default="")
    created_at = Column(String(64), default=utcnow)
    raw_json = Column(JSON, default=dict)


class HoldingValidationIssueDB(Base):
    __tablename__ = "holding_validation_issues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), nullable=True, index=True)
    snapshot_id = Column(String(64), nullable=True, index=True)
    row_number = Column(Integer, default=0)
    symbol = Column(String(32), default="")
    field = Column(String(64), default="")
    level = Column(String(16), default="WARN")
    message = Column(Text, default="")
    created_at = Column(String(64), default=utcnow)


class DataHealthCheckDB(Base):
    __tablename__ = "data_health_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_type = Column(String(32), default="")
    symbol = Column(String(32), default="")
    adapter_id = Column(String(64), default="")
    provider = Column(String(64), default="")
    category = Column(String(64), default="")
    status = Column(String(32), default="")
    healthy = Column(Boolean, default=False)
    latency_ms = Column(Integer, default=0)
    message = Column(Text, default="")
    error = Column(Text, default="")
    payload_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class DataAdapterEventDB(Base):
    __tablename__ = "data_adapter_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), default="")
    adapter_id = Column(String(64), default="")
    provider = Column(String(64), default="")
    category = Column(String(64), default="")
    event_type = Column(String(32), default="")
    message = Column(Text, default="")
    error = Column(Text, default="")
    payload_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class SignalDB(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(String(128), unique=True, nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    stock_name = Column(String(64), default="")
    status = Column(String(32), default="IDEA", index=True)
    source_run_id = Column(String(128), nullable=True, index=True)
    latest_run_id = Column(String(128), nullable=True, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    risk_passed = Column(Boolean, default=False)
    dvg_passed = Column(Boolean, default=False)
    dvg_status = Column(String(32), default="")
    qiam_passed = Column(Boolean, default=False)
    qiam_status = Column(String(32), default="")
    execution_reachable = Column(Boolean, default=False)
    portfolio_allowed = Column(Boolean, default=True)
    trigger_conditions = Column(JSON, default=list)
    invalidation_conditions = Column(JSON, default=list)
    review_fields = Column(JSON, default=list)
    attached_runs = Column(JSON, default=list)
    blocked_reason = Column(String(256), default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class SignalTransitionDB(Base):
    __tablename__ = "signal_transitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transition_id = Column(String(128), unique=True, nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    from_status = Column(String(32), nullable=False)
    to_status = Column(String(32), nullable=False)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=True, index=True)
    actor = Column(String(64), default="system")
    reason = Column(Text, default="")
    gate_checks = Column(JSON, default=list)
    passed = Column(Boolean, default=False)
    created_at = Column(String(64), default=utcnow)


class SignalReviewDB(Base):
    __tablename__ = "signal_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(String(128), unique=True, nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    reviewer = Column(String(64), default="human")
    review_type = Column(String(32), default="MANUAL")
    decision = Column(String(32), default="PENDING")
    note = Column(Text, default="")
    review_fields = Column(JSON, default=list)
    created_at = Column(String(64), default=utcnow)


class SignalWatchConditionDB(Base):
    __tablename__ = "signal_watch_conditions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    condition_id = Column(String(128), unique=True, nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    condition_type = Column(String(32), default="TRIGGER")
    description = Column(Text, default="")
    status = Column(String(32), default="ACTIVE")
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class SignalInvalidationEventDB(Base):
    __tablename__ = "signal_invalidation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(128), unique=True, nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    condition = Column(Text, default="")
    triggered = Column(Boolean, default=False)
    source_run_id = Column(String(128), nullable=True, index=True)
    payload_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)


class PaperPortfolioDB(Base):
    __tablename__ = "paper_portfolios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(String(128), unique=True, nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=True, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    initial_cash = Column(Float, default=100000.0)
    available_cash = Column(Float, default=100000.0)
    market_value = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    risk_budget = Column(JSON, default=dict)
    created_by_agent = Column(String(64), default="signalops")
    simulation_only = Column(Boolean, default=True)
    is_real_trade = Column(Boolean, default=False)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class PaperPositionDB(Base):
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(String(128), unique=True, nullable=False, index=True)
    portfolio_id = Column(String(128), nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    quantity = Column(Float, default=0.0)
    virtual_cost = Column(Float, default=0.0)
    current_value = Column(Float, default=0.0)
    floating_pnl = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    updated_at = Column(String(64), default=utcnow)


class PaperOrderDB(Base):
    __tablename__ = "paper_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(128), unique=True, nullable=False, index=True)
    paper_portfolio_id = Column(String(128), nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=True, index=True)
    agent_id = Column(String(64), default="paper_trading_agent")
    action = Column(String(32), nullable=False)
    action_reason = Column(Text, default="")
    simulated_price = Column(Float, default=0.0)
    simulated_quantity = Column(Float, default=0.0)
    fill_status = Column(String(32), default="PENDING")
    risk_constraints = Column(JSON, default=dict)
    invalidation_conditions = Column(JSON, default=list)
    data_snapshot_hash = Column(String(128), default="")
    simulated_fill = Column(JSON, default=dict)
    simulation_only = Column(Boolean, default=True)
    is_real_trade = Column(Boolean, default=False)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class PaperExecutionDB(Base):
    __tablename__ = "paper_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(128), unique=True, nullable=False, index=True)
    order_id = Column(String(128), nullable=False, index=True)
    paper_portfolio_id = Column(String(128), nullable=False, index=True)
    signal_id = Column(String(128), nullable=False, index=True)
    audit_id = Column(String(128), nullable=False, index=True)
    fill_status = Column(String(32), default="FILLED")
    filled_price = Column(Float, default=0.0)
    filled_quantity = Column(Float, default=0.0)
    fees = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    rule_checks = Column(JSON, default=list)
    created_at = Column(String(64), default=utcnow)


class AgentSimulationCaseDB(Base):
    __tablename__ = "agent_simulation_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(128), unique=True, nullable=False, index=True)
    case_source = Column(String(64), default="AGENT_SIMULATION", index=True)
    operator_type = Column(String(32), default="AGENT")
    source_signal_id = Column(String(128), nullable=False, index=True)
    source_paper_order_id = Column(String(128), nullable=False, index=True)
    run_id = Column(String(128), nullable=True, index=True)
    agent_id = Column(String(64), default="paper_trading_agent")
    audit_id = Column(String(128), nullable=False, index=True)
    simulation_only = Column(Boolean, default=True)
    is_real_trade = Column(Boolean, default=False)
    outcome = Column(JSON, default=dict)
    failure_tags = Column(JSON, default=list)
    knowledge_candidate_status = Column(String(32), default="REVIEWING")
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class PluginRegistryDB(Base):
    __tablename__ = "plugin_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plugin_id = Column(String(128), unique=True, nullable=False, index=True)
    version = Column(String(32), default="0.1.0")
    name = Column(String(128), default="")
    description = Column(Text, default="")
    agents = Column(JSON, default=list)
    permissions = Column(JSON, default=list)
    input_schema = Column(JSON, default=dict)
    output_schema = Column(JSON, default=dict)
    risk_level = Column(String(32), default="LOW")
    enabled = Column(Boolean, default=True)
    source = Column(String(32), default="registry")
    manifest = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class PluginAuditDB(Base):
    __tablename__ = "plugin_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(128), nullable=False, index=True)
    plugin_id = Column(String(128), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    actor = Column(String(64), default="system")
    message = Column(Text, default="")
    payload_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
