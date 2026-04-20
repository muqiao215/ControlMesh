"""Shared helpers for cron tool scripts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from controlmesh.cron.policy import default_task_policy, load_task_policy, task_policy_path
from controlmesh._home_defaults.workspace.tools._tool_shared import (
    available_ids,
    find_by_id,
    load_collection_or_default,
    load_collection_strict,
    sanitize_name,
    save_collection,
)

# Re-export so existing tool scripts keep working with ``from _shared import sanitize_name``
sanitize_name = sanitize_name

CONTROLMESH_HOME = Path(os.environ.get("CONTROLMESH_HOME", "~/.controlmesh")).expanduser()
CONFIG_PATH = CONTROLMESH_HOME / "config" / "config.json"
JOBS_PATH = CONTROLMESH_HOME / "cron_jobs.json"
CRON_TASKS_DIR = CONTROLMESH_HOME / "workspace" / "cron_tasks"

# Provider rule files — only create for authenticated providers.
_RULE_FILENAMES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")


def read_user_timezone() -> str:
    """Read user_timezone from config.json. Returns empty string if not set."""
    if not CONFIG_PATH.exists():
        return ""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return str(data.get("user_timezone", "")).strip()
    except (json.JSONDecodeError, OSError):
        return ""


def detect_rule_filenames() -> list[str]:
    """Determine which rule files to create based on parent cron_tasks/ contents.

    Checks which provider rule files (CLAUDE.md, AGENTS.md, GEMINI.md) exist
    in the ``cron_tasks/`` root.  These are deployed by the RulesSelector during
    workspace init based on CLI authentication status.

    Falls back to ``["CLAUDE.md"]`` when no rule files are found.
    """
    found = [name for name in _RULE_FILENAMES if (CRON_TASKS_DIR / name).is_file()]
    return found or ["CLAUDE.md"]


def render_cron_task_claude_md(name: str) -> str:
    """Render fixed CLAUDE.md/AGENTS.md content for a cron task folder."""
    return f"""\
# Your Mission

You are an **automated agent**. You run on a schedule with NO human interaction.
Complete your task autonomously and update memory when done.

## Workflow

1. **Read** `{name}_MEMORY.md` first -- it contains context from previous runs.
2. **Read** the whole `TASK_DESCRIPTION.md`!
3. **Follow the assignment** in `TASK_DESCRIPTION.md`!
4. Perform the task conscientiously!
5. **Update** `{name}_MEMORY.md` with the current date/time and what you did.

## Rules

- Stay focused on this task only. Do not deviate.
- Do not modify files outside this task folder.
- Check whether all scripts are already present in the script folder! (IF they are needed!)
- Use `.venv` for Python dependencies: `source .venv/bin/activate`

## Important

You provide the final answer after the task is completed in a pleasant, concise,
and well-formatted manner.
"""


def load_jobs_or_default(jobs_path: Path) -> dict[str, Any]:
    """Load cron jobs JSON or return an empty payload if missing/corrupt."""
    return load_collection_or_default(jobs_path, "jobs")


def load_jobs_strict(jobs_path: Path) -> dict[str, Any]:
    """Load cron jobs JSON and raise on malformed structure."""
    return load_collection_strict(jobs_path, "jobs")


def find_job_by_id_or_task_folder(jobs: list[dict[str, Any]], job_id: str) -> dict[str, Any] | None:
    """Find a job by exact id, then by task_folder."""
    exact = find_by_id(jobs, job_id)
    if exact:
        return exact
    return next((j for j in jobs if j.get("task_folder") == job_id), None)


def available_job_ids(jobs: list[dict[str, Any]]) -> list[str]:
    """Return all job IDs for diagnostics."""
    return available_ids(jobs)


def safe_task_dir(task_folder: str) -> Path:
    """Resolve and validate a cron task folder path under CRON_TASKS_DIR."""
    folder_path = (CRON_TASKS_DIR / task_folder).resolve()
    if not folder_path.is_relative_to(CRON_TASKS_DIR.resolve()):
        msg = f"Path traversal blocked: {task_folder!r} resolves outside cron_tasks"
        raise ValueError(msg)
    return folder_path


def save_jobs(jobs_path: Path, data: dict[str, Any]) -> None:
    """Persist cron jobs JSON with stable formatting."""
    save_collection(jobs_path, data)


def update_task_policy(
    task_dir: Path,
    *,
    delivery_primary: str | None = None,
    delivery_format: str | None = None,
    artifact_mode: str | None = None,
    artifact_path: str | None = None,
    publish_enabled: bool | None = None,
    publish_target: str | None = None,
    publish_mode: str | None = None,
    publish_require_review: bool | None = None,
    create_if_missing: bool = True,
) -> tuple[Path, list[str], bool]:
    """Create or update the task-local cron policy sidecar.

    Returns ``(path, updated_fields, created)``. ``updated_fields`` uses dotted
    field names matching the sidecar structure.
    """
    path = task_policy_path(task_dir)
    if not task_dir.is_dir():
        msg = f"Cron task folder does not exist: {task_dir}"
        raise FileNotFoundError(msg)

    requested_updates = any(
        value is not None
        for value in (
            delivery_primary,
            delivery_format,
            artifact_mode,
            artifact_path,
            publish_enabled,
            publish_target,
            publish_mode,
            publish_require_review,
        )
    )
    created = False
    if path.exists():
        policy = load_task_policy(task_dir)
    else:
        if not create_if_missing and not requested_updates:
            return path, [], False
        policy = default_task_policy()
        created = True

    updated_fields: list[str] = []
    if delivery_primary is not None:
        value = delivery_primary.strip()
        if not value:
            msg = "delivery.primary must not be empty"
            raise ValueError(msg)
        if policy.delivery.primary != value:
            policy.delivery.primary = value
            updated_fields.append("delivery.primary")
    if delivery_format is not None:
        value = delivery_format.strip()
        if not value:
            msg = "delivery.format must not be empty"
            raise ValueError(msg)
        if policy.delivery.format != value:
            policy.delivery.format = value
            updated_fields.append("delivery.format")
    if artifact_mode is not None:
        value = artifact_mode.strip()
        if not value:
            msg = "artifact.mode must not be empty"
            raise ValueError(msg)
        if policy.artifact.mode != value:
            policy.artifact.mode = value
            updated_fields.append("artifact.mode")
    if artifact_path is not None:
        value = artifact_path.strip()
        if not value:
            msg = "artifact.path must not be empty"
            raise ValueError(msg)
        if policy.artifact.path != value:
            policy.artifact.path = value
            updated_fields.append("artifact.path")
    if publish_enabled is not None and policy.publish.enabled != publish_enabled:
        policy.publish.enabled = publish_enabled
        updated_fields.append("publish.enabled")
    if publish_target is not None:
        value = publish_target.strip()
        if not value:
            msg = "publish.target must not be empty"
            raise ValueError(msg)
        if policy.publish.target != value:
            policy.publish.target = value
            updated_fields.append("publish.target")
    if publish_mode is not None:
        value = publish_mode.strip()
        if not value:
            msg = "publish.mode must not be empty"
            raise ValueError(msg)
        if policy.publish.mode != value:
            policy.publish.mode = value
            updated_fields.append("publish.mode")
    if (
        publish_require_review is not None
        and policy.publish.require_review != publish_require_review
    ):
        policy.publish.require_review = publish_require_review
        updated_fields.append("publish.require_review")

    if created or updated_fields:
        path.write_text(
            json.dumps(policy.to_dict(), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    return path, updated_fields, created
