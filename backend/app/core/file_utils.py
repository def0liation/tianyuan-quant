"""
Shared file-system utilities: atomic writes, temp-file management, etc.

Extracted to remove duplicated retry logic from agent_runtime_store and
analysis_job_store.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


_STATE_LOCKS: dict[str, threading.RLock] = {}
_STATE_LOCKS_GUARD = threading.Lock()
_STATE_LOCK_CONTEXT = threading.local()


@contextmanager
def file_state_lock(target: Path):
    """Serialize a full read/modify/write transaction across threads/processes.

    The sidecar is independent of atomic replacement of the target. Locks are
    reentrant for the same thread and target, and acquisition is bounded to 5s.
    """
    key = os.path.normcase(str(target.resolve()))
    with _STATE_LOCKS_GUARD:
        thread_lock = _STATE_LOCKS.setdefault(key, threading.RLock())
    if not thread_lock.acquire(timeout=5.0):
        raise TimeoutError("Local storage transaction lock timed out.")
    try:
        held = getattr(_STATE_LOCK_CONTEXT, "held", None)
        if held is None:
            held = _STATE_LOCK_CONTEXT.held = set()
        if key in held:
            yield
            return
        lock_path = target.with_name(f".{target.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        thread_lock.release()


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
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    write_text_atomic(target, serialized, max_attempts=max_attempts, backoff_factor=backoff_factor)


def write_text_atomic(
    target: Path,
    text: str,
    *,
    max_attempts: int = 5,
    backoff_factor: float = 0.05,
) -> None:
    """Write UTF-8 text through a flushed temporary file and atomic replacement."""
    write_bytes_atomic(target, text.encode("utf-8"), max_attempts=max_attempts, backoff_factor=backoff_factor)


def write_bytes_atomic(
    target: Path,
    data: bytes,
    *,
    max_attempts: int = 5,
    backoff_factor: float = 0.05,
) -> None:
    """Preserve the previous destination if any stage of writing fails."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace_file(temp, target, max_attempts=max_attempts, backoff_factor=backoff_factor)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
