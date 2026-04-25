"""Tests for memory-v2 file bootstrap helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.memory.dreaming import load_checkpoints, load_sweep_state
from controlmesh.memory.store import append_dream_entry, ensure_daily_note, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def test_initialize_memory_v2_bootstraps_layout(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)

    initialize_memory_v2(paths)

    assert paths.authority_memory_path.exists()
    assert paths.dream_diary_path.exists()
    assert paths.memory_v2_machine_state_dir.exists()
    assert "ControlMesh Memory v2" in paths.authority_memory_path.read_text(encoding="utf-8")
    assert "ControlMesh Dream Diary" in paths.dream_diary_path.read_text(encoding="utf-8")

    state = load_sweep_state(paths)
    assert state.status == "idle"
    assert state.last_completed_at is None
    assert load_checkpoints(paths) == {}


def test_ensure_daily_note_creates_template(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)

    note_path = ensure_daily_note(paths, date(2026, 4, 8))

    assert note_path == paths.memory_v2_daily_dir / "2026-04-08.md"
    content = note_path.read_text(encoding="utf-8")
    assert "# Daily Memory: 2026-04-08" in content
    assert "## Events" in content
    assert "## Signals" in content
    assert "## Evidence" in content
    assert "## Open Candidates" in content


def test_append_dream_entry_appends_markdown(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    append_dream_entry(
        paths,
        title="Cross-day signal",
        body="Repeated preference for file-backed memory authority.",
        dreamed_at=datetime(2026, 4, 8, 3, 0, 0, tzinfo=UTC),
    )

    content = paths.dream_diary_path.read_text(encoding="utf-8")
    assert "Cross-day signal" in content
    assert "Repeated preference for file-backed memory authority." in content
    assert "2026-04-08 03:00:00" in content
