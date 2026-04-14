"""Optional single-message Feishu streaming preview cards."""

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

_STATUS_TITLES: dict[str, str] = {
    "running": "处理中",
    "complete": "已完成",
    "failed": "处理失败",
}

_STATUS_TEMPLATES: dict[str, str] = {
    "running": "blue",
    "complete": "green",
    "failed": "red",
}


class _FeishuCardPreviewTransport(Protocol):
    async def _send_card_to_chat_ref(
        self,
        chat_ref: str,
        content: dict[str, object],
        *,
        reply_to_message_id: str | None = None,
    ) -> str | None: ...

    async def _patch_message(
        self,
        message_id: str,
        *,
        msg_type: str,
        content: dict[str, object],
    ) -> None: ...


class FeishuCardPreviewReporter:
    """Drive a single Feishu interactive card across the full turn lifecycle."""

    _bot: _FeishuCardPreviewTransport
    _chat_ref: str
    _reply_to_message_id: str | None
    _max_messages: int

    def __init__(
        self,
        bot: _FeishuCardPreviewTransport,
        *,
        chat_ref: str,
        reply_to_message_id: str | None,
        max_messages: int,
    ) -> None:
        self._bot = bot
        self._chat_ref = chat_ref
        self._reply_to_message_id = reply_to_message_id
        self._max_messages = max_messages
        self._message_id: str | None = None
        self._message_lock = asyncio.Lock()
        self._sent_labels: set[str] = set()
        self._progress_count = 0
        self._start_task: asyncio.Task[None] | None = None
        self._preview_unavailable = False

    @property
    def handles_final_response(self) -> bool:
        return not self._preview_unavailable

    def start(self) -> None:
        self._start_task = asyncio.create_task(self._emit_initial_preview())

    async def close(self) -> None:
        task = self._start_task
        if task is None:
            return
        await task

    async def on_tool(self, tool_name: str) -> None:
        if not tool_name:
            return
        await self._emit(f"[TOOL: {tool_name}]")

    async def on_system(self, status: str | None) -> None:
        if status is None:
            return
        label = _SYSTEM_LABELS.get(status)
        if label:
            await self._emit(label)

    async def finish_success(self, text: str) -> None:
        await self._set_body(text or "_No output._", status="complete")

    async def finish_failure(self, error_text: str) -> None:
        await self._set_body(error_text or "处理失败", status="failed")

    async def _emit_initial_preview(self) -> None:
        await self._emit("处理中...")

    async def _emit(self, label: str) -> None:
        if not label or label in self._sent_labels:
            return
        if self._progress_count >= self._max_messages:
            return
        self._sent_labels.add(label)
        self._progress_count += 1
        await self._set_body(label, status="running")

    async def _set_body(self, body: str, *, status: str) -> None:
        if self._preview_unavailable:
            return
        content = render_feishu_progress_card(status=status, body=body)
        async with self._message_lock:
            if self._preview_unavailable:
                return
            if not self._message_id:
                self._message_id = await self._bot._send_card_to_chat_ref(
                    self._chat_ref,
                    content,
                    reply_to_message_id=self._reply_to_message_id,
                )
                if self._message_id is None:
                    self._preview_unavailable = True
                return
            await self._bot._patch_message(
                self._message_id,
                msg_type="interactive",
                content=content,
            )


def render_feishu_progress_card(*, status: str, body: str) -> dict[str, object]:
    """Render a minimal interactive card for live preview/final state updates."""
    return {
        "config": {
            "wide_screen_mode": True,
            "enable_forward": True,
        },
        "header": {
            "template": _STATUS_TEMPLATES.get(status, "blue"),
            "title": {
                "tag": "plain_text",
                "content": _STATUS_TITLES.get(status, "处理中"),
            },
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": body or "_No output._",
                },
            }
        ],
    }
