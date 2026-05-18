"""Tests for runtime-owned cron/webhook artifact persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from controlmesh.cli.codex_cache import CodexModelCache
from controlmesh.cli.codex_discovery import CodexModelInfo
from controlmesh.cli.param_resolver import TaskOverrides
from controlmesh.config import AgentConfig
from controlmesh.cron.execution import OneShotExecutionResult
from controlmesh.infra.base_task_observer import BaseTaskObserver
from controlmesh.infra.task_runner import execute_in_task_folder
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    paths = ControlMeshPaths(
        controlmesh_home=tmp_path / "home", home_defaults=fw / "workspace", framework_root=fw
    )
    paths.cron_tasks_dir.mkdir(parents=True)
    return paths


def _make_codex_cache() -> CodexModelCache:
    cache = MagicMock(spec=CodexModelCache)
    cache.validate_model.return_value = True
    cache.get_model.return_value = CodexModelInfo(
        id="gpt-5.2-codex",
        display_name="GPT-5.2 Codex",
        description="Codex model",
        supported_efforts=("low", "medium", "high"),
        default_effort="medium",
        is_default=True,
    )
    return cache


class _Observer(BaseTaskObserver):
    pass


async def test_execute_in_task_folder_persists_last_run_artifact(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    task_dir = paths.cron_tasks_dir / "demo"
    task_dir.mkdir()
    (task_dir / "demo_MEMORY.md").write_text("# demo\n", encoding="utf-8")

    observer = _Observer(
        paths=paths,
        config=AgentConfig(provider="claude", model="sonnet"),
        codex_cache=_make_codex_cache(),
    )

    fake_execution = OneShotExecutionResult(
        status="success",
        result_text="ok",
        stdout=b'{"result":"ok"}',
        stderr=b"",
        returncode=0,
        timed_out=False,
    )

    with patch(
        "controlmesh.infra.task_runner.run_oneshot_task",
        return_value=type("R", (), {"status": "success", "result_text": "ok", "execution": fake_execution})(),
    ):
        result = await execute_in_task_folder(
            observer,
            cron_tasks_dir=paths.cron_tasks_dir,
            task_folder="demo",
            instruction="Do work",
            overrides=TaskOverrides(),
            dependency=None,
            task_id="demo",
            task_label="Cron job",
            timeout_seconds=60,
        )

    artifact_path = task_dir / "output" / "last_run.json"
    assert result.artifact_path == artifact_path
    assert artifact_path.is_file()
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["result_text"] == "ok"
    assert payload["provider"] == "claude"
    assert payload["model"] == "sonnet"
