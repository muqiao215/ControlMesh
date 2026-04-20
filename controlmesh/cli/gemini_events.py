"""NDJSON parser for the Google Gemini CLI.

Translates Gemini-specific events into normalized StreamEvents.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from controlmesh.cli.stream_events import (
    AssistantTextDelta,
    ResultEvent,
    StreamEvent,
    SystemInitEvent,
    ToolResultEvent,
    ToolUseEvent,
)

logger = logging.getLogger(__name__)

_StreamParser = Callable[[dict[str, Any]], list[StreamEvent]]


def parse_gemini_stream_line(line: str) -> list[StreamEvent]:
    """Parse a single NDJSON line from Gemini CLI into normalized stream events."""
    stripped = line.strip()
    if not stripped:
        return []

    try:
        data: dict[str, Any] = json.loads(stripped)
    except json.JSONDecodeError:
        logger.debug("Gemini: unparseable stream line: %.200s", stripped)
        return []

    parser = _STREAM_PARSERS.get(data.get("type", ""))
    return parser(data) if parser else []


def parse_gemini_json(raw: str) -> str:
    """Extract result text from Gemini CLI JSON batch output (non-streaming).

    Handles both dict (single result) and list (array of events) formats.
    """
    if not raw:
        return ""
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:2000]

    if isinstance(parsed, dict):
        return extract_result_text(parsed)

    if isinstance(parsed, list):
        texts = [extract_result_text(item) for item in parsed if isinstance(item, dict)]
        return "\n\n".join(text for text in texts if text)

    return ""


def _parse_gemini_message(data: dict[str, Any]) -> list[StreamEvent]:
    """Parse Gemini's flat message structure."""
    role = data.get("role")
    content = data.get("content")
    if role not in ("assistant", "model") or not content:
        return []

    if isinstance(content, str):
        return [AssistantTextDelta(type="assistant", text=content)]

    if isinstance(content, list):
        events: list[StreamEvent] = []
        for block in content:
            events.extend(_parse_message_content_block(block))
        return events

    return []


def _parse_gemini_result(data: dict[str, Any]) -> ResultEvent:
    """Extract metrics and final output from Gemini's result event."""
    stats = data.get("stats", {})
    if not isinstance(stats, dict):
        stats = {}

    usage = {
        "input_tokens": stats.get("input_tokens", 0),
        "output_tokens": stats.get("output_tokens", 0),
        "cached_tokens": stats.get("cached_tokens", stats.get("cached", 0)),
    }

    is_error = bool(data.get("is_error")) or data.get("status") == "error"
    res = extract_result_text(data)

    if not res and is_error:
        err = data.get("error")
        if isinstance(err, dict):
            res = extract_text(err, ("message", "error", "detail"))
        elif err is not None:
            res = str(err)

    return ResultEvent(
        type="result",
        session_id=data.get("session_id"),
        result=res or "",
        is_error=is_error,
        duration_ms=stats.get("duration_ms"),
        usage=usage,
    )


def _parse_gemini_init(data: dict[str, Any]) -> list[StreamEvent]:
    return [
        SystemInitEvent(
            type="system",
            subtype="init",
            session_id=data.get("session_id"),
        ),
    ]


def _parse_gemini_tool_use(data: dict[str, Any]) -> list[StreamEvent]:
    return [
        ToolUseEvent(
            type="assistant",
            tool_name=str(data.get("tool_name") or data.get("name") or ""),
            tool_id=_as_optional_str(data.get("tool_id") or data.get("id")),
            parameters=_as_dict(data.get("parameters") or data.get("input")),
        ),
    ]


def _parse_gemini_tool_result(data: dict[str, Any]) -> list[StreamEvent]:
    return [
        ToolResultEvent(
            type="tool_result",
            tool_id=str(data.get("tool_id", "")),
            tool_name=str(data.get("tool_name") or data.get("name") or ""),
            status=str(data.get("status", "")),
            output=str(data.get("output", "")),
        ),
    ]


def _parse_gemini_result_event(data: dict[str, Any]) -> list[StreamEvent]:
    return [_parse_gemini_result(data)]


def _parse_gemini_error(data: dict[str, Any]) -> list[StreamEvent]:
    return [
        ResultEvent(
            type="result",
            result=extract_text(data, ("message", "error", "detail")) or "Unknown Gemini error",
            is_error=True,
        ),
    ]


def _parse_message_content_block(block: Any) -> list[StreamEvent]:
    if not isinstance(block, dict):
        return []

    block_type = block.get("type")
    if block_type == "text":
        return [AssistantTextDelta(type="assistant", text=str(block.get("text", "")))]
    if block_type == "tool_use":
        return [
            ToolUseEvent(
                type="assistant",
                tool_name=str(block.get("name", "")),
                tool_id=_as_optional_str(block.get("id")),
                parameters=_as_dict(block.get("input")),
            ),
        ]
    return []


def extract_result_text(data: dict[str, Any]) -> str:
    return extract_text(data, ("result", "response", "content", "output"))


def extract_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        return value if isinstance(value, str) else str(value)
    return ""


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


_STREAM_PARSERS: dict[str, _StreamParser] = {
    "init": _parse_gemini_init,
    "message": _parse_gemini_message,
    "tool_use": _parse_gemini_tool_use,
    "tool_result": _parse_gemini_tool_result,
    "result": _parse_gemini_result_event,
    "error": _parse_gemini_error,
}
