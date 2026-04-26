"""Shared Matrix streaming callback mode routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

_TextCallback = Callable[[str], Awaitable[None]]
_StatusCallback = Callable[[str | None], Awaitable[None]]


def stream_callbacks_for_mode(
    mode: str,
    *,
    on_text: _TextCallback,
    on_tool: _TextCallback,
    on_system: _StatusCallback,
) -> tuple[_TextCallback | None, _TextCallback | None, _StatusCallback | None]:
    """Map streaming output mode to Matrix callbacks."""
    if mode == "full":
        return on_text, on_tool, on_system
    if mode == "tools":
        return on_text, on_tool, None
    if mode == "conversation":
        return on_text, None, None
    if mode == "off":
        return None, None, None
    return on_text, on_tool, on_system
