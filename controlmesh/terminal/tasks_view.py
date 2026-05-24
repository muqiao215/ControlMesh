"""Terminal rendering helpers for task commands."""

from __future__ import annotations

from controlmesh.orchestrator.registry import OrchestratorResult


class TerminalTasksView:
    """Thin terminal facade over the existing orchestrator task command."""

    def __init__(self, runtime: object) -> None:
        self._runtime = runtime

    async def handle(self, command: str) -> OrchestratorResult:
        """Delegate task commands to the enhanced runtime."""
        return await self._runtime.handle_control_command(command)
