"""Terminal mode definitions."""

from __future__ import annotations

from enum import StrEnum


class TerminalMode(StrEnum):
    """Top-level local terminal modes."""

    ENHANCED = "enhanced"
    NATIVE = "native"
