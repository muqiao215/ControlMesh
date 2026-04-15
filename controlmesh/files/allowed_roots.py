"""Resolve allowed root directories for file access."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_allowed_roots(file_access: str, workspace: Path) -> list[Path] | None:
    """Resolve allowed root directories based on ``file_access`` config value.

    Returns ``None`` when all paths are allowed (mode ``"all"``).
    Falls back to ``[workspace]`` (most restrictive) for unrecognized values.
    """
    if file_access == "all":
        return None
    if file_access == "home":
        return [Path.home()]
    if file_access == "workspace":
        return [workspace]
    logger.warning(
        "Unknown file_access value %r, falling back to workspace-only",
        file_access,
    )
    return [workspace]
