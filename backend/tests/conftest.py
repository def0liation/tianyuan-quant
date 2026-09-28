import os

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
test_db_name = os.environ.get("TIANYUAN_QUANT_TEST_DB_NAME") or f"test_tianyuan_quant_{os.getpid()}.db"
test_db_path = project_root / ".pytest_cache" / test_db_name
test_db_path.parent.mkdir(parents=True, exist_ok=True)
if test_db_path.exists():
    test_db_path.unlink()
os.environ["TIANYUAN_QUANT_DB_URL"] = f"sqlite+aiosqlite:///{test_db_path}"
sys.path.insert(0, str(project_root))

import pytest
import asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.api import routes_analysis
from app.core import agent_runtime_store, analysis_job_store
from app.db.session import engine, Base
from app.db import models, models_backtest, models_case_library, models_research  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_create())
    yield


@pytest.fixture(autouse=True)
def cleanup_test_db():
    yield

    async def _cleanup():
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())

    asyncio.run(_cleanup())


@pytest.fixture(autouse=True)
def isolate_analysis_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_runtime_store, "STORAGE_FILE", tmp_path / "agent_runtime.json")
    monkeypatch.setattr(agent_runtime_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(analysis_job_store, "STORAGE_FILE", tmp_path / "analysis_jobs.json")
    monkeypatch.setattr(analysis_job_store, "SQLITE_DB_FILE", tmp_path / "analysis_jobs.db")
    monkeypatch.setenv("OPS_LOG_FILE", str(tmp_path / "ops_events.jsonl"))
    monkeypatch.setattr(routes_analysis, "runs_store", {})
    monkeypatch.setattr(routes_analysis, "analysis_tasks", {})

    yield

    for task in list(routes_analysis.analysis_tasks.values()):
        if task and not task.done():
            task.cancel()
    routes_analysis.analysis_tasks.clear()


@pytest.fixture(scope="function")
def db_engine():
    return engine


@pytest.fixture
def db_session():
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _create():
        return SessionLocal()

    session = asyncio.run(_create())
    yield session

    async def _close():
        await session.close()

    asyncio.run(_close())
