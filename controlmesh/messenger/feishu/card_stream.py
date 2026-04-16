"""Feishu CardKit streaming progress cards."""

from __future__ import annotations

import asyncio
from typing import Protocol

_SYSTEM_LABELS: dict[str, str] = {
    "thinking": "处理中...",
    "compacting": "整理上下文后继续...",
    "recovering": "恢复会话后继续...",
    "timeout_warning": "处理时间较长, 继续执行中...",
    "timeout_extended": "已延长处理时间, 继续执行中...",
}


class _FeishuCardStreamTransport(Protocol):
    async def _create_streaming_card(self, card: dict[str, object]) -> str | None: ...

    async def _send_card_to_chat_ref(
        self,
        chat_ref: str,
        content: dict[str, object],
        *,
        reply_to_message_id: str | None = None,
    ) -> str | None: ...

    async def _update_streaming_card_content(
        self,
        card_id: str,
        content: str,
        *,
        sequence: int,
        uuid: str,
    ) -> None: ...

    async def _close_streaming_card(
        self,
        card_id: str,
        *,
        summary: str,
        sequence: int,
        uuid: str,
    ) -> None: ...


def merge_streaming_text(previous_text: str | None, next_text: str | None) -> str:
    """Merge snapshot or delta text updates without losing overlapping chunks."""
    previous = previous_text or ""
    next_value = next_text or ""
    if not next_value:
        merged = previous
    elif not previous or next_value == previous or next_value.startswith(previous):
        merged = next_value
    elif previous.startswith(next_value) or next_value in previous:
        merged = previous
    elif previous in next_value:
        merged = next_value
    else:
        max_overlap = min(len(previous), len(next_value))
        merged = f"{previous}{next_value}"
        for overlap in range(max_overlap, 0, -1):
            if previous[-overlap:] == next_value[:overlap]:
                merged = f"{previous}{next_value[overlap:]}"
                break
    return merged


def render_feishu_streaming_card(
    *,
    title: str,
    body: str,
    note: str | None = None,
) -> dict[str, object]:
    """Render a CardKit streaming card shell."""
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": body or "处理中...",
            "element_id": "content",
        }
    ]
    if note:
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"<font color='grey'>{note}</font>",
                    "element_id": "note",
                },
            ]
        )
    return {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "config": {
            "streaming_mode": True,
            "summary": {"content": "[Generating...]"},
            "streaming_config": {
                "print_frequency_ms": {"default": 50},
                "print_step": {"default": 1},
            },
        },
        "body": {"elements": elements},
    }


def _truncate_summary(text: str, max_chars: int = 50) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= max_chars:
        return clean
    return f"{clean[: max_chars - 3]}..."


class FeishuCardStreamReporter:
    """Drive a Feishu CardKit streaming card across the turn lifecycle."""

    def __init__(
        self,
        bot: _FeishuCardStreamTransport,
        *,
        chat_ref: str,
        reply_to_message_id: str | None,
        title: str,
        note: str | None = None,
    ) -> None:
        self._bot = bot
        self._chat_ref = chat_ref
        self._reply_to_message_id = reply_to_message_id
        self._title = title
        self._note = note
        self._card_id: str | None = None
        self._message_id: str | None = None
        self._body = ""
        self._sequence = 1
        self._message_lock = asyncio.Lock()
        self._start_task: asyncio.Task[None] | None = None
        self._stream_unavailable = False
        self._finalized = False
        self._saw_text_delta = False

    @property
    def handles_final_response(self) -> bool:
        return not self._stream_unavailable

    def start(self) -> None:
        self._start_task = asyncio.create_task(self._ensure_started("处理中..."))

    async def close(self) -> None:
        task = self._start_task
        if task is not None:
            await task

    async def on_text_delta(self, text: str) -> None:
        if not text:
            return
        self._saw_text_delta = True
        await self._set_body(merge_streaming_text(self._body, text))

    async def on_tool(self, tool_name: str) -> None:
        if not tool_name or self._saw_text_delta:
            return
        await self._set_body(f"[TOOL: {tool_name}]")

    async def on_system(self, status: str | None) -> None:
        if self._saw_text_delta:
            return
        label = _SYSTEM_LABELS.get(status or "")
        if label:
            await self._set_body(label)

    async def finish_success(self, text: str) -> None:
        final_text = merge_streaming_text(self._body, text or "")
        await self._finalize(final_text or "_No output._")

    async def finish_failure(self, error_text: str) -> None:
        await self._finalize(error_text or "处理失败")

    async def _ensure_started(self, initial_body: str) -> None:
        if self._stream_unavailable or self._card_id is not None:
            return
        async with self._message_lock:
            if self._stream_unavailable or self._card_id is not None:
                return
            card = render_feishu_streaming_card(
                title=self._title,
                body=initial_body,
                note=self._note,
            )
            card_id = await self._bot._create_streaming_card(card)
            if not card_id:
                self._stream_unavailable = True
                return
            message_id = await self._bot._send_card_to_chat_ref(
                self._chat_ref,
                {"type": "card", "data": {"card_id": card_id}},
                reply_to_message_id=self._reply_to_message_id,
            )
            if not message_id:
                self._stream_unavailable = True
                return
            self._card_id = card_id
            self._message_id = message_id

    async def _set_body(self, body: str) -> None:
        if self._stream_unavailable or self._finalized:
            return
        await self._ensure_started(body or "处理中...")
        if self._stream_unavailable or self._card_id is None:
            return
        merged = merge_streaming_text(self._body, body)
        if not merged or merged == self._body:
            return
        async with self._message_lock:
            if self._stream_unavailable or self._card_id is None:
                return
            if merged == self._body:
                return
            self._sequence += 1
            self._body = merged
            await self._bot._update_streaming_card_content(
                self._card_id,
                merged,
                sequence=self._sequence,
                uuid=f"s_{self._card_id}_{self._sequence}",
            )

    async def _finalize(self, text: str) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self._stream_unavailable:
            return
        await self._ensure_started(text or "处理中...")
        if self._stream_unavailable or self._card_id is None:
            return
        final_text = text or self._body or "_No output._"
        if final_text != self._body:
            async with self._message_lock:
                if self._card_id is None:
                    return
                self._sequence += 1
                self._body = final_text
                await self._bot._update_streaming_card_content(
                    self._card_id,
                    final_text,
                    sequence=self._sequence,
                    uuid=f"s_{self._card_id}_{self._sequence}",
                )
        self._sequence += 1
        await self._bot._close_streaming_card(
            self._card_id,
            summary=_truncate_summary(final_text),
            sequence=self._sequence,
            uuid=f"c_{self._card_id}_{self._sequence}",
        )
