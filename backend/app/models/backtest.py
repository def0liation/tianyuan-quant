from typing import Dict, List, Optional, Any
from pydantic import BaseModel, ConfigDict, Field


class BacktestRequest(BaseModel):
    symbol: str
    stock_name: str = ""
    patch_id: Optional[str] = None
    case_id: Optional[str] = None
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 100000.0
    scenario_label: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    reuse_existing: bool = True
    force_new: bool = False


class BacktestParameterScanWindow(BaseModel):
    start: str
    end: str
    label: str = ""


class BacktestParameterScanRequest(BaseModel):
    symbol: str
    stock_name: str = ""
    patch_id: Optional[str] = None
    case_id: Optional[str] = None
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 100000.0
    scenario_label: str = ""
    base_parameters: Dict[str, Any] = Field(default_factory=dict)
    parameter_grid: Dict[str, List[Any]] = Field(default_factory=dict)
    windows: List[BacktestParameterScanWindow] = Field(default_factory=list)
    max_combinations: int = 8
    ranking_metric: str = "research_grade_score"
    reuse_existing: bool = True
    force_new: bool = False


class SignalOpsBacktestSampleRequest(BaseModel):
    symbol: Optional[str] = None
    signal_id: Optional[str] = None
    source_run_id: Optional[str] = None
    start_date: str = ""
    end_date: str = ""
    signal_date: str = ""
    initial_capital: float = 100000.0
    data_source: str = "AUTO"
    reuse_existing: bool = True
    force_new: bool = False


class SignalOpsExperimentWindow(BaseModel):
    start: str
    end: str


class SignalOpsExperimentRequest(BaseModel):
    symbol: str
    stock_name: str = ""
    train_window: SignalOpsExperimentWindow
    validation_window: SignalOpsExperimentWindow
    baseline_config: Dict[str, Any] = Field(default_factory=dict)
    candidate_config: Dict[str, Any] = Field(default_factory=dict)
    experiment_package_hash: str
    initial_capital: float = 100000.0
    benchmark_symbol: str = "000300.SH"
    reviewer: str = "auto_backtest_runner"


class BacktestTradeItem(BaseModel):
    trade_id: str
    run_id: str
    direction: str
    price: float
    quantity: int
    amount: float
    slippage: float = 0.0
    timestamp: str
    reason: str = ""
    realized_pnl: Optional[float] = None


class BacktestSignalItem(BaseModel):
    signal_id: str
    run_id: str
    signal_type: str
    direction: str
    strength: float = 0.0
    price: float
    timestamp: str
    source_node: str = ""
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class BacktestReport(BaseModel):
    data_source: str = "MOCK"
    data_error: Optional[str] = None
    data_points: int = 0
    signal_source: str = "MOCK"
    signal_source_count: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    hit_rate: float = 0.0
    false_positive_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    manual_review_pass_rate: float = 0.0
    t_plus_one_blocked: int = 0
    price_limit_blocked: int = 0
    slippage_total: float = 0.0
    final_capital: float = 0.0
    total_return_pct: float = 0.0
    benchmark: Dict[str, Any] = Field(default_factory=dict)
    sampleWindow: Dict[str, Any] = Field(default_factory=dict)
    tradingCost: Dict[str, Any] = Field(default_factory=dict)
    slippage: Dict[str, Any] = Field(default_factory=dict)
    executionConstraints: Dict[str, Any] = Field(default_factory=dict)
    outOfSampleWindow: Dict[str, Any] = Field(default_factory=dict)
    statisticalConfidence: Dict[str, Any] = Field(default_factory=dict)
    evidenceStrength: Dict[str, Any] = Field(default_factory=dict)
    researchGradeScore: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    researchContract: Dict[str, Any] = Field(default_factory=dict)
    validationProtocol: Dict[str, Any] = Field(default_factory=dict)
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list)
    trade_log: List[BacktestTradeItem] = Field(default_factory=list)
    signal_log: List[BacktestSignalItem] = Field(default_factory=list)


