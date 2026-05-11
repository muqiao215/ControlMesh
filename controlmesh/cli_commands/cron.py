"""Host-side cron maintenance CLI commands."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from controlmesh.cli.codex_cache import CodexModelCache
from controlmesh.cli.gemini_cache import GeminiModelCache
from controlmesh.config import AgentConfig
from controlmesh.cron.manager import CronJob, CronManager
from controlmesh.cron.observer import CronObserver
from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths

_console = Console()
_HELP_FLAGS = {"--help", "-h"}
_SCRIPT_REF_RE = re.compile(r"(?<!\w)(scripts/[^\s)`\"']+)")

_CRON_USAGE = """Usage:
  controlmesh cron list [--json]
  controlmesh cron get <job-id> [--json]
  controlmesh cron run <job-id> [--dry-run] [--json] [--no-notify]
  controlmesh cron validate <job-id>

Commands:
  list      Show configured cron jobs.
  get       Show one cron job.
  run       Trigger one cron job immediately from the host shell.
  validate  Validate one cron job's task folder and referenced scripts.
"""


@dataclass(frozen=True, slots=True)
class CronValidationResult:
    job_id: str
    ok: bool
    errors: list[str]


def load_config() -> AgentConfig:
    """Import lazily to avoid a cycle with ``controlmesh.__main__``."""
    from controlmesh.__main__ import load_config as _load_config

    return _load_config()


def cmd_cron(args: Sequence[str]) -> None:
    """Handle `controlmesh cron ...` commands."""
    action_args = _parse_cron_command(args)
    if not action_args or action_args[0] in _HELP_FLAGS:
        _console.print(_CRON_USAGE)
        return

    action = action_args[0]
    if action == "list":
        _cmd_cron_list(action_args[1:])
        return
    if action == "get":
        _cmd_cron_get(action_args[1:])
        return
    if action == "run":
        _cmd_cron_run(action_args[1:])
        return
    if action == "validate":
        _cmd_cron_validate(action_args[1:])
        return
    raise SystemExit(1)


def _parse_cron_command(args: Sequence[str]) -> list[str]:
    if not args:
        return []
    if args[0] == "cron":
        return list(args[1:])
    if len(args) > 1 and args[1] == "cron":
        return list(args[2:])
    return list(args)


def _cron_context() -> tuple[AgentConfig, ControlMeshPaths, object, CronManager]:
    config = load_config()
    paths = resolve_paths(controlmesh_home=config.controlmesh_home)
    codex_cache = asyncio.run(
        CodexModelCache.load_or_refresh(
            paths.controlmesh_home / "codex_models.json",
            force_refresh=False,
        ),
    )
    asyncio.run(
        GeminiModelCache.load_or_refresh(
            paths.controlmesh_home / "gemini_models.json",
            force_refresh=False,
        ),
    )
    manager = CronManager(jobs_path=paths.cron_jobs_path)
    return config, paths, codex_cache, manager


def _job_to_payload(job: CronJob) -> dict[str, object]:
    return {
        "id": job.id,
        "enabled": job.enabled,
        "schedule": job.schedule,
        "provider": job.provider,
        "model": job.model,
        "reasoning_effort": job.reasoning_effort,
        "task_folder": job.task_folder,
        "last_run_at": job.last_run_at,
        "last_run_status": job.last_run_status,
        "manual_run_at": job.manual_run_at,
        "manual_run_status": job.manual_run_status,
        "execution_mode": job.execution_mode,
    }


def _cmd_cron_list(args: Sequence[str]) -> None:
    json_mode = "--json" in args
    _config, _paths, _codex_cache, manager = _cron_context()
    jobs = manager.list_jobs()
    if json_mode:
        _console.print_json(json.dumps([_job_to_payload(job) for job in jobs], ensure_ascii=False))
        return
    if not jobs:
        _console.print("No cron jobs configured.")
        return
    for job in jobs:
        _console.print(
            f"{job.id} enabled={str(job.enabled).lower()} schedule={job.schedule} "
            f"provider={job.provider or '-'} model={job.model or '-'}"
        )


def _cmd_cron_get(args: Sequence[str]) -> None:
    json_mode = "--json" in args
    positional = [arg for arg in args if not arg.startswith("-")]
    if not positional:
        raise SystemExit(1)
    job_id = positional[0]
    _config, _paths, _codex_cache, manager = _cron_context()
    job = manager.get_job(job_id)
    if job is None:
        _console.print(f"Cron job `{job_id}` not found.")
        raise SystemExit(1)
    payload = _job_to_payload(job)
    if json_mode:
        _console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    _console.print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_cron_run(args: Sequence[str]) -> None:
    json_mode = "--json" in args
    dry_run = "--dry-run" in args
    no_notify = "--no-notify" in args
    positional = [arg for arg in args if not arg.startswith("-")]
    if not positional:
        raise SystemExit(1)
    job_id = positional[0]
    config, paths, codex_cache, manager = _cron_context()
    job = manager.get_job(job_id)
    if job is None:
        _emit_run_error(job_id, "error:not_found", "Cron job not found.", json_mode, dry_run)
    if job is not None and not job.enabled:
        _emit_run_error(job_id, "error:disabled", "Cron job is disabled.", json_mode, dry_run)

    validation = _validate_job(paths.cron_tasks_dir, job) if job is not None else None
    if validation is not None and not validation.ok:
        _emit_run_error(job_id, "error:validation_failed", "; ".join(validation.errors), json_mode, dry_run)

    result = asyncio.run(_run_job(paths, manager, config, codex_cache, job_id, dry_run=dry_run, no_notify=no_notify))
    exit_code = 0 if result["ok"] else 1
    if json_mode:
        _console.print_json(json.dumps(result, ensure_ascii=False))
    else:
        _console.print(str(result["result_summary"]))
    raise SystemExit(exit_code)


def _cmd_cron_validate(args: Sequence[str]) -> None:
    positional = [arg for arg in args if not arg.startswith("-")]
    if not positional:
        raise SystemExit(1)
    job_id = positional[0]
    _config, paths, _codex_cache, manager = _cron_context()
    job = manager.get_job(job_id)
    if job is None:
        _console.print(f"Cron job `{job_id}` not found.")
        raise SystemExit(1)
    result = _validate_job(paths.cron_tasks_dir, job)
    if result.ok:
        _console.print(f"Cron job `{job_id}` validation passed.")
        return
    for error in result.errors:
        _console.print(error)
    raise SystemExit(1)


def _emit_run_error(
    job_id: str,
    status: str,
    summary: str,
    json_mode: bool,
    dry_run: bool,
) -> None:
    payload = {
        "job_id": job_id,
        "status": status,
        "started_at": None,
        "finished_at": None,
        "manual": True,
        "dry_run": dry_run,
        "result_summary": summary,
        "ok": False,
    }
    if json_mode:
        _console.print_json(json.dumps(payload, ensure_ascii=False))
    else:
        _console.print(summary)
    raise SystemExit(1)


async def _run_job(
    paths: ControlMeshPaths,
    manager: CronManager,
    config: AgentConfig,
    codex_cache: object,
    job_id: str,
    *,
    dry_run: bool,
    no_notify: bool,
) -> dict[str, object]:
    observer = CronObserver(paths, manager, config=config, codex_cache=codex_cache)
    observer.set_result_handler(_noop_result_handler)
    del no_notify
    started_at = datetime.now(UTC).isoformat()
    status, text = await observer.run_job_now(job_id, dry_run=dry_run)
    finished_at = datetime.now(UTC).isoformat()
    ok = status in {"dry_run", "success"}
    return {
        "job_id": job_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "manual": True,
        "dry_run": dry_run,
        "result_summary": text,
        "ok": ok,
    }


async def _noop_result_handler(
    _job_title: str,
    _result_text: str,
    _status: str,
    _chat_id: int,
    _topic_id: int | None,
    _transport: str,
) -> None:
    return


def _validate_job(cron_tasks_dir: Path, job: CronJob) -> CronValidationResult:
    errors: list[str] = []
    folder = cron_tasks_dir / job.task_folder
    if not folder.is_dir():
        errors.append(f"Missing task folder: {folder}")
    task_description = folder / "TASK_DESCRIPTION.md"
    if not task_description.is_file():
        errors.append(f"Missing TASK_DESCRIPTION.md: {task_description}")
    if task_description.is_file():
        text = task_description.read_text(encoding="utf-8")
        for ref in sorted(set(_SCRIPT_REF_RE.findall(text))):
            script_path = folder / ref
            if not script_path.is_file():
                errors.append(f"Missing referenced script: {script_path}")
    return CronValidationResult(job_id=job.id, ok=not errors, errors=errors)
