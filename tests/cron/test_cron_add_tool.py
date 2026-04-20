"""Tests for the cron_add.py CLI tool (subprocess-based)."""

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
    / "cron_add.py"
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


def _full_args(name: str = "test-job") -> list[str]:
    return [
        "--name",
        name,
        "--title",
        "Test Job",
        "--description",
        "A test cron job",
        "--schedule",
        "0 9 * * *",
    ]


def test_cron_add_creates_json_and_folder(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("my-job"))
    assert result.returncode == 0

    output = json.loads(result.stdout)
    assert output["job_id"] == "my-job"
    assert output["folder_created"] is True
    assert output["json_entry_created"] is True

    # JSON entry exists
    data = json.loads((tmp_path / "cron_jobs.json").read_text())
    assert any(j["id"] == "my-job" for j in data["jobs"])

    # Folder structure exists
    task_dir = tmp_path / "workspace" / "cron_tasks" / "my-job"
    assert task_dir.is_dir()
    assert (task_dir / "CLAUDE.md").exists()
    # By default only CLAUDE.md exists when no parent provider files are seeded.
    assert not (task_dir / "AGENTS.md").exists()
    assert (task_dir / "TASK_DESCRIPTION.md").exists()
    assert (task_dir / "my-job_MEMORY.md").exists()
    assert (task_dir / "scripts").is_dir()


def test_cron_add_duplicate_exits_1(tmp_path: Path) -> None:
    _run_tool(tmp_path, _full_args("dup"))
    result = _run_tool(tmp_path, _full_args("dup"))
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert "already exists" in output["error"]


def test_cron_add_missing_params_shows_tutorial(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, ["--name", "incomplete"])
    assert result.returncode == 1
    assert "CRON ADD" in result.stdout
    assert "CRON EXPRESSION FORMAT" in result.stdout
    assert "Missing required parameters" in result.stdout


def test_cron_add_no_args_shows_tutorial(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, [])
    assert result.returncode == 1
    assert "CRON ADD" in result.stdout


def test_cron_add_sanitizes_name(tmp_path: Path) -> None:
    args = _full_args("My Feature!!")
    result = _run_tool(tmp_path, args)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["job_id"] == "my-feature"


def test_cron_add_claude_md_has_fixed_content(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("rule-test"))
    assert result.returncode == 0
    task_dir = tmp_path / "workspace" / "cron_tasks" / "rule-test"
    content = (task_dir / "CLAUDE.md").read_text()
    assert "Your Mission" in content
    assert "TASK_DESCRIPTION.md" in content
    assert "automated agent" in content
    # Description should NOT be in CLAUDE.md (it's in TASK_DESCRIPTION.md)
    assert "A test cron job" not in content


def test_cron_add_creates_task_description(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("desc-test"))
    assert result.returncode == 0
    task_dir = tmp_path / "workspace" / "cron_tasks" / "desc-test"
    content = (task_dir / "TASK_DESCRIPTION.md").read_text()
    assert "A test cron job" in content
    assert "Test Job" in content
    assert "## Assignment" in content
    assert "## Output" in content


def test_cron_add_json_has_fixed_instruction(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("instr-test"))
    assert result.returncode == 0
    data = json.loads((tmp_path / "cron_jobs.json").read_text())
    job = next(j for j in data["jobs"] if j["id"] == "instr-test")
    assert "TASK_DESCRIPTION.md" in job["agent_instruction"]


def test_cron_add_output_includes_action_required(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("step-test"))
    assert result.returncode == 0
    output = json.loads(result.stdout)
    actions = output["action_required"]
    assert isinstance(actions, list)
    assert len(actions) >= 3
    joined = " ".join(actions)
    assert "TASK_DESCRIPTION.md" in joined
    assert "scripts/" in joined
    assert "step-test_MEMORY.md" in joined


def test_cron_add_agents_md_mirrors_claude_md(tmp_path: Path) -> None:
    cron_tasks_dir = tmp_path / "workspace" / "cron_tasks"
    cron_tasks_dir.mkdir(parents=True, exist_ok=True)
    (cron_tasks_dir / "CLAUDE.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "AGENTS.md").write_text("parent", encoding="utf-8")

    result = _run_tool(tmp_path, _full_args("mirror-test"))
    assert result.returncode == 0
    task_dir = tmp_path / "workspace" / "cron_tasks" / "mirror-test"
    assert (task_dir / "CLAUDE.md").read_text() == (task_dir / "AGENTS.md").read_text()


def test_cron_add_no_venv_by_default(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("venv-test"))
    assert result.returncode == 0
    task_dir = tmp_path / "workspace" / "cron_tasks" / "venv-test"
    assert not (task_dir / ".venv").exists()


def test_cron_add_creates_default_task_config(tmp_path: Path) -> None:
    result = _run_tool(tmp_path, _full_args("policy-default"))
    assert result.returncode == 0

    task_config = (
        tmp_path / "workspace" / "cron_tasks" / "policy-default" / "task.config.json"
    )
    assert task_config.exists()

    policy = json.loads(task_config.read_text(encoding="utf-8"))
    assert policy == {
        "delivery": {
            "primary": "feishu",
            "format": "markdown_text",
        },
        "artifact": {
            "mode": "local",
            "path": "output",
        },
        "publish": {
            "enabled": False,
            "target": "none",
            "mode": "none",
            "require_review": True,
        },
    }


def test_cron_add_accepts_explicit_publish_policy_without_changing_job_schema(
    tmp_path: Path,
) -> None:
    result = _run_tool(
        tmp_path,
        [
            *_full_args("policy-explicit"),
            "--delivery-primary",
            "matrix",
            "--delivery-format",
            "markdown_file",
            "--artifact-mode",
            "shared",
            "--artifact-path",
            "artifacts/daily.md",
            "--publish-enabled",
            "--publish-target",
            "feishu_bitable",
            "--publish-mode",
            "upsert",
            "--publish-no-review",
        ],
    )
    assert result.returncode == 0

    task_config = (
        tmp_path / "workspace" / "cron_tasks" / "policy-explicit" / "task.config.json"
    )
    policy = json.loads(task_config.read_text(encoding="utf-8"))
    assert policy == {
        "delivery": {
            "primary": "matrix",
            "format": "markdown_file",
        },
        "artifact": {
            "mode": "shared",
            "path": "artifacts/daily.md",
        },
        "publish": {
            "enabled": True,
            "target": "feishu_bitable",
            "mode": "upsert",
            "require_review": False,
        },
    }

    data = json.loads((tmp_path / "cron_jobs.json").read_text(encoding="utf-8"))
    job = next(j for j in data["jobs"] if j["id"] == "policy-explicit")
    assert "delivery" not in job
    assert "artifact" not in job
    assert "publish" not in job


def test_cron_add_rolls_back_task_folder_when_policy_validation_fails(tmp_path: Path) -> None:
    result = _run_tool(
        tmp_path,
        [
            *_full_args("policy-invalid"),
            "--delivery-primary",
            "   ",
        ],
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["error"] == "delivery.primary must not be empty"
    assert not (tmp_path / "workspace" / "cron_tasks" / "policy-invalid").exists()
    assert not (tmp_path / "cron_jobs.json").exists()
