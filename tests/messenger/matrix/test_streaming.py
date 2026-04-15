"""Tests for MatrixStreamEditor (segment-based streaming for Matrix)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from controlmesh.messenger.matrix.buttons import ButtonTracker
from controlmesh.messenger.matrix.streaming import MatrixStreamEditor


def _make_editor(
    *,
    send_fn: AsyncMock | None = None,
    button_tracker: ButtonTracker | None = None,
) -> tuple[MatrixStreamEditor, AsyncMock, AsyncMock]:
    """Create a MatrixStreamEditor with mock dependencies.

    Returns (editor, client_mock, send_fn_mock).
    """
    client = AsyncMock()
    sf = send_fn or AsyncMock(return_value="$evt")
    bt = button_tracker or ButtonTracker()
    editor = MatrixStreamEditor(
        client,
        "!room:test",
        send_fn=sf,
        button_tracker=bt,
    )
    return editor, client, sf


class TestOnDelta:
    async def test_delta_accumulates_in_buffer(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("Hello ")
        await editor.on_delta("world")
        # Buffer not flushed yet — no messages sent.
        send_fn.assert_not_awaited()

    async def test_empty_delta_accepted(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("")
        send_fn.assert_not_awaited()


class TestOnTool:
    async def test_flushes_buffer_on_tool(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("reasoning text")
        await editor.on_tool("SearchTool")
        send_fn.assert_awaited_once_with("!room:test", "reasoning text")

    async def test_empty_buffer_not_sent(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_tool("SearchTool")
        send_fn.assert_not_awaited()

    async def test_whitespace_only_buffer_not_sent(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("   \n  ")
        await editor.on_tool("SearchTool")
        send_fn.assert_not_awaited()

    async def test_resets_typing_indicator(self) -> None:
        editor, client, _send_fn = _make_editor()
        await editor.on_delta("text")
        await editor.on_tool("Tool")
        client.room_typing.assert_awaited_once_with("!room:test", typing_state=True, timeout=30000)

    async def test_increments_segment_count(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("seg1")
        await editor.on_tool("Tool1")
        await editor.on_delta("seg2")
        await editor.on_tool("Tool2")
        assert send_fn.await_count == 2

    async def test_clears_buffer_after_flush(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("first")
        await editor.on_tool("Tool")
        send_fn.reset_mock()
        # Buffer should be empty now — tool flush with empty buffer sends nothing.
        await editor.on_tool("Tool2")
        send_fn.assert_not_awaited()


class TestOnSystem:
    async def test_known_status_flushes(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("thinking...")
        await editor.on_system("thinking")
        send_fn.assert_awaited_once_with("!room:test", "thinking...")

    async def test_unknown_status_ignored(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("some text")
        await editor.on_system("unknown_status")
        send_fn.assert_not_awaited()

    async def test_none_status_ignored(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("some text")
        await editor.on_system(None)
        send_fn.assert_not_awaited()

    async def test_all_known_statuses(self) -> None:
        for status in (
            "thinking",
            "compacting",
            "recovering",
            "timeout_warning",
            "timeout_extended",
        ):
            editor, _client, send_fn = _make_editor()
            await editor.on_delta("buf")
            await editor.on_system(status)
            send_fn.assert_awaited_once()

    async def test_resets_typing_indicator(self) -> None:
        editor, client, _send_fn = _make_editor()
        await editor.on_delta("text")
        await editor.on_system("compacting")
        client.room_typing.assert_awaited_once_with("!room:test", typing_state=True, timeout=30000)


class TestFinalize:
    async def test_sends_remaining_buffer(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("final answer")
        await editor.finalize(None)
        send_fn.assert_awaited_once_with("!room:test", "final answer")

    async def test_fallback_to_result_text(self) -> None:
        editor, _client, send_fn = _make_editor()
        # No deltas received — buffer is empty.
        await editor.finalize("orchestrator result")
        send_fn.assert_awaited_once_with("!room:test", "orchestrator result")

    async def test_no_text_at_all(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.finalize(None)
        send_fn.assert_not_awaited()

    async def test_empty_buffer_empty_result(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.finalize("")
        send_fn.assert_not_awaited()

    async def test_button_extraction_on_final(self) -> None:
        bt = ButtonTracker()
        editor, _client, send_fn = _make_editor(button_tracker=bt)
        await editor.on_delta("Pick one [button:Yes] [button:No]")
        await editor.finalize(None)
        # The send_fn should receive text with buttons extracted.
        sent_text = send_fn.call_args[0][1]
        assert "[button:" not in sent_text
        assert "Yes" in sent_text
        assert "No" in sent_text

    async def test_button_extraction_on_fallback(self) -> None:
        bt = ButtonTracker()
        editor, _client, send_fn = _make_editor(button_tracker=bt)
        await editor.finalize("Choose [button:A] [button:B]")
        sent_text = send_fn.call_args[0][1]
        assert "[button:" not in sent_text
        assert "A" in sent_text
        assert "B" in sent_text

    async def test_whitespace_only_buffer_not_sent(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.on_delta("   ")
        await editor.finalize(None)
        send_fn.assert_not_awaited()


class TestFullFlow:
    """Integration-style tests simulating a complete streaming session."""

    async def test_multi_segment_streaming(self) -> None:
        editor, client, send_fn = _make_editor()

        # First reasoning segment
        await editor.on_delta("Reasoning about the problem...")
        await editor.on_tool("SearchTool")

        # Second reasoning segment
        await editor.on_delta("Found relevant information...")
        await editor.on_system("thinking")

        # Final answer
        await editor.on_delta("Here is the answer.")
        await editor.finalize(None)

        assert send_fn.await_count == 3
        calls = send_fn.call_args_list
        assert calls[0][0] == ("!room:test", "Reasoning about the problem...")
        assert calls[1][0] == ("!room:test", "Found relevant information...")
        assert calls[2][0] == ("!room:test", "Here is the answer.")

        # Typing indicator re-set after each segment flush (tool + system)
        assert client.room_typing.await_count == 2

    async def test_no_deltas_uses_result_text(self) -> None:
        editor, _client, send_fn = _make_editor()
        await editor.finalize("Direct result from orchestrator")
        send_fn.assert_awaited_once_with("!room:test", "Direct result from orchestrator")

    async def test_typing_error_suppressed(self) -> None:
        editor, client, send_fn = _make_editor()
        client.room_typing.side_effect = RuntimeError("connection lost")
        await editor.on_delta("text")
        # Should not raise despite typing error.
        await editor.on_tool("Tool")
        send_fn.assert_awaited_once()
