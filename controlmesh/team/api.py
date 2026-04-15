"""Read-only JSON envelope API for additive team state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from controlmesh.team.contracts import (
    TEAM_API_OPERATIONS,
    TEAM_API_WRITE_OPERATIONS,
    TEAM_EVENT_TYPES,
)
from controlmesh.team.live import TeamLiveDispatcher
from controlmesh.team.models import TeamDispatchResult
from controlmesh.team.state import TeamStateStore
from controlmesh.team.state.snapshot import TeamControlSnapshotManager
from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths


class _NoopTeamBus:
    async def submit(self, envelope: object) -> None:
        msg = "dispatch submission is not available through the team API"
        raise RuntimeError(msg)


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


def _require_request_object(request: object) -> dict[str, object]:
    if not isinstance(request, dict):
        msg = "request must be an object"
        raise TypeError(msg)
    return request


def _require_request_id(request: dict[str, object]) -> str:
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        msg = "request_id is required"
        raise ValueError(msg)
    return request_id.strip()


def _validated_dispatch_result(request: dict[str, object]) -> TeamDispatchResult:
    result = request.get("result")
    if not isinstance(result, dict):
        msg = "result is required"
        raise TypeError(msg)
    return TeamDispatchResult.model_validate(result)


def _optional_bool(request: dict[str, object], field_name: str) -> bool | None:
    value = request.get(field_name)
    if value is None:
        return None
    if not isinstance(value, bool):
        msg = f"{field_name} must be a boolean when provided"
        raise TypeError(msg)
    return value


def resolve_team_state_root(
    state_root: Path | str | None = None,
    *,
    paths: ControlMeshPaths | None = None,
) -> Path:
    """Resolve the canonical team state root for runtime/CLI callers."""
    if state_root is not None:
        return Path(state_root)
    resolved_paths = paths or resolve_paths()
    return resolved_paths.team_state_dir


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


def _read_snapshot_response(
    request: dict[str, object],
    *,
    team_name: str,
    state_root: Path | str | None = None,
    paths: ControlMeshPaths | None = None,
) -> dict[str, Any]:
    resolved_paths = paths or resolve_paths()
    refresh = _optional_bool(request, "refresh") or False
    max_age_seconds = _int_or_none(request.get("max_age_seconds"), "max_age_seconds")
    manager = TeamControlSnapshotManager(
        resolved_paths,
        state_root=resolve_team_state_root(state_root, paths=resolved_paths),
    )
    if max_age_seconds is None:
        snapshot = manager.write(team_name) if refresh else manager.read(team_name)
        return _success("read-snapshot", {"snapshot": snapshot.model_dump(mode="json")})

    if refresh:
        manager.write(team_name)
    status = manager.read_status(team_name, max_age_seconds=max_age_seconds)
    return _success(
        "read-snapshot",
        {
            "snapshot": status.snapshot.model_dump(mode="json"),
            "stale": status.stale,
        },
    )


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


def _record_dispatch_result_response(
    store: TeamStateStore,
    request: dict[str, object],
) -> dict[str, Any]:
    dispatcher = TeamLiveDispatcher(store, _NoopTeamBus())
    updated = dispatcher.record_dispatch_result(
        _require_request_id(request),
        _validated_dispatch_result(request),
    )
    return _success(
        "record-dispatch-result",
        {"dispatch_request": updated.model_dump(mode="json")},
    )


def _execute_known_team_api_operation(
    operation: str,
    request_data: dict[str, object],
    *,
    state_root: Path | str | None = None,
    paths: ControlMeshPaths | None = None,
) -> dict[str, Any]:
    team_name = _require_team_name(request_data)
    store = TeamStateStore(resolve_team_state_root(state_root, paths=paths), team_name, create=False)
    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "read-manifest": lambda: _read_manifest_response(store),
        "list-tasks": lambda: _list_tasks_response(store, request_data),
        "get-summary": lambda: _get_summary_response(store),
        "read-snapshot": lambda: _read_snapshot_response(
            request_data,
            team_name=team_name,
            state_root=state_root,
            paths=paths,
        ),
        "read-events": lambda: _read_events_response(store, request_data),
        "record-dispatch-result": lambda: _record_dispatch_result_response(store, request_data),
    }
    handler = handlers.get(operation)
    if handler is None:
        return _error(operation, "internal_error", f"unhandled operation '{operation}'")
    return handler()


def execute_team_api_operation(
    operation: str,
    request: dict[str, object] | None,
    *,
    state_root: Path | str | None = None,
    allow_writes: bool = False,
    paths: ControlMeshPaths | None = None,
) -> dict[str, Any]:
    """Execute a narrow team API operation against persisted state."""
    if operation not in TEAM_API_OPERATIONS:
        return _error("unknown", "unknown_operation", f"unsupported operation '{operation}'")
    if operation in TEAM_API_WRITE_OPERATIONS and not allow_writes:
        return _error(
            operation,
            "operation_not_allowed",
            f"operation '{operation}' requires internal write access",
        )

    try:
        request_data = _require_request_object(request or {})
        return _execute_known_team_api_operation(
            operation,
            request_data,
            state_root=state_root,
            paths=paths,
        )
    except FileNotFoundError as exc:
        return _error(operation, "not_found", str(exc))
    except (TypeError, ValidationError, ValueError) as exc:
        return _error(operation, "invalid_request", str(exc))
    except Exception as exc:  # pragma: no cover - defensive envelope
        return _error(operation, "internal_error", str(exc))
