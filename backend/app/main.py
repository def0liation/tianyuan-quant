import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_agents import router as agents_router
from .api.routes_analysis import router as analysis_router
from .api.routes_audit import router as audit_router
from .api.routes_auto_paper_trading import router as auto_paper_trading_router
from .api.routes_backtest import router as backtest_router
from .api.routes_case_library import router as case_library_router
from .api.routes_evaluation import router as evaluation_router
from .api.routes_config import router as config_router
from .api.routes_data_pipeline import router as data_pipeline_router
from .api.routes_data_reliability import router as data_reliability_router
from .api.routes_health import router as health_router
from .api.routes_global_market import router as global_market_router
from .api.routes_knowledge import router as knowledge_router
from .api.routes_kline import router as kline_router
from .api.routes_portfolio import router as portfolio_router
from .api.routes_pet_alerts import router as pet_alerts_router
from .api.routes_plugins import router as plugins_router
from .api.routes_research import router as research_router
from .api.routes_signalops import router as signalops_router
from .api.routes_stream import router as stream_router
from .api.routes_technical_kline import router as technical_kline_router
from .core.http_auth import APIWriteAuthMiddleware
from .core.ops_log import ops_event_log
from .core.startup_status import startup_status
from .db.session import create_tables, run_migrations
from .core.auto_paper_trading import auto_paper_trading_store


