"""Provider subprocess supervision primitives.

The executor still owns the actual asyncio subprocess I/O, but this class is
the shared state machine for facts, diagnostics, and liveness policy.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from controlmesh.cli.diagnostics import ProviderRunDiagnostic
from controlmesh.cli.events import (
    ProviderFinalErrorEvent,
    ProviderParsedEvent,
    ProviderProcessExitEvent,
    ProviderRunEvent,
    ProviderStartedEvent,
    ProviderStderrEvent,
    ProviderStdoutEvent,
    ProviderTimeoutEvent,
)
from controlmesh.cli.liveness import FOREGROUND_POLICY, RunLivenessPolicy
from controlmesh.cli.stream_events import StreamEvent
from controlmesh.cli.types import CLIResponse

if TYPE_CHECKING:
    from controlmesh.cli.base import BaseCLI
    from controlmesh.cli.types import AgentRequest


@dataclass(slots=True)
class ProviderRunSupervisor:
    """Maintain diagnostic and event facts for one provider process."""

    provider: str
    policy: RunLivenessPolicy = FOREGROUND_POLICY
    diagnostic: ProviderRunDiagnostic = field(init=False)
    events: list[ProviderRunEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.diagnostic = ProviderRunDiagnostic(provider=self.provider)

    def started(self, *, pid: int | None, command: Iterable[str] = ()) -> ProviderStartedEvent:
        self.diagnostic.pid = pid
        self.diagnostic.phase = "waiting_first_event"
        event = ProviderStartedEvent(
            provider=self.provider,
            kind="provider_started",
            phase=self.diagnostic.phase,
            pid=pid,
            command=tuple(command),
        )
        self.events.append(event)
        return event

    def stdout(self, text: str) -> ProviderStdoutEvent:
        self.diagnostic.note_stdout(text)
        event = ProviderStdoutEvent(
            provider=self.provider,
            kind="provider_stdout",
            phase=self.diagnostic.phase,
            text=text,
        )
        self.events.append(event)
        return event

    def stderr(self, text: str) -> ProviderStderrEvent:
        self.diagnostic.note_stderr(text)
        event = ProviderStderrEvent(
            provider=self.provider,
            kind="provider_stderr",
            phase=self.diagnostic.phase,
            text=text,
        )
        self.events.append(event)
        return event

    def parsed(self, provider_event: object) -> ProviderParsedEvent:
        self.diagnostic.note_event(provider_event)
        event_type = self.diagnostic.last_event_type
        event = ProviderParsedEvent(
            provider=self.provider,
            kind="provider_parsed",
            phase=self.diagnostic.phase,
            event_type=event_type,
            payload=provider_event,
        )
        self.events.append(event)
        return event

    def exited(self, exit_code: int | None) -> ProviderProcessExitEvent:
        self.diagnostic.note_exit(exit_code)
        event = ProviderProcessExitEvent(
            provider=self.provider,
            kind="process_exit_error" if exit_code not in (0, None) else "process_exit",
            phase=self.diagnostic.phase,
            exit_code=exit_code,
        )
        self.events.append(event)
        return event

    def timed_out(self, reason: str, exit_code: int | None = None) -> ProviderTimeoutEvent:
        self.diagnostic.note_timeout(reason, exit_code)
        event = ProviderTimeoutEvent(
            provider=self.provider,
            kind="timeout_error",
            phase=self.diagnostic.phase,
            reason=reason,
            exit_code=exit_code,
        )
        self.events.append(event)
        return event

    def final_error(self) -> ProviderFinalErrorEvent:
        message = self.diagnostic.render_user_error()
        event = ProviderFinalErrorEvent(
            provider=self.provider,
            kind="diagnostic_error",
            phase=self.diagnostic.phase,
            message=message,
            exit_code=self.diagnostic.exit_code,
            timed_out=self.diagnostic.timed_out,
        )
        self.events.append(event)
        return event

    def should_warn_no_first_event(self) -> bool:
        return (
            not self.diagnostic.first_event_received
            and time.monotonic() - self.diagnostic.started_at >= self.policy.first_event_timeout_s
        )

    def should_soft_timeout_idle(self) -> bool:
        if not self.policy.kill_on_idle:
            return False
        return time.monotonic() - self.diagnostic.last_activity_at >= self.policy.idle_soft_timeout_s

    async def run_oneshot(
        self,
        provider_adapter: BaseCLI,
        request: AgentRequest,
    ) -> CLIResponse:
        """Run a provider adapter one-shot call through a supervisor boundary."""
        try:
            response = await provider_adapter.send(
                prompt=request.prompt,
                resume_session=request.resume_session,
                continue_session=request.continue_session,
                timeout_seconds=request.timeout_seconds,
                timeout_controller=request.timeout_controller,
                hard_timeout_seconds=request.hard_timeout_seconds,
            )
        except TimeoutError:
            self.timed_out("timeout")
            return CLIResponse(result=self.final_error().message, is_error=True, timed_out=True)
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as exc:
            self.stderr(str(exc))
            self.exited(1)
            return CLIResponse(result=self.final_error().message, is_error=True, returncode=1)
        self.exited(response.returncode)
        if (response.is_error or response.timed_out or response.returncode not in (0, None)) and not response.result.strip():
            response.result = self.final_error().message
            response.is_error = True
        return response

    async def run_streaming(
        self,
        provider_adapter: BaseCLI,
        request: AgentRequest,
        dispatch: Callable[[StreamEvent], object],
    ) -> CLIResponse:
        """Run provider streaming and return the final response event as CLIResponse."""
        final = CLIResponse()
        try:
            async for event in provider_adapter.send_streaming(
                prompt=request.prompt,
                resume_session=request.resume_session,
                continue_session=request.continue_session,
                timeout_seconds=request.timeout_seconds,
                timeout_controller=request.timeout_controller,
                hard_timeout_seconds=request.hard_timeout_seconds,
            ):
                self.parsed(event)
                maybe_response = dispatch(event)
                if asyncio.iscoroutine(maybe_response):
                    await maybe_response
                if getattr(event, "type", "") == "result":
                    final = CLIResponse(
                        session_id=getattr(event, "session_id", None),
                        result=getattr(event, "result", ""),
                        is_error=bool(getattr(event, "is_error", False)),
                        returncode=getattr(event, "returncode", None),
                        timed_out=getattr(event, "subtype", None) == "timeout_error",
                        duration_ms=getattr(event, "duration_ms", None),
                        duration_api_ms=getattr(event, "duration_api_ms", None),
                        total_cost_usd=getattr(event, "total_cost_usd", None),
                        usage=getattr(event, "usage", {}),
                        model_usage=getattr(event, "model_usage", {}),
                        num_turns=getattr(event, "num_turns", None),
                    )
        except TimeoutError:
            self.timed_out("timeout")
            return CLIResponse(result=self.final_error().message, is_error=True, timed_out=True)
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError) as exc:
            self.stderr(str(exc))
            self.exited(1)
            return CLIResponse(result=self.final_error().message, is_error=True, returncode=1)
        self.exited(final.returncode)
        if (final.is_error or final.timed_out or final.returncode not in (0, None)) and not final.result.strip():
            final.result = self.final_error().message
            final.is_error = True
        return final
