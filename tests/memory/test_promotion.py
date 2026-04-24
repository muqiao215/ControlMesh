"""Tests for deterministic promotion candidate parsing and application."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from controlmesh.memory.commands import (
    apply_daily_note_promotions,
    preview_daily_note_promotions,
)
from controlmesh.memory.compat import (
    _COMPAT_END_MARKER,
    _COMPAT_START_MARKER,
    sync_authority_to_legacy_mainmemory,
)
from controlmesh.memory.promotion import parse_promotion_candidates
from controlmesh.memory.store import ensure_daily_note, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def test_parse_promotion_candidates_from_explicit_section() -> None:
    note = """# Daily Memory: 2026-04-08

## Signals
- Routine observation

## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
- [preference score=0.90] Prefer OpenClaw-style split memory, but adapted for ControlMesh.
"""

    candidates = parse_promotion_candidates(
        note,
        source_path=Path("memory/2026-04-08.md"),
        source_date=date(2026, 4, 8),
    )

    assert [candidate.category for candidate in candidates] == ["decision", "preference"]
    assert candidates[0].content == "Keep canonical authority file-backed and human-readable."
    assert candidates[1].score == 0.9
    assert candidates[0].line_start == 7


def test_preview_and_apply_daily_note_promotions(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
- [preference score=0.70] Prefer OpenClaw-style split memory, but adapted for ControlMesh.
""",
        encoding="utf-8",
    )

    preview = preview_daily_note_promotions(paths, date(2026, 4, 8), min_score=0.8)

    assert len(preview.selected) == 1
    assert preview.selected[0].category == "decision"
    assert preview.skipped_low_score == 1

    result = apply_daily_note_promotions(paths, date(2026, 4, 8), min_score=0.8)
    assert result.applied_count == 1
    assert result.skipped_existing == 0

    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "Keep canonical authority file-backed and human-readable." in memory_text
    assert "memory/2026-04-08.md" in memory_text

    second = apply_daily_note_promotions(paths, date(2026, 4, 8), min_score=0.8)
    assert second.applied_count == 0
    assert second.skipped_existing == 1

    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert _COMPAT_START_MARKER in legacy_text
    assert _COMPAT_END_MARKER in legacy_text
    assert "Keep canonical authority file-backed and human-readable." in legacy_text


def test_sync_authority_to_legacy_mainmemory_replaces_existing_compat_block(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.memory_system_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.mainmemory_path.write_text(
        "# Main Memory\n\n"
        "--- MEMORY V2 COMPAT START ---\nold mirror\n--- MEMORY V2 COMPAT END ---\n\n"
        "--- SHARED KNOWLEDGE START ---\nshared\n--- SHARED KNOWLEDGE END ---\n",
        encoding="utf-8",
    )

    written = sync_authority_to_legacy_mainmemory(
        paths,
        authority_text="# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n- New mirror.\n",
    )

    assert written is True
    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert "old mirror" not in legacy_text
    assert "New mirror." in legacy_text
    assert "shared" in legacy_text
    assert legacy_text.count(_COMPAT_START_MARKER) == 1
    assert legacy_text.count(_COMPAT_END_MARKER) == 1


def test_sync_authority_to_legacy_mainmemory_creates_file_on_first_compat_sync(
    tmp_path: Path,
) -> None:
    paths = _make_paths(tmp_path)
    assert not paths.mainmemory_path.exists()

    written = sync_authority_to_legacy_mainmemory(
        paths,
        authority_text="# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n- First compat sync.\n",
    )

    assert written is True
    assert paths.mainmemory_path.exists()
    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert _COMPAT_START_MARKER in legacy_text
    assert "First compat sync." in legacy_text


def test_sync_authority_to_legacy_mainmemory_removes_empty_compat_block(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.memory_system_dir.mkdir(parents=True, exist_ok=True)
    paths.mainmemory_path.write_text(
        "# Main Memory\n\n"
        "--- MEMORY V2 COMPAT START ---\nold mirror\n--- MEMORY V2 COMPAT END ---\n",
        encoding="utf-8",
    )

    written = sync_authority_to_legacy_mainmemory(
        paths,
        authority_text="# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n",
    )

    assert written is True
    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert _COMPAT_START_MARKER not in legacy_text
    assert "old mirror" not in legacy_text
