"""Line-oriented enhanced terminal shell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from rich.console import Console

from controlmesh.config import AgentConfig
from controlmesh.terminal.command_router import TerminalCommandRouter
from controlmesh.terminal.native_pty import NativePTYSession


class EnhancedShell:
    """Interactive ``cm>`` shell backed by the ControlMesh orchestrator."""

    def __init__(
        self,
        *,
        runtime,
        config: AgentConfig,
        prompt_input: Callable[[str], str] | None = None,
        console: Console | None = None,
    ) -> None:
        self.runtime = runtime
        self.config = config
        self.console = console or Console()
        self._prompt_input = prompt_input or input
        self.router = TerminalCommandRouter(runtime, console=self.console)

    async def run(self) -> None:
        """Run the enhanced shell until exit."""
        self.console.print("[bold green]ControlMesh Enhanced Codex[/bold green]")
        self.console.print("[dim]输入 /cm 进入 Codex 原生模式，/exit 退出。[/dim]")
        while True:
            line = await asyncio.to_thread(self._prompt_input, self._prompt())
            text = line.strip()
            if not text:
                continue
            if text in {"/exit", "exit", "quit"}:
                return
            if text == self.config.terminal.native_escape_command:
                await self.enter_native()
                continue
            if text == self.config.terminal.back_command:
                self.console.print("Already in ControlMesh enhanced mode.")
                continue
            if self.router.is_terminal_command(text):
                await self.router.handle(text)
                continue
            await self.handle_enhanced_message(line)

    async def enter_native(self) -> None:
        """Run the native provider session and return to enhanced mode."""
        native = NativePTYSession(
            provider=self.runtime.provider,
            config=self.config,
            back_command=self.config.terminal.back_command,
            prompt_input=self._prompt_input,
            console=self.console,
        )
        await native.run()

    async def handle_enhanced_message(self, text: str) -> None:
        """Send a normal enhanced message to the orchestrator."""
        saw_delta = False

        async def on_delta(delta: str) -> None:
            nonlocal saw_delta
            saw_delta = True
            self.console.print(delta, end="")

        result = await self.runtime.handle_user_message(text, on_text_delta=on_delta)
        if result.text and not saw_delta:
            self.console.print(result.text)
        elif saw_delta:
            self.console.print()

    def _prompt(self) -> str:
        updates = len(self.runtime.inbox.list_unread())
        base = self.config.terminal.prompt
        if updates and self.config.terminal.show_background_notifications:
            return f"cm [{updates} updates]> "
        return base
