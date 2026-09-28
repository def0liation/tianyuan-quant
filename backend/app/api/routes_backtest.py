from fastapi import APIRouter, HTTPException, Path, Query
from typing import Optional

from ..core.constants import RUN_ID_PATH_PATTERN
from ..core.backtest_store import BacktestRunReferencedError, backtest_store
from ..models.backtest import (
    BacktestRequest,
    BacktestExperimentPackageResponse,
    BacktestParameterScanHistoryItem,
    BacktestParameterScanJob,
    BacktestParameterScanJobHandoff,
    BacktestParameterScanRequest,
    BacktestParameterScanResponse,
    BacktestRunItem,
    BacktestTradeItem,
    BacktestSignalItem,
    SignalOpsExperimentRequest,
    SignalOpsExperimentResponse,
    SignalOpsRandomValidationRequest,
    SignalOpsRandomValidationJob,
    SignalOpsBacktestSampleRequest,
    SignalOpsBacktestSampleResponse,
)

router = APIRouter()


@router.post("/research/backtest/runs", response_model=BacktestRunItem)
@router.post("/backtest/runs", response_model=BacktestRunItem, deprecated=True)
async def create_backtest_run(request: BacktestRequest):
    result = await backtest_store.create_run(
        symbol=request.symbol,
        stock_name=request.stock_name,
        patch_id=request.patch_id,
        case_id=request.case_id,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        scenario_label=request.scenario_label,
        parameters=request.parameters if request.parameters else None,
        reuse_existing=request.reuse_existing,
        force_new=request.force_new,
    )
    return BacktestRunItem(**result)


