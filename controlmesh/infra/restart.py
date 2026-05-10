"""Restart sentinel and request helpers for graceful hot-reload."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from controlmesh.infra.atomic_io import atomic_bytes_save

logger = logging.getLogger(__name__)

EXIT_RESTART = 42
"""Exit code that tells the supervisor to restart immediately."""


def write_restart_sentinel(
    chat_id: int,
    message: str = "Restart completed.",
    *,
    sentinel_path: Path,
) -> None:
    """Write a sentinel file so the bot can notify the user after restart."""
    data = {
        "chat_id": chat_id,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    atomic_bytes_save(sentinel_path, json.dumps(data).encode())
    logger.info("Restart sentinel written for chat=%d", chat_id)


def consume_restart_sentinel(*, sentinel_path: Path) -> dict[str, Any] | None:
    """Read and delete the sentinel file. Returns None if absent."""
    if not sentinel_path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(sentinel_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read restart sentinel")
        sentinel_path.unlink(missing_ok=True)
        return None
    else:
        sentinel_path.unlink(missing_ok=True)
        logger.info("Restart sentinel consumed for chat=%s", data.get("chat_id"))
        return data


def write_restart_marker(*, marker_path: Path) -> None:
    """Write a marker file that tells the running bot to shut down with EXIT_RESTART."""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("1", encoding="utf-8")
    logger.info("Restart marker written")


def consume_restart_marker(*, marker_path: Path) -> bool:
    """Check and delete the restart marker. Returns True if it existed."""
    if not marker_path.exists():
        return False
    marker_path.unlink(missing_ok=True)
    return True


def should_delegate_restart_to_service_manager() -> bool:
    """Return True when the current process is running under a service manager."""
    return bool(os.environ.get("CONTROLMESH_SUPERVISOR") or os.environ.get("INVOCATION_ID"))


def request_restart(*, marker_path: Path) -> bool:
    """Request a full restart via service manager when possible.

    Writes the restart marker first so the legacy watcher path still works.
    Returns True when an explicit service-manager restart request was issued.
    """
    write_restart_marker(marker_path=marker_path)

    if not should_delegate_restart_to_service_manager():
        return False

    try:
        from controlmesh.infra.service import is_service_installed, restart_service
    except Exception:
        logger.debug("Service facade unavailable for restart request", exc_info=True)
        return False

    try:
        if not is_service_installed():
            return False
        restart_service()
    except Exception:
        logger.warning("Explicit service-manager restart request failed", exc_info=True)
        return False
    else:
        logger.info("Requested explicit service-manager restart")
        return True
