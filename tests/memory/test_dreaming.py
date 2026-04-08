"""Tests for dreaming sweep state and lock helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ductor_bot.memory.dreaming import (
    DreamingCheckpoint,
    DreamingSweepState,
    acquire_dream_lock,
    load_checkpoints,
    load_sweep_state,
    release_dream_lock,
    save_checkpoints,
    save_sweep_state,
)
from ductor_bot.memory.store import initialize_memory_v2
from ductor_bot.workspace.paths import DuctorPaths


def _make_paths(tmp_path: Path) -> DuctorPaths:
    fw = tmp_path / "fw"
    return DuctorPaths(
        ductor_home=tmp_path / "home",
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
