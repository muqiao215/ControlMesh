"""Shared file-browsing utilities for workspace directory listing."""

from __future__ import annotations

from pathlib import Path

BROWSER_EXCLUDED_NAMES = frozenset({"__pycache__", ".git"})


def list_directory(target: Path) -> tuple[list[str], list[str]]:
    """List directory contents, returning ``(dirs, files)`` sorted alphabetically.

    Hidden files and excluded directories are filtered out.
    """
    dirs: list[str] = []
    files: list[str] = []
    try:
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            name = entry.name
            if name.startswith(".") or name in BROWSER_EXCLUDED_NAMES:
                continue
            if entry.is_dir():
                dirs.append(name)
            else:
                files.append(name)
    except PermissionError:
        pass
    return dirs, files
