"""Native provider session for the local terminal."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

from rich.console import Console

from controlmesh.config import AgentConfig
from controlmesh.terminal.providers import resolve_native_provider_argv
from controlmesh.workspace.paths import resolve_paths


class NativePTYSession:
    """Run a real provider CLI and intercept only the configured back command.

    This first implementation intentionally uses line-mode I/O. It preserves
    the product boundary and gives a portable fallback before raw PTY passthrough.
    """

    def __init__(
        self,
        *,
        provider: str,
        config: AgentConfig,
        back_command: str,
        prompt_input: Callable[[str], str] | None = None,
        console: Console | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.back_command = back_command
        self._prompt_input = prompt_input or input
        self._console = console or Console()

    async def run(self) -> None:
        """Run the native provider until ``/back`` or provider exit."""
        argv = resolve_native_provider_argv(self.provider, self.config)
        paths = resolve_paths(controlmesh_home=self.config.controlmesh_home)
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=paths.workspace,
        )
        reader_task = asyncio.create_task(self._read_output(process), name="terminal-native-read")
        prompt = f"{self.provider}> "
        try:
            while process.returncode is None:
                line = await asyncio.to_thread(self._prompt_input, prompt)
                if line.strip() == self.back_command:
                    process.terminate()
                    break
                if process.stdin is None:
                    break
                process.stdin.write((line + "\n").encode())
                await process.stdin.drain()
        finally:
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader_task

    async def _read_output(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            return
        while True:
            data = await process.stdout.readline()
            if not data:
                return
            self._console.print(data.decode(errors="replace"), end="")
