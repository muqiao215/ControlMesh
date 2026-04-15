"""Tests for dreaming sweep state and lock helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from controlmesh.memory.dreaming import (
    DreamingCheckpoint,
    DreamingSweepState,
    acquire_dream_lock,
    apply_dreaming_sweep,
    load_checkpoints,
    load_sweep_state,
    preview_dreaming_sweep,
    release_dream_lock,
    save_checkpoints,
    save_sweep_state,
)
from controlmesh.memory.store import ensure_daily_note, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def test_save_and_load_sweep_state(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    state = DreamingSweepState(
        status="completed",
        last_started_at="2026-04-08T03:00:00Z",
        last_completed_at="2026-04-08T03:04:00Z",
        last_processed_day="2026-04-07",
        promoted_candidate_keys=["abc123"],
    )

    save_sweep_state(paths, state)
    loaded = load_sweep_state(paths)

    assert loaded.status == "completed"
    assert loaded.last_processed_day == "2026-04-07"
    assert loaded.promoted_candidate_keys == ["abc123"]


def test_save_and_load_checkpoints(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    checkpoints = {
        "2026-04-07": DreamingCheckpoint(
            note_date="2026-04-07",
            note_path="memory/2026-04-07.md",
            note_hash="deadbeef",
            candidate_keys=["abc123", "def456"],
            processed_at="2026-04-08T03:04:00Z",
        )
    }

    save_checkpoints(paths, checkpoints)
    loaded = load_checkpoints(paths)

    assert tuple(loaded) == ("2026-04-07",)
    assert loaded["2026-04-07"].note_hash == "deadbeef"


def test_dream_lock_is_exclusive_until_released_or_expired(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    now = datetime(2026, 4, 8, 3, 0, 0, tzinfo=UTC)

    first = acquire_dream_lock(paths, owner="worker-a", now=now, ttl_seconds=600)
    assert first is not None
    assert first.owner == "worker-a"

    second = acquire_dream_lock(
        paths,
        owner="worker-b",
        now=now + timedelta(minutes=5),
        ttl_seconds=600,
    )
    assert second is None

    assert release_dream_lock(paths, owner="worker-b") is False
    assert release_dream_lock(paths, owner="worker-a") is True

    third = acquire_dream_lock(
        paths,
        owner="worker-b",
        now=now + timedelta(minutes=5),
        ttl_seconds=600,
    )
    assert third is not None
    assert third.owner == "worker-b"


def test_preview_dreaming_sweep_reports_candidates_without_writing_checkpoints(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    first_note = ensure_daily_note(paths, datetime(2026, 4, 7, tzinfo=UTC).date())
    second_note = ensure_daily_note(paths, datetime(2026, 4, 8, tzinfo=UTC).date())
    first_note.write_text(
        """# Daily Memory: 2026-04-07

## Promotion Candidates
- [decision] Keep local memory canonical.
""",
        encoding="utf-8",
    )
    second_note.write_text(
        """# Daily Memory: 2026-04-08

## Promotion Candidates
- [preference score=0.90] Prefer deterministic dreaming sweeps.
""",
        encoding="utf-8",
    )

    result = preview_dreaming_sweep(
        paths,
        owner="preview-worker",
        now=datetime(2026, 4, 8, 5, 0, 0, tzinfo=UTC),
        min_score=0.8,
    )
    state = load_sweep_state(paths)

    assert result.mode == "preview"
    assert result.changed_notes == 2
    assert result.selected_count == 2
    assert result.applied_count == 0
    assert load_checkpoints(paths) == {}
    assert state.status == "previewed"
    assert state.last_processed_day == "2026-04-08"
    assert paths.dreaming_lock_path.exists() is False


def test_apply_dreaming_sweep_applies_new_candidates_and_skips_unchanged_notes(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    first_note = ensure_daily_note(paths, datetime(2026, 4, 7, tzinfo=UTC).date())
    second_note = ensure_daily_note(paths, datetime(2026, 4, 8, tzinfo=UTC).date())
    first_note.write_text(
        """# Daily Memory: 2026-04-07

## Promotion Candidates
- [decision] Keep local memory canonical.
""",
        encoding="utf-8",
    )
    second_note.write_text(
        """# Daily Memory: 2026-04-08

## Promotion Candidates
- [preference score=0.90] Prefer deterministic dreaming sweeps.
""",
        encoding="utf-8",
    )

    first = apply_dreaming_sweep(
        paths,
        owner="apply-worker",
        now=datetime(2026, 4, 8, 5, 5, 0, tzinfo=UTC),
        min_score=0.8,
    )
    second = apply_dreaming_sweep(
        paths,
        owner="apply-worker",
        now=datetime(2026, 4, 8, 5, 10, 0, tzinfo=UTC),
        min_score=0.8,
    )
    state = load_sweep_state(paths)
    checkpoints = load_checkpoints(paths)
    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")
    dreams_text = paths.dream_diary_path.read_text(encoding="utf-8")

    assert first.mode == "apply"
    assert first.changed_notes == 2
    assert first.applied_count == 2
    assert tuple(checkpoints) == ("2026-04-07", "2026-04-08")
    assert "Keep local memory canonical." in memory_text
    assert "Prefer deterministic dreaming sweeps." in memory_text
    assert "Dreaming sweep apply" in dreams_text
    assert second.changed_notes == 0
    assert second.skipped_unchanged_notes == 2
    assert second.applied_count == 0
    assert state.status == "completed"
    assert second.promoted_candidate_keys == []
    assert state.promoted_candidate_keys == []