logger = logging.getLogger(__name__)
startup_warmup_task: asyncio.Task | None = None
startup_market_data_status_task: asyncio.Task | None = None
MARKET_DATA_STATUS_WARMUP_TIMEOUT_SECONDS = float(
    os.getenv("MARKET_DATA_STATUS_WARMUP_TIMEOUT_SECONDS", "12")
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await startup_event()
    try:
        yield
    finally:
        await shutdown_event()


app = FastAPI(
    title="Tianyuan Quant Multi-Agent Control API",
    description="Backend API for the multi-agent research and control console.",
    version="0.2.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_correlation_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    client = request.client.host if request.client else ""
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception("Unhandled request error request_id=%s path=%s", request_id, request.url.path)
        ops_event_log.record_request(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=elapsed_ms,
            client=client,
            error="Unhandled request error",
        )
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-ms"] = str(round(elapsed_ms, 3))
    ops_event_log.record_request(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=elapsed_ms,
        client=client,
    )
    return response


def _resolve_cors_origins() -> list[str]:
    """Build CORS allowed origins from env or sensible dev defaults."""
    env_origins = os.getenv("CORS_ORIGINS", "").strip()
    if env_origins:
        return [origin.strip() for origin in env_origins.split(",") if origin.strip()]

    # Default dev origins
    origins: list[str] = []
    for port in range(5173, 5178):
        origins.append(f"http://localhost:{port}")
        origins.append(f"http://127.0.0.1:{port}")
    return origins


app.add_middleware(APIWriteAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(analysis_router, prefix="/api", tags=["analysis"])
app.include_router(auto_paper_trading_router, prefix="/api", tags=["auto-paper-trading"])
app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(knowledge_router, prefix="/api", tags=["knowledge"])
app.include_router(case_library_router, prefix="/api", tags=["case-library"])
app.include_router(evaluation_router, prefix="/api", tags=["evaluation"])
app.include_router(data_pipeline_router, prefix="/api", tags=["data-pipeline"])
app.include_router(data_reliability_router, prefix="/api", tags=["data-reliability"])
app.include_router(global_market_router, prefix="/api", tags=["market-data"])
app.include_router(kline_router, prefix="/api", tags=["market-data"])
app.include_router(technical_kline_router, prefix="/api", tags=["technical-kline"])
app.include_router(portfolio_router, prefix="/api", tags=["portfolio"])
app.include_router(pet_alerts_router, prefix="/api", tags=["pet-alerts"])
app.include_router(signalops_router, prefix="/api", tags=["signalops"])
app.include_router(plugins_router, prefix="/api", tags=["plugins"])
app.include_router(research_router, prefix="/api", tags=["research"])
app.include_router(audit_router, prefix="/api", tags=["audit"])
app.include_router(stream_router, prefix="/api", tags=["stream"])
app.include_router(agents_router, prefix="/api", tags=["agents"])
app.include_router(backtest_router, prefix="/api", tags=["backtest"])


@app.get("/")
async def root():
    return {
        "message": "Tianyuan Quant multi-agent backend is running.",
        "status": "ok",
        "api_root": "/api/health",
        "agents_runtime": "/api/agents/runtime",
    }


async def startup_event():
    global startup_warmup_task
    await startup_status.reset()
    await startup_status.run_component("database_migrations", "core", run_migrations, required=True)
    await startup_status.run_component("database_schema", "core", create_tables, required=True)
    await startup_status.mark_core_ready()
    startup_warmup_task = asyncio.create_task(_run_optional_startup_warmers())


async def shutdown_event():
    if startup_warmup_task and not startup_warmup_task.done():
        startup_warmup_task.cancel()
        try:
            await startup_warmup_task
        except asyncio.CancelledError:
            pass
    if startup_market_data_status_task and not startup_market_data_status_task.done():
        startup_market_data_status_task.cancel()
        try:
            await startup_market_data_status_task
        except asyncio.CancelledError:
            pass
    auto_paper_trading_store.stop_background_loop()


async def _run_optional_startup_warmers():
    global startup_market_data_status_task
    await startup_status.mark_warming()
    warmers = [
        ("analysis_history", _warm_analysis_history),
        ("research_summary", _warm_research_summary),
        ("backtest_summary", _warm_backtest_summary),
        ("plugin_defaults", _warm_plugin_defaults),
        ("auto_paper_loop", _warm_auto_paper_loop),
    ]
    await asyncio.gather(
        *(startup_status.run_component(name, "optional", callback) for name, callback in warmers)
    )
    await startup_status.start_component("market_data_status", "optional")
    startup_market_data_status_task = asyncio.create_task(_finish_deferred_market_data_status_warmer())
    await startup_status.mark_finished()


async def _finish_deferred_market_data_status_warmer():
    started = time.perf_counter()
    warmup_task = asyncio.create_task(_warm_market_data_status())
    try:
        done, pending = await asyncio.wait(
            {warmup_task},
            timeout=MARKET_DATA_STATUS_WARMUP_TIMEOUT_SECONDS,
        )
        if pending:
            warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await warmup_task
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            await startup_status.finish_component(
                "market_data_status",
                status="ERROR",
                elapsed_ms=elapsed_ms,
                error=f"Timeout after {MARKET_DATA_STATUS_WARMUP_TIMEOUT_SECONDS}s",
            )
            logger.warning("Startup warmer timed out: market_data_status after %.3fms", elapsed_ms)
            return None
        result = next(iter(done)).result()
    except asyncio.CancelledError:
        warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await warmup_task
        raise
    except asyncio.TimeoutError:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        await startup_status.finish_component(
            "market_data_status",
            status="ERROR",
            elapsed_ms=elapsed_ms,
            error=f"Timeout after {MARKET_DATA_STATUS_WARMUP_TIMEOUT_SECONDS}s",
        )
        logger.warning("Startup warmer timed out: market_data_status after %.3fms", elapsed_ms)
        return None
    except Exception as exc:
        await startup_status.finish_component(
            "market_data_status",
            status="ERROR",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            error=f"{type(exc).__name__}: {exc}",
        )
        logger.exception("Startup warmer failed: market_data_status")
        return None

    component_status = "OK"
    details = result if isinstance(result, dict) else None
    if isinstance(result, dict) and str(result.get("status") or "").upper() == "SKIPPED":
        component_status = "SKIPPED"
    await startup_status.finish_component(
        "market_data_status",
        status=component_status,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        details=details,
    )
    return result


async def _warm_analysis_history():
    from .api import routes_analysis

    await asyncio.to_thread(routes_analysis.warm_analysis_history_index)


async def _warm_research_summary():
    from .core.research_store import research_loop_store

    await research_loop_store.get_summary()


async def _warm_backtest_summary():
    from .core.backtest_store import backtest_store

    await backtest_store.get_summary()


async def _warm_plugin_defaults():
    from .core.plugin_store import plugin_store

    await plugin_store.ensure_default_plugins()


async def _warm_market_data_status():
    if _market_data_warmup_disabled():
        return {"status": "SKIPPED", "reason": "mock_market_data_mode"}
    from .core.market_data_adapter import register_default_market_data_adapters

    registry = await asyncio.to_thread(register_default_market_data_adapters)
    return await registry.build_status_matrix()


def _market_data_warmup_disabled() -> bool:
    force_mock = str(os.getenv("TIANYUAN_FORCE_MOCK_MARKET_DATA") or "").strip().lower()
    mode = str(os.getenv("TIANYUAN_MARKET_DATA_MODE") or "").strip().lower()
    return force_mock in {"1", "true", "yes", "on"} or mode in {"mock", "fallback", "simulation"}


async def _warm_auto_paper_loop():
    if _market_data_warmup_disabled():
        return {"status": "SKIPPED", "reason": "mock_market_data_mode"}
    auto_paper_trading_store.start_background_loop()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
