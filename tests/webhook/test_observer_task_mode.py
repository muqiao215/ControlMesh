"""Tests for webhook task mode: external hook -> TaskHub background task."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from controlmesh.cli.codex_cache import CodexModelCache
from controlmesh.config import AgentConfig, WebhookConfig
from controlmesh.tasks.models import TaskSubmit
from controlmesh.webhook.manager import WebhookManager
from controlmesh.webhook.models import WebhookEntry
from controlmesh.webhook.observer import _SAFETY_END, _SAFETY_START, WebhookObserver
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def _make_config(**overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = {
        "webhooks": WebhookConfig(enabled=True, token="test-token"),
        "allowed_user_ids": [123456],
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_codex_cache() -> CodexModelCache:
    return CodexModelCache(last_updated=datetime.now(UTC).isoformat(), models=[])


def _make_observer(tmp_path: Path) -> tuple[WebhookObserver, WebhookManager]:
    paths = _make_paths(tmp_path)
    manager = WebhookManager(hooks_path=paths.webhooks_path)
    observer = WebhookObserver(
        paths,
        manager,
        config=_make_config(),
        codex_cache=_make_codex_cache(),
    )
    return observer, manager


def _add_task_hook(manager: WebhookManager, **overrides: Any) -> WebhookEntry:
    defaults: dict[str, Any] = {
        "id": "gh-ci-failed",
        "title": "GitHub CI failed",
        "description": "Create a background triage task for failed CI runs.",
        "mode": "task",
        "prompt_template": "repo={{repo}} sha={{sha}} run={{run_url}}",
        "task_name": "CI failure triage",
        "parent_agent": "main",
        "task_transport": "telegram",
        "provider": "codex",
        "model": "gpt-5.5",
        "reasoning_effort": "high",
        "workunit_kind": "test_execution",
        "route": "auto",
        "topology": "pipeline",
    }
    defaults.update(overrides)
    hook = WebhookEntry(**defaults)
    manager.add_hook(hook)
    return hook


async def test_task_mode_submits_background_task(tmp_path: Path) -> None:
    observer, manager = _make_observer(tmp_path)
    _add_task_hook(manager)

    hub = MagicMock()
    hub.submit = MagicMock(return_value="abc12345")
    observer.set_task_hub(hub)

    result = await observer._dispatch(
        "gh-ci-failed",
        {
            "repo": "muqiao215/ControlMesh",
            "sha": "deadbeef",
            "run_url": "https://github.com/example/actions/runs/1",
        },
    )

    assert result.status == "success"
    assert result.mode == "task"
    assert result.result_text == "Background task created: abc12345"

    submit = hub.submit.call_args.args[0]
    assert isinstance(submit, TaskSubmit)
    assert submit.chat_id == 123456
    assert submit.parent_agent == "main"
    assert submit.transport == "telegram"
    assert submit.name == "CI failure triage"
    assert submit.provider_override == "codex"
    assert submit.model_override == "gpt-5.5"
    assert submit.thinking_override == "high"
    assert submit.workunit_kind == "test_execution"
    assert submit.route == "auto"
    assert submit.topology == "pipeline"
    assert _SAFETY_START in submit.prompt
    assert "repo=muqiao215/ControlMesh" in submit.prompt
    assert _SAFETY_END in submit.prompt


async def test_task_mode_requires_task_hub(tmp_path: Path) -> None:
    observer, manager = _make_observer(tmp_path)
    _add_task_hook(manager)

    result = await observer._dispatch("gh-ci-failed", {"repo": "x", "sha": "y", "run_url": "z"})

    assert result.status == "error:no_task_hub"
    assert result.mode == "task"


async def test_task_mode_reports_submit_error(tmp_path: Path) -> None:
    observer, manager = _make_observer(tmp_path)
    _add_task_hook(manager)

    hub = MagicMock()
    hub.submit = MagicMock(side_effect=ValueError("Too many background tasks (5 max)"))
    observer.set_task_hub(hub)

    result = await observer._dispatch("gh-ci-failed", {"repo": "x", "sha": "y", "run_url": "z"})

    assert result.status == "error:Too many background tasks (5 max)"
    assert result.mode == "task"
