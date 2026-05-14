"""Tests for the cron_monitor.py CLI tool."""

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
    / "cron_tools"
    / "cron_monitor.py"
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


def _full_args(name: str = "release-ci-watch") -> list[str]:
    return [
        "--name",
        name,
        "--title",
        "Release CI Monitor",
        "--description",
        "Watch one release CI run and hand back the next step",
        "--schedule",
        "*/2 * * * *",
    ]


def test_cron_monitor_creates_taskhub_backed_monitor(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args())
    assert result.returncode == 0

    output = json.loads(result.stdout)
    assert output["job_kind"] == "monitor"
    assert output["execution_mode"] == "taskhub"
    assert output["template"] == "release-ci-monitor-template"
    assert output["monitor_entry"] == "cron_monitor.py"

    data = json.loads((tmp_path / "cron_jobs.json").read_text(encoding="utf-8"))
    job = next(j for j in data["jobs"] if j["id"] == "release-ci-watch")
    assert job["job_kind"] == "monitor"
    assert job["execution_mode"] == "taskhub"
    assert job["output_policy"] == "summarized_only"

    task_dir = tmp_path / "workspace" / "cron_tasks" / "release-ci-watch"
    assert task_dir.is_dir()
    task_desc = (task_dir / "TASK_DESCRIPTION.md").read_text(encoding="utf-8")
    assert "Release CI Monitor" in task_desc
    rules = (task_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "temporary release-phase monitor agent" in rules


def test_cron_monitor_missing_params_shows_tutorial(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, ["--name", "incomplete"])
    assert result.returncode == 1
    assert "CRON MONITOR" in result.stdout
    assert "Missing required parameters" in result.stdout
