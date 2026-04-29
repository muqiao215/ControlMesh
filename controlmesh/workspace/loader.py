"""Workspace file reader: safe reads with fallback defaults."""

from __future__ import annotations

import logging
from pathlib import Path

from controlmesh.memory.store import has_meaningful_memory_content
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


def read_file(path: Path) -> str | None:
    """Read a file, returning None if it does not exist or cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("Failed to read file: %s", path, exc_info=True)
        return None


def read_startup_memory_context(paths: ControlMeshPaths) -> str:
    """Build the durable memory context injected into a brand-new session."""
    authority = read_file(paths.authority_memory_path) or ""
    if not has_meaningful_memory_content(authority):
        return ""
    return f"## Memory\n\n{authority.strip()}"
