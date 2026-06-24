"""Workspace file reader: safe reads with fallback defaults."""

from __future__ import annotations

import logging
from pathlib import Path

from controlmesh.memory.store import has_meaningful_memory_content
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)

_UNCONFIGURED_MARKER = "status: unconfigured"


def read_file(path: Path) -> str | None:
    """Read a file, returning None if it does not exist or cannot be read."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("Failed to read file: %s", path, exc_info=True)
        return None


def _is_configured_context(content: str) -> bool:
    """Return True when a host context file should be injected."""
    stripped = content.strip()
    if not stripped:
        return False
    return _UNCONFIGURED_MARKER not in {line.strip().lower() for line in stripped.splitlines()}


def _read_configured_context(path: Path, title: str) -> str:
    content = read_file(path) or ""
    if not _is_configured_context(content):
        return ""
    return f"## {title}\n\n{content.strip()}"


def read_startup_memory_context(paths: ControlMeshPaths) -> str:
    """Build the durable memory context injected into a brand-new session."""
    authority = read_file(paths.authority_memory_path) or ""
    if not has_meaningful_memory_content(authority):
        return ""
    return f"## Memory\n\n{authority.strip()}"


def read_startup_context(paths: ControlMeshPaths) -> str:
    """Build all file-backed context injected into a brand-new session."""
    sections = [
        _read_configured_context(paths.server_profile_path, "Server Profile"),
        _read_configured_context(paths.server_soul_path, "Server Operating Doctrine"),
        read_startup_memory_context(paths),
    ]
    return "\n\n".join(section for section in sections if section.strip())
