"""Base class for task-executing observers (cron, webhook)."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from controlmesh.cli.param_resolver import TaskOverrides, resolve_cli_config
from controlmesh.bus.envelope import ExecutionContext

if TYPE_CHECKING:
    from controlmesh.cli.codex_cache import CodexModelCache
    from controlmesh.cli.param_resolver import TaskExecutionConfig
    from controlmesh.config import AgentConfig
    from controlmesh.infra.task_runner import TaskResult
    from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


class BaseTaskObserver:
    """Shared base for observers that execute one-shot CLI tasks.

    Provides:
    - Config and cache storage
    - ``resolve_execution_config()`` for building CLI execution configs
    - ``log_execution_result()`` for shared post-execution logging
    """

    def __init__(
        self,
        paths: ControlMeshPaths,
        config: AgentConfig,
        codex_cache: CodexModelCache,
    ) -> None:
        self._paths = paths
        self._config = config
        self._codex_cache = codex_cache
        self._docker_container = ""
        self._sandbox_state_known = False

    def set_docker_container(self, container: str) -> None:
        """Update the confirmed sandbox container used by one-shot executions."""
        self._docker_container = container
        self._sandbox_state_known = True

    def execution_context_for_run(self, context: ExecutionContext) -> ExecutionContext:
        """Return source provenance once startup has confirmed sandbox state.

        Direct observer unit calls made without lifecycle startup retain the
        historical host-compatible behavior. Production startup always calls
        ``set_docker_container`` (including with an empty value after failed
        Docker setup), so unattended runs still fail closed.
        """
        return context if self._sandbox_state_known else ExecutionContext.legacy()

    def resolve_execution_config(
        self,
        task_overrides: TaskOverrides,
    ) -> TaskExecutionConfig:
        """Build a CLI execution config from current settings and overrides."""
        return resolve_cli_config(
            self._config,
            self._codex_cache,
            task_overrides=task_overrides,
        )

    def execution_config_for(
        self,
        task_overrides: TaskOverrides,
        *,
        execution_context: ExecutionContext | None = None,
    ) -> TaskExecutionConfig:
        """Resolve one-shot config with current sandbox and provenance state."""
        return replace(
            self.resolve_execution_config(task_overrides),
            docker_container=self._docker_container,
            execution_context=execution_context,
        )

    def log_execution_result(
        self,
        result: TaskResult,
        label: str,
        job_id: str,
    ) -> None:
        """Log common post-execution details (timeout, stderr)."""
        if result.execution is None:
            return
        if result.execution.timed_out:
            logger.warning(
                "%s %s timed out after %.0fs",
                label,
                job_id,
                self._config.cli_timeout,
            )
        if result.execution.stderr:
            stderr_preview = result.execution.stderr.decode(errors="replace")[:500]
            logger.debug("%s stderr (%s): %s", label, job_id, stderr_preview)
