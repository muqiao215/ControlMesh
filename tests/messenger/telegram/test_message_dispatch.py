"""Tests for Telegram message dispatch output modes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from aiogram.types import Chat, Message, User

from controlmesh.cli.stream_events import ToolResultEvent, ToolUseEvent
from controlmesh.config import StreamingConfig
from controlmesh.messenger.telegram.message_dispatch import (
    StreamingDispatch,
    run_non_streaming_message,
    run_streaming_message,
)
from controlmesh.session.key import SessionKey


def _make_message(*, chat_id: int = 1, message_id: int = 10) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = chat_id
    type(msg).message_id = PropertyMock(return_value=message_id)
    msg.answer = AsyncMock(return_value=msg)
    msg.from_user = MagicMock(spec=User)
    return msg


def _make_dispatch(*, output_mode: str, tool_display: str = "name") -> tuple[StreamingDispatch, MagicMock]:
    message = _make_message()
    orchestrator = MagicMock()
    dispatch = StreamingDispatch(
        bot=MagicMock(),
        orchestrator=orchestrator,
        message=message,
        key=SessionKey(chat_id=1),
        text="hello",
        streaming_cfg=StreamingConfig(
            output_mode=output_mode,
            tool_display=tool_display,
            min_chars=1,
            idle_ms=1,
        ),
        allowed_roots=None,
    )
    return dispatch, orchestrator


@pytest.mark.asyncio
async def test_non_streaming_long_reply_stays_full_without_auto_attachment() -> None:
    message = _make_message()
    orchestrator = MagicMock()
    orchestrator.handle_message = AsyncMock(
        return_value=SimpleNamespace(
            text=("line\n" * 80).strip(),
            metadata={},
            model_name=None,
        )
    )
    orchestrator.paths.output_to_user_dir = MagicMock()
    dispatch = SimpleNamespace(
        bot=MagicMock(),
        orchestrator=orchestrator,
        reply_to=message,
        key=SessionKey(chat_id=1),
        text="hello",
        allowed_roots=None,
        thread_id=None,
        scene_config=None,
    )

    with patch(
        "controlmesh.messenger.telegram.message_dispatch.send_rich", new_callable=AsyncMock
    ) as mock_send:
        await run_non_streaming_message(dispatch)

    orchestrator.handle_message.assert_awaited_once_with(
        SessionKey(chat_id=1),
        "hello",
        message_id=10,
    )
    delivered = mock_send.await_args.args[2]
    assert "Output trimmed for chat view" not in delivered
    assert "<file:" not in delivered
    assert delivered.count("line") == 80


@pytest.mark.asyncio
async def test_streaming_full_mode_shows_tools_and_system_status() -> None:
    dispatch, orchestrator = _make_dispatch(output_mode="full")
    editor = SimpleNamespace(
        append_text=AsyncMock(),
        append_tool=AsyncMock(),
        append_system=AsyncMock(),
        finalize=AsyncMock(),
        has_content=True,
    )

    async def _fake_stream(
        key: SessionKey,
        text: str,
        *,
        on_text_delta: AsyncMock | None,
        on_tool_activity: AsyncMock | None,
        on_system_status: AsyncMock | None,
        **_kwargs: object,
    ) -> SimpleNamespace:
        assert key == SessionKey(chat_id=1)
        assert text == "hello"
        assert on_text_delta is not None
        assert on_tool_activity is not None
        assert on_system_status is not None
        await on_text_delta("stream body")
        await on_tool_activity("Bash")
        await on_system_status("thinking")
        return SimpleNamespace(text="stream body", stream_fallback=False, model_name=None)

    orchestrator.handle_message_streaming = AsyncMock(side_effect=_fake_stream)

    with (
        patch(
            "controlmesh.messenger.telegram.message_dispatch.create_stream_editor",
            return_value=editor,
        ),
        patch(
            "controlmesh.messenger.telegram.message_dispatch.send_files_from_text",
            new_callable=AsyncMock,
        ) as mock_send_files,
        patch(
            "controlmesh.messenger.telegram.message_dispatch.send_rich", new_callable=AsyncMock
        ) as mock_send_rich,
    ):
        result = await run_streaming_message(dispatch)

    assert result == "stream body"
    assert orchestrator.handle_message_streaming.await_args.kwargs["message_id"] == 10
    editor.append_text.assert_awaited()
    editor.append_tool.assert_awaited_once_with("Bash")
    editor.append_system.assert_awaited_once_with("THINKING")
    mock_send_files.assert_awaited_once()
    mock_send_rich.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_tools_mode_hides_system_status() -> None:
    dispatch, orchestrator = _make_dispatch(output_mode="tools")
    editor = SimpleNamespace(
        append_text=AsyncMock(),
        append_tool=AsyncMock(),
        append_system=AsyncMock(),
        finalize=AsyncMock(),
        has_content=True,
    )

    async def _fake_stream(
        _key: SessionKey,
        _text: str,
        *,
        on_text_delta: AsyncMock | None,
        on_tool_activity: AsyncMock | None,
        on_system_status: AsyncMock | None,
        **_kwargs: object,
    ) -> SimpleNamespace:
        assert on_text_delta is not None
        assert on_tool_activity is not None
        assert on_system_status is None
        await on_text_delta("stream body")
        await on_tool_activity("Bash")
        return SimpleNamespace(text="stream body", stream_fallback=False, model_name=None)

    orchestrator.handle_message_streaming = AsyncMock(side_effect=_fake_stream)

    with (
        patch(
            "controlmesh.messenger.telegram.message_dispatch.create_stream_editor",
            return_value=editor,
        ),
        patch(
            "controlmesh.messenger.telegram.message_dispatch.send_files_from_text",
            new_callable=AsyncMock,
        ),
    ):
        await run_streaming_message(dispatch)

    editor.append_tool.assert_awaited_once_with("Bash")
    editor.append_system.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_conversation_mode_hides_tools_and_system_status() -> None:
    dispatch, orchestrator = _make_dispatch(output_mode="conversation")
    editor = SimpleNamespace(
        append_text=AsyncMock(),
        append_tool=AsyncMock(),
        append_system=AsyncMock(),
        finalize=AsyncMock(),
        has_content=True,
    )

    async def _fake_stream(
        _key: SessionKey,
        _text: str,
        *,
        on_text_delta: AsyncMock | None,
        on_tool_activity: AsyncMock | None,
        on_system_status: AsyncMock | None,
        **_kwargs: object,
    ) -> SimpleNamespace:
        assert on_text_delta is not None
        assert on_tool_activity is None
        assert on_system_status is None
        await on_text_delta("stream body")
        return SimpleNamespace(text="stream body", stream_fallback=False, model_name=None)

    orchestrator.handle_message_streaming = AsyncMock(side_effect=_fake_stream)

    with (
        patch(
            "controlmesh.messenger.telegram.message_dispatch.create_stream_editor",
            return_value=editor,
        ),
        patch(
            "controlmesh.messenger.telegram.message_dispatch.send_files_from_text",
            new_callable=AsyncMock,
        ),
    ):
        await run_streaming_message(dispatch)

    editor.append_text.assert_awaited()
    editor.append_tool.assert_not_awaited()
    editor.append_system.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_tool_details_mode_renders_command_and_output() -> None:
    dispatch, orchestrator = _make_dispatch(output_mode="tools", tool_display="details")
    editor = SimpleNamespace(
        append_text=AsyncMock(),
        append_tool=AsyncMock(),
        append_system=AsyncMock(),
        finalize=AsyncMock(),
        has_content=True,
    )

    async def _fake_stream(
        _key: SessionKey,
        _text: str,
        *,
        on_text_delta: AsyncMock | None,
        on_tool_activity: AsyncMock | None,
        on_system_status: AsyncMock | None,
        on_tool_event: AsyncMock | None = None,
        **_kwargs: object,
    ) -> SimpleNamespace:
        assert on_text_delta is not None
        assert on_tool_activity is None
        assert on_system_status is None
        assert on_tool_event is not None
        await on_tool_event(
            ToolUseEvent(
                type="assistant",
                tool_name="Bash",
                parameters={"command": "printf hi"},
            )
        )
        await on_tool_event(
            ToolResultEvent(
                type="tool_result",
                tool_id="tool-1",
                tool_name="Bash",
                status="exit 0",
                output="hi",
            )
        )
        return SimpleNamespace(text="done", stream_fallback=False, model_name=None)

    orchestrator.handle_message_streaming = AsyncMock(side_effect=_fake_stream)

    with (
        patch(
            "controlmesh.messenger.telegram.message_dispatch.create_stream_editor",
            return_value=editor,
        ),
        patch(
            "controlmesh.messenger.telegram.message_dispatch.send_files_from_text",
            new_callable=AsyncMock,
        ),
    ):
        await run_streaming_message(dispatch)

    rendered = "".join(call.args[0] for call in editor.append_text.await_args_list)
    assert "printf hi" in rendered
    assert "hi" in rendered
    editor.append_tool.assert_not_awaited()
