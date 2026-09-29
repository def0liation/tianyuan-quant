from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

RunStoreProvider = Callable[[], MutableMapping[str, dict]]
LoadRun = Callable[[str], dict | None]
SaveRun = Callable[[dict], None]
MarkRunCancelled = Callable[[str, dict, str], None]
ExecuteAndPersistRun = Callable[..., Awaitable[None]]
CreateRun = Callable[[Any], Awaitable[Any]]
StartRun = Callable[[str, dict | None], Awaitable[Any]]
PersistRun = Callable[[dict, str, str], Awaitable[None]]
CompareRuns = Callable[[str, str], dict]

_run_store_provider: RunStoreProvider | None = None
_load_run: LoadRun | None = None
_save_run: SaveRun | None = None
_mark_run_cancelled: MarkRunCancelled | None = None
_execute_and_persist_run: ExecuteAndPersistRun | None = None
_create_run: CreateRun | None = None
_start_run: StartRun | None = None
_persist_run: PersistRun | None = None
_compare_runs: CompareRuns | None = None


def initialize_analysis_lifecycle() -> None:
    """Register analysis callbacks for a worker without starting the HTTP app."""
    if _run_store_provider is None:
        from ..analysis_bootstrap import bind_analysis_callbacks
        bind_analysis_callbacks()
    _ensure_bound()


def bind_analysis_lifecycle(
    *,
    run_store_provider: RunStoreProvider,
    load_run: LoadRun,
    save_run: SaveRun,
    mark_run_cancelled: MarkRunCancelled,
    execute_and_persist_run: ExecuteAndPersistRun,
    create_run: CreateRun,
    start_run: StartRun,
    persist_run: PersistRun,
    compare_runs: CompareRuns,
) -> None:
    global _run_store_provider
    global _load_run
    global _save_run
    global _mark_run_cancelled
    global _execute_and_persist_run
    global _create_run
    global _start_run
    global _persist_run
    global _compare_runs

    _run_store_provider = run_store_provider
    _load_run = load_run
    _save_run = save_run
    _mark_run_cancelled = mark_run_cancelled
    _execute_and_persist_run = execute_and_persist_run
    _create_run = create_run
    _start_run = start_run
    _persist_run = persist_run
    _compare_runs = compare_runs


def _ensure_bound() -> None:
    if all(
        item is not None
        for item in (
            _run_store_provider,
            _load_run,
            _save_run,
            _mark_run_cancelled,
            _execute_and_persist_run,
            _create_run,
            _start_run,
            _persist_run,
            _compare_runs,
        )
    ):
        return

    raise RuntimeError("analysis lifecycle service is not bound")


def run_store() -> MutableMapping[str, dict]:
    _ensure_bound()
    assert _run_store_provider is not None
    return _run_store_provider()


def peek_run(run_id: str) -> dict | None:
    run = run_store().get(run_id)
    return run if isinstance(run, dict) else None


def get_run(run_id: str) -> dict | None:
    _ensure_bound()
    assert _load_run is not None
    return _load_run(run_id)


def set_run(run_id: str, run: dict, *, persist: bool = False) -> None:
    run_store()[run_id] = run
    if persist:
        save_run(run)


def save_run(run: dict) -> None:
    _ensure_bound()
    assert _save_run is not None
    _save_run(run)


def mark_run_cancelled(run_id: str, run: dict, reason: str) -> None:
    _ensure_bound()
    assert _mark_run_cancelled is not None
    _mark_run_cancelled(run_id, run, reason)


async def execute_and_persist_run(
    run_id: str, *, worker_id: str | None = None, expected_job_id: str | None = None,
) -> None:
    _ensure_bound()
    assert _execute_and_persist_run is not None
    if expected_job_id is None:
        await _execute_and_persist_run(run_id, worker_id=worker_id)
    else:
        await _execute_and_persist_run(run_id, worker_id=worker_id, expected_job_id=expected_job_id)


async def create_run(request: Any) -> Any:
    _ensure_bound()
    assert _create_run is not None
    return await _create_run(request)


async def start_run(run_id: str, payload: dict | None = None) -> Any:
    _ensure_bound()
    assert _start_run is not None
    return await _start_run(run_id, payload)


async def persist_run(run_data: dict, run_id: str, symbol: str) -> None:
    _ensure_bound()
    assert _persist_run is not None
    await _persist_run(run_data, run_id, symbol)


def compare_runs(left_id: str, right_id: str) -> dict:
    _ensure_bound()
    assert _compare_runs is not None
    return _compare_runs(left_id, right_id)
