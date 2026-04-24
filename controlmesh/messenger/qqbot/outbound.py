"""Outbound helpers aligned with the Tencent qqbot module split."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Literal

from controlmesh.orchestrator.selectors.models import ButtonGrid

_INTERNAL_MARKER_RE = re.compile(r"\[\[[a-z_]+:\s*[^\]]*\]\]", re.IGNORECASE)
_INTERNAL_MEDIA_REF_RE = re.compile(r"@(?:image|voice|video|file):[a-zA-Z0-9_.-]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")
_MESSAGE_REPLY_LIMIT = 4
_MESSAGE_REPLY_TTL_SECONDS = 60 * 60
_MESSAGE_REPLY_TRACKER: dict[str, tuple[int, float]] = {}


@dataclass(frozen=True, slots=True)
class QQBotReplyModeDecision:
    """Decision for whether one send should stay passive or fall back to proactive."""

    msg_id: str | None
    fallback_to_proactive: bool = False
    fallback_reason: Literal["expired", "limit_exceeded"] | None = None


def sanitize_outbound_text(text: str) -> str:
    """Remove framework-internal markers before qqbot user-visible sends.

    Mirrors the upstream `utils/text-parsing.ts` `filterInternalMarkers()` seam:
    - strips `[[reply_to: ...]]`-style internal markers
    - strips `@image:` / `@voice:` / `@video:` / `@file:` framework references
    - collapses excessive blank lines after removal
    """
    if not text:
        return text

    cleaned = _INTERNAL_MARKER_RE.sub("", text)
    cleaned = _INTERNAL_MEDIA_REF_RE.sub("", cleaned)
    cleaned = _EXCESS_NEWLINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def choose_reply_mode(
    target_type: str,
    reply_to_message_id: str | None,
    *,
    now: float | None = None,
) -> QQBotReplyModeDecision:
    """Choose passive vs proactive reply mode for one outbound qqbot send.

    Mirrors the upstream outbound reply-window seam for `c2c/group`:
    - passive replies are limited to 4 sends per `msg_id`
    - passive replies expire after 1 hour
    - once the window is exhausted, the send falls back to proactive mode

    Channel and DM targets keep the original `msg_id` because this CM-direct slice
    does not claim an honest proactive fallback there.
    """
    if not reply_to_message_id:
        return QQBotReplyModeDecision(msg_id=None)
    if target_type not in {"c2c", "group"}:
        return QQBotReplyModeDecision(msg_id=reply_to_message_id)

    current_time = time.time() if now is None else now
    _cleanup_reply_tracker(current_time)
    record = _MESSAGE_REPLY_TRACKER.get(reply_to_message_id)
    if record is None:
        return QQBotReplyModeDecision(msg_id=reply_to_message_id)

    count, first_reply_at = record
    if current_time - first_reply_at > _MESSAGE_REPLY_TTL_SECONDS:
        return QQBotReplyModeDecision(
            msg_id=None,
            fallback_to_proactive=True,
            fallback_reason="expired",
        )
    if count >= _MESSAGE_REPLY_LIMIT:
        return QQBotReplyModeDecision(
            msg_id=None,
            fallback_to_proactive=True,
            fallback_reason="limit_exceeded",
        )
    return QQBotReplyModeDecision(msg_id=reply_to_message_id)


def record_passive_reply(
    target_type: str,
    reply_to_message_id: str | None,
    *,
    now: float | None = None,
) -> None:
    """Record one passive reply send for `c2c/group` qqbot targets."""
    if not reply_to_message_id or target_type not in {"c2c", "group"}:
        return

    current_time = time.time() if now is None else now
    _cleanup_reply_tracker(current_time)
    record = _MESSAGE_REPLY_TRACKER.get(reply_to_message_id)
    if record is None:
        _MESSAGE_REPLY_TRACKER[reply_to_message_id] = (1, current_time)
        return

    count, first_reply_at = record
    if current_time - first_reply_at > _MESSAGE_REPLY_TTL_SECONDS:
        _MESSAGE_REPLY_TRACKER[reply_to_message_id] = (1, current_time)
        return
    _MESSAGE_REPLY_TRACKER[reply_to_message_id] = (count + 1, first_reply_at)


def reset_reply_tracker() -> None:
    """Clear in-memory qqbot passive-reply tracking state for tests."""
    _MESSAGE_REPLY_TRACKER.clear()


def _cleanup_reply_tracker(current_time: float) -> None:
    if len(_MESSAGE_REPLY_TRACKER) <= 10_000:
        return
    expired = [
        message_id
        for message_id, (_, first_reply_at) in _MESSAGE_REPLY_TRACKER.items()
        if current_time - first_reply_at > _MESSAGE_REPLY_TTL_SECONDS
    ]
    for message_id in expired:
        _MESSAGE_REPLY_TRACKER.pop(message_id, None)


def button_grid_to_inline_keyboard(buttons: ButtonGrid) -> dict[str, object] | None:
    """Convert a generic ControlMesh ``ButtonGrid`` to a QQ inline keyboard."""
    if not buttons.rows:
        return None

    rows: list[dict[str, object]] = []
    button_index = 0
    for row_index, row in enumerate(buttons.rows):
        qq_buttons: list[dict[str, object]] = []
        for button in row:
            qq_buttons.append(
                {
                    "id": f"cm-btn-{button_index}",
                    "render_data": {
                        "label": button.text,
                        "visited_label": button.text,
                        "style": 1,
                    },
                    "action": {
                        "type": 1,
                        "data": button.callback_data,
                        "permission": {"type": 0},
                        "click_limit": 1,
                    },
                    "group_id": f"cm-row-{row_index}",
                }
            )
            button_index += 1
        if qq_buttons:
            rows.append({"buttons": qq_buttons})

    if not rows:
        return None
    return {"content": {"rows": rows}}
