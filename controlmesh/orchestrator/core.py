"""Core orchestrator: routes messages through command and conversation flows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from controlmesh.background import (
    BackgroundSubmit,
    BackgroundTask,
)
from controlmesh.bus.envelope import Envelope, Origin
from controlmesh.cli.process_registry import ProcessRegistry
from controlmesh.cli.service import CLIService, CLIServiceConfig
from controlmesh.cli.stream_events import ToolResultEvent, ToolUseEvent
from controlmesh.config import AgentConfig
from controlmesh.cron.manager import CronManager
from controlmesh.errors import (
    CLIError,
    CronError,
    SessionError,
    StreamError,
    WebhookError,
    WorkspaceError,
)
from controlmesh.files.tags import (
    FILE_PATH_RE,
    classify_mime,
    extract_file_paths,
    guess_mime,
    path_from_file_tag,
)
from controlmesh.history import TranscriptAttachment, TranscriptStore, TranscriptTurn
from controlmesh.history.index import HistoryIndex
from controlmesh.infra.docker import DockerManager
from controlmesh.infra.inflight import InflightTracker
from controlmesh.orchestrator.commands import (
    cmd_back,
    cmd_controlmesh,
    cmd_cron,
    cmd_diagnose,
    cmd_history,
    cmd_memory,
    cmd_model,
    cmd_reset,
    cmd_sessions,
    cmd_settings,
    cmd_status,
    cmd_tasks,
    cmd_upgrade,
)
from controlmesh.orchestrator.directives import ParsedDirectives, parse_directives
from controlmesh.orchestrator.flows import (
    StreamingCallbacks,
    heartbeat_flow,
    named_session_flow,
    named_session_streaming,
    normal,
    normal_streaming,
    provider_native_command,
    provider_native_command_streaming,
)
from controlmesh.orchestrator.hooks import (
    DELEGATION_BRIEF,
    DELEGATION_REMINDER,
    MAINMEMORY_REMINDER,
    MessageHookRegistry,
)
from controlmesh.orchestrator.observers import ObserverManager
from controlmesh.orchestrator.providers import ProviderManager
from controlmesh.orchestrator.registry import CommandRegistry, OrchestratorResult
from controlmesh.orchestrator.selectors.agent_router import RouteDecisionKind, decide_backend_route
from controlmesh.security import detect_suspicious_patterns
from controlmesh.session import SessionKey, SessionManager
from controlmesh.session.manager import SessionData
from controlmesh.session.named import NamedSessionRegistry
from controlmesh.webhook.manager import WebhookManager
from controlmesh.workspace.paths import ControlMeshPaths

if TYPE_CHECKING:
    from controlmesh.background import BackgroundObserver
    from controlmesh.bus.bus import MessageBus
    from controlmesh.config import ModelRegistry
    from controlmesh.multiagent.bus import AsyncInterAgentResult
    from controlmesh.multiagent.supervisor import AgentSupervisor
    from controlmesh.session.named import NamedSession
    from controlmesh.tasks.hub import TaskHub

logger = logging.getLogger(__name__)

_NATIVE_COMMAND_MODE_PROVIDERS = frozenset({"claude", "codex", "gemini", "claw", "opencode"})


_TextCallback = Callable[[str], Awaitable[None]]
_SystemStatusCallback = Callable[[str | None], Awaitable[None]]
_ToolEventCallback = Callable[[ToolUseEvent | ToolResultEvent], Awaitable[None]]


@dataclass(slots=True)
class NamedSessionRequest:
    """Parameters for submitting a named background session."""

    message_id: int
    thread_id: int | None
    provider_override: str | None = None
    model_override: str | None = None


@dataclass(slots=True)
class _MessageDispatch:
    """Normalized input for one orchestrator message routing pass."""

    key: SessionKey
    text: str
    cmd: str
    streaming: bool = False
    on_text_delta: _TextCallback | None = None
    on_tool_activity: _TextCallback | None = None
    on_tool_event: _ToolEventCallback | None = None
    on_system_status: _SystemStatusCallback | None = None

    def streaming_callbacks(self) -> StreamingCallbacks:
        """Bundle the streaming callbacks into a StreamingCallbacks instance."""
        return StreamingCallbacks(
            on_text_delta=self.on_text_delta,
            on_tool_activity=self.on_tool_activity,
            on_tool_event=self.on_tool_event,
            on_system_status=self.on_system_status,
        )


class Orchestrator:
    """Routes messages through command dispatch and conversation flows."""

    def __init__(
        self,
        config: AgentConfig,
        paths: ControlMeshPaths,
        *,
        docker_container: str = "",
        agent_name: str = "main",
        interagent_port: int = 8799,
    ) -> None:
        self._config = config
        self._paths: ControlMeshPaths = paths
        self._docker: DockerManager | None = None
        self._providers = ProviderManager(config)
        self._sessions = SessionManager(paths.sessions_path, config)
        self._named_sessions = NamedSessionRegistry(paths.named_sessions_path)
        self._transcripts = TranscriptStore(paths)
        self._history_index = HistoryIndex(paths)
        self._process_registry = ProcessRegistry()
        self._cli_service = CLIService(
            config=CLIServiceConfig(
                working_dir=str(paths.workspace),
                default_model=config.model,
                provider=config.provider,
                max_turns=config.max_turns,
                max_budget_usd=config.max_budget_usd,
                permission_mode=config.permission_mode,
                reasoning_effort=config.reasoning_effort,
                gemini_api_key=config.gemini_api_key,
                docker_container=docker_container,
                claude_cli_parameters=tuple(config.cli_parameters.claude),
                codex_cli_parameters=tuple(config.cli_parameters.codex),
                gemini_cli_parameters=tuple(config.cli_parameters.gemini),
                agent_name=agent_name,
                interagent_port=interagent_port,
            ),
            models=self._providers.models,
            available_providers=frozenset(),
            process_registry=self._process_registry,
        )
        self._cron_manager = CronManager(jobs_path=paths.cron_jobs_path)
        self._webhook_manager = WebhookManager(hooks_path=paths.webhooks_path)
        self._observers = ObserverManager(config, paths)

        async def _heartbeat_handler(
            chat_id: int,
            topic_id: int | None = None,
            prompt: str | None = None,
            ack_token: str | None = None,
        ) -> str | None:
            return await self.handle_heartbeat(
                SessionKey(chat_id=chat_id, topic_id=topic_id),
                prompt=prompt,
                ack_token=ack_token,
            )

        self._observers.heartbeat.set_heartbeat_handler(_heartbeat_handler)
        self._observers.heartbeat.set_busy_check(self._process_registry.has_active)
        stale_max = config.cli_timeout * 2
        self._observers.heartbeat.set_stale_cleanup(
            lambda: self._process_registry.kill_stale(stale_max)
        )
        self._api_stop: Callable[[], Awaitable[None]] | None = None
        self._inflight_tracker = InflightTracker(paths.inflight_turns_path)
        self._hook_registry = MessageHookRegistry()
        self._hook_registry.register(MAINMEMORY_REMINDER)
        self._hook_registry.register(DELEGATION_BRIEF)
        self._hook_registry.register(DELEGATION_REMINDER)
        self._supervisor: AgentSupervisor | None = None  # Set by AgentSupervisor after creation
        self._task_hub: TaskHub | None = None  # Set by supervisor or __main__.py
        self._command_registry = CommandRegistry()
        self._register_commands()

    @property
    def paths(self) -> ControlMeshPaths:
        """Public access to resolved workspace paths."""
        return self._paths

    @property
    def task_hub(self) -> TaskHub | None:
        """Public access to the task hub (None when tasks are disabled)."""
        return self._task_hub

    @property
    def config(self) -> AgentConfig:
        """Public access to the agent config."""
        return self._config

    @property
    def inflight_tracker(self) -> InflightTracker:
        """Public access to the inflight turn tracker."""
        return self._inflight_tracker

    @property
    def named_sessions(self) -> NamedSessionRegistry:
        """Public access to the named session registry."""
        return self._named_sessions

    @property
    def history_index(self) -> HistoryIndex:
        """Public access to the derived history index."""
        return self._history_index

    @property
    def available_providers(self) -> frozenset[str]:
        """Public access to the set of authenticated providers."""
        return self._providers.available_providers

    @property
    def cli_service(self) -> CLIService:
        """Public access to the CLI service."""
        return self._cli_service

    @property
    def process_registry(self) -> ProcessRegistry:
        """Public access to the process registry."""
        return self._process_registry

    @property
    def bg_observer(self) -> BackgroundObserver | None:
        """Public access to the background observer."""
        return self._observers.background

    @property
    def supervisor(self) -> AgentSupervisor | None:
        """Public access to the agent supervisor."""
        return self._supervisor

    @supervisor.setter
    def supervisor(self, value: AgentSupervisor | None) -> None:
        self._supervisor = value
        self._cli_service.update_runtime_dependencies(
            task_hub=self._task_hub,
            interagent_bus=value.bus if value is not None else None,
        )

    def set_task_hub(self, hub: TaskHub) -> None:
        """Inject the task hub (called by supervisor or startup wiring)."""
        self._task_hub = hub
        self._cli_service.update_runtime_dependencies(
            task_hub=hub,
            interagent_bus=self._supervisor.bus if self._supervisor is not None else None,
        )
        hub.start_maintenance()

    @classmethod
    async def create(
        cls,
        config: AgentConfig,
        *,
        agent_name: str = "main",
    ) -> Orchestrator:
        """Async factory: build Orchestrator.

        Workspace must already be initialized by the caller (``__main__.load_config``).
        """
        from controlmesh.orchestrator.lifecycle import create_orchestrator

        return await create_orchestrator(config, agent_name=agent_name)

    @property
    def models(self) -> ModelRegistry:
        """Public access to the model registry (delegates to ProviderManager)."""
        return self._providers.models

    @property
    def gemini_api_key_mode(self) -> bool:
        """Return cached Gemini API-key mode status."""
        return self._providers.gemini_api_key_mode

    @property
    def active_provider_name(self) -> str:
        """Human-readable name for the active CLI provider."""
        return self._providers.active_provider_name

    async def handle_message(self, key: SessionKey, text: str) -> OrchestratorResult:
        """Main entry point: route message to appropriate handler."""
        dispatch = _MessageDispatch(key=key, text=text, cmd=text.strip().lower())
        return await self._handle_message_impl(dispatch)

    async def handle_message_streaming(
        self,
        key: SessionKey,
        text: str,
        *,
        on_text_delta: _TextCallback | None = None,
        on_tool_activity: _TextCallback | None = None,
        on_tool_event: _ToolEventCallback | None = None,
        on_system_status: _SystemStatusCallback | None = None,
    ) -> OrchestratorResult:
        """Main entry point with streaming support."""
        dispatch = _MessageDispatch(
            key=key,
            text=text,
            cmd=text.strip().lower(),
            streaming=True,
            on_text_delta=on_text_delta,
            on_tool_activity=on_tool_activity,
            on_tool_event=on_tool_event,
            on_system_status=on_system_status,
        )
        return await self._handle_message_impl(dispatch)

    async def _handle_message_impl(self, dispatch: _MessageDispatch) -> OrchestratorResult:
        self._process_registry.clear_abort(dispatch.key.chat_id)
        logger.info("Message received text=%s", dispatch.cmd[:80])

        should_record_history = not Orchestrator._is_history_read_command(dispatch.cmd)
        if should_record_history:
            await self._record_frontstage_user_turn(dispatch.key, dispatch.text)

        patterns = detect_suspicious_patterns(dispatch.text)
        if patterns:
            logger.warning("Suspicious input patterns: %s", ", ".join(patterns))

        try:
            result = await self._route_message(dispatch)
        except asyncio.CancelledError:
            raise
        except (CLIError, StreamError, SessionError, CronError, WebhookError, WorkspaceError):
            logger.exception("Domain error in handle_message")
            result = OrchestratorResult(text="An internal error occurred. Please try again.")
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            logger.exception("Unexpected error in handle_message")
            result = OrchestratorResult(text="An internal error occurred. Please try again.")

        if should_record_history:
            await self._record_frontstage_assistant_turn(dispatch.key, result)
        return result

    @staticmethod
    def _is_history_read_command(cmd: str) -> bool:
        """Return True when *cmd* is the transcript read surface."""
        normalized = cmd.strip().lower()
        if not normalized:
            return False
        head, *tail = normalized.split(None, 1)
        head = head.split("@", 1)[0]
        rebuilt = head if not tail else f"{head} {tail[0]}"
        return rebuilt in {"/history", "/cm /history"} or rebuilt.startswith(
            ("/history ", "/cm /history ")
        )

    async def _record_frontstage_user_turn(self, key: SessionKey, text: str) -> None:
        """Persist the user's visible frontstage turn."""
        if not text.strip():
            return
        turn = TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="user",
            visible_content=text,
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
        await asyncio.to_thread(self._transcripts.append_turn, turn)

    async def _record_frontstage_assistant_turn(
        self, key: SessionKey, result: OrchestratorResult
    ) -> None:
        """Persist the final visible frontstage result turn."""
        content, attachments = self._normalize_transcript_content(result.text)
        if not content and not attachments:
            return
        turn = TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content=content,
            attachments=attachments,
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
        await asyncio.to_thread(self._transcripts.append_turn, turn)

    async def record_frontstage_delivery(self, envelope: Envelope) -> None:
        """Persist visible non-command deliveries that belong in frontstage history."""
        source = self._frontstage_delivery_source(envelope.origin)
        if source is None:
            return

        visible_text = envelope.delivery_text or envelope.result_text
        content, attachments = self._normalize_transcript_content(visible_text)
        if not content and not attachments:
            return

        key = SessionKey(
            transport=envelope.transport,
            chat_id=envelope.chat_id,
            topic_id=envelope.topic_id,
        )
        turn = TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content=content,
            attachments=attachments,
            source=source,
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
        await asyncio.to_thread(self._transcripts.append_turn, turn)

    async def read_frontstage_history(
        self,
        key: SessionKey,
        *,
        limit: int = 20,
    ) -> list[TranscriptTurn]:
        """Read recent visible transcript turns for a frontstage session."""
        return await asyncio.to_thread(self._transcripts.read_recent, key, limit=limit)

    async def _route_message(self, dispatch: _MessageDispatch) -> OrchestratorResult:
        result = await self._command_registry.dispatch(
            dispatch.cmd,
            self,
            dispatch.key,
            dispatch.text,
        )
        if result is not None:
            return result

        native_target = await self._native_mode_target(dispatch)
        if native_target is not None:
            provider, model = native_target
            return await self._route_provider_native_message(dispatch, provider=provider, model=model)

        fallback_target = await self._unknown_slash_native_target(dispatch)
        if fallback_target is not None:
            provider, model = fallback_target
            return await self._route_provider_native_message(dispatch, provider=provider, model=model)

        return await self._route_non_command_message(dispatch)

    async def _route_non_command_message(
        self,
        dispatch: _MessageDispatch,
    ) -> OrchestratorResult:
        """Route a message that was not claimed by ControlMesh commands."""
        await self._ensure_docker()

        directives = parse_directives(dispatch.text, self._providers._known_model_ids)

        # Check if a leading @directive matches a named session
        if directives.raw_directives:
            first_key = next(iter(directives.raw_directives))
            ns = self._named_sessions.get(dispatch.key.chat_id, first_key)
            if ns is not None:
                session_prompt = directives.cleaned or dispatch.text
                if dispatch.streaming:
                    return await named_session_streaming(
                        self,
                        dispatch.key,
                        first_key,
                        session_prompt,
                        cbs=dispatch.streaming_callbacks(),
                    )
                return await named_session_flow(self, dispatch.key, first_key, session_prompt)

        if directives.is_directive_only and directives.has_model:
            return OrchestratorResult(
                text=f"Next message will use: {directives.model}\n"
                f"(Send a message with @{directives.model} <text> to use it.)",
            )

        prompt_text = directives.cleaned or dispatch.text
        routed = await self._route_with_backend_decision(dispatch, prompt_text, directives)
        if routed is not None:
            return routed

        if dispatch.streaming:
            return await normal_streaming(
                self,
                dispatch.key,
                prompt_text,
                model_override=directives.model,
                cbs=dispatch.streaming_callbacks(),
            )

        return await normal(
            self,
            dispatch.key,
            prompt_text,
            model_override=directives.model,
        )

    async def _route_with_backend_decision(
        self,
        dispatch: _MessageDispatch,
        prompt_text: str,
        directives: ParsedDirectives,
    ) -> OrchestratorResult | None:
        """Apply router-only backend decisions before legacy normal-flow dispatch."""
        route = decide_backend_route(self._config, directives)

        if route.kind is RouteDecisionKind.LEGACY_CLI:
            return None

        if route.kind is RouteDecisionKind.OPENAI_AGENTS:
            if dispatch.streaming:
                return await normal_streaming(
                    self,
                    dispatch.key,
                    prompt_text,
                    model_override=route.model_override,
                    provider_override=route.provider_override,
                    cbs=dispatch.streaming_callbacks(),
                )

            return await normal(
                self,
                dispatch.key,
                prompt_text,
                model_override=route.model_override,
                provider_override=route.provider_override,
            )

        if route.kind in {RouteDecisionKind.CLARIFY, RouteDecisionKind.REJECT} and route.message:
            return OrchestratorResult(text=route.message)

        logger.info("Agent router decision deferred kind=%s", route.kind.value)
        return OrchestratorResult(
            text="That route is recognized but not wired yet. Please use the legacy path."
        )

    def _register_commands(self) -> None:
        reg = self._command_registry
        reg.register_async("/new", cmd_reset)
        # /stop is handled entirely by the Middleware abort path (before the lock)
        # and never reaches the orchestrator command registry.
        reg.register_async("/status", cmd_status)
        reg.register_async("/model", cmd_model)
        reg.register_async("/model ", cmd_model)
        reg.register_async("/memory", cmd_memory)
        reg.register_async("/history", cmd_history)
        reg.register_async("/history ", cmd_history)
        reg.register_async("/settings", cmd_settings)
        reg.register_async("/settings ", cmd_settings)
        reg.register_async("/cm", cmd_controlmesh)
        reg.register_async("/cm ", cmd_controlmesh)
        reg.register_async("/back", cmd_back)
        reg.register_async("/cron", cmd_cron)
        reg.register_async("/diagnose", cmd_diagnose)
        reg.register_async("/upgrade", cmd_upgrade)
        reg.register_async("/sessions", cmd_sessions)
        reg.register_async("/tasks", cmd_tasks)

    def register_multiagent_commands(self) -> None:
        """Register /agents, /agent_start, /agent_stop, /agent_restart commands.

        Called by the AgentSupervisor after setting ``_supervisor``.
        """
        from controlmesh.multiagent.commands import (
            cmd_agent_restart,
            cmd_agent_start,
            cmd_agent_stop,
            cmd_agents,
        )

        reg = self._command_registry
        reg.register_async("/agents", cmd_agents)
        reg.register_async("/agent_start", cmd_agent_start)
        reg.register_async("/agent_start ", cmd_agent_start)
        reg.register_async("/agent_stop", cmd_agent_stop)
        reg.register_async("/agent_stop ", cmd_agent_stop)
        reg.register_async("/agent_restart", cmd_agent_restart)
        reg.register_async("/agent_restart ", cmd_agent_restart)
        logger.info("Multi-agent commands registered")

    async def reset_session(self, key: SessionKey) -> None:
        """Reset the session for a given key."""
        await self._sessions.reset_session(key)
        logger.info("Session reset")

    async def reset_active_provider_session(self, key: SessionKey) -> str:
        """Reset only the active provider session bucket for a given key."""
        active = await self._sessions.get_active(key)
        if active is not None:
            provider = active.provider
            model = active.model
        else:
            model, provider = self.resolve_runtime_target(self._config.model)

        await self._sessions.reset_provider_session(
            key,
            provider=provider,
            model=model,
        )
        logger.info("Active provider session reset provider=%s", provider)
        return provider

    async def abort(self, chat_id: int) -> int:
        """Kill all active CLI processes and background tasks for chat_id."""
        killed = await self._process_registry.kill_all(chat_id)
        if self._observers.background:
            killed += await self._observers.background.cancel_all(chat_id)
        self._named_sessions.end_all(chat_id)
        return killed

    def interrupt(self, chat_id: int) -> int:
        """Send SIGINT to active CLI processes for *chat_id*.

        Unlike :meth:`abort` this does not kill or unregister the processes.
        It sends a soft interrupt so the CLI can cancel the current tool
        execution (equivalent to pressing ESC in the terminal).
        """
        return self._process_registry.interrupt_all(chat_id)

    async def abort_all(self) -> int:
        """Kill all active CLI processes across all chats on this agent."""
        return await self._process_registry.kill_all_active()

    def resolve_runtime_target(self, requested_model: str | None = None) -> tuple[str, str]:
        """Resolve requested model to the effective ``(model, provider)`` pair."""
        return self._providers.resolve_runtime_target(requested_model)

    async def dispatch_controlmesh_command(self, key: SessionKey, text: str) -> OrchestratorResult:
        """Dispatch a nested ControlMesh slash command directly."""
        result = await self._command_registry.dispatch(text.strip().lower(), self, key, text)
        if result is not None:
            return result
        head = text.strip().split(None, 1)[0] if text.strip() else "/"
        return OrchestratorResult(text=f"Unknown ControlMesh command: {head}")

    async def _native_mode_target(
        self, dispatch: _MessageDispatch
    ) -> tuple[str, str] | None:
        """Return the selected provider-native target for this slash command, if any."""
        normalized = dispatch.cmd.strip()
        if not normalized.startswith("/"):
            return None

        head = normalized.split(None, 1)[0].split("@", 1)[0]
        if head in {"/back", "/cm"}:
            return None

        session = await self._sessions.get_active(dispatch.key)
        if session is None:
            return None
        if session.command_mode == "cm":
            return None
        if session.command_mode not in _NATIVE_COMMAND_MODE_PROVIDERS:
            return None
        if not session.command_mode_model:
            return None
        return session.command_mode, session.command_mode_model

    async def _unknown_slash_native_target(
        self, dispatch: _MessageDispatch
    ) -> tuple[str, str] | None:
        """Return the active provider target for unclaimed slash commands.

        This preserves ControlMesh's established top-level commands while letting
        provider-native slash commands such as ``/compact`` or ``/review`` pass
        through without requiring a separate public switch command.
        """
        normalized = dispatch.cmd.strip()
        if not normalized.startswith("/"):
            return None

        head = normalized.split(None, 1)[0].split("@", 1)[0]
        if head in {"/back", "/cm"}:
            return None
        if self._command_registry.matches(normalized):
            return None

        session = await self._sessions.get_active(dispatch.key)
        if session is not None:
            return session.provider, session.model

        model, provider = self.resolve_runtime_target(self._config.model)
        if provider not in _NATIVE_COMMAND_MODE_PROVIDERS:
            return None
        return provider, model

    async def _route_provider_native_message(
        self,
        dispatch: _MessageDispatch,
        *,
        provider: str,
        model: str,
    ) -> OrchestratorResult:
        """Send the raw message to the active provider without CM slash dispatch."""
        session = await self._sessions.get_active(dispatch.key)
        restore_target: tuple[str, str] | None = None
        if session is not None:
            restore_target = (session.provider, session.model)

        try:
            if dispatch.streaming:
                return await provider_native_command_streaming(
                    self,
                    dispatch.key,
                    dispatch.text,
                    dispatch.streaming_callbacks(),
                    provider_override=provider,
                    model_override=model,
                )

            return await provider_native_command(
                self,
                dispatch.key,
                dispatch.text,
                provider_override=provider,
                model_override=model,
            )
        finally:
            if session is not None and restore_target is not None:
                restore_provider, restore_model = restore_target
                await self._sessions.sync_session_target(
                    session,
                    provider=restore_provider,
                    model=restore_model,
                )

    def wire_observers_to_bus(
        self,
        bus: MessageBus,
        *,
        wake_handler: Callable[[int, str], Awaitable[str | None]] | None = None,
    ) -> None:
        """Wire all observer result callbacks to the message bus."""
        self._observers.wire_to_bus(bus, wake_handler=wake_handler)
        bus.set_injector(self)
        bus.set_pre_deliver_hook(self.record_frontstage_delivery)

    @staticmethod
    def _frontstage_delivery_source(origin: Origin) -> str | None:
        """Map bus origins to transcript-worthy assistant delivery sources."""
        return {
            Origin.BACKGROUND: "background_session_result",
            Origin.INTERAGENT: "foreground_interagent_result",
            Origin.TASK_RESULT: "foreground_task_result",
        }.get(origin)

    @staticmethod
    def _normalize_transcript_content(
        text: str,
    ) -> tuple[str, list[TranscriptAttachment]]:
        """Split visible text from attached file metadata for transcript storage."""
        attachments = [
            Orchestrator._attachment_from_tag(file_tag) for file_tag in extract_file_paths(text)
        ]
        content = FILE_PATH_RE.sub("", text).strip()
        return content, attachments

    @staticmethod
    def _attachment_from_tag(file_tag: str) -> TranscriptAttachment:
        """Convert one ``<file:...>`` tag into normalized transcript metadata."""
        path = path_from_file_tag(file_tag)
        try:
            mime = guess_mime(path)
        except OSError:
            mime = "application/octet-stream"
        return TranscriptAttachment(
            kind=classify_mime(mime),
            label=path.name,
            path=str(path),
        )

    async def handle_heartbeat(
        self,
        key: SessionKey,
        *,
        prompt: str | None = None,
        ack_token: str | None = None,
    ) -> str | None:
        """Run a heartbeat turn in the main session. Returns alert text or None."""
        logger.debug("Heartbeat flow starting")
        return await heartbeat_flow(self, key, prompt=prompt, ack_token=ack_token)

    def submit_named_session(
        self,
        chat_id: int,
        prompt: str,
        request: NamedSessionRequest,
    ) -> tuple[str, str]:
        """Submit a new named background session. Returns (task_id, session_name)."""
        from controlmesh.cli.param_resolver import resolve_cli_config

        if self._observers.background is None:
            msg = "Background observer not initialized"
            raise RuntimeError(msg)

        model_name, provider_name = self.resolve_runtime_target(self._config.model)
        if request.provider_override:
            provider_name = request.provider_override
            model_name = request.model_override or self.default_model_for_provider(
                request.provider_override
            )

        ns = self._named_sessions.create(chat_id, provider_name, model_name, prompt)
        exec_config = resolve_cli_config(self._config, self._observers.codex_cache)
        sub = BackgroundSubmit(
            chat_id=chat_id,
            prompt=prompt,
            message_id=request.message_id,
            thread_id=request.thread_id,
            session_name=ns.name,
            provider_override=provider_name,
            model_override=model_name,
        )
        task_id = self._observers.background.submit(sub, exec_config)
        return task_id, ns.name

    def submit_named_followup_bg(
        self,
        chat_id: int,
        session_name: str,
        prompt: str,
        message_id: int,
        thread_id: int | None,
    ) -> str:
        """Submit a background follow-up to an existing named session. Returns task_id."""
        from controlmesh.cli.param_resolver import resolve_cli_config

        if self._observers.background is None:
            msg = "Background observer not initialized"
            raise RuntimeError(msg)

        ns = self._named_sessions.get(chat_id, session_name)
        if ns is None:
            msg = f"Session '{session_name}' not found"
            raise ValueError(msg)
        if ns.status == "ended":
            msg = f"Session '{session_name}' has ended"
            raise ValueError(msg)
        if ns.status == "running":
            msg = f"Session '{session_name}' is still processing"
            raise ValueError(msg)

        self._named_sessions.mark_running(chat_id, session_name, prompt)
        exec_config = resolve_cli_config(self._config, self._observers.codex_cache)
        sub = BackgroundSubmit(
            chat_id=chat_id,
            prompt=prompt,
            message_id=message_id,
            thread_id=thread_id,
            session_name=session_name,
            resume_session_id=ns.session_id,
            provider_override=ns.provider,
            model_override=ns.model,
        )
        return self._observers.background.submit(sub, exec_config)

    async def end_named_session(self, chat_id: int, name: str) -> bool:
        """Kill process and end a named session."""
        ns = self._named_sessions.get(chat_id, name)
        if ns is None:
            return False
        await self._process_registry.kill_by_label(chat_id, f"ns:{name}")
        self._process_registry.clear_label_abort(chat_id, f"ns:{name}")
        return self._named_sessions.end_session(chat_id, name)

    def is_known_model(self, candidate: str) -> bool:
        """Return True if *candidate* is a recognized model ID for any provider."""
        return self._providers.is_known_model(candidate)

    def default_model_for_provider(self, provider: str) -> str:
        """Return the default model ID for a provider, or empty string if unknown."""
        return self._providers.default_model_for_provider(provider)

    def resolve_session_directive(self, key: str) -> tuple[str, str] | None:
        """Resolve a ``@key`` directive to ``(provider, model)`` or ``None``."""
        return self._providers.resolve_session_directive(key)

    def get_named_session(self, chat_id: int, name: str) -> NamedSession | None:
        """Look up a named session."""
        return self._named_sessions.get(chat_id, name)

    def list_named_sessions(self, chat_id: int) -> list[NamedSession]:
        """List active named sessions for a chat."""
        return self._named_sessions.list_active(chat_id)

    async def list_topic_sessions(self, chat_id: int) -> list[SessionData]:
        """Return fresh topic sessions for *chat_id*."""
        all_sessions = await self._sessions.list_active_for_chat(chat_id)
        return [s for s in all_sessions if s.topic_id is not None]

    def active_background_tasks(self, chat_id: int | None = None) -> list[BackgroundTask]:
        """Return active background tasks, optionally filtered by chat_id."""
        if self._observers.background is None:
            return []
        return self._observers.background.active_tasks(chat_id)

    def is_chat_busy(self, chat_id: int, topic_id: int | None = None) -> bool:
        """Check if a chat has active CLI processes."""
        return self._process_registry.has_active(chat_id, topic_id)

    async def _ensure_docker(self) -> None:
        """Health-check Docker before CLI calls; auto-recover or fall back."""
        from controlmesh.orchestrator.lifecycle import ensure_docker

        await ensure_docker(self)

    def set_config_hot_reload_handler(
        self,
        handler: Callable[[AgentConfig, dict[str, object]], None],
    ) -> None:
        """Register an external hot-reload callback (e.g. TelegramBot auth update)."""
        self._config_hot_reload_handler = handler

    def _on_config_hot_reload(self, config: AgentConfig, hot: dict[str, object]) -> None:
        """Apply hot-reloaded config fields to dependent services."""
        if any(
            k in hot
            for k in (
                "model",
                "provider",
                "max_turns",
                "max_budget_usd",
                "permission_mode",
                "reasoning_effort",
                "cli_parameters",
            )
        ):
            self._cli_service.update_config(
                CLIServiceConfig(
                    working_dir=str(self._paths.workspace),
                    default_model=config.model,
                    provider=config.provider,
                    max_turns=config.max_turns,
                    max_budget_usd=config.max_budget_usd,
                    permission_mode=config.permission_mode,
                    reasoning_effort=config.reasoning_effort,
                    gemini_api_key=config.gemini_api_key,
                    docker_container=self._cli_service._config.docker_container,
                    claude_cli_parameters=tuple(config.cli_parameters.claude),
                    codex_cli_parameters=tuple(config.cli_parameters.codex),
                    gemini_cli_parameters=tuple(config.cli_parameters.gemini),
                    agent_name=self._cli_service._config.agent_name,
                    interagent_port=self._cli_service._config.interagent_port,
                    task_hub=self._cli_service._config.task_hub,
                    interagent_bus=self._cli_service._config.interagent_bus,
                )
            )

        if "model" in hot:
            self._providers.refresh_known_model_ids()

        if "language" in hot:
            from controlmesh.i18n import init as init_i18n

            init_i18n(config.language)

        if "heartbeat" in hot:
            hb = self._observers.heartbeat
            if config.heartbeat.enabled and not hb.running:
                task = asyncio.create_task(hb.start())
                task.add_done_callback(lambda _: None)
                logger.info("Heartbeat observer started via hot-reload")
            elif not config.heartbeat.enabled and hb.running:
                task = asyncio.create_task(hb.stop())
                task.add_done_callback(lambda _: None)
                logger.info("Heartbeat observer stopped via hot-reload")

        handler = getattr(self, "_config_hot_reload_handler", None)
        if handler is not None:
            handler(config, hot)

        logger.info("Hot-reload applied to orchestrator services")

    # -- Inter-agent communication ------------------------------------------

    async def handle_interagent_message(
        self,
        sender: str,
        message: str,
        *,
        new_session: bool = False,
    ) -> tuple[str, str, str]:
        """Process a message from another agent via the InterAgentBus."""
        from controlmesh.orchestrator.injection import (
            handle_interagent_message as _handle_ia,
        )

        return await _handle_ia(self, sender, message, new_session=new_session)

    async def handle_async_interagent_result(
        self,
        result: AsyncInterAgentResult,
        *,
        chat_id: int = 0,
    ) -> str:
        """Inject an async inter-agent result into the current active session."""
        from controlmesh.orchestrator.injection import (
            handle_async_interagent_result as _handle_async_ia,
        )

        return await _handle_async_ia(self, result, chat_id=chat_id)

    async def inject_prompt(
        self,
        prompt: str,
        chat_id: int,
        label: str,
        *,
        topic_id: int | None = None,
        transport: str = "tg",
    ) -> str:
        """Execute *prompt* in the active session (fulfils ``SessionInjector`` protocol)."""
        from controlmesh.orchestrator.injection import _inject_prompt

        return await _inject_prompt(
            self, prompt, chat_id, label, topic_id=topic_id, transport=transport
        )

    async def shutdown(self) -> None:
        """Cleanup on bot shutdown."""
        from controlmesh.orchestrator.lifecycle import shutdown

        await shutdown(self)
