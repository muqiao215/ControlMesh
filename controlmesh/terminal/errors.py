"""Terminal-specific exceptions."""

from __future__ import annotations


class TerminalError(RuntimeError):
    """Base class for local terminal runtime failures."""


class TerminalProviderError(TerminalError):
    """Raised when a provider cannot be used in native terminal mode."""
