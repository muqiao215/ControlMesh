"""Helpers for rendering provider output into safe user-visible text."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


_EVENT_TYPE_PREFIXES = ("item.", "turn.", "thread.", "response.", "message.", "session.")
_EVENT_TYPE_EXACT = frozenset({"assistant", "result", "system", "event"})


@dataclass(frozen=True, slots=True)
class PresentedOutput:
    """Normalized presentation decision for one provider output payload."""

    text: str
    is_internal_event_payload: bool = False

    @property
    def is_metadata_only(self) -> bool:
        """Return True when the payload was internal-only and had no visible text."""
        return self.is_internal_event_payload and not self.text.strip()


def normalize_user_visible_output(text: str) -> PresentedOutput:
    """Return a safe user-visible rendering for one provider output blob."""
    stripped = text.strip()
    if not stripped:
        return PresentedOutput(text=text)

    events = _parse_internal_event_lines(stripped)
    if events is None:
        return PresentedOutput(text=text)

    visible_parts: list[str] = []
    for data in events:
        visible_parts.extend(_extract_visible_text_fragments(data))
    visible_text = "\n".join(part for part in visible_parts if part.strip()).strip()
    return PresentedOutput(text=visible_text, is_internal_event_payload=True)


def _parse_internal_event_lines(text: str) -> list[dict[str, Any]] | None:
    """Parse *text* as an internal event payload when every line matches the shape."""
    parsed: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or not _looks_like_internal_event(data):
            return None
        parsed.append(data)
    return parsed or None


def _looks_like_internal_event(data: dict[str, Any]) -> bool:
    """Return True when *data* resembles a structured internal event."""
    event_type = str(data.get("type") or "")
    if event_type.startswith(_EVENT_TYPE_PREFIXES):
        return True
    if event_type in _EVENT_TYPE_EXACT and any(
        key in data for key in ("item", "message", "content", "session_id", "result", "subtype")
    ):
        return True
    return isinstance(data.get("item"), dict) or isinstance(data.get("message"), dict)


def _extract_visible_text_fragments(data: dict[str, Any]) -> list[str]:
    """Extract any assistant-visible text fragments from one event object."""
    parts: list[str] = []

    event_type = str(data.get("type") or "")
    if event_type == "result":
        result_text = _as_str(data.get("result"))
        if result_text:
            parts.append(result_text)

    item = data.get("item")
    if isinstance(item, dict) and str(item.get("type") or "") == "agent_message":
        item_text = _as_str(item.get("text"))
        if item_text:
            parts.append(item_text)
        parts.extend(_extract_text_blocks(item.get("content")))

    message = data.get("message")
    if isinstance(message, dict):
        parts.extend(_extract_text_blocks(message.get("content")))

    if str(data.get("role") or "") == "assistant":
        parts.extend(_extract_text_blocks(data.get("content")))

    if event_type == "assistant":
        assistant_text = _as_str(data.get("text"))
        if assistant_text:
            parts.append(assistant_text)

    return parts


def _extract_text_blocks(raw_blocks: Any) -> list[str]:
    """Extract ``text`` values from content block arrays."""
    if not isinstance(raw_blocks, list):
        return []
    parts: list[str] = []
    for block in raw_blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") != "text":
            continue
        block_text = _as_str(block.get("text"))
        if block_text:
            parts.append(block_text)
    return parts


def _as_str(value: Any) -> str:
    """Return a stripped string when *value* is a non-empty string."""
    return value.strip() if isinstance(value, str) else ""
