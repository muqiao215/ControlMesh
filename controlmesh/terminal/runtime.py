"""Runtime wiring for the local enhanced terminal."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from controlmesh.config import AgentConfig
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.session import SessionKey
from controlmesh.terminal.inbox import TerminalInbox
from controlmesh.terminal.memory_context import TerminalMemoryContext
from controlmesh.workspace.paths import resolve_paths

_TextCallback = Callable[[str], Awaitable[None]]


class TerminalRuntime:
    """Owns terminal session state and orchestrator access."""

    def __init__(self, config: AgentConfig, provider: str) -> None:
        self.config = config
        self.provider = provider
        self.paths = resolve_paths(controlmesh_home=config.controlmesh_home)
        self.session_key = SessionKey.terminal(config.terminal.foreground_session_name)
        self.orchestrator: Orchestrator | None = None
        self.supervisor = None
        self.inbox = TerminalInbox(self.paths.runtime_dir / "terminal_inbox.jsonl")
        self.memory = TerminalMemoryContext(self.paths)

    @classmethod
    async def start(cls, config: AgentConfig, provider: str) -> TerminalRuntime:
        """Create and start a terminal runtime."""
        runtime = cls(config=config, provider=provider)
        await runtime.start_main_orchestrator()
        await runtime.start_optional_background_runtime()
        return runtime

    async def start_main_orchestrator(self) -> None:
        """Start the foreground enhanced orchestrator."""
        terminal_config = _config_with_terminal_provider(self.config, self.provider)
        self.orchestrator = await Orchestrator.create(
            terminal_config,
            agent_name=self.config.terminal.foreground_session_name,
        )

    async def start_optional_background_runtime(self) -> None:
        """Start terminal background runtime when enabled.

        The terminal remains usable if background agent startup fails; provider
        chat should not depend on transport credentials or sub-agent readiness.
        """
        if not self.config.terminal.enable_background_agents:
            return
        try:
            from controlmesh.multiagent.supervisor import AgentSupervisor

            supervisor = AgentSupervisor(self.config)
            await supervisor.start_core()
            await supervisor.start_sub_agents(transport_enabled=False)
        except Exception:
            return
        self.supervisor = supervisor
        if self.orchestrator is not None:
            self.orchestrator.supervisor = supervisor
            self.orchestrator.register_multiagent_commands()
            if supervisor.task_hub is not None:
                self.orchestrator.set_task_hub(supervisor.task_hub)

    async def handle_user_message(
        self,
        text: str,
        on_text_delta: _TextCallback,
        on_tool_activity: _TextCallback | None = None,
    ) -> OrchestratorResult:
        """Route an enhanced terminal user message through the orchestrator."""
        if self.orchestrator is None:
            msg = "Terminal orchestrator is not started"
            raise RuntimeError(msg)
        prompt = self.memory.consume_for_prompt(text)
        return await self.orchestrator.handle_message_streaming(
            self.session_key,
            prompt,
            message_id=0,
            on_text_delta=on_text_delta,
            on_tool_activity=on_tool_activity,
        )

    async def handle_control_command(self, command: str) -> OrchestratorResult:
        """Route a ControlMesh command through the orchestrator."""
        if self.orchestrator is None:
            msg = "Terminal orchestrator is not started"
            raise RuntimeError(msg)
        return await self.orchestrator.handle_message(
            self.session_key,
            command,
            message_id=0,
        )

    async def send_agent(self, agent: str, message: str) -> OrchestratorResult:
        """Send a message to a registered sub-agent."""
        supervisor = self.supervisor
        if supervisor is None or supervisor.bus is None:
            return OrchestratorResult(text="No terminal agent bus is running.")
        response = await supervisor.bus.send("terminal", agent, message)
        if not response.success:
            return OrchestratorResult(text=response.error or "Agent request failed.")
        return OrchestratorResult(text=response.text)

    async def stop(self) -> None:
        """Stop runtime-owned resources."""
        if self.orchestrator is not None:
            await self.orchestrator.shutdown()
        if self.supervisor is not None:
            await self.supervisor.stop_all()


def _config_with_terminal_provider(config: AgentConfig, provider: str) -> AgentConfig:
    model = config.terminal.default_model if provider == config.terminal.default_provider else config.model
    data = config.model_dump()
    data["provider"] = provider
    data["model"] = model
    return AgentConfig.model_validate(data)
