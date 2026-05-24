"""Terminal session state."""

from __future__ import annotations

from dataclasses import dataclass

from controlmesh.terminal.modes import TerminalMode


@dataclass(slots=True)
class TerminalSessionState:
    """Mutable local terminal session state."""

    mode: TerminalMode = TerminalMode.ENHANCED
    session_name: str = "main"
