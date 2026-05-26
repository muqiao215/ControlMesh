"""Command routing for enhanced terminal mode."""

from __future__ import annotations

from rich.console import Console

from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.terminal.help import TERMINAL_HELP
from controlmesh.terminal.rendering import render_result


class TerminalCommandRouter:
    """Handle terminal-local commands before falling back to Orchestrator."""

    CONTROL_COMMANDS = frozenset(
        {
            "tasks",
            "task",
            "agents",
            "agent",
            "agent_start",
            "agent_stop",
            "agent_restart",
            "memory",
            "cron",
            "inbox",
            "status",
            "model",
            "route",
            "upgrade",
            "diagnose",
            "history",
            "sessions",
        }
    )
    LOCAL_COMMANDS = frozenset({"help", "cm"})

    def __init__(self, runtime, console: Console | None = None) -> None:
        self.runtime = runtime
        self.console = console or Console()

    def is_terminal_command(self, line: str) -> bool:
        """Return whether this line is a terminal/ControlMesh command."""
        text = line.strip()
        if not text:
            return False
        head = _command_head(text)
        if head.startswith("@"):
            return True
        return head in self.CONTROL_COMMANDS or head in self.LOCAL_COMMANDS

    async def handle(self, line: str) -> OrchestratorResult | None:
        """Handle a terminal command and render its result."""
        text = line.strip()
        canonical = _canonical_command(text)
        if canonical == "/help":
            result = OrchestratorResult(text=TERMINAL_HELP)
        elif canonical == "/cm":
            result = OrchestratorResult(
                text="`/cm` has moved to `native` in the terminal. Run `native` to enter provider CLI."
            )
        elif canonical.startswith("/inbox"):
            result = await self._handle_inbox(canonical)
        elif canonical.startswith("/@"):
            result = await self._handle_at_agent(canonical)
        elif canonical.startswith("/memory search "):
            result = await self._handle_memory_search(canonical)
        elif canonical.startswith("/memory inject "):
            result = await self._handle_memory_inject(canonical)
        else:
            result = await self.runtime.handle_control_command(canonical)
        render_result(self.console, result)
        return result

    async def _handle_at_agent(self, text: str) -> OrchestratorResult:
        parts = text[2:].strip().split(None, 1)
        if len(parts) != 2:
            return OrchestratorResult(text="Usage: /@<agent> <message>")
        return await self.runtime.send_agent(parts[0], parts[1])

    async def _handle_inbox(self, text: str) -> OrchestratorResult:
        parts = text.split()
        if len(parts) >= 2 and parts[1] in {"clear", "read", "mark-read"}:
            changed = self.runtime.inbox.mark_all_read()
            return OrchestratorResult(text=f"Marked {changed} inbox item(s) read.")

        items = self.runtime.inbox.list_all(limit=20)
        if not items:
            return OrchestratorResult(text="Inbox is empty.")
        lines = ["## Terminal Inbox", ""]
        for item in items:
            marker = " " if item.read else "*"
            lines.append(f"{marker} {item.id} [{item.kind}] {item.title}")
            if item.body:
                lines.append(item.body)
            lines.append("")
        return OrchestratorResult(text="\n".join(lines).strip())

    async def _handle_memory_search(self, text: str) -> OrchestratorResult:
        query = text.removeprefix("/memory search").strip()
        if not query:
            return OrchestratorResult(text="Usage: /memory search <query>")
        hits = await self.runtime.memory.search(query)
        if not hits:
            return OrchestratorResult(text=f"No results found for: {query}")
        lines = [f"## Search: {query}", ""]
        for hit_id, block in hits:
            lines.append(f"**{hit_id}**")
            lines.append(block)
            lines.append("")
        lines.append("Run `/memory inject <hit-id>` to apply a hit to the next enhanced message.")
        return OrchestratorResult(text="\n".join(lines))

    async def _handle_memory_inject(self, text: str) -> OrchestratorResult:
        hit_id = text.removeprefix("/memory inject").strip()
        if not hit_id:
            return OrchestratorResult(text="Usage: /memory inject <hit-id>")
        try:
            self.runtime.memory.inject(hit_id)
        except KeyError as exc:
            return OrchestratorResult(text=str(exc))
        return OrchestratorResult(text=f"Queued {hit_id} for the next enhanced message.")


def _command_head(text: str) -> str:
    head = text.split(None, 1)[0]
    return head.removeprefix("/")


def _canonical_command(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("/"):
        return stripped
    return f"/{stripped}"
