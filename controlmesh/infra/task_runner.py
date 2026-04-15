"""Shared one-shot CLI task execution for cron, webhook, and background observers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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
    from controlmesh.cron.execution import build_cmd, execute_one_shot

    one_shot = build_cmd(exec_config, prompt)
    if one_shot is None:
        return TaskResult(
            status=f"error:cli_not_found_{exec_config.provider}",
            result_text=f"[{exec_config.provider} CLI not found]",
            execution=None,
        )

    execution = await execute_one_shot(
        one_shot,
        cwd=cwd,
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


async def execute_in_task_folder(  # noqa: PLR0913
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

    dep_queue = get_dependency_queue()

    async with dep_queue.acquire(task_id, task_label, dependency):
        folder = cron_tasks_dir / task_folder
        if not await check_folder(folder):
            return TaskResult(
                status="error:folder_missing",
                result_text="",
                execution=None,
            )

        exec_config = observer.resolve_execution_config(overrides)
        enriched = enrich_instruction(instruction, task_folder)

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

        if result.execution is not None:
            observer.log_execution_result(result, task_label, task_id)

        return result