@router.post("/research/backtest/parameter-scan", response_model=BacktestParameterScanResponse)
@router.post("/backtest/parameter-scan", response_model=BacktestParameterScanResponse, deprecated=True)
async def create_backtest_parameter_scan(request: BacktestParameterScanRequest):
    try:
        result = await backtest_store.create_parameter_scan(
            symbol=request.symbol,
            stock_name=request.stock_name,
            patch_id=request.patch_id,
            case_id=request.case_id,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            scenario_label=request.scenario_label,
            base_parameters=request.base_parameters,
            parameter_grid=request.parameter_grid,
            windows=[window.model_dump() for window in request.windows],
            max_combinations=request.max_combinations,
            ranking_metric=request.ranking_metric,
            reuse_existing=request.reuse_existing,
            force_new=request.force_new,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BacktestParameterScanResponse(**result)


@router.post("/research/backtest/parameter-scan/jobs", response_model=BacktestParameterScanJob)
@router.post("/backtest/parameter-scan/jobs", response_model=BacktestParameterScanJob, deprecated=True)
async def create_backtest_parameter_scan_job(request: BacktestParameterScanRequest):
    try:
        result = await backtest_store.create_parameter_scan_job(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BacktestParameterScanJob(**result)


@router.get("/research/backtest/parameter-scan/jobs/{job_id}", response_model=BacktestParameterScanJob)
@router.get("/backtest/parameter-scan/jobs/{job_id}", response_model=BacktestParameterScanJob, deprecated=True)
async def get_backtest_parameter_scan_job(job_id: str):
    result = await backtest_store.get_parameter_scan_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest parameter scan job not found")
    return BacktestParameterScanJob(**result)


@router.post("/research/backtest/parameter-scan/jobs/{job_id}/cancel", response_model=BacktestParameterScanJob)
@router.post("/backtest/parameter-scan/jobs/{job_id}/cancel", response_model=BacktestParameterScanJob, deprecated=True)
async def cancel_backtest_parameter_scan_job(job_id: str):
    result = await backtest_store.cancel_parameter_scan_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest parameter scan job not found")
    return BacktestParameterScanJob(**result)


@router.post("/research/backtest/parameter-scan/jobs/{job_id}/handoff", response_model=BacktestParameterScanJobHandoff)
@router.post("/backtest/parameter-scan/jobs/{job_id}/handoff", response_model=BacktestParameterScanJobHandoff, deprecated=True)
async def handoff_backtest_parameter_scan_job(job_id: str):
    result = await backtest_store.handoff_parameter_scan_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest parameter scan job not found")
    return BacktestParameterScanJobHandoff(**result)


@router.get("/research/backtest/parameter-scans", response_model=list[BacktestParameterScanHistoryItem])
@router.get("/backtest/parameter-scans", response_model=list[BacktestParameterScanHistoryItem], deprecated=True)
async def list_backtest_parameter_scans(
    symbol: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    scans = await backtest_store.list_parameter_scans(symbol=symbol, limit=limit)
    return [BacktestParameterScanHistoryItem(**item) for item in scans]


@router.post("/research/backtest/signalops-sample", response_model=SignalOpsBacktestSampleResponse)
@router.post("/backtest/signalops-sample", response_model=SignalOpsBacktestSampleResponse, deprecated=True)
async def create_signalops_backtest_sample(request: SignalOpsBacktestSampleRequest):
    try:
        result = await backtest_store.create_signalops_sample(
            symbol=request.symbol,
            signal_id=request.signal_id,
            source_run_id=request.source_run_id,
            start_date=request.start_date,
            end_date=request.end_date,
            signal_date=request.signal_date,
            initial_capital=request.initial_capital,
            data_source=request.data_source,
            reuse_existing=request.reuse_existing,
            force_new=request.force_new,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SignalOpsBacktestSampleResponse(**result)


@router.post("/research/backtest/signalops-experiment", response_model=SignalOpsExperimentResponse)
@router.post("/backtest/signalops-experiment", response_model=SignalOpsExperimentResponse, deprecated=True)
async def create_signalops_experiment(request: SignalOpsExperimentRequest):
    try:
        result = await backtest_store.create_signalops_experiment(
            symbol=request.symbol,
            stock_name=request.stock_name,
            train_window=request.train_window.model_dump(),
            validation_window=request.validation_window.model_dump(),
            baseline_config=request.baseline_config,
            candidate_config=request.candidate_config,
            experiment_package_hash=request.experiment_package_hash,
            initial_capital=request.initial_capital,
            benchmark_symbol=request.benchmark_symbol,
            reviewer=request.reviewer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SignalOpsExperimentResponse(**result)


@router.post("/research/backtest/signalops-random-validation/jobs", response_model=SignalOpsRandomValidationJob)
@router.post("/backtest/signalops-random-validation/jobs", response_model=SignalOpsRandomValidationJob, deprecated=True)
async def create_signalops_random_validation_job(request: SignalOpsRandomValidationRequest):
    try:
        result = await backtest_store.create_signalops_random_validation_job(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SignalOpsRandomValidationJob(**result)


@router.get("/research/backtest/signalops-random-validation/jobs/{job_id}", response_model=SignalOpsRandomValidationJob)
@router.get("/backtest/signalops-random-validation/jobs/{job_id}", response_model=SignalOpsRandomValidationJob, deprecated=True)
async def get_signalops_random_validation_job(job_id: str):
    result = await backtest_store.get_signalops_random_validation_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="SignalOps random validation job not found")
    return SignalOpsRandomValidationJob(**result)


@router.post("/research/backtest/signalops-random-validation/jobs/{job_id}/cancel", response_model=SignalOpsRandomValidationJob)
@router.post("/backtest/signalops-random-validation/jobs/{job_id}/cancel", response_model=SignalOpsRandomValidationJob, deprecated=True)
async def cancel_signalops_random_validation_job(job_id: str):
    result = await backtest_store.cancel_signalops_random_validation_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="SignalOps random validation job not found")
    return SignalOpsRandomValidationJob(**result)


@router.get("/research/backtest/runs", response_model=list[BacktestRunItem])
@router.get("/backtest/runs", response_model=list[BacktestRunItem], deprecated=True)
async def list_backtest_runs(
    patch_id: Optional[str] = Query(default=None),
    case_id: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    runs = await backtest_store.list_runs(
        patch_id=patch_id,
        case_id=case_id,
        symbol=symbol,
        status=status,
        limit=limit,
    )
    return [BacktestRunItem(**r) for r in runs]


@router.get("/research/backtest/runs/{run_id}", response_model=BacktestRunItem)
@router.get("/backtest/runs/{run_id}", response_model=BacktestRunItem, deprecated=True)
async def get_backtest_run(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run = await backtest_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestRunItem(**run)


@router.get("/research/backtest/runs/{run_id}/experiment-package", response_model=BacktestExperimentPackageResponse)
@router.get("/backtest/runs/{run_id}/experiment-package", response_model=BacktestExperimentPackageResponse, deprecated=True)
async def get_backtest_experiment_package(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    package = await backtest_store.get_experiment_package(run_id)
    if not package:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestExperimentPackageResponse(**package)


@router.get("/research/backtest/runs/{run_id}/trades", response_model=list[BacktestTradeItem])
@router.get("/backtest/runs/{run_id}/trades", response_model=list[BacktestTradeItem], deprecated=True)
async def get_backtest_trades(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run = await backtest_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    trades = await backtest_store.get_trades(run_id)
    return [BacktestTradeItem(**t) for t in trades]


@router.get("/research/backtest/runs/{run_id}/signals", response_model=list[BacktestSignalItem])
@router.get("/backtest/runs/{run_id}/signals", response_model=list[BacktestSignalItem], deprecated=True)
async def get_backtest_signals(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    run = await backtest_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    signals = await backtest_store.get_signals(run_id)
    return [BacktestSignalItem(**s) for s in signals]


@router.delete("/research/backtest/runs/{run_id}")
@router.delete("/backtest/runs/{run_id}", deprecated=True)
async def delete_backtest_run(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    try:
        deleted = await backtest_store.delete_run(run_id, protect_research_references=True)
    except BacktestRunReferencedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "已被研究证据引用，不能删除",
                "run_id": exc.run_id,
                "references": exc.references,
            },
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return {"deleted": run_id}


@router.get("/research/backtest/summary")
@router.get("/backtest/summary", deprecated=True)
async def get_backtest_summary():
    return await backtest_store.get_summary()
