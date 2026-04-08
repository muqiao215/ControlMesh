"""Tests for memory-v2 workspace path helpers."""

from __future__ import annotations

from pathlib import Path

from ductor_bot.workspace.paths import DuctorPaths


def test_memory_v2_paths() -> None:
    paths = DuctorPaths(
        ductor_home=Path("/home/test/.ductor"),
        home_defaults=Path("/opt/ductor/home-defaults"),
        framework_root=Path("/opt/ductor"),
    )

    assert paths.authority_memory_path == Path("/home/test/.ductor/workspace/MEMORY.md")
    assert paths.dream_diary_path == Path("/home/test/.ductor/workspace/DREAMS.md")
    assert paths.memory_v2_daily_dir == Path("/home/test/.ductor/workspace/memory")
    assert paths.memory_v2_machine_state_dir == Path("/home/test/.ductor/workspace/memory/.dreams")
    assert paths.dreaming_sweep_state_path == Path(
        "/home/test/.ductor/workspace/memory/.dreams/sweep_state.json"
    )
    assert paths.dreaming_checkpoints_path == Path(
        "/home/test/.ductor/workspace/memory/.dreams/checkpoints.json"
    )
    assert paths.dreaming_lock_path == Path(
        "/home/test/.ductor/workspace/memory/.dreams/dreaming.lock.json"
    )
    assert paths.memory_promotion_log_path == Path(
        "/home/test/.ductor/workspace/memory/.dreams/promotion_log.json"
    )
    assert paths.memory_search_index_path == Path(
        "/home/test/.ductor/workspace/memory/.dreams/search.sqlite3"
    )
    assert paths.dreaming_sweep_log_path == Path(
        "/home/test/.ductor/workspace/memory/.dreams/sweep_log.jsonl"
    )
