"""Restart sentinel and request helpers for graceful hot-reload."""

from __future__ import annotations

import json
import logging
import os
import socket
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


def write_restart_marker(
    *,
    marker_path: Path,
    source: str = "unknown",
    details: dict[str, Any] | None = None,
) -> None:
    """Write a marker file that tells the running bot to shut down with EXIT_RESTART."""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_at": datetime.now(UTC).isoformat(),
        "source": source,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "details": details or {},
    }
    marker_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    logger.info("Restart marker written source=%s pid=%d", source, os.getpid())


def consume_restart_marker(*, marker_path: Path) -> dict[str, Any] | None:
    """Check and delete the restart marker. Returns metadata if it existed."""
    if not marker_path.exists():
        return None
    try:
        raw = marker_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read restart marker")
        marker_path.unlink(missing_ok=True)
        return {"source": "unreadable", "details": {}}
    marker_path.unlink(missing_ok=True)
    if raw.strip() == "1":
        return {"source": "legacy-marker", "details": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Restart marker was not valid JSON; treating as legacy payload")
        return {"source": "legacy-nonjson", "details": {"raw": raw[:200]}}
    if not isinstance(data, dict):
        return {"source": "legacy-invalid-shape", "details": {"raw_type": type(data).__name__}}
    return data


def should_delegate_restart_to_service_manager() -> bool:
    """Return True when the current process is running under a service manager."""
    if os.environ.get("CONTROLMESH_SUPERVISOR"):
        return True
    # Treat bare host/root test shells conservatively: some environments may
    # leak INVOCATION_ID without providing a usable service-manager user bus.
    if os.environ.get("INVOCATION_ID") and os.environ.get("XDG_RUNTIME_DIR"):
        return True
    return False


def request_restart(
    *,
    marker_path: Path | None = None,
    source: str = "unknown",
    details: dict[str, Any] | None = None,
) -> bool:
    """Request a full restart via service manager when possible.

    When not running under a service manager, optionally write the legacy
    restart marker for in-process watcher paths and return False so the caller
    can continue with the existing graceful shutdown flow.
    Returns True when an explicit service-manager restart request was issued.
    """
    if should_delegate_restart_to_service_manager():
        try:
            from controlmesh.infra.service import is_service_installed, restart_service
        except Exception:
            logger.debug("Service facade unavailable for restart request", exc_info=True)
            if marker_path is not None:
                write_restart_marker(marker_path=marker_path, source=source, details=details)
            return False

        try:
            if not is_service_installed():
                if marker_path is not None:
                    write_restart_marker(marker_path=marker_path, source=source, details=details)
                return False
            restart_service()
        except Exception:
            logger.warning("Explicit service-manager restart request failed", exc_info=True)
            if marker_path is not None:
                write_restart_marker(marker_path=marker_path, source=source, details=details)
            return False
        else:
            logger.info("Requested explicit service-manager restart source=%s", source)
            return True

    if marker_path is not None:
        write_restart_marker(marker_path=marker_path, source=source, details=details)
    return False
