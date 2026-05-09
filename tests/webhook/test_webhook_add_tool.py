"""Tests for the webhook_add.py CLI tool (subprocess-based)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "controlmesh"
    / "_home_defaults"
    / "workspace"
    / "tools"
    / "webhook_tools"
    / "webhook_add.py"
)


def _run_tool(tmp_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CONTROLMESH_HOME": str(tmp_path)}
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_webhook_add_task_mode_creates_task_hook(tmp_path: Path) -> None:
    result = _run_tool(
        tmp_path,
        [
            "--name",
            "github-ci-failed",
            "--title",
            "GitHub CI Failed",
            "--description",
            "Create a background triage task for failed CI runs",
            "--mode",
            "task",
            "--prompt-template",
            "repo={{repo}} sha={{sha}} run={{run_url}}",
            "--provider",
            "codex",
            "--model",
            "gpt-5.5",
            "--reasoning-effort",
            "high",
            "--task-name",
            "CI failure triage",
            "--parent-agent",
            "main",
            "--task-transport",
            "telegram",
            "--workunit-kind",
            "test_execution",
            "--route",
            "auto",
            "--topology",
            "pipeline",
        ],
    )
    assert result.returncode == 0, result.stderr

    output = json.loads(result.stdout)
    assert output["hook_id"] == "github-ci-failed"
    assert output["mode"] == "task"
    assert output["task_defaults"] == {
        "task_name": "CI failure triage",
        "parent_agent": "main",
        "task_transport": "telegram",
        "workunit_kind": "test_execution",
        "route": "auto",
        "topology": "pipeline",
    }

    data = json.loads((tmp_path / "webhooks.json").read_text(encoding="utf-8"))
    hook = next(h for h in data["hooks"] if h["id"] == "github-ci-failed")
    assert hook["mode"] == "task"
    assert hook["provider"] == "codex"
    assert hook["model"] == "gpt-5.5"
    assert hook["reasoning_effort"] == "high"
    assert hook["task_name"] == "CI failure triage"
    assert hook["parent_agent"] == "main"
    assert hook["task_transport"] == "telegram"
    assert hook["workunit_kind"] == "test_execution"
    assert hook["route"] == "auto"
    assert hook["topology"] == "pipeline"
    assert hook["task_folder"] is None


def test_webhook_add_rejects_task_only_flags_for_non_task_mode(tmp_path: Path) -> None:
    result = _run_tool(
        tmp_path,
        [
            "--name",
            "wake-hook",
            "--title",
            "Wake Hook",
            "--description",
            "Wake the main chat",
            "--mode",
            "wake",
            "--prompt-template",
            "hello {{name}}",
            "--task-name",
            "Should Fail",
        ],
    )
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["error"] == "--task-name are only valid for mode 'task'"
