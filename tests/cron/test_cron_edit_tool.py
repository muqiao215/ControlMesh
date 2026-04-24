"""Tests for the cron_edit.py CLI tool (subprocess-based)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

TOOL_ADD = (
    Path(__file__).resolve().parents[2]
    / "controlmesh"
    / "_home_defaults"
    / "workspace"
    / "tools"
    / "cron_tools"
    / "cron_add.py"
)
TOOL_EDIT = (
    Path(__file__).resolve().parents[2]
    / "controlmesh"
    / "_home_defaults"
    / "workspace"
    / "tools"
    / "cron_tools"
    / "cron_edit.py"
)


def _run(tmp_path: Path, tool: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CONTROLMESH_HOME": str(tmp_path)}
    return subprocess.run(
        [sys.executable, str(tool), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _add_job(tmp_path: Path, name: str = "edit-test") -> None:
    result = _run(
        tmp_path,
        TOOL_ADD,
        [
            "--name",
            name,
            "--title",
            "Edit Test",
            "--description",
            "Original description",
            "--schedule",
            "0 9 * * *",
        ],
    )
    assert result.returncode == 0


def _job(tmp_path: Path, job_id: str) -> dict[str, Any]:
    data = json.loads((tmp_path / "cron_jobs.json").read_text())
    return next(j for j in data["jobs"] if j["id"] == job_id)


def test_cron_edit_updates_title_description_schedule(tmp_path: Path) -> None:
    _add_job(tmp_path, "meta-job")

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "meta-job",
            "--title",
            "Meta Job Updated",
            "--description",
            "New description",
            "--schedule",
            "30 7 * * 1-5",
        ],
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["updated"] is True
    assert "title" in output["updated_fields"]
    assert "description" in output["updated_fields"]
    assert "schedule" in output["updated_fields"]

    job = _job(tmp_path, "meta-job")
    assert job["title"] == "Meta Job Updated"
    assert job["description"] == "New description"
    assert job["schedule"] == "30 7 * * 1-5"


def test_cron_edit_normalizes_claw_code_provider_alias(tmp_path: Path) -> None:
    _add_job(tmp_path, "provider-edit")

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "provider-edit",
            "--provider",
            "claw-code",
            "--model",
            "sonnet",
        ],
    )
    assert result.returncode == 0

    job = _job(tmp_path, "provider-edit")
    assert job["provider"] == "claw"
    assert job["model"] == "sonnet"


def test_cron_edit_accepts_opencode_provider(tmp_path: Path) -> None:
    _add_job(tmp_path, "provider-opencode")

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "provider-opencode",
            "--provider",
            "opencode",
            "--model",
            "openai/gpt-4.1",
        ],
    )
    assert result.returncode == 0

    job = _job(tmp_path, "provider-opencode")
    assert job["provider"] == "opencode"
    assert job["model"] == "openai/gpt-4.1"


def test_cron_edit_rename_updates_json_and_folder(tmp_path: Path) -> None:
    _add_job(tmp_path, "old-name")
    old_dir = tmp_path / "workspace" / "cron_tasks" / "old-name"
    assert (old_dir / "old-name_MEMORY.md").exists()

    result = _run(tmp_path, TOOL_EDIT, ["old-name", "--name", "new-name"])
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["job_id"] == "new-name"
    assert output["folder_renamed"] is True
    assert output["memory_file_renamed"] is True
    assert "id" in output["updated_fields"]
    assert "task_folder" in output["updated_fields"]

    data = json.loads((tmp_path / "cron_jobs.json").read_text())
    assert any(j["id"] == "new-name" and j["task_folder"] == "new-name" for j in data["jobs"])
    assert not old_dir.exists()

    new_dir = tmp_path / "workspace" / "cron_tasks" / "new-name"
    assert new_dir.is_dir()
    assert (new_dir / "new-name_MEMORY.md").exists()
    claude = (new_dir / "CLAUDE.md").read_text()
    agents = (new_dir / "AGENTS.md").read_text()
    assert "new-name_MEMORY.md" in claude
    assert agents == claude


def test_cron_edit_disable_then_enable(tmp_path: Path) -> None:
    _add_job(tmp_path, "toggle-job")

    disabled = _run(tmp_path, TOOL_EDIT, ["toggle-job", "--disable"])
    assert disabled.returncode == 0
    assert _job(tmp_path, "toggle-job")["enabled"] is False

    enabled = _run(tmp_path, TOOL_EDIT, ["toggle-job", "--enable"])
    assert enabled.returncode == 0
    assert _job(tmp_path, "toggle-job")["enabled"] is True


def test_cron_edit_no_change_flags_exits_1(tmp_path: Path) -> None:
    _add_job(tmp_path, "no-change")
    result = _run(tmp_path, TOOL_EDIT, ["no-change"])
    assert result.returncode == 1
    assert "CRON EDIT" in result.stdout
    assert "Missing changes" in result.stdout


def test_cron_edit_nonexistent_exits_1(tmp_path: Path) -> None:
    (tmp_path / "cron_jobs.json").write_text('{"jobs": []}')
    result = _run(tmp_path, TOOL_EDIT, ["ghost", "--title", "x"])
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert "not found" in output["error"]


def test_cron_edit_updates_task_config_without_recreating_job(tmp_path: Path) -> None:
    _add_job(tmp_path, "policy-edit")
    before_job = _job(tmp_path, "policy-edit").copy()
    task_dir = tmp_path / "workspace" / "cron_tasks" / "policy-edit"
    memory_before = (task_dir / "policy-edit_MEMORY.md").read_text(encoding="utf-8")

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "policy-edit",
            "--delivery-primary",
            "telegram",
            "--artifact-path",
            "output/report.md",
            "--publish-enabled",
            "--publish-target",
            "feishu_doc",
            "--publish-mode",
            "append",
            "--publish-no-review",
        ],
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["updated"] is True
    assert output["policy_updated"] is True
    assert output["policy_updated_fields"] == [
        "delivery.primary",
        "artifact.path",
        "publish.enabled",
        "publish.target",
        "publish.mode",
        "publish.require_review",
    ]

    after_job = _job(tmp_path, "policy-edit")
    assert after_job == before_job
    assert (task_dir / "policy-edit_MEMORY.md").read_text(encoding="utf-8") == memory_before

    policy = json.loads((task_dir / "task.config.json").read_text(encoding="utf-8"))
    assert policy["delivery"]["primary"] == "telegram"
    assert policy["delivery"]["format"] == "markdown_text"
    assert policy["artifact"]["mode"] == "local"
    assert policy["artifact"]["path"] == "output/report.md"
    assert policy["publish"] == {
        "enabled": True,
        "target": "feishu_doc",
        "mode": "append",
        "require_review": False,
    }


def test_cron_edit_rename_rolls_back_when_followup_validation_fails(tmp_path: Path) -> None:
    _add_job(tmp_path, "rename-rollback")
    old_dir = tmp_path / "workspace" / "cron_tasks" / "rename-rollback"

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "rename-rollback",
            "--name",
            "rename-new",
            "--title",
            "",
        ],
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["error"] == "Title must not be empty"

    assert old_dir.is_dir()
    assert not (tmp_path / "workspace" / "cron_tasks" / "rename-new").exists()

    job = _job(tmp_path, "rename-rollback")
    assert job["id"] == "rename-rollback"
    assert job["task_folder"] == "rename-rollback"


def test_cron_edit_rename_updates_gemini_rule_file_memory_reference(tmp_path: Path) -> None:
    cron_tasks_dir = tmp_path / "workspace" / "cron_tasks"
    cron_tasks_dir.mkdir(parents=True, exist_ok=True)
    (cron_tasks_dir / "CLAUDE.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "AGENTS.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "GEMINI.md").write_text("parent", encoding="utf-8")
    _add_job(tmp_path, "gemini-old")

    result = _run(tmp_path, TOOL_EDIT, ["gemini-old", "--name", "gemini-new"])

    assert result.returncode == 0
    new_dir = tmp_path / "workspace" / "cron_tasks" / "gemini-new"
    gemini = (new_dir / "GEMINI.md").read_text(encoding="utf-8")
    assert "gemini-new_MEMORY.md" in gemini
    assert "gemini-old_MEMORY.md" not in gemini


def test_cron_edit_rename_restores_memory_and_rules_when_policy_validation_fails(
    tmp_path: Path,
) -> None:
    cron_tasks_dir = tmp_path / "workspace" / "cron_tasks"
    cron_tasks_dir.mkdir(parents=True, exist_ok=True)
    (cron_tasks_dir / "CLAUDE.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "AGENTS.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "GEMINI.md").write_text("parent", encoding="utf-8")
    _add_job(tmp_path, "rollback-policy-old")

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "rollback-policy-old",
            "--name",
            "rollback-policy-new",
            "--delivery-primary",
            "   ",
        ],
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["error"] == "delivery.primary must not be empty"

    restored_dir = tmp_path / "workspace" / "cron_tasks" / "rollback-policy-old"
    assert restored_dir.is_dir()
    assert not (tmp_path / "workspace" / "cron_tasks" / "rollback-policy-new").exists()
    assert (restored_dir / "rollback-policy-old_MEMORY.md").exists()
    assert not (restored_dir / "rollback-policy-new_MEMORY.md").exists()
    assert "rollback-policy-old_MEMORY.md" in (restored_dir / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    assert "rollback-policy-old_MEMORY.md" in (restored_dir / "GEMINI.md").read_text(
        encoding="utf-8"
    )


def test_cron_edit_rename_restores_legacy_id_memory_reference_on_policy_failure(
    tmp_path: Path,
) -> None:
    cron_tasks_dir = tmp_path / "workspace" / "cron_tasks"
    cron_tasks_dir.mkdir(parents=True, exist_ok=True)
    (cron_tasks_dir / "CLAUDE.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "AGENTS.md").write_text("parent", encoding="utf-8")
    (cron_tasks_dir / "GEMINI.md").write_text("parent", encoding="utf-8")
    _add_job(tmp_path, "legacy-folder")

    data = json.loads((tmp_path / "cron_jobs.json").read_text(encoding="utf-8"))
    data["jobs"][0]["id"] = "legacy-job-id"
    data["jobs"][0]["task_folder"] = "legacy-folder"
    (tmp_path / "cron_jobs.json").write_text(json.dumps(data), encoding="utf-8")

    task_dir = tmp_path / "workspace" / "cron_tasks" / "legacy-folder"
    (task_dir / "legacy-folder_MEMORY.md").rename(task_dir / "legacy-job-id_MEMORY.md")
    rule_text = (task_dir / "CLAUDE.md").read_text(encoding="utf-8").replace(
        "legacy-folder_MEMORY.md",
        "legacy-job-id_MEMORY.md",
    )
    for filename in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        (task_dir / filename).write_text(rule_text, encoding="utf-8")

    result = _run(
        tmp_path,
        TOOL_EDIT,
        [
            "legacy-job-id",
            "--name",
            "new-folder",
            "--delivery-primary",
            "   ",
        ],
    )

    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["error"] == "delivery.primary must not be empty"

    restored_dir = tmp_path / "workspace" / "cron_tasks" / "legacy-folder"
    assert restored_dir.is_dir()
    assert (restored_dir / "legacy-job-id_MEMORY.md").exists()
    assert not (restored_dir / "legacy-folder_MEMORY.md").exists()
    for filename in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        text = (restored_dir / filename).read_text(encoding="utf-8")
        assert "legacy-job-id_MEMORY.md" in text
        assert "legacy-folder_MEMORY.md" not in text


def test_cron_edit_legacy_metadata_update_preserves_cron_jobs_schema(
    tmp_path: Path,
) -> None:
    _add_job(tmp_path, "legacy-edit")
    before_keys = set(_job(tmp_path, "legacy-edit"))

    result = _run(tmp_path, TOOL_EDIT, ["legacy-edit", "--schedule", "15 8 * * *"])
    assert result.returncode == 0

    job = _job(tmp_path, "legacy-edit")
    assert set(job) == before_keys
    assert job["schedule"] == "15 8 * * *"
    assert "delivery" not in job
    assert "artifact" not in job
    assert "publish" not in job
