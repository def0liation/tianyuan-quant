"""
Shared file-system utilities: atomic writes, temp-file management, etc.

Extracted to remove duplicated retry logic from agent_runtime_store and
analysis_job_store.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any


def atomic_replace_file(source: Path, target: Path, max_attempts: int = 5, backoff_factor: float = 0.05) -> None:
    """Atomically replace *target* with *source* using ``os.replace``.

    Retries on PermissionError (e.g. Windows anti-virus lock) with linear
    back-off, raising the last error after *max_attempts* exhaustions.
    """
    for attempt in range(max_attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == max_attempts - 1:
                raise
            time.sleep(backoff_factor * (attempt + 1))


def write_json_atomic(
    target: Path,
    payload: Any,
    *,
    max_attempts: int = 5,
    backoff_factor: float = 0.05,
) -> None:
    """Serialize *payload* as JSON and atomically write it to *target*.

    The payload is written to a uniquely named temporary file in the target's
    directory, then swapped in via :func:`atomic_replace_file` (which retries on
    Windows ``PermissionError``). The temporary file is always removed when any
    step fails, so an interrupted or locked write never leaks ``*.tmp`` artifacts
    next to the destination.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    temp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(serialized)
        atomic_replace_file(temp, target, max_attempts=max_attempts, backoff_factor=backoff_factor)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
