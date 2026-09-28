import asyncio
import json
import logging
import time

from fastapi import APIRouter, Path, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..core.constants import RUN_ID_PATH_PATTERN
from ..core.agent_framework import stream_events_for_run
from ..core.analysis_run_registry import contains_run, get_run
from ..core.http_auth import (
    configured_api_tokens,
    extract_token_from_headers,
    extract_token_from_query,
    full_api_auth_enabled,
    operator_from_token,
)
from ..core.operator_context import reset_current_operator, set_current_operator

router = APIRouter()
logger = logging.getLogger(__name__)
TERMINAL_RUN_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "STALE"}
TERMINAL_EVENT_BY_STATUS = {
    "COMPLETED": "RUN_FINISHED",
    "FAILED": "RUN_FAILED",
    "CANCELLED": "RUN_CANCELLED",
    "STALE": "RUN_STALE_RECOVERED",
}


def _terminal_websocket_event(run_id: str, status: str | None, last_event_type: str | None) -> dict | None:
    event_type = TERMINAL_EVENT_BY_STATUS.get(status or "")
    if event_type is None or event_type == last_event_type:
        return None
    return {"event_type": event_type, "run_id": run_id, "status": status}


async def generate_events(run_id: str):
    run = get_run(run_id)
    if run is None:
        yield f"data: {json.dumps({'event_type': 'RUN_NOT_FOUND', 'run_id': run_id, 'message': 'Run not found or hidden because it is legacy mock data.'})}\n\n"
        yield "event: done\ndata: {}\n\n"
        return

    if "streamEvents" not in run:
        events = stream_events_for_run(run, run_id)
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0.35)
        yield "event: done\ndata: {}\n\n"
        return

    index = 0
    start_time = time.time()
    max_stream_seconds = 600
    last_heartbeat = start_time
    heartbeat_interval = 15

    while True:
        events = run.get("streamEvents", [])
        while index < len(events):
            yield f"data: {json.dumps(events[index])}\n\n"
            index += 1

        if run.get("status") in TERMINAL_RUN_STATUSES and index >= len(events):
            break

        now = time.time()
        if now - start_time > max_stream_seconds:
            yield f"data: {json.dumps({'event_type': 'STREAM_TIMEOUT', 'message': f'Stream timeout after {max_stream_seconds}s'})}\n\n"
            break

        if now - last_heartbeat >= heartbeat_interval:
            yield f"data: {json.dumps({'event_type': 'HEARTBEAT', 'run_id': run_id, 'status': run.get('status', 'UNKNOWN')})}\n\n"
            last_heartbeat = now

        if not contains_run(run_id):
            yield f"data: {json.dumps({'event_type': 'RUN_REMOVED', 'message': 'Run no longer exists'})}\n\n"
            break

        await asyncio.sleep(0.35)

    yield "event: done\ndata: {}\n\n"


@router.get("/analysis/runs/{run_id}/stream")
async def stream_analysis_events(run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    return StreamingResponse(
        generate_events(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.websocket("/ws/runs/{run_id}")
async def websocket_analysis_events(ws: WebSocket, run_id: str = Path(..., pattern=RUN_ID_PATH_PATTERN)):
    authorized, operator_token = await _authorize_websocket(ws)
    if not authorized:
        return

    await ws.accept()
    try:
        run = get_run(run_id)
        if run is None:
            await ws.send_json({"event_type": "ERROR", "message": "Run not found"})
            await ws.close()
            return

        index = 0
        start_time = time.time()
        max_stream_seconds = 600
        last_heartbeat = start_time
        heartbeat_interval = 15
        last_sent_event_type = None
        while True:
            run = get_run(run_id)
            if run is None:
                await ws.send_json({"event_type": "RUN_REMOVED", "run_id": run_id, "message": "Run no longer exists"})
                break

            now = time.time()
            if now - start_time > max_stream_seconds:
                await ws.send_json(
                    {
                        "event_type": "STREAM_TIMEOUT",
                        "run_id": run_id,
                        "message": f"Stream timeout after {max_stream_seconds}s",
                    }
                )
                break

            events = run.get("streamEvents", [])
            while index < len(events):
                event = events[index]
                await ws.send_json(event)
                if isinstance(event, dict):
                    last_sent_event_type = event.get("event_type")
                index += 1

            status = run.get("status")
            if status in TERMINAL_RUN_STATUSES and index >= len(events):
                terminal_event = _terminal_websocket_event(run_id, status, last_sent_event_type)
                if terminal_event is not None:
                    await ws.send_json(terminal_event)
                break

            if now - last_heartbeat >= heartbeat_interval:
                await ws.send_json({"event_type": "HEARTBEAT", "run_id": run_id, "status": run.get("status", "UNKNOWN")})
                last_heartbeat = now

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket run stream failed for run_id=%s", run_id)
        try:
            await ws.close()
        except Exception:
            pass
    finally:
        if operator_token is not None:
            reset_current_operator(operator_token)


async def _authorize_websocket(ws: WebSocket):
    if not full_api_auth_enabled():
        return True, None

    if not configured_api_tokens():
        await ws.close(code=1008, reason="API authentication token is not configured.")
        return False, None

    provided_token = extract_token_from_headers(ws.headers) or extract_token_from_query(ws.query_params)
    operator = operator_from_token(provided_token)
    if operator is None:
        await ws.close(code=1008, reason="API authentication required.")
        return False, None

    ws.scope.setdefault("state", {})["operator"] = operator
    return True, set_current_operator(operator)