class BacktestComparison(BaseModel):
    before: Optional[BacktestReport] = None
    after: Optional[BacktestReport] = None
    hit_rate_delta: float = 0.0
    drawdown_delta: float = 0.0
    false_positive_delta: float = 0.0
    pnl_delta: float = 0.0
    return_delta: float = 0.0
    verdict: str = ""
    researchContract: Dict[str, Any] = Field(default_factory=dict)


class BacktestRunItem(BaseModel):
    run_id: str
    patch_id: Optional[str] = None
    case_id: Optional[str] = None
    symbol: str
    stock_name: str = ""
    scenario_label: str = ""
    status: str = "PENDING"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 100000.0
    parameters: Dict[str, Any] = Field(default_factory=dict)
    report: Dict[str, Any] = Field(default_factory=dict)
    comparison: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    elapsed_ms: int = 0
    created_at: str
    updated_at: str


class BacktestParameterScanResponse(BaseModel):
    scan_id: str
    status: str = "COMPLETED"
    symbol: str
    start_date: str = ""
    end_date: str = ""
    ranking_metric: str = "research_grade_score"
    parameter_grid: Dict[str, List[Any]] = Field(default_factory=dict)
    combinations: List[Dict[str, Any]] = Field(default_factory=list)
    windows: List[BacktestParameterScanWindow] = Field(default_factory=list)
    window_count: int = 0
    run_ids: List[str] = Field(default_factory=list)
    best_run_id: Optional[str] = None
    best_score: float = 0.0
    summary: Dict[str, Any] = Field(default_factory=dict)
    runs: List[BacktestRunItem] = Field(default_factory=list)
    trial_count: int = 0
    simulation_only: bool = True
    is_real_trade: bool = False


class BacktestParameterScanHistoryItem(BaseModel):
    scan_id: str
    status: str = "COMPLETED"
    symbol: str
    stock_name: str = ""
    start_date: str = ""
    end_date: str = ""
    ranking_metric: str = "research_grade_score"
    parameter_grid: Dict[str, List[Any]] = Field(default_factory=dict)
    combinations: List[Dict[str, Any]] = Field(default_factory=list)
    windows: List[BacktestParameterScanWindow] = Field(default_factory=list)
    window_count: int = 0
    run_ids: List[str] = Field(default_factory=list)
    best_run_id: Optional[str] = None
    best_score: float = 0.0
    summary: Dict[str, Any] = Field(default_factory=dict)
    trial_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    simulation_only: bool = True
    is_real_trade: bool = False


class BacktestParameterScanJobAttempt(BaseModel):
    attemptId: str
    attemptNumber: int = 0
    status: str = ""
    progressStep: str = ""
    startedAt: str = ""
    finishedAt: Optional[str] = None
    error: Optional[str] = None
    scanId: str = ""
    runIds: List[str] = Field(default_factory=list)
    bestRunId: Optional[str] = None
    idempotencyKey: str = ""
    queueMode: str = "LOCAL_DURABLE_JSON"
    leaseOwner: str = ""
    leaseId: str = ""
    leaseStatus: str = "UNKNOWN"
    leaseAcquiredAt: Optional[str] = None
    leaseExpiresAt: Optional[str] = None
    leaseReleasedAt: Optional[str] = None
    leaseSeconds: int = 0
    recovered: bool = False
    recoveryAttemptCount: int = 0
    simulationOnly: bool = True
    isRealTrade: bool = False


class BacktestParameterScanJob(BaseModel):
    jobId: str
    status: str
    progressStep: str = "QUEUED"
    request: Dict[str, Any] = Field(default_factory=dict)
    scan: Optional[BacktestParameterScanResponse] = None
    scanId: str = ""
    runIds: List[str] = Field(default_factory=list)
    bestRunId: Optional[str] = None
    totalCombinations: int = 0
    totalTrials: int = 0
    windowCount: int = 0
    simulationOnly: bool = True
    isRealTrade: bool = False
    error: Optional[str] = None
    queueMode: str = "LOCAL_DURABLE_JSON"
    storageSchema: str = "backtest_parameter_scan_jobs_v1"
    durable: bool = True
    recovered: bool = False
    recoveredAt: Optional[str] = None
    recoveryAttemptCount: int = 0
    idempotencyKey: str = ""
    attemptCount: int = 0
    currentAttemptId: Optional[str] = None
    lastAttemptStatus: Optional[str] = None
    attempts: List[BacktestParameterScanJobAttempt] = Field(default_factory=list)
    leaseOwner: str = ""
    leaseId: str = ""
    leaseStatus: str = "UNCLAIMED"
    leaseAcquiredAt: Optional[str] = None
    leaseExpiresAt: Optional[str] = None
    leaseReleasedAt: Optional[str] = None
    leaseSeconds: int = 0
    handoffStatus: Dict[str, Any] = Field(default_factory=dict)
    createdAt: str = ""
    updatedAt: str = ""


