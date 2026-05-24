"""Tests for provider-run supervision diagnostics and fake CLI fixtures."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.executor import SubprocessSpec, run_oneshot_subprocess, run_streaming_subprocess
from controlmesh.cli.liveness import BACKGROUND_POLICY, FOREGROUND_POLICY
from controlmesh.cli.stream_events import ResultEvent, StreamEvent, parse_stream_line
from controlmesh.cli.types import AgentRequest, CLIResponse
from controlmesh.cli.supervisor import ProviderRunSupervisor


FIXTURES = Path(__file__).parent / "fixtures" / "fake_cli"


def _cmd(name: str) -> list[str]:
    return [sys.executable, str(FIXTURES / name)]


def _parse_empty(stdout: bytes, stderr: bytes, returncode: int | None) -> CLIResponse:
    return CLIResponse(
        result=stdout.decode(errors="replace").strip(),
        is_error=returncode not in (0, None),
        returncode=returncode,
        stderr=stderr.decode(errors="replace"),
    )


async def _line_handler(line: str) -> AsyncGenerator[StreamEvent, None]:
    for event in parse_stream_line(line):
        yield event


async def test_oneshot_silent_exit_1_returns_diagnostic_error() -> None:
    response = await run_oneshot_subprocess(
        CLIConfig(provider="fake"),
        SubprocessSpec(_cmd("silent_then_exit_1.py"), None, "", timeout_seconds=2),
        _parse_empty,
        provider_label="Fake",
    )

    assert response.is_error is True
    assert response.returncode == 1
    assert "Fake exited with code 1 and produced no stdout/stderr." in response.result
    assert "provider: Fake" in response.result


async def test_oneshot_stderr_only_exit_1_returns_stderr_tail() -> None:
    response = await run_oneshot_subprocess(
        CLIConfig(provider="fake"),
        SubprocessSpec(_cmd("stderr_only_exit_1.py"), None, "", timeout_seconds=2),
        _parse_empty,
        provider_label="Fake",
    )

    assert response.is_error is True
    assert "Fake exited with code 1." in response.result
    assert "fatal auth" in response.result
    assert "stderr_tail:" in response.result


async def test_streaming_mcp_startup_then_timeout_reports_phase() -> None:
    events = [
        event
        async for event in run_streaming_subprocess(
            CLIConfig(provider="fake"),
            SubprocessSpec(_cmd("mcp_startup_then_silent.py"), None, "", timeout_seconds=0.2),
            _line_handler,
            provider_label="Fake",
        )
    ]

    result = events[-1]
    assert isinstance(result, ResultEvent)
    assert result.is_error is True
    assert result.subtype == "timeout_error"
    assert "phase: timeout" in result.result
    assert "mcp startup: no servers" in result.result


async def test_streaming_jsonl_init_then_timeout_keeps_last_event() -> None:
    events = [
        event
        async for event in run_streaming_subprocess(
            CLIConfig(provider="fake"),
            SubprocessSpec(_cmd("jsonl_init_then_silent.py"), None, "", timeout_seconds=0.2),
            _line_handler,
            provider_label="Fake",
        )
    ]

    result = events[-1]
    assert isinstance(result, ResultEvent)
    assert "last_event_type: system.init" in result.result
    assert "stdout_tail:" in result.result


def test_background_policy_does_not_soft_timeout_idle() -> None:
    supervisor = ProviderRunSupervisor("Fake", BACKGROUND_POLICY)
    supervisor.started(pid=123, command=["fake"])
    supervisor.diagnostic.last_activity_at -= BACKGROUND_POLICY.idle_soft_timeout_s + 1

    assert supervisor.should_soft_timeout_idle() is False


def test_foreground_policy_soft_timeouts_idle() -> None:
    supervisor = ProviderRunSupervisor("Fake", FOREGROUND_POLICY)
    supervisor.started(pid=123, command=["fake"])
    supervisor.diagnostic.last_activity_at -= FOREGROUND_POLICY.idle_soft_timeout_s + 1

    assert supervisor.should_soft_timeout_idle() is True


class _Adapter:
    async def send(self, **_kwargs: object) -> CLIResponse:
        return CLIResponse(result="", is_error=True, returncode=9)

    async def send_streaming(self, **_kwargs: object) -> AsyncGenerator[StreamEvent, None]:
        yield ResultEvent(type="result", result="done", is_error=False, returncode=0)


async def test_supervisor_run_oneshot_wraps_adapter() -> None:
    supervisor = ProviderRunSupervisor("Fake", FOREGROUND_POLICY)
    response = await supervisor.run_oneshot(_Adapter(), AgentRequest(prompt="go"))

    assert response.returncode == 9
    assert supervisor.diagnostic.exit_code == 9


async def test_supervisor_run_streaming_wraps_adapter() -> None:
    seen: list[StreamEvent] = []
    supervisor = ProviderRunSupervisor("Fake", FOREGROUND_POLICY)

    response = await supervisor.run_streaming(
        _Adapter(),
        AgentRequest(prompt="go"),
        seen.append,
    )

    assert response.result == "done"
    assert supervisor.diagnostic.last_event_type == "result"
    assert len(seen) == 1
