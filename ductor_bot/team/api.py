"""Read-only JSON envelope API for additive team state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ductor_bot.team.contracts import TEAM_API_OPERATIONS, TEAM_EVENT_TYPES
from ductor_bot.team.models import TeamManifest
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
        store = TeamStateStore(Path(state_root), team_name)

        if operation == "read-manifest":
            manifest = store.read_manifest()
            return _success(operation, {"manifest": manifest.model_dump(mode="json")})

        if operation == "list-tasks":
            status = request_data.get("status")
            owner = request_data.get("owner")
            if status is not None and not isinstance(status, str):
                raise ValueError("status must be a string when provided")
            if owner is not None and not isinstance(owner, str):
                raise ValueError("owner must be a string when provided")
            tasks = store.list_tasks(status=status, owner=owner)
            return _success(
                operation,
                {
                    "count": len(tasks),
                    "tasks": [task.model_dump(mode="json") for task in tasks],
                },
            )

        if operation == "get-summary":
            return _success(operation, {"summary": store.build_summary()})

        if operation == "read-events":
            after_event_id = request_data.get("after_event_id")
            worker = request_data.get("worker")
            task_id = request_data.get("task_id")
            event_type = request_data.get("event_type")
            limit = _int_or_none(request_data.get("limit"), "limit")
            if after_event_id is not None and not isinstance(after_event_id, str):
                raise ValueError("after_event_id must be a string when provided")
            if worker is not None and not isinstance(worker, str):
                raise ValueError("worker must be a string when provided")
            if task_id is not None and not isinstance(task_id, str):
                raise ValueError("task_id must be a string when provided")
            if event_type is not None:
                if not isinstance(event_type, str):
                    raise ValueError("event_type must be a string when provided")
                if event_type not in TEAM_EVENT_TYPES:
                    raise ValueError(f"event_type must be one of: {', '.join(TEAM_EVENT_TYPES)}")
            events = store.read_events(
                after_event_id=after_event_id,
                event_type=event_type,
                worker=worker,
                task_id=task_id,
                limit=limit,
            )
            return _success(
                operation,
                {
                    "count": len(events),
                    "cursor": events[-1].event_id if events else after_event_id,
                    "events": [event.model_dump(mode="json") for event in events],
                },
            )

    except FileNotFoundError as exc:
        return _error(operation, "not_found", str(exc))
    except (ValidationError, ValueError) as exc:
        return _error(operation, "invalid_request", str(exc))
    except Exception as exc:  # pragma: no cover - defensive envelope
        return _error(operation, "internal_error", str(exc))

    return _error(operation, "internal_error", f"unhandled operation '{operation}'")
