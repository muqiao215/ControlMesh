"""Normalize OpenAI Agents SDK streaming items into ControlMesh stream events."""

from __future__ import annotations

import json
from typing import Any

from controlmesh.cli.stream_events import (
    AssistantTextDelta,
    StreamEvent,
    SystemStatusEvent,
    ToolResultEvent,
    ToolUseEvent,
)

_STATUS_EVENT_NAMES: dict[str, str] = {
    "handoff_requested": "handoff_requested",
    "handoff_occured": "handoff_accepted",
    "handoff_occurred": "handoff_accepted",
    "guardrail_tripped": "guardrail_blocked",
    "guardrail_blocked": "guardrail_blocked",
}


def sdk_event_to_stream_events(event: Any) -> list[StreamEvent]:
    """Convert one SDK stream event into zero or more normalized stream events."""
    event_type = _string_field(event, "type")
    if event_type == "raw_response_event":
        return _raw_response_to_stream_events(_field(event, "data"))
    if event_type == "run_item_stream_event":
        return _run_item_to_stream_events(event)
    return []


def tool_output_to_status_events(tool_name: str, output: Any) -> list[StreamEvent]:
    """Emit bounded system statuses from known ControlMesh-owned tool envelopes only."""
    payload = _tool_output_payload(output)
    if not payload:
        return []

    operation = str(payload.get("operation") or tool_name or "")
    if operation == "create_background_task" and payload.get("ok") is True:
        return [
            SystemStatusEvent(
                type="system",
                subtype="status",
                status="background_task_created",
            )
        ]

    if operation == "send_async_to_agent" and payload.get("ok") is True:
        return [SystemStatusEvent(type="system", subtype="status", status="async_agent_task_created")]

    return []


def _raw_response_to_stream_events(data: Any) -> list[StreamEvent]:
    raw_type = _string_field(data, "type")
    if "output_text.delta" not in raw_type:
        return []
    delta = _string_field(data, "delta")
    if not delta:
        return []
    return [AssistantTextDelta(type="assistant", text=delta)]


def _run_item_to_stream_events(event: Any) -> list[StreamEvent]:
    name = _string_field(event, "name").lower()
    item = _field(event, "item")
    item_type = _string_field(item, "type").lower()

    if name == "tool_called" or item_type == "tool_call_item":
        tool_name = _tool_name(item)
        if tool_name:
            return [ToolUseEvent(type="assistant", tool_name=tool_name, tool_id=_optional_string(item, "id"))]
        return []

    if name == "tool_output" or item_type == "tool_call_output_item":
        tool_name = _tool_name(item)
        output = _field(item, "output")
        events: list[StreamEvent] = [
            ToolResultEvent(
                type="tool_result",
                tool_id=_string_field(item, "id"),
                tool_name=tool_name,
                status=_tool_result_status(output),
                output=_stringify_output(output),
            )
        ]
        events.extend(tool_output_to_status_events(tool_name, output))
        return events

    status_name = _STATUS_EVENT_NAMES.get(name)
    if status_name:
        return [SystemStatusEvent(type="system", subtype="status", status=status_name)]

    if "guardrail" in name:
        return [SystemStatusEvent(type="system", subtype="status", status="guardrail_blocked")]

    return []


def _tool_name(item: Any) -> str:
    return (
        _string_field(item, "name")
        or _string_field(_field(item, "raw_item"), "name")
        or _string_field(_field(item, "tool"), "name")
        or _optional_string(item, "tool_name")
        or _string_field(_tool_output_payload(_field(item, "output")), "operation")
        or ""
    )


def _tool_result_status(output: Any) -> str:
    payload = _tool_output_payload(output)
    if payload:
        return "success" if payload.get("ok") is True else "error"
    return "completed"


def _tool_output_payload(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        parsed = model_dump(mode="json")
        return parsed if isinstance(parsed, dict) else {}
    if hasattr(output, "__dict__"):
        return dict(vars(output))
    return {}


def _stringify_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        return json.dumps(output, ensure_ascii=True, sort_keys=True)
    return str(output)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _string_field(value: Any, name: str) -> str:
    field = _field(value, name)
    if field is None:
        return ""
    return str(field)


def _optional_string(value: Any, name: str) -> str | None:
    field = _field(value, name)
    if field in (None, ""):
        return None
    return str(field)
