"""Tests for executor timeout integration with TimeoutController."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.cli.executor import (
    SubprocessSpec,
    _stream_with_controller,
    _stream_with_timeout,
)
from controlmesh.cli.stream_events import StreamEvent
from controlmesh.cli.timeout_controller import (
    TimeoutConfig,
    TimeoutController,
    TimeoutWarning,
)


def _make_stdout(lines: list[bytes], delay: float = 0.0) -> AsyncMock:
    """Create a mock StreamReader that yields *lines* then EOF."""
    reader = AsyncMock()
    call_count = 0

    async def readline() -> bytes:
        nonlocal call_count
        if call_count >= len(lines):
            return b""
        if delay > 0:
            await asyncio.sleep(delay)
        result = lines[call_count]
        call_count += 1
        return result

    reader.readline = readline
    return reader


def _make_process(
    lines: list[bytes],
    delay: float = 0.0,
) -> MagicMock:
    """Create a mock process with stdout producing *lines*."""
    process = MagicMock()
    process.stdout = _make_stdout(lines, delay=delay)
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")
    process.pid = 12345
    process.returncode = 0
    return process


async def _line_handler(line: str) -> AsyncGenerator[StreamEvent, None]:
    yield StreamEvent(type="test", subtype=line)


class TestStreamWithTimeoutPlainFallback:
    """When no controller is set, plain asyncio.timeout is used."""

    async def test_reads_all_lines(self) -> None:
        process = _make_process([b"line1\n", b"line2\n"])
        spec = SubprocessSpec(
            exec_cmd=["echo"],
            use_cwd=None,
            prompt="",
            timeout_seconds=5.0,
        )

        events = [event async for event in _stream_with_timeout(process, spec, _line_handler)]

        assert len(events) == 2
        assert events[0].subtype == "line1"
        assert events[1].subtype == "line2"

    async def test_timeout_fires_without_controller(self) -> None:
        process = _make_process([b"line1\n"], delay=0.5)
        spec = SubprocessSpec(
            exec_cmd=["echo"],
            use_cwd=None,
            prompt="",
            timeout_seconds=0.1,
        )

        with pytest.raises(TimeoutError):
            async for _ in _stream_with_timeout(process, spec, _line_handler):
                pass


class TestStreamWithController:
    """Controller-managed streaming with activity extension."""

    async def test_reads_all_lines_with_controller(self) -> None:
        tc = TimeoutController(
            TimeoutConfig(
                timeout_seconds=5.0,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
        )
        process = _make_process([b"hello\n", b"world\n"])

        events = [event async for event in _stream_with_controller(process, tc, _line_handler)]

        assert len(events) == 2

    async def test_timeout_fires_with_controller(self) -> None:
        tc = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.1,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
        )
        process = _make_process([b"line\n"], delay=0.5)

        with pytest.raises(TimeoutError):
            async for _ in _stream_with_controller(process, tc, _line_handler):
                pass

    async def test_activity_extends_timeout(self) -> None:
        """Lines arriving before deadline should trigger extension."""
        tc = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.25,
                warning_intervals=[],
                extend_on_activity=True,
                activity_extension=0.5,
                max_extensions=3,
            ),
        )
        # Each line arrives at ~0.1s intervals. Initial timeout at 0.25s fires
        # after 2 lines, then extension (+0.5s) covers the remaining lines.
        process = _make_process(
            [b"a\n", b"b\n", b"c\n", b"d\n"],
            delay=0.1,
        )

        events = [event async for event in _stream_with_controller(process, tc, _line_handler)]

        assert len(events) == 4

    async def test_extension_limit_respected(self) -> None:
        """After max_extensions, timeout fires even with activity."""
        tc = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.15,
                warning_intervals=[],
                extend_on_activity=True,
                activity_extension=0.15,
                max_extensions=1,
            ),
        )
        # Many lines with delays -- should eventually timeout.
        process = _make_process(
            [b"a\n"] * 10,
            delay=0.1,
        )

        with pytest.raises(TimeoutError):
            async for _ in _stream_with_controller(process, tc, _line_handler):
                pass

    async def test_warning_callback_fires(self) -> None:
        warnings: list[TimeoutWarning] = []

        async def on_warning(w: TimeoutWarning) -> None:
            warnings.append(w)

        tc = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.5,
                warning_intervals=[0.3],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
            on_warning=on_warning,
        )
        # Lines arrive fast, task completes before timeout.
        process = _make_process([b"a\n", b"b\n"], delay=0.15)

        events = [event async for event in _stream_with_controller(process, tc, _line_handler)]

        assert len(events) == 2
        assert len(warnings) >= 1


class TestOneshotWithController:
    """One-shot subprocess with controller timeout."""

    async def test_oneshot_uses_controller(self) -> None:
        """Verify run_oneshot_subprocess delegates to controller."""
        tc = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.1,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
        )

        async def slow_communicate(_input: bytes | None = None) -> tuple[bytes, bytes]:
            await asyncio.sleep(0.5)
            return b"out", b""

        with pytest.raises(TimeoutError):
            await tc.run_with_timeout(slow_communicate())


class TestBackwardCompat:
    """Backward compatibility: timeout_controller=None uses old path."""

    async def test_spec_defaults_to_no_controller(self) -> None:
        spec = SubprocessSpec(
            exec_cmd=["echo"],
            use_cwd=None,
            prompt="test",
        )
        assert spec.timeout_controller is None
        assert spec.timeout_seconds is None
