"""Compatibility helpers for bridging memory-v2 into legacy MAINMEMORY.md."""

from __future__ import annotations

from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.workspace.paths import ControlMeshPaths

_COMPAT_START_MARKER = "--- MEMORY V2 COMPAT START ---"
_COMPAT_END_MARKER = "--- MEMORY V2 COMPAT END ---"
_AUTHORITY_TEMPLATE_LINES = frozenset(
    {
        "# ControlMesh Memory v2",
        "This file is the additive, human-readable authority for durable memory promoted",
        "from daily notes and future dreaming/search layers. It does not replace the",
        "legacy `memory_system/MAINMEMORY.md` yet.",
        "## Durable Memory",
        "### Fact",
        "### Preference",
        "### Decision",
        "### Project",
        "### Person",
    }
)


def has_meaningful_authority_content(content: str) -> bool:
    """Return True when ``MEMORY.md`` contains promoted memory entries."""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in _AUTHORITY_TEMPLATE_LINES:
            continue
        return True
    return False


def strip_legacy_authority_compat(content: str) -> str:
    """Remove the authority mirror block from legacy MAINMEMORY text."""
    if _COMPAT_START_MARKER not in content:
        return content

    before = content.split(_COMPAT_START_MARKER, 1)[0]
    after_parts = content.split(_COMPAT_END_MARKER, 1)
    after = after_parts[1] if len(after_parts) > 1 else ""
    trimmed = (
        f"{before.rstrip()}\n{after.lstrip()}"
        if before.strip() and after.strip()
        else before + after
    )
    return trimmed.strip()


def sync_authority_to_legacy_mainmemory(
    paths: ControlMeshPaths,
    *,
    authority_text: str | None = None,
) -> bool:
    """Mirror meaningful authority-memory content into legacy MAINMEMORY.md."""
    authority = authority_text
    if authority is None:
        try:
            authority = paths.authority_memory_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False

    return sync_authority_text_to_legacy_mainmemory(paths.mainmemory_path, authority)


def sync_authority_text_to_legacy_mainmemory(mainmemory_path: Path, authority_text: str) -> bool:
    """Mirror authority-memory text into a specific legacy MAINMEMORY path."""
    current = (
        mainmemory_path.read_text(encoding="utf-8")
        if mainmemory_path.exists()
        else "# Main Memory\n"
    )
    new_content = _apply_compat_block(current, authority_text)
    if new_content == current:
        return False

    mainmemory_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text_save(mainmemory_path, new_content)
    return True


def _apply_compat_block(current: str, authority_text: str) -> str:
    block = (
        _render_compat_block(authority_text)
        if has_meaningful_authority_content(authority_text)
        else None
    )
    if _COMPAT_START_MARKER in current:
        before = current.split(_COMPAT_START_MARKER, 1)[0]
        after_parts = current.split(_COMPAT_END_MARKER, 1)
        after = after_parts[1] if len(after_parts) > 1 else ""
        if block is None:
            trimmed = (
                f"{before.rstrip()}\n{after.lstrip()}"
                if before.strip() and after.strip()
                else before + after
            )
            return trimmed.rstrip() + ("\n" if trimmed.strip() else "")
        return f"{before.rstrip()}\n\n{block}\n{after.lstrip()}".rstrip() + "\n"

    if block is None:
        return current
    return f"{current.rstrip()}\n\n{block}\n"


def _render_compat_block(authority_text: str) -> str:
    return (
        f"{_COMPAT_START_MARKER}\n"
        "## Authority Memory (v2 compatibility mirror)\n\n"
        f"{authority_text.strip()}\n"
        f"{_COMPAT_END_MARKER}"
    )
