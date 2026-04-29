"""Shared message execution flows for TelegramBot (streaming and non-streaming)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh.cli.coalescer import CoalesceConfig, StreamCoalescer
from controlmesh.cli.stream_events import ToolResultEvent, ToolUseEvent
from controlmesh.messenger.telegram.sender import (
    SendRichOpts,
    send_files_from_text,
    send_rich,
)
from controlmesh.messenger.telegram.streaming import create_stream_editor
from controlmesh.messenger.telegram.typing import TypingContext
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.session.key import SessionKey
from controlmesh.text.tool_event_format import format_tool_event_text

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

    from controlmesh.config import SceneConfig, StreamingConfig
    from controlmesh.orchestrator.core import Orchestrator

logger = logging.getLogger(__name__)

_TextStreamCallback = Callable[[str], Awaitable[None]]
_StatusStreamCallback = Callable[[str | None], Awaitable[None]]
_ToolEventStreamCallback = Callable[[ToolUseEvent | ToolResultEvent], Awaitable[None]]


def _stream_callbacks_for_mode(
    mode: str,
    *,
    on_text: _TextStreamCallback,
    on_tool: _TextStreamCallback | None,
    on_tool_event: _ToolEventStreamCallback | None,
    on_system: _StatusStreamCallback,
) -> tuple[
    _TextStreamCallback | None,
    _TextStreamCallback | None,
    _ToolEventStreamCallback | None,
    _StatusStreamCallback | None,
]:
    """Map Telegram streaming output mode to the enabled callbacks."""
    if mode == "full":
        return on_text, on_tool, on_tool_event, on_system
    if mode == "tools":
        return on_text, on_tool, on_tool_event, None
    if mode == "conversation":
        return on_text, None, None, None
    if mode == "off":
        return None, None, None, None
    return on_text, on_tool, on_tool_event, on_system


def _build_footer(result: OrchestratorResult, scene: SceneConfig | None) -> str:
    """Build technical footer string if enabled and metadata is available."""
    if scene is None or not scene.technical_footer or not result.model_name:
        return ""
    from controlmesh.text.response_format import format_technical_footer

    return format_technical_footer(
        result.model_name,
        result.total_tokens,
        result.input_tokens,
        result.cost_usd,
        result.duration_ms,
    )


@dataclass(slots=True)
class NonStreamingDispatch:
    """Input payload for one non-streaming message turn."""

    bot: Bot
    orchestrator: Orchestrator
    key: SessionKey
    text: str
    allowed_roots: list[Path] | None
    reply_to: Message | None = None
    thread_id: int | None = None
    scene_config: SceneConfig | None = None


@dataclass(slots=True)
class StreamingDispatch:
    """Input payload for one streaming message turn."""

    bot: Bot
    orchestrator: Orchestrator
    message: Message
    key: SessionKey
    text: str
    streaming_cfg: StreamingConfig
    allowed_roots: list[Path] | None
    thread_id: int | None = None
    scene_config: SceneConfig | None = None


async def run_non_streaming_message(
    dispatch: NonStreamingDispatch,
) -> str:
    """Execute one non-streaming turn and deliver the result to Telegram."""
    async with TypingContext(dispatch.bot, dispatch.key.chat_id, thread_id=dispatch.thread_id):
        result = await dispatch.orchestrator.handle_message(dispatch.key, dispatch.text)

    footer = _build_footer(result, dispatch.scene_config)
    result.text += footer
    deliver_text = result.text
    reply_id = dispatch.reply_to.message_id if dispatch.reply_to else None
    await send_rich(
        dispatch.bot,
        dispatch.key.chat_id,
        deliver_text,
        SendRichOpts(
            reply_to_message_id=reply_id,
            allowed_roots=dispatch.allowed_roots,
            thread_id=dispatch.thread_id,
        ),
    )
    return result.text


async def run_streaming_message(
    dispatch: StreamingDispatch,
) -> str:
    """Execute one streaming turn and deliver text/files to Telegram."""
    logger.info("Streaming flow started")

    editor = create_stream_editor(
        dispatch.bot,
        dispatch.key.chat_id,
        reply_to=dispatch.message,
        cfg=dispatch.streaming_cfg,
        thread_id=dispatch.thread_id,
    )
    coalescer = StreamCoalescer(
        config=CoalesceConfig(
            min_chars=dispatch.streaming_cfg.min_chars,
            max_chars=dispatch.streaming_cfg.max_chars,
            idle_ms=dispatch.streaming_cfg.idle_ms,
            sentence_break=dispatch.streaming_cfg.sentence_break,
        ),
        on_flush=editor.append_text,
    )

    async def on_text(delta: str) -> None:
        await coalescer.feed(delta)

    async def on_tool(tool_name: str) -> None:
        await coalescer.flush(force=True)
        await editor.append_tool(tool_name)

    async def on_system(status: str | None) -> None:
        system_map: dict[str, str] = {
            "thinking": "THINKING",
            "compacting": "COMPACTING",
            "recovering": "Please wait, recovering...",
            "timeout_warning": "TIMEOUT APPROACHING",
            "timeout_extended": "TIMEOUT EXTENDED",
            "background_task_created": "BACKGROUND TASK CREATED",
            "async_agent_task_created": "BACKGROUND AGENT TASK CREATED",
            "handoff_requested": "HANDOFF REQUESTED",
            "handoff_accepted": "HANDOFF ACCEPTED",
            "guardrail_blocked": "GUARDRAIL BLOCKED",
        }
        label = system_map.get(status or "")
        if label is None:
            return
        await coalescer.flush(force=True)
        await editor.append_system(label)

    async def on_tool_event(event: ToolUseEvent | ToolResultEvent) -> None:
        await coalescer.flush(force=True)
        await editor.append_text(format_tool_event_text(event))

    tool_cb_input: _TextStreamCallback | None = on_tool
    tool_event_input: _ToolEventStreamCallback | None = None
    if dispatch.streaming_cfg.tool_display == "details":
        tool_cb_input = None
        tool_event_input = on_tool_event

    text_cb, tool_cb, tool_event_cb, system_cb = _stream_callbacks_for_mode(
        dispatch.streaming_cfg.output_mode,
        on_text=on_text,
        on_tool=tool_cb_input,
        on_tool_event=tool_event_input,
        on_system=on_system,
    )

    async with TypingContext(dispatch.bot, dispatch.key.chat_id, thread_id=dispatch.thread_id):
        result = await dispatch.orchestrator.handle_message_streaming(
            dispatch.key,
            dispatch.text,
            on_text_delta=text_cb,
            on_tool_activity=tool_cb,
            on_tool_event=tool_event_cb,
            on_system_status=system_cb,
        )

    await coalescer.flush(force=True)
    coalescer.stop()
    footer = _build_footer(result, dispatch.scene_config)
    if footer:
        await editor.append_text(footer)
        result.text += footer
    deliver_text = result.text
    await editor.finalize(deliver_text)

    logger.info(
        "Streaming flow completed fallback=%s content=%s",
        result.stream_fallback,
        editor.has_content,
    )

    if result.stream_fallback or not editor.has_content:
        await send_rich(
            dispatch.bot,
            dispatch.key.chat_id,
            deliver_text,
            SendRichOpts(
                reply_to_message_id=dispatch.message.message_id,
                allowed_roots=dispatch.allowed_roots,
                thread_id=dispatch.thread_id,
            ),
        )
    else:
        await send_files_from_text(
            dispatch.bot,
            dispatch.key.chat_id,
            deliver_text,
            allowed_roots=dispatch.allowed_roots,
            thread_id=dispatch.thread_id,
        )

    return result.text
