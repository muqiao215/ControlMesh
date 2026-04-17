"""Tests for product-facing task runtime CLI commands."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

from rich.console import Console

from controlmesh.config import AgentConfig
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.workspace.paths import resolve_paths


def _import_tasks_cli_module() -> ModuleType:
    return importlib.import_module("controlmesh.cli_commands.tasks")


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(controlmesh_home=str(tmp_path))


def _submit(name: str = "Feishu research") -> TaskSubmit:
    return TaskSubmit(
        chat_id=1,
        prompt="read Feishu thread and produce summary",
        message_id=1,
        thread_id=None,
        parent_agent="main",
        name=name,
    )


def test_tasks_list_renders_registry_entries(monkeypatch, tmp_path: Path) -> None:
    module = _import_tasks_cli_module()
    config = _config(tmp_path)
    paths = resolve_paths(controlmesh_home=tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    entry = registry.create(_submit(), "codex", "gpt-5.4")
    registry.update_status(entry.task_id, "done", elapsed_seconds=12.0)
    console = Console(record=True, width=160)

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_console", console, raising=False)

    module.cmd_tasks(["tasks", "list"])

    rendered = console.export_text()
    assert entry.task_id in rendered
    assert "Feishu research" in rendered
    assert "done" in rendered


def test_tasks_doctor_shows_policy_and_runtime_primitives(monkeypatch, tmp_path: Path) -> None:
    module = _import_tasks_cli_module()
    config = _config(tmp_path)
    console = Console(record=True, width=160)

    monkeypatch.setattr(module, "load_config", lambda: config, raising=False)
    monkeypatch.setattr(module, "_console", console, raising=False)

    module.cmd_tasks(["tasks", "doctor"])

    rendered = console.export_text()
    assert "Task runtime doctor" in rendered
    assert "Delegation threshold: >30 seconds" in rendered
    assert "/tasks/create" in rendered
    assert "/tasks/list" in rendered
    assert "/interagent/send" in rendered