class BacktestParameterScanJobHandoff(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default="backtest_parameter_scan_job_handoff_v1", alias="schema")
    status: str
    reason: str = ""
    createdAt: str = ""
    jobId: str = ""
    scanId: str = ""
    jobStatus: str = ""
    handoffId: str = ""
    handoffDir: str = ""
    handoffDestination: str = ""
    handoffRequiresCompletedJob: bool = True
    bundleFile: str = ""
    manifestFile: str = ""
    bundleChecksum: str = ""
    queueMode: str = "LOCAL_DURABLE_JSON"
    idempotencyKey: str = ""
    manifest: Dict[str, Any] = Field(default_factory=dict)
    appendOnly: bool = True
    simulationOnly: bool = True
    isRealTrade: bool = False


class BacktestExperimentPackageResponse(BaseModel):
    package_id: str
    run_id: str
    generated_at: str
    manifest: Dict[str, Any] = Field(default_factory=dict)
    hashes: Dict[str, Any] = Field(default_factory=dict)
    reproducibility: Dict[str, Any] = Field(default_factory=dict)
    run: BacktestRunItem
    trades: List[BacktestTradeItem] = Field(default_factory=list)
    signals: List[BacktestSignalItem] = Field(default_factory=list)
    simulation_only: bool = True
    is_real_trade: bool = False


class SignalOpsBacktestSampleResponse(BaseModel):
    run_id: str
    signal_source: str
    market_data_source: str
    sample_window: Dict[str, Any] = Field(default_factory=dict)
    evidence_strength: Dict[str, Any] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)
    run: BacktestRunItem


class SignalOpsExperimentResponse(BaseModel):
    status: str
    message: str
    experiment_package_hash: str
    promotion_status: str
    walk_forward_run_ids: Dict[str, str] = Field(default_factory=dict)
    walk_forward_validation: Dict[str, Any] = Field(default_factory=dict)
    benchmark_comparison: Dict[str, Any] = Field(default_factory=dict)
    benchmark_unavailable_reason: str = ""
    review_queue_sync_status: str = "NOT_SYNCED"
    warnings: List[str] = Field(default_factory=list)
    research_evidence_package: Dict[str, Any] = Field(default_factory=dict)
    baseline_run: BacktestRunItem
    candidate_run: BacktestRunItem
    simulation_only: bool = True
    is_real_trade: bool = False


class SignalOpsRandomValidationRequest(BaseModel):
    mode: str = "VALIDATE_AND_FEEDBACK"
    seed: Optional[int] = None
    history_years: int = 10
    min_window_days: int = 365
    max_window_days: int = 540
    min_trading_days: int = 200
    initial_capital: float = 100000.0
    benchmark_symbol: str = ""


class SignalOpsRandomValidationJob(BaseModel):
    jobId: str
    status: str
    progressStep: str = "QUEUED"
    seed: int
    mode: str = "VALIDATE_AND_FEEDBACK"
    simulationOnly: bool = True
    isRealTrade: bool = False
    sampleWindows: List[Dict[str, Any]] = Field(default_factory=list)
    dataQuality: Dict[str, Any] = Field(default_factory=dict)
    baselineResults: Dict[str, Any] = Field(default_factory=dict)
    candidateResults: Dict[str, Any] = Field(default_factory=dict)
    evidenceLevel: str = "PENDING"
    appliedAdjustment: Dict[str, Any] = Field(default_factory=dict)
    rejectionReasons: List[str] = Field(default_factory=list)
    reviewQueueSyncStatus: str = "NOT_SYNCED"
    error: Optional[str] = None
    createdAt: str = ""
    updatedAt: str = ""
