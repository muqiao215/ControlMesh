"""Application entry point for ControlMesh Enhanced Terminal."""

from __future__ import annotations

from collections.abc import Sequence

from controlmesh.config import AgentConfig
from controlmesh.terminal.config import parse_mode, parse_provider
from controlmesh.terminal.enhanced_shell import EnhancedShell
from controlmesh.terminal.modes import TerminalMode
from controlmesh.terminal.runtime import TerminalRuntime


class TerminalApp:
    """Top-level terminal application."""

    def __init__(self, config: AgentConfig, provider: str, mode: TerminalMode) -> None:
        self.config = config
        self.provider = provider
        self.mode = mode
        self.runtime: TerminalRuntime | None = None
        self.shell: EnhancedShell | None = None

    @classmethod
    def from_args(cls, *, config: AgentConfig, args: Sequence[str]) -> TerminalApp:
        """Build an app from parsed ControlMesh config and raw CLI args."""
        provider = parse_provider(args, config)
        mode = parse_mode(args, config)
        return cls(config=config, provider=provider, mode=mode)

    async def run(self) -> None:
        """Run the terminal app."""
        self.runtime = await TerminalRuntime.start(self.config, provider=self.provider)
        self.shell = EnhancedShell(runtime=self.runtime, config=self.config)
        try:
            if self.mode is TerminalMode.NATIVE:
                await self.shell.enter_native()
                await self.shell.run()
            else:
                await self.shell.run()
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown terminal resources."""
        if self.runtime is not None:
            await self.runtime.stop()
