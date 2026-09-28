from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List


logger = logging.getLogger(__name__)

StartupCallable = Callable[[], Awaitable[Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StartupStatusRegistry:
    def __init__(self) -> None:
        self._phase = "BOOTING"
        self._components: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def reset(self) -> None:
        async with self._lock:
            self._phase = "BOOTING"
            self._components = {}

    async def run_component(
        self,
        name: str,
        tier: str,
        callback: StartupCallable,
        *,
        required: bool = False,
        timeout_seconds: float | None = None,
    ) -> Any:
        await self.start_component(name, tier, required=required)
        started = time.perf_counter()
        try:
            if timeout_seconds is not None:
                result = await asyncio.wait_for(callback(), timeout=timeout_seconds)
            else:
                result = await callback()
        except asyncio.TimeoutError:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            await self.finish_component(
                name,
                status="ERROR",
                elapsed_ms=elapsed_ms,
                error=f"Timeout after {timeout_seconds}s",
            )
            if required:
                raise
            logger.warning("Startup warmer timed out: %s after %.3fms", name, elapsed_ms)
            return None
        except Exception as exc:
            await self.finish_component(
                name,
                status="ERROR",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
            if required:
                raise
            logger.exception("Startup warmer failed: %s", name)
            return None
        component_status = "OK"
        details = result if isinstance(result, dict) else None
        if isinstance(result, dict) and str(result.get("status") or "").upper() == "SKIPPED":
            component_status = "SKIPPED"
        await self.finish_component(
            name,
            status=component_status,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            details=details,
        )
        return result

    async def start_component(self, name: str, tier: str, *, required: bool = False) -> None:
        async with self._lock:
            self._components[name] = {
                "name": name,
                "tier": tier,
                "required": required,
                "status": "RUNNING",
                "startedAt": _now(),
            }

    async def finish_component(
        self,
        name: str,
        *,
        status: str,
        elapsed_ms: float,
        error: str = "",
        details: Dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            component = self._components.setdefault(
                name,
                {
                    "name": name,
                    "tier": "optional",
                    "required": False,
                    "startedAt": _now(),
                },
            )
            component["status"] = status
            component["finishedAt"] = _now()
            component["elapsedMs"] = elapsed_ms
            if error:
                component["error"] = error
            if details is not None:
                component["details"] = dict(details)

    async def set_phase(self, phase: str) -> None:
        async with self._lock:
            self._phase = phase

    async def mark_core_ready(self) -> None:
        await self.set_phase("CORE_READY")

    async def mark_warming(self) -> None:
        await self.set_phase("WARMING")

    async def mark_finished(self) -> None:
        async with self._lock:
            failed = [item for item in self._components.values() if item.get("status") == "ERROR"]
            self._phase = "DEGRADED" if failed else "READY"

    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            components: List[Dict[str, Any]] = [dict(item) for item in self._components.values()]
            phase = self._phase
        degraded = [item["name"] for item in components if item.get("status") == "ERROR"]
        core_ready = phase in {"CORE_READY", "WARMING", "READY", "DEGRADED"}
        ready = phase == "READY"
        return {
            "phase": phase,
            "coreReady": core_ready,
            "ready": ready,
            "degradedComponents": degraded,
            "components": sorted(components, key=lambda item: (item.get("tier", ""), item.get("name", ""))),
        }


startup_status = StartupStatusRegistry()
