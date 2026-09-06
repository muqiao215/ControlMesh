"""Shared one-shot CLI task execution for cron, webhook, and background observers."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh.bus.envelope import ExecutionContext

if TYPE_CHECKING:
    from controlmesh.cli.param_resolver import TaskExecutionConfig, TaskOverrides
    from controlmesh.cron.execution import OneShotExecutionResult
    from controlmesh.infra.base_task_observer import BaseTaskObserver

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """Normalized outcome of a one-shot task run."""

    status: str
    result_text: str
    execution: OneShotExecutionResult | None
    artifact_path: Path | None = None


async def run_oneshot_task(
    exec_config: TaskExecutionConfig,
    prompt: str,
    *,
    cwd: Path,
    timeout_seconds: float,
    timeout_label: str,
) -> TaskResult:
    """Build the CLI command and execute it, returning a normalized result.

    Returns a ``cli_not_found`` result instead of raising when the provider
    binary is missing.  All other execution details (timeout, stderr, status
    mapping) are delegated to ``execute_one_shot``.
    """
    from controlmesh.cli.base import CLIConfig, docker_wrap
    from controlmesh.cron.execution import build_cmd, execute_one_shot
    from controlmesh.execution_policy import enforce_execution_policy

    context = exec_config.execution_context or ExecutionContext.legacy()
    enforce_execution_policy(
        context,
        sandbox_available=bool(exec_config.docker_container),
    )
    if exec_config.tool_grant is not None and exec_config.tool_grant.restrictive:
        from controlmesh.execution_grants import map_tool_grant

        mapping = map_tool_grant(
            exec_config.provider,
            exec_config.tool_grant,
            config_permission_mode=exec_config.permission_mode,
            config_cli_parameters=tuple(exec_config.cli_parameters),
        )
    else:
        mapping = None
    one_shot = build_cmd(exec_config, prompt)
    if one_shot is None:
        return TaskResult(
            status=f"error:cli_not_found_{exec_config.provider}",
            result_text=f"[{exec_config.provider} CLI not found]",
            execution=None,
        )
    if mapping is not None and mapping.flags:
        one_shot = replace(
            one_shot,
            cmd=[one_shot.cmd[0], *mapping.flags, *one_shot.cmd[1:]],
        )

    wrapped_cmd, host_cwd = docker_wrap(
        one_shot.cmd,
        CLIConfig(
            provider=exec_config.provider,
            model=exec_config.model,
            working_dir=str(cwd),
            docker_container=exec_config.docker_container,
        ),
        extra_env=one_shot.env_overrides,
        interactive=one_shot.stdin_input is not None,
    )
    wrapped = replace(one_shot, cmd=wrapped_cmd, env_overrides={}) if host_cwd is None else one_shot
    execution = await execute_one_shot(
        wrapped,
        cwd=Path(host_cwd) if host_cwd is not None else None,
        provider=exec_config.provider,
        timeout_seconds=timeout_seconds,
        timeout_label=timeout_label,
    )

    return TaskResult(
        status=execution.status,
        result_text=execution.result_text,
        execution=execution,
    )


async def check_folder(folder: Path) -> bool:
    """Return True if *folder* exists as a directory (runs in a thread)."""
    return await asyncio.to_thread(folder.is_dir)


async def execute_in_task_folder(
    observer: BaseTaskObserver,
    *,
    cron_tasks_dir: Path,
    task_folder: str,
    instruction: str,
    overrides: TaskOverrides,
    dependency: str | None,
    task_id: str,
    task_label: str,
    timeout_seconds: float,
    execution_context: ExecutionContext | None = None,
) -> TaskResult:
    """Execute a one-shot CLI task inside a ``cron_tasks`` subfolder.

    Shared core for :class:`CronObserver` and :class:`WebhookObserver`.
    Handles dependency locking, folder validation, config resolution,
    instruction enrichment, subprocess execution, and result logging.

    Caller-specific concerns (result delivery, status persistence,
    quiet-hour checks) remain with the caller.
    """
    from controlmesh.cron.dependency_queue import get_dependency_queue
    from controlmesh.cron.execution import enrich_instruction
    from controlmesh.cron.policy import load_task_policy

    dep_queue = get_dependency_queue()

    async with dep_queue.acquire(task_id, task_label, dependency):
        folder = cron_tasks_dir / task_folder
        if not await check_folder(folder):
            return TaskResult(
                status="error:folder_missing",
                result_text="",
                execution=None,
            )

        exec_config = observer.execution_config_for(
            overrides,
            execution_context=execution_context,
        )
        policy = load_task_policy(folder)
        enriched = enrich_instruction(instruction, task_folder, policy=policy)

        logger.debug(
            "%s cwd=%s provider=%s model=%s timeout=%.0fs",
            task_label,
            folder,
            exec_config.provider,
            exec_config.model,
            timeout_seconds,
        )

        result = await run_oneshot_task(
            exec_config,
            enriched,
            cwd=folder,
            timeout_seconds=timeout_seconds,
            timeout_label=task_label,
        )

        artifact_path = await _persist_local_artifact(
            folder=folder,
            status=result.status,
            result_text=result.result_text,
            provider=exec_config.provider,
            model=exec_config.model,
        )
        result = TaskResult(
            status=result.status,
            result_text=result.result_text,
            execution=result.execution,
            artifact_path=artifact_path,
        )

        if result.execution is not None:
            observer.log_execution_result(result, task_label, task_id)

        return result


async def _persist_local_artifact(
    *,
    folder: Path,
    status: str,
    result_text: str,
    provider: str,
    model: str,
) -> Path:
    """Write a runtime-owned artifact for cron/webhook runs.

    This avoids relying on the model to create local files successfully.
    """
    output_dir = folder / "output"
    artifact_path = output_dir / "last_run.json"

    payload = {
        "status": status,
        "result_text": result_text,
        "provider": provider,
        "model": model,
        "written_at": datetime.now(UTC).isoformat(),
    }

    def _write() -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return artifact_path

    return await asyncio.to_thread(_write)
