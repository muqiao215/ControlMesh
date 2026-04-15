"""Tests for CLAUDE.md / AGENTS.md recursive synchronization."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import time
from pathlib import Path

from controlmesh.workspace.init import sync_rule_files, watch_rule_files


def test_sync_does_not_create_missing_files(tmp_path: Path) -> None:
    """_sync_group only syncs existing files, does not create missing ones."""
    (tmp_path / "CLAUDE.md").write_text("# Rules")
    sync_rule_files(tmp_path)
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "GEMINI.md").exists()


def test_sync_does_not_create_claude_from_agents(tmp_path: Path) -> None:
    """AGENTS.md exists alone -> CLAUDE.md is NOT created."""
    (tmp_path / "AGENTS.md").write_text("# Codex Rules")
    sync_rule_files(tmp_path)
    assert not (tmp_path / "CLAUDE.md").exists()


def test_sync_newer_claude_overwrites_agents(tmp_path: Path) -> None:
    """CLAUDE.md is newer -> overwrites AGENTS.md."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text("old content")

    # Ensure mtime difference
    time.sleep(0.05)

    claude = tmp_path / "CLAUDE.md"
    claude.write_text("new content")

    sync_rule_files(tmp_path)
    assert agents.read_text() == "new content"


def test_sync_newer_agents_overwrites_claude(tmp_path: Path) -> None:
    """AGENTS.md is newer -> overwrites CLAUDE.md."""
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("old content")

    time.sleep(0.05)

    agents = tmp_path / "AGENTS.md"
    agents.write_text("new content")

    sync_rule_files(tmp_path)
    assert claude.read_text() == "new content"


def test_sync_identical_no_write(tmp_path: Path) -> None:
    """Both exist with same mtime -> no writes happen."""
    claude = tmp_path / "CLAUDE.md"
    agents = tmp_path / "AGENTS.md"
    claude.write_text("same content")
    agents.write_text("same content")

    # Set same mtime
    mtime = claude.stat().st_mtime
    os.utime(agents, (mtime, mtime))

    stat_before = agents.stat().st_mtime
    sync_rule_files(tmp_path)
    stat_after = agents.stat().st_mtime
    assert stat_before == stat_after


def test_sync_recursive_subdirs(tmp_path: Path) -> None:
    """Sync works across nested subdirectories when both files exist."""
    sub1 = tmp_path / "sub1"
    sub2 = tmp_path / "sub1" / "sub2"
    sub2.mkdir(parents=True)

    # Create both files in each subdir, CLAUDE.md newer
    (sub1 / "AGENTS.md").write_text("old")
    (sub2 / "AGENTS.md").write_text("old")
    time.sleep(0.05)
    (sub1 / "CLAUDE.md").write_text("# Sub1 Rules")
    (sub2 / "CLAUDE.md").write_text("# Sub2 Rules")

    sync_rule_files(tmp_path)

    assert (sub1 / "AGENTS.md").read_text() == "# Sub1 Rules"
    assert (sub2 / "AGENTS.md").read_text() == "# Sub2 Rules"


def test_sync_recursive_does_not_create_missing(tmp_path: Path) -> None:
    """Sync in subdirectories does not create missing files."""
    sub = tmp_path / "sub1"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("# Rules")

    sync_rule_files(tmp_path)

    assert not (sub / "AGENTS.md").exists()
    assert not (sub / "GEMINI.md").exists()


def test_sync_skips_venv_and_dotdirs(tmp_path: Path) -> None:
    """Directories like .venv, .git, __pycache__ are skipped."""
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "CLAUDE.md").write_text("should not sync")

    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "CLAUDE.md").write_text("should not sync")

    sync_rule_files(tmp_path)

    assert not (venv_dir / "AGENTS.md").exists()
    assert not (pycache / "AGENTS.md").exists()


# -- watch_rule_files (async watcher) --


async def test_watch_rule_files_syncs_after_change(tmp_path: Path) -> None:
    """Watcher syncs existing AGENTS.md when CLAUDE.md is updated."""
    # Both files must exist; watcher only syncs existing files
    claude = tmp_path / "CLAUDE.md"
    agents = tmp_path / "AGENTS.md"
    agents.write_text("old content")
    # Make CLAUDE.md newer via explicit mtime
    claude.write_text("# Synced")
    os.utime(agents, (0, 0))

    task = asyncio.create_task(watch_rule_files(tmp_path, interval=0.1))
    try:
        await asyncio.sleep(0.3)
        assert agents.read_text() == "# Synced"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_watch_rule_files_syncs_subdirs(tmp_path: Path) -> None:
    """Watcher syncs AGENTS.md -> CLAUDE.md in subdirectories when both exist."""
    sub = tmp_path / "cron_tasks" / "daily"
    sub.mkdir(parents=True)

    # Both files must exist; AGENTS.md newer
    (sub / "CLAUDE.md").write_text("old content")
    (sub / "AGENTS.md").write_text("# Updated by Codex")
    os.utime(sub / "CLAUDE.md", (0, 0))

    task = asyncio.create_task(watch_rule_files(tmp_path, interval=0.1))
    try:
        await asyncio.sleep(0.3)
        assert (sub / "CLAUDE.md").read_text() == "# Updated by Codex"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_watch_does_not_create_missing_files(tmp_path: Path) -> None:
    """Watcher does not create missing files from a single existing one."""
    (tmp_path / "CLAUDE.md").write_text("# Rules")

    task = asyncio.create_task(watch_rule_files(tmp_path, interval=0.1))
    try:
        await asyncio.sleep(0.3)
        assert not (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / "GEMINI.md").exists()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def test_sync_skips_git_tracked_root_rule_files(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    agents = tmp_path / "AGENTS.md"
    claude.write_text("root truth")
    agents.write_text("older value")
    subprocess.run(["git", "add", "CLAUDE.md", "AGENTS.md"], cwd=tmp_path, check=True)
    os.utime(agents, (0, 0))

    sync_rule_files(tmp_path)

    assert agents.read_text() == "older value"


async def test_watch_skips_git_tracked_root_rule_files(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    agents = tmp_path / "AGENTS.md"
    claude.write_text("root truth")
    agents.write_text("older value")
    await asyncio.to_thread(
        subprocess.run,
        ["git", "add", "CLAUDE.md", "AGENTS.md"],
        cwd=tmp_path,
        check=True,
    )
    os.utime(agents, (0, 0))

    task = asyncio.create_task(watch_rule_files(tmp_path, interval=0.1))
    try:
        await asyncio.sleep(0.3)
        assert agents.read_text() == "older value"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
