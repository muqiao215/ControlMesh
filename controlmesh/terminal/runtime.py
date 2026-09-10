"""Runtime wiring for the local enhanced terminal."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING

from controlmesh.config import AgentConfig
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.provider_binding import normalize_provider_name
from controlmesh.session import SessionKey
from controlmesh.terminal.inbox import TerminalInbox, TerminalInboxItem
from controlmesh.terminal.memory_context import TerminalMemoryContext
from controlmesh.workspace.paths import resolve_paths

if TYPE_CHECKING:
    from controlmesh.tasks.models import TaskResult

_TextCallback = Callable[[str], Awaitable[None]]
logger = logging.getLogger(__name__)


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
            with _suppress_optional_startup_tracebacks():
                await supervisor.start_core()
                await supervisor.start_sub_agents(transport_enabled=False)
        except Exception as exc:
            logger.warning(
                "Optional terminal background runtime did not start: %s: %s",
                type(exc).__name__,
                exc,
            )
            if "supervisor" in locals():
                await supervisor.stop_all()
            return
        self.supervisor = supervisor
        if self.orchestrator is not None:
            self.orchestrator.supervisor = supervisor
            self.orchestrator.register_multiagent_commands()
            if supervisor.task_hub is not None:
                hub = supervisor.task_hub
                self.orchestrator.set_task_hub(hub)
                # The enhanced terminal starts no main transport stack. Wire its
                # own service and inbox explicitly instead of relying on a bot.
                hub.set_cli_service("main", self.orchestrator.cli_service)
                hub.set_agent_paths("main", self.paths)
                hub.set_result_handler("main", self._on_task_result)
                hub.set_question_handler("main", self._on_task_question)
                hub.start_maintenance()

    async def _on_task_result(self, result: TaskResult) -> None:
        self.inbox.append(TerminalInboxItem(
            kind="task_update", title=f"Task {result.task_id}: {result.status}",
            body=result.delivery_text or result.result_text, task_id=result.task_id,
            agent=result.parent_agent,
        ))

    async def _on_task_question(
        self, task_id: str, question: str, prompt_preview: str, chat_id: object, thread_id: object,
    ) -> None:
        self.inbox.append(TerminalInboxItem(
            kind="task_update", title=f"Task {task_id} needs input",
            body=question, task_id=task_id, agent="main",
        ))

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

    def current_model_label(self) -> str:
        """Return the active provider/model label for terminal chrome."""
        orch = self._require_orchestrator()
        try:
            model, provider = orch.resolve_runtime_target(orch._config.model)
        except ValueError:
            provider = normalize_provider_name(orch._config.provider)
            model = orch._config.model
        return f"{provider} / {model}"

    def model_overview(self) -> OrchestratorResult:
        """Return terminal-native model switching guidance."""
        orch = self._require_orchestrator()
        current = self.current_model_label()
        providers = ["codex", "claude", "gemini", "opencode", "claw"]
        lines = [
            "Model",
            f"Current: {current}",
            "",
            "Switch with:",
        ]
        for provider in providers:
            default_model = orch.default_model_for_provider(provider).strip()
            suffix = f" {default_model}" if default_model else " <model>"
            lines.append(f"  model {provider}{suffix}")
        lines.extend(
            [
                "",
                "Examples:",
                "  model codex gpt-5.5",
                "  model claude sonnet",
                "  model gemini gemini-2.5-pro",
                "",
                "Use `native` for the raw provider CLI.",
            ]
        )
        return OrchestratorResult(text="\n".join(lines))

    async def switch_model(self, provider: str, model: str | None = None) -> OrchestratorResult:
        """Switch the terminal model using the shared model-switching path."""
        orch = self._require_orchestrator()
        normalized_provider = normalize_provider_name(provider)
        selected_model = (model or "").strip() or orch.default_model_for_provider(normalized_provider)
        if not selected_model:
            return OrchestratorResult(
                text=(
                    f"No default model is known for `{normalized_provider}`.\n"
                    f"Run `model {normalized_provider} <model>`."
                )
            )

        from controlmesh.orchestrator.selectors.model_selector import switch_model

        try:
            summary = await switch_model(
                orch,
                self.session_key,
                selected_model,
                provider_override=normalized_provider,
            )
        except ValueError as exc:
            return OrchestratorResult(text=f"Could not switch model: {exc}")
        return OrchestratorResult(text=summary)

    async def send_agent(self, agent: str, message: str) -> OrchestratorResult:
        """Send a message to a registered sub-agent."""
        supervisor = self.supervisor
        if supervisor is None or supervisor.bus is None:
            return OrchestratorResult(text="No terminal agent bus is running.")
        response = await supervisor.bus.send("terminal", agent, message)
        if not response.success:
            return OrchestratorResult(text=response.error or "Agent request failed.")
        return OrchestratorResult(text=response.text)

    def _require_orchestrator(self) -> Orchestrator:
        if self.orchestrator is None:
            msg = "Terminal orchestrator is not started"
            raise RuntimeError(msg)
        return self.orchestrator

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


@contextmanager
def _suppress_optional_startup_tracebacks():
    noisy_loggers = [
        logging.getLogger("controlmesh.multiagent.internal_api"),
        logging.getLogger("controlmesh.multiagent.supervisor"),
    ]
    old_disabled = [log.disabled for log in noisy_loggers]
    try:
        for log in noisy_loggers:
            log.disabled = True
        yield
    finally:
        for log, disabled in zip(noisy_loggers, old_disabled, strict=True):
            log.disabled = disabled
