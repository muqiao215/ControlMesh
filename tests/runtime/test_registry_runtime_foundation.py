"""Tests for lightweight runtime registry and repo worktree foundation."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

from controlmesh.cli.process_registry import ProcessRegistry
from controlmesh.runtime.registry import (
    ProcessLeaseStore,
    RepoWorktreeManager,
    RuntimeRegistry,
)
from controlmesh.tasks.models import TaskEntry
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=tmp_path / "repo",
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")


def _entry(task_id: str, *, workunit_kind: str = "code_review") -> TaskEntry:
    return TaskEntry(
        task_id=task_id,
        chat_id=1,
        parent_agent="main",
        name="Review",
        prompt_preview="review",
        provider="claude",
        model="sonnet",
        status="running",
        workunit_kind=workunit_kind,
        tasks_dir="",
    )


def test_runtime_registry_records_provider_binding(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    registry = RuntimeRegistry(paths)

    registry.record_provider_binding(
        requested_provider="claude",
        requested_model="sonnet",
        effective_provider="claude",
        effective_model="sonnet",
        process_label="task:abc",
    )

    data = json.loads(paths.runtime_registry_path.read_text(encoding="utf-8"))
    assert data["providers"]["claude"]["effective_model"] == "sonnet"
    assert data["providers"]["claude"]["process_label"] == "task:abc"


def test_process_registry_persists_and_removes_process_leases(tmp_path: Path) -> None:
    store = ProcessLeaseStore(tmp_path / "processes.json")
    registry = ProcessRegistry(store)
    process = AsyncMock(spec=asyncio.subprocess.Process)
    process.pid = 12345
    process.returncode = None

    tracked = registry.register(1, process, "task:abc", topic_id=9)
    data = json.loads((tmp_path / "processes.json").read_text(encoding="utf-8"))
    assert data["processes"]["1:task:abc:12345"]["topic_id"] == 9

    registry.unregister(tracked)
    data = json.loads((tmp_path / "processes.json").read_text(encoding="utf-8"))
    assert data["processes"] == {}


def test_repo_worktree_manager_binds_readonly_task_to_detached_worktree(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _init_repo(paths.framework_root)
    entry = _entry("abc12345")
    entry.tasks_dir = str(paths.tasks_dir)

    binding = RepoWorktreeManager(paths).bind_task(entry)

    assert binding is not None
    assert binding.mode == "readonly"
    assert binding.worktree_path == paths.worktrees_dir / entry.task_id
    assert binding.worktree_path.is_dir()
    saved = json.loads((paths.tasks_dir / entry.task_id / "REPO_BINDING.json").read_text())
    assert saved["commit_sha"] == binding.commit_sha


def test_repo_worktree_manager_marks_release_binding_with_repo_lock(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _init_repo(paths.framework_root)
    entry = _entry("rel12345", workunit_kind="github_release")
    entry.tasks_dir = str(paths.tasks_dir)

    binding = RepoWorktreeManager(paths).bind_task(entry)

    assert binding is not None
    assert binding.mode == "release_locked"
    assert binding.repo_lock == f"{paths.framework_root.name}:release"
