"""Workspace file reader: safe reads with fallback defaults."""

from __future__ import annotations

import logging
from pathlib import Path

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


def read_mainmemory(paths: ControlMeshPaths) -> str:
    """Read MAINMEMORY.md, returning empty string if missing."""
    return read_file(paths.mainmemory_path) or ""


def read_startup_memory_context(paths: ControlMeshPaths) -> str:
    """Build the memory context injected into a brand-new session.

    Includes memory-v2 authority only when it appears to contain actual promoted
    memory entries, and includes legacy MAINMEMORY.md when non-empty.
    """
    sections: list[str] = []
    authority = read_file(paths.authority_memory_path) or ""
    if _has_meaningful_authority_content(authority):
        sections.extend(["## Authority Memory (v2)", authority.strip()])

    legacy = read_mainmemory(paths)
    if legacy.strip():
        sections.extend(["## Legacy Main Memory", legacy.strip()])

    return "\n\n".join(sections)


def _has_meaningful_authority_content(content: str) -> bool:
    """Return True when ``MEMORY.md`` contains promoted memory entries."""
    return any(line.lstrip().startswith("- ") for line in content.splitlines())
