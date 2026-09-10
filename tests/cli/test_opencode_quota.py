"""Quota failures stop a live child, without confusing content or rate limits."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.executor import SubprocessSpec, run_oneshot_subprocess
from controlmesh.cli.opencode_provider import OpenCodeCLI
from controlmesh.cli.opencode_quota import quota_from_stderr
from controlmesh.cli.service import _cli_response_to_agent_response


def native_error(message: str) -> str:
    return (
        'timestamp=2026-09-10T08:30:07Z level=ERROR run=example message="stream error" '
        'providerID=example modelID=example session.id=ses_Example123 '
        'error.error=' + json.dumps(message)
    )


@pytest.mark.parametrize("message", [
    "Usage limit reached for 5 hour. Your limit will reset at 2026-09-10 20:39:15",
    "insufficient_quota", "quota_exceeded", "Your credit balance is too low",
])
def test_classifies_explicit_quota(message: str) -> None:
    response = quota_from_stderr(native_error(message))
    assert response is not None
    assert response.error_code == "quota_exhausted"
    assert response.session_id == "ses_Example123"
    assert response.is_error
    assert not response.timed_out


@pytest.mark.parametrize("line", [
    native_error("HTTP 429 Too Many Requests; retry after 1 second"),
    native_error("invalid API key"),
    native_error("connect ETIMEDOUT"),
    "Usage limit reached for 5 hour",
    native_error("Usage limit reached").replace("level=ERROR", "level=INFO"),
    native_error("Usage limit reached").replace('message="stream error"', 'message="tool result"'),
])
def test_does_not_classify_ambiguous_or_untrusted_output(line: str) -> None:
    assert quota_from_stderr(line) is None


def test_reset_metadata_and_no_raw_error_leak() -> None:
    response = quota_from_stderr(native_error(
        "Usage limit reached for 5 hour. Your limit will reset at 2026-09-10 20:39:15 secret=PRIVATE"
    ))
    assert response is not None
    assert response.quota_reset_at == "2026-09-10 20:39:15"
    assert "PRIVATE" not in response.result
    agent = _cli_response_to_agent_response(response)
    assert agent.error_code == "quota_exhausted"
    assert agent.quota_reset_at == response.quota_reset_at


def test_error_event_and_assistant_text_are_distinct() -> None:
    error = {"type": "error", "sessionID": "ses_Example123", "error": {
        "data": {"message": "insufficient_quota"}}}
    result = OpenCodeCLI._parse_output(json.dumps(error).encode(), b"", 0)
    assert result.error_code == "quota_exhausted"
    text = {"type": "text", "part": {"text": "insufficient_quota"}}
    result = OpenCodeCLI._parse_output(json.dumps(text).encode(), b"", 0)
    assert result.error_code is None
    assert not result.is_error


async def test_live_child_quota_is_stopped_before_timeout(tmp_path: Path) -> None:
    line = native_error("Usage limit reached for 5 hour. Your limit will reset at 2026-09-10 20:39:15")
    # Split a real native log record across pipe writes, then emulate native retries.
    script = (
        "import sys,time; "
        f"sys.stderr.write({line[:65]!r}); sys.stderr.flush(); time.sleep(.05); "
        f"sys.stderr.write({(line[65:] + chr(10))!r}); sys.stderr.flush(); time.sleep(60)"
    )
    start = time.monotonic()
    response = await run_oneshot_subprocess(
        CLIConfig(working_dir=tmp_path),
        SubprocessSpec([sys.executable, "-c", script], str(tmp_path), "", 10,
                       stderr_abort=quota_from_stderr),
        OpenCodeCLI._parse_output, provider_label="OpenCode",
    )
    assert time.monotonic() - start < 5
    assert response.error_code == "quota_exhausted"
    assert not response.timed_out
    assert response.returncode is not None


async def test_live_child_transient_limit_is_not_aborted(tmp_path: Path) -> None:
    line = native_error("429 Too Many Requests")
    output = json.dumps({"type": "text", "part": {"text": "OK"}})
    script = f"import sys; print({line!r},file=sys.stderr); print({output!r})"
    response = await run_oneshot_subprocess(
        CLIConfig(working_dir=tmp_path),
        SubprocessSpec([sys.executable, "-c", script], str(tmp_path), "", 5,
                       stderr_abort=quota_from_stderr),
        OpenCodeCLI._parse_output,
    )
    assert response.result == "OK"
    assert not response.is_error
    assert response.error_code is None


async def test_streaming_preserves_quota_and_does_not_report_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock
    from controlmesh.cli.stream_events import ResultEvent

    monkeypatch.setattr(OpenCodeCLI, "_find_cli", staticmethod(lambda: sys.executable))
    response = quota_from_stderr(native_error("insufficient_quota"))
    assert response is not None
    cli = OpenCodeCLI(CLIConfig())
    send = AsyncMock(return_value=response)
    monkeypatch.setattr(cli, "send", send)
    events = [event async for event in cli.send_streaming("hello")]
    final = events[-1]
    assert isinstance(final, ResultEvent)
    assert final.subtype == "quota_exhausted"
    assert final.error_code == "quota_exhausted"
    assert final.session_id == "ses_Example123"
    assert final.is_error
    send.assert_awaited_once()
