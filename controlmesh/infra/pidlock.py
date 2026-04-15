"""PID lockfile: prevents multiple bot instances from running simultaneously."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_bytes_save
from controlmesh.infra.process_tree import (
    force_kill_process_tree,
    list_process_descendants,
    terminate_process_tree,
)

logger = logging.getLogger(__name__)

_KILL_WAIT_SECONDS = 5.0
_KILL_POLL_INTERVAL = 0.2


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Windows raises various OSError subclasses for invalid/stale PIDs.
        return False
    return True


def _terminate_process(pid: int) -> None:
    """Send a graceful termination signal to a process tree."""
    terminate_process_tree(pid)


def _force_kill_process(pid: int) -> None:
    """Force-kill a process tree."""
    force_kill_process_tree(pid)


def _kill_and_wait(pid: int) -> None:
    """Send termination signal, wait for exit, escalate to force-kill if needed."""
    logger.info("Stopping existing bot instance (pid=%d)", pid)
    descendants = [child for child in list_process_descendants(pid) if child != os.getpid()]
    try:
        _terminate_process(pid)
    except OSError:
        logger.warning("Failed to terminate pid=%d", pid, exc_info=True)
        return

    deadline = time.monotonic() + _KILL_WAIT_SECONDS
    while _is_process_alive(pid) and time.monotonic() < deadline:
        time.sleep(_KILL_POLL_INTERVAL)

    if _is_process_alive(pid):
        logger.warning("pid=%d did not exit after %.0fs, force killing", pid, _KILL_WAIT_SECONDS)
        with contextlib.suppress(OSError):
            _force_kill_process(pid)
        time.sleep(_KILL_POLL_INTERVAL)
    else:
        logger.info("Previous instance (pid=%d) exited cleanly", pid)

    alive_desc = _alive_pids(descendants)
    if not alive_desc:
        return

    logger.warning(
        "Cleaning up %d orphan child process(es) for pid=%d",
        len(alive_desc),
        pid,
    )
    for child_pid in alive_desc:
        with contextlib.suppress(OSError):
            _force_kill_process(child_pid)

    child_deadline = time.monotonic() + _KILL_WAIT_SECONDS
    remaining = _alive_pids(alive_desc)
    while remaining and time.monotonic() < child_deadline:
        time.sleep(_KILL_POLL_INTERVAL)
        remaining = _alive_pids(remaining)

    if remaining:
        logger.warning("Some child processes did not exit: %s", ",".join(str(p) for p in remaining))


def _alive_pids(pids: list[int]) -> list[int]:
    return [pid for pid in pids if _is_process_alive(pid)]


def acquire_lock(*, pid_file: Path, kill_existing: bool = False) -> None:
    """Write PID file after ensuring no other instance is running.

    Args:
        pid_file: Path to the PID lockfile.
        kill_existing: If True, kill any running instance before acquiring.
                       If False, raise ``SystemExit`` when another instance is found.
    """
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            existing_pid = None

        if existing_pid is not None and _is_process_alive(existing_pid):
            if kill_existing:
                _kill_and_wait(existing_pid)
            else:
                logger.error(
                    "Another bot instance is already running (pid=%d). "
                    "Kill it first or delete %s if stale.",
                    existing_pid,
                    pid_file,
                )
                raise SystemExit(1)
        else:
            logger.warning("Stale PID file found (pid=%s), overwriting", existing_pid)

    atomic_bytes_save(pid_file, str(os.getpid()).encode())
    logger.info("PID lock acquired (pid=%d)", os.getpid())


def release_lock(*, pid_file: Path) -> None:
    """Remove PID file if it belongs to the current process."""
    if not pid_file.exists():
        return
    try:
        stored_pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return

    if stored_pid == os.getpid():
        pid_file.unlink(missing_ok=True)
        logger.info("PID lock released")
    else:
        logger.debug("PID file belongs to pid=%d, not removing", stored_pid)
