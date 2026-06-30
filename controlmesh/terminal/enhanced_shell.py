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
        self.console.print("[bold green]ControlMesh[/bold green]")
        self.console.print(f"[dim]{self.runtime.current_model_label()}[/dim]")
        self.console.print("[dim]Ask anything, or run: model, tasks, agents, memory, native, help[/dim]")
        while True:
            try:
                line = await asyncio.to_thread(self._prompt_input, self._prompt())
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                return
            text = line.strip()
            if not text:
                continue
            if text in {"/exit", "exit", "quit"}:
                return
            if text in self._native_commands():
                await self.enter_native()
                continue
            if text == self.config.terminal.back_command:
                self.console.print("Already in ControlMesh enhanced mode.")
                continue
            chat_message = self._chat_message(text)
            if chat_message is not None:
                if chat_message:
                    await self._handle_chat_safely(chat_message)
                else:
                    self.console.print("Usage: chat <message>")
                continue
            if self.router.is_terminal_command(text):
                await self.router.handle(text)
                continue
            await self._handle_chat_safely(line)

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

    @staticmethod
    def _chat_message(text: str) -> str | None:
        if text == "chat" or text.startswith("chat "):
            return text.removeprefix("chat").strip()
        if text == "/chat" or text.startswith("/chat "):
            return text.removeprefix("/chat").strip()
        return None

    async def _handle_chat_safely(self, text: str) -> None:
        try:
            await self.handle_enhanced_message(text)
        except (KeyboardInterrupt, asyncio.CancelledError):
            self.console.print("\nInterrupted.")

    def _native_commands(self) -> set[str]:
        commands = {"/native", "native"}
        configured = self.config.terminal.native_escape_command
        if configured and configured != "/cm":
            commands.add(configured)
        return commands
