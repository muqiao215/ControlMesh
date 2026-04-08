"""Read-only JSON envelope API for additive team state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ductor_bot.team.contracts import TEAM_API_OPERATIONS, TEAM_EVENT_TYPES
from ductor_bot.team.state import TeamStateStore


def _success(operation: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": operation,
        "data": data,
    }


def _error(operation: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": False,
        "operation": operation,
        "error": {"code": code, "message": message},
    }


def _require_team_name(request: dict[str, object]) -> str:
    team_name = request.get("team_name")
    if not isinstance(team_name, str) or not team_name.strip():
        msg = "team_name is required"
        raise ValueError(msg)
    return team_name.strip()


def _int_or_none(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        msg = f"{field_name} must be a non-negative integer when provided"
        raise ValueError(msg)
    return value


def _optional_str(request: dict[str, object], field_name: str) -> str | None:
    value = request.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string when provided"
        raise TypeError(msg)
    return value


def _validated_event_type(request: dict[str, object]) -> str | None:
    event_type = _optional_str(request, "event_type")
    if event_type is None:
        return None
    if event_type not in TEAM_EVENT_TYPES:
        msg = f"event_type must be one of: {', '.join(TEAM_EVENT_TYPES)}"
        raise ValueError(msg)
    return event_type


def _read_manifest_response(store: TeamStateStore) -> dict[str, Any]:
    manifest = store.read_manifest()
    return _success("read-manifest", {"manifest": manifest.model_dump(mode="json")})


def _list_tasks_response(store: TeamStateStore, request: dict[str, object]) -> dict[str, Any]:
    tasks = store.list_tasks(
        status=_optional_str(request, "status"),
        owner=_optional_str(request, "owner"),
    )
    return _success(
        "list-tasks",
        {
            "count": len(tasks),
            "tasks": [task.model_dump(mode="json") for task in tasks],
        },
    )


def _get_summary_response(store: TeamStateStore) -> dict[str, Any]:
    return _success("get-summary", {"summary": store.build_summary()})


def _read_events_response(store: TeamStateStore, request: dict[str, object]) -> dict[str, Any]:
    after_event_id = _optional_str(request, "after_event_id")
    worker = _optional_str(request, "worker")
    task_id = _optional_str(request, "task_id")
    event_type = _validated_event_type(request)
    limit = _int_or_none(request.get("limit"), "limit")
    events = store.read_events(
        after_event_id=after_event_id,
        event_type=event_type,
        worker=worker,
        task_id=task_id,
        limit=limit,
    )
    return _success(
        "read-events",
        {
            "count": len(events),
            "cursor": events[-1].event_id if events else after_event_id,
            "events": [event.model_dump(mode="json") for event in events],
        },
    )


def execute_team_api_operation(
    operation: str,
    request: dict[str, object] | None,
    *,
    state_root: Path | str,
) -> dict[str, Any]:
    """Execute a read-only team API operation against persisted state."""
    if operation not in TEAM_API_OPERATIONS:
        return _error("unknown", "unknown_operation", f"unsupported operation '{operation}'")

    request_data = request or {}

    try:
        team_name = _require_team_name(request_data)
        store = TeamStateStore(Path(state_root), team_name, create=False)
        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "read-manifest": lambda: _read_manifest_response(store),
            "list-tasks": lambda: _list_tasks_response(store, request_data),
            "get-summary": lambda: _get_summary_response(store),
            "read-events": lambda: _read_events_response(store, request_data),
        }
        handler = handlers.get(operation)
        if handler is None:
            return _error(operation, "internal_error", f"unhandled operation '{operation}'")
        return handler()

    except FileNotFoundError as exc:
        return _error(operation, "not_found", str(exc))
    except (TypeError, ValidationError, ValueError) as exc:
        return _error(operation, "invalid_request", str(exc))
    except Exception as exc:  # pragma: no cover - defensive envelope
        return _error(operation, "internal_error", str(exc))
