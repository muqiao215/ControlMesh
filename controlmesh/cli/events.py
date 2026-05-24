"""Provider-run event facts emitted by ControlMesh supervision."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderRunEvent:
    """Base event for facts observed during one provider run."""

    provider: str
    kind: str
    phase: str = ""
    created_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class ProviderStartedEvent(ProviderRunEvent):
    pid: int | None = None
    command: tuple[str, ...] = ()


@dataclass(slots=True)
class ProviderStdoutEvent(ProviderRunEvent):
    text: str = ""


@dataclass(slots=True)
class ProviderStderrEvent(ProviderRunEvent):
    text: str = ""


@dataclass(slots=True)
class ProviderParsedEvent(ProviderRunEvent):
    event_type: str = ""
    payload: Any = None


@dataclass(slots=True)
class ProviderStillRunningEvent(ProviderRunEvent):
    idle_for_s: float = 0.0


@dataclass(slots=True)
class ProviderSilentWarningEvent(ProviderRunEvent):
    idle_for_s: float = 0.0


@dataclass(slots=True)
class ProviderNoFirstEventWarningEvent(ProviderRunEvent):
    elapsed_s: float = 0.0


@dataclass(slots=True)
class ProviderProcessExitEvent(ProviderRunEvent):
    exit_code: int | None = None


@dataclass(slots=True)
class ProviderTimeoutEvent(ProviderRunEvent):
    reason: str = ""
    exit_code: int | None = None


@dataclass(slots=True)
class ProviderFinalErrorEvent(ProviderRunEvent):
    message: str = ""
    exit_code: int | None = None
    timed_out: bool = False
