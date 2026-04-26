"""Tests for Matrix streaming callback mode routing."""

from __future__ import annotations

from controlmesh.messenger.matrix.streaming_mode import stream_callbacks_for_mode


async def _noop_text(_text: str) -> None:
    return None


async def _noop_status(_status: str | None) -> None:
    return None


def test_full_mode_enables_all_callbacks() -> None:
    text_cb, tool_cb, system_cb = stream_callbacks_for_mode(
        "full",
        on_text=_noop_text,
        on_tool=_noop_text,
        on_system=_noop_status,
    )

    assert text_cb is _noop_text
    assert tool_cb is _noop_text
    assert system_cb is _noop_status


def test_tools_mode_hides_system_status() -> None:
    text_cb, tool_cb, system_cb = stream_callbacks_for_mode(
        "tools",
        on_text=_noop_text,
        on_tool=_noop_text,
        on_system=_noop_status,
    )

    assert text_cb is _noop_text
    assert tool_cb is _noop_text
    assert system_cb is None


def test_conversation_mode_hides_tool_and_system_callbacks() -> None:
    text_cb, tool_cb, system_cb = stream_callbacks_for_mode(
        "conversation",
        on_text=_noop_text,
        on_tool=_noop_text,
        on_system=_noop_status,
    )

    assert text_cb is _noop_text
    assert tool_cb is None
    assert system_cb is None


def test_off_mode_disables_all_callbacks() -> None:
    text_cb, tool_cb, system_cb = stream_callbacks_for_mode(
        "off",
        on_text=_noop_text,
        on_tool=_noop_text,
        on_system=_noop_status,
    )

    assert text_cb is None
    assert tool_cb is None
    assert system_cb is None
