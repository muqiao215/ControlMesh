"""Segment-based stream editor for Matrix.

Matrix cannot edit messages, so streaming works by sending each reasoning
segment as a separate message and then sending the final answer.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from controlmesh.text.response_format import normalize_tool_name

if TYPE_CHECKING:
    from nio import AsyncClient

    from controlmesh.messenger.matrix.buttons import ButtonTracker

logger = logging.getLogger(__name__)

# Maps system status codes to human-readable labels.
_SYSTEM_MAP: dict[str, str] = {
    "thinking": "THINKING",
    "compacting": "COMPACTING",
    "recovering": "Please wait, recovering...",
    "timeout_warning": "TIMEOUT APPROACHING",
    "timeout_extended": "TIMEOUT EXTENDED",
}


class MatrixStreamEditor:
    """Segment-based stream editor for Matrix.

    Matrix cannot edit messages, so streaming works by sending
    each reasoning segment as a separate message and then sending
    the final answer.
    """

    def __init__(
        self,
        client: AsyncClient,
        room_id: str,
        *,
        send_fn: Callable[[str, str], Awaitable[str | None]],
        button_tracker: ButtonTracker,
    ) -> None:
        self._client = client
        self._room_id = room_id
        self._send_fn = send_fn
        self._button_tracker = button_tracker
        self._buffer = ""
        self._segment_count = 0

    async def on_delta(self, delta: str) -> None:
        """Append text to the current segment buffer."""
        self._buffer += delta

    async def on_tool(self, tool_name: str) -> None:
        """Flush the buffer on tool activity and log the segment."""
        tool_name = normalize_tool_name(tool_name)
        self._segment_count += 1
        logger.info(
            "Matrix streaming: tool=%s segment=%d buf_len=%d",
            tool_name,
            self._segment_count,
            len(self._buffer.strip()),
        )
        await self._flush_and_tag(f"**[TOOL: {tool_name}]**")

    async def on_system(self, status: str | None) -> None:
        """Flush the buffer on system status change."""
        label = _SYSTEM_MAP.get(status or "")
        if label is None:
            return
        await self._flush_and_tag(f"*[{label}]*")

    async def finalize(self, result_text: str | None) -> None:
        """Send the final segment with button extraction."""
        final_text = (result_text or "").strip()
        logger.info(
            "Matrix streaming done: segments=%d final_buf_len=%d result_len=%d",
            self._segment_count,
            len(self._buffer.strip()),
            len(result_text) if result_text else 0,
        )
        if final_text:
            formatted = self._button_tracker.extract_and_format(self._room_id, final_text)
            await self._send_fn(self._room_id, formatted)
        else:
            buffered = self._buffer.strip()
            if not buffered:
                return
            formatted = self._button_tracker.extract_and_format(self._room_id, buffered)
            await self._send_fn(self._room_id, formatted)

    async def _flush_and_tag(self, _tag: str) -> None:
        """Flush buffer and re-set typing indicator.

        The *tag* (tool/system marker) is intentionally not sent to
        keep the Matrix chat clean -- only reasoning text and the
        final summary are visible to the user.
        """
        seg_text = self._buffer.strip()
        if seg_text:
            await self._send_fn(self._room_id, self._buffer)
        self._buffer = ""
        # Re-set typing indicator (sending messages clears it in Matrix)
        with contextlib.suppress(Exception):
            await self._client.room_typing(self._room_id, typing_state=True, timeout=30000)
