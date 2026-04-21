"""Compatibility supervisor helpers for the legacy ``controlmesh.run`` API.

This module keeps the small process-based supervisor contract that older tests
and integrations still import, while the main runtime now uses the newer
multi-agent stack elsewhere.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from controlmesh.infra.restart import EXIT_RESTART

WATCH_DIR = Path.cwd()
SIGTERM_TIMEOUT = 5.0
_FAST_CRASH_WINDOW = 5.0
_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 60.0


async def _spawn_child() -> asyncio.subprocess.Process:
    env = os.environ.copy()
    env["CONTROLMESH_SUPERVISOR"] = "1"
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "controlmesh",
        env=env,
    )


async def _terminate_child(proc: asyncio.subprocess.Process) -> int:
    """Terminate a child process gracefully, escalating to SIGKILL on timeout."""
    if proc.returncode is not None:
        return int(proc.returncode)

    proc.terminate()
    try:
        return await asyncio.wait_for(proc.wait(), timeout=SIGTERM_TIMEOUT)
    except TimeoutError:
        proc.kill()
        return await proc.wait()


async def supervisor() -> int:
    """Run the legacy process supervisor loop.

    Exit semantics:
    - ``0``: stop supervising
    - ``EXIT_RESTART``: respawn immediately
    - any other code: treat as a crash and apply exponential backoff
    """
    consecutive_fast_crashes = 0

    while True:
        started_at = time.monotonic()
        proc = await _spawn_child()
        exit_code = await proc.wait()

        if exit_code == 0:
            return 0
        if exit_code == EXIT_RESTART:
            consecutive_fast_crashes = 0
            continue

        runtime = time.monotonic() - started_at
        if runtime < _FAST_CRASH_WINDOW:
            consecutive_fast_crashes += 1
        else:
            consecutive_fast_crashes = 1

        delay = min(_BACKOFF_BASE**consecutive_fast_crashes, _BACKOFF_CAP)
        await asyncio.sleep(delay)


__all__ = [
    "EXIT_RESTART",
    "SIGTERM_TIMEOUT",
    "WATCH_DIR",
    "_terminate_child",
    "supervisor",
]
