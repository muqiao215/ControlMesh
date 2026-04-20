"""Formatting helpers for streaming tool events."""

from __future__ import annotations

import json
from typing import Any

from controlmesh.cli.stream_events import ToolResultEvent, ToolUseEvent
from controlmesh.text.response_format import normalize_tool_name

_MAX_TOOL_OUTPUT_CHARS = 3000


def format_tool_event_text(event: ToolUseEvent | ToolResultEvent) -> str:
    """Render a tool event as readable markdown/plain text."""
    if isinstance(event, ToolUseEvent):
        return _format_tool_use(event)
    return _format_tool_result(event)


def _format_tool_use(event: ToolUseEvent) -> str:
    name = normalize_tool_name(event.tool_name)
    detail = _tool_use_detail(name, event.parameters)
    if not detail:
        return f"[TOOL: {name}]"
    return f"[TOOL: {name}]\n```text\n{detail}\n```"


def _format_tool_result(event: ToolResultEvent) -> str:
    name = normalize_tool_name(event.tool_name)
    status = (event.status or "").strip()
    header = f"[TOOL RESULT: {name}]"
    if status:
        header = f"{header} ({status})"
    output = _truncate_tool_output((event.output or "").rstrip())
    if not output:
        return header
    return f"{header}\n```text\n{output}\n```"


def _tool_use_detail(tool_name: str, parameters: dict[str, Any] | None) -> str:
    if not parameters:
        return ""
    if tool_name == "Bash":
        command = parameters.get("command")
        if isinstance(command, str) and command.strip():
            return command.strip()
    return json.dumps(parameters, ensure_ascii=False, indent=2, sort_keys=True)


def _truncate_tool_output(output: str) -> str:
    if len(output) <= _MAX_TOOL_OUTPUT_CHARS:
        return output
    return f"{output[:_MAX_TOOL_OUTPUT_CHARS].rstrip()}\n... [truncated]"
