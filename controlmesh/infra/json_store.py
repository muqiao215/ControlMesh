"""Atomic JSON file persistence.

Provides shared helpers for JSON-based storage used by cron, webhook,
and session managers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from controlmesh.infra.atomic_io import atomic_text_save

logger = logging.getLogger(__name__)


def atomic_json_save(path: Path, data: dict[str, Any] | list[Any]) -> None:
    """Write JSON atomically using temp file + rename."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    atomic_text_save(path, content)


def load_json(path: Path) -> dict[str, Any] | None:
    """Load JSON from file, return None if missing or corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        logger.warning("Corrupt or unreadable JSON file: %s", path)
        return None
