"""User-visible diagnostics for provider subprocess runs."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field


_TAIL_LIMIT = 100


@dataclass(slots=True)
class ProviderRunDiagnostic:
    """Facts ControlMesh observed while supervising one provider process."""

    provider: str
    phase: str = "starting"
    pid: int | None = None
    exit_code: int | None = None
    timed_out: bool = False
    timeout_reason: str = ""
    stdout_tail: deque[str] = field(default_factory=lambda: deque(maxlen=_TAIL_LIMIT))
    stderr_tail: deque[str] = field(default_factory=lambda: deque(maxlen=_TAIL_LIMIT))
    last_event_type: str = ""
    started_at: float = field(default_factory=time.monotonic)
    last_activity_at: float = field(default_factory=time.monotonic)
    first_event_received: bool = False

    def note_stdout(self, text: str) -> None:
        self.stdout_tail.append(text)
        self.last_activity_at = time.monotonic()
        self.phase = "active"

    def note_stderr(self, text: str) -> None:
        self.stderr_tail.append(text)
        self.last_activity_at = time.monotonic()
        lower = text.lower()
        if "mcp startup" in lower:
            self.phase = "mcp_startup"

    def note_event(self, event: object) -> None:
        event_type = getattr(event, "type", "") or event.__class__.__name__
        subtype = getattr(event, "subtype", "")
        self.last_event_type = f"{event_type}.{subtype}" if subtype else str(event_type)
        self.first_event_received = True
        self.phase = "active"
        self.last_activity_at = time.monotonic()

    def note_exit(self, exit_code: int | None) -> None:
        self.exit_code = exit_code
        if self.timed_out:
            self.phase = "timeout"
        elif exit_code not in (0, None):
            self.phase = "failed"
        else:
            self.phase = "stopping"

    def note_timeout(self, reason: str, exit_code: int | None = None) -> None:
        self.timed_out = True
        self.timeout_reason = reason
        self.exit_code = exit_code
        self.phase = "timeout"

    @property
    def duration(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def render_user_error(self) -> str:
        """Render a compact diagnostic that is safe to show to users."""
        stdout_tail = _tail_text(self.stdout_tail)
        stderr_tail = _tail_text(self.stderr_tail)
        fallback = self.fallback_message()
        lines = [
            fallback,
            "",
            "provider: " + self.provider,
            "exit_code: " + str(self.exit_code),
            "timed_out: " + str(self.timed_out),
            "phase: " + self.phase,
            "last_event_type: " + (self.last_event_type or "(none)"),
            "duration: " + f"{self.duration:.1f}s",
            "fallback_message: " + fallback,
            "stdout_tail:",
            stdout_tail or "(no output)",
            "stderr_tail:",
            stderr_tail or "(no output)",
        ]
        return "\n".join(lines)[-4000:]

    def fallback_message(self) -> str:
        if self.timed_out:
            return (
                f"{self.provider} timed out.\n"
                f"phase: {self.phase}\n"
                f"last_event: {self.last_event_type or '(none)'}"
            )
        if self.stderr_tail:
            return (
                f"{self.provider} exited with code {self.exit_code}.\n"
                "stderr:\n"
                + _tail_text(self.stderr_tail)[-1500:]
            )
        if self.stdout_tail:
            return f"{self.provider} exited with code {self.exit_code}."
        return (
            f"{self.provider} exited with code {self.exit_code} "
            "and produced no stdout/stderr."
        )


def diagnostic_from_completed_process(
    provider: str,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int | None = None,
) -> ProviderRunDiagnostic:
    diag = ProviderRunDiagnostic(provider=provider)
    diag.note_exit(returncode)
    for line in _decode_lines(stdout):
        diag.note_stdout(line)
    for line in _decode_lines(stderr):
        diag.note_stderr(line)
    diag.note_exit(returncode)
    return diag


def _decode_lines(data: bytes) -> list[str]:
    text = data.decode(errors="replace") if data else ""
    return [line.rstrip() for line in text.splitlines() if line.rstrip()]


def _tail_text(values: Iterable[str]) -> str:
    return "\n".join(list(values)[-8:])
