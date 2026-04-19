"""Feishu CardKit streaming progress cards."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

_SYSTEM_LABELS: dict[str, str] = {
    "thinking": "处理中...",
    "compacting": "整理上下文后继续...",
    "recovering": "恢复会话后继续...",
    "timeout_warning": "处理时间较长, 继续执行中...",
    "timeout_extended": "已延长处理时间, 继续执行中...",
}

_STATUS_LABELS: dict[str, str] = {
    "running": "running",
    "success": "success",
    "error": "error",
}

_KIT_SUCCESS_STATES = {"completed", "success", "succeeded"}
_KIT_ERROR_STATES = {"error", "failed", "failure"}


@dataclass(slots=True)
class _ToolStep:
    name: str
    status: str


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
    status: str = "running",
    tool_steps: tuple[_ToolStep, ...] = (),
) -> dict[str, object]:
    """Render a CardKit streaming card shell."""
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": _render_streaming_content(
                body=body,
                status=status,
                tool_steps=tool_steps,
            ),
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


def render_feishu_streaming_card_from_single_card_run(
    run: Mapping[str, Any],
    *,
    title: str = "ControlMesh",
    note: str | None = "feishu-auth-kit cardkit",
) -> dict[str, object]:
    """Render a ControlMesh card from feishu-auth-kit SingleCardRun.to_dict()."""
    return render_feishu_streaming_card(
        title=title,
        body=_single_card_run_body(run),
        note=note,
        status=_kit_status_to_stream_status(run.get("status")),
        tool_steps=tuple(_tool_steps_from_single_card_run(run)),
    )


def tool_step_from_auth_kit_agent_event(event: Mapping[str, Any]) -> _ToolStep | None:
    """Convert feishu-auth-kit AgentEvent.to_dict() into a CM stream tool step."""
    kind = str(event.get("kind") or "")
    if kind == "tool_call":
        return _ToolStep(
            name=str(event.get("tool_name") or "unknown"),
            status="running",
        )
    if kind == "tool_result":
        return _ToolStep(
            name=str(event.get("tool_name") or "unknown"),
            status=_kit_status_to_tool_status(event.get("state")),
        )
    return None


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
        self._status = "running"
        self._tool_steps: list[_ToolStep] = []

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
        self._mark_tool_running(tool_name)
        await self._set_body(f"[TOOL: {tool_name}]")

    async def on_agent_event(self, event: Mapping[str, Any]) -> None:
        """Consume a feishu-auth-kit AgentEvent-compatible payload."""
        step = tool_step_from_auth_kit_agent_event(event)
        if step is not None:
            self._append_or_update_tool_step(step)
            if step.status == "running" and not self._saw_text_delta:
                await self._set_body(f"[TOOL: {step.name}]")
            return
        kind = str(event.get("kind") or "")
        text = event.get("text")
        if kind == "assistant_message" and isinstance(text, str) and text:
            await self.on_text_delta(text)
            return
        if kind in {"running", "start", "status"} and isinstance(text, str) and text:
            await self._set_body(text)

    async def finish_with_single_card_run(self, run: Mapping[str, Any]) -> None:
        """Finalize from a feishu-auth-kit SingleCardRun-compatible payload."""
        self._status = _kit_status_to_stream_status(run.get("status"))
        self._tool_steps = _tool_steps_from_single_card_run(run)
        await self._finalize(_single_card_run_body(run) or "_No output._")

    async def on_system(self, status: str | None) -> None:
        if self._saw_text_delta:
            return
        label = _SYSTEM_LABELS.get(status or "")
        if label:
            await self._set_body(label)

    async def finish_success(self, text: str) -> None:
        self._status = "success"
        self._mark_running_tool("success")
        final_text = merge_streaming_text(self._body, text or "")
        await self._finalize(final_text or "_No output._")

    async def finish_failure(self, error_text: str) -> None:
        self._status = "error"
        self._mark_running_tool("error")
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
                status=self._status,
                tool_steps=tuple(self._tool_steps),
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
                _render_streaming_content(
                    body=merged,
                    status=self._status,
                    tool_steps=tuple(self._tool_steps),
                ),
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
        async with self._message_lock:
            if self._card_id is None:
                return
            self._sequence += 1
            self._body = final_text
            await self._bot._update_streaming_card_content(
                self._card_id,
                _render_streaming_content(
                    body=final_text,
                    status=self._status,
                    tool_steps=tuple(self._tool_steps),
                ),
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

    def _mark_tool_running(self, tool_name: str) -> None:
        self._mark_running_tool("success")
        self._tool_steps.append(_ToolStep(name=tool_name, status="running"))

    def _mark_running_tool(self, status: str) -> None:
        for index in range(len(self._tool_steps) - 1, -1, -1):
            if self._tool_steps[index].status == "running":
                self._tool_steps[index] = _ToolStep(
                    name=self._tool_steps[index].name,
                    status=status,
                )
                return

    def _append_or_update_tool_step(self, step: _ToolStep) -> None:
        if step.status == "running":
            self._mark_tool_running(step.name)
            return
        for index in range(len(self._tool_steps) - 1, -1, -1):
            if self._tool_steps[index].name == step.name:
                self._tool_steps[index] = step
                return
        self._tool_steps.append(step)


def _render_streaming_content(
    *,
    body: str,
    status: str,
    tool_steps: tuple[_ToolStep, ...],
) -> str:
    del status, tool_steps
    return body or "处理中..."


def _single_card_run_body(run: Mapping[str, Any]) -> str:
    final_text = run.get("final_text")
    if isinstance(final_text, str) and final_text.strip():
        return final_text.strip()
    summary = run.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return ""


def _tool_steps_from_single_card_run(run: Mapping[str, Any]) -> list[_ToolStep]:
    raw_steps = run.get("steps")
    if not isinstance(raw_steps, list):
        return []
    steps: list[_ToolStep] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, Mapping):
            continue
        title = raw_step.get("title")
        name = title if isinstance(title, str) and title.strip() else raw_step.get("kind")
        if not isinstance(name, str) or not name.strip():
            continue
        steps.append(
            _ToolStep(
                name=name.strip(),
                status=_kit_status_to_tool_status(raw_step.get("status")),
            )
        )
    return steps


def _kit_status_to_stream_status(value: object) -> str:
    status = str(value or "").lower()
    if status in _KIT_ERROR_STATES:
        return "error"
    if status in _KIT_SUCCESS_STATES:
        return "success"
    return "running"


def _kit_status_to_tool_status(value: object) -> str:
    status = str(value or "").lower()
    if status in _KIT_ERROR_STATES:
        return "error"
    if status in _KIT_SUCCESS_STATES:
        return "success"
    return "running"
