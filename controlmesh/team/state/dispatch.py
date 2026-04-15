"""Dispatch request state primitives."""

from __future__ import annotations

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.contracts import (
    validate_dispatch_request_creation,
    validate_dispatch_transition_metadata,
)
from controlmesh.team.models import TeamDispatchRequest, TeamDispatchResult
from controlmesh.team.state.base import TeamStatePaths, utc_now

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"notified", "delivered", "failed", "cancelled"}),
    "notified": frozenset({"delivered", "failed", "cancelled"}),
    "delivered": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def _load(paths: TeamStatePaths) -> list[TeamDispatchRequest]:
    raw = load_json(paths.dispatch_path) or {"dispatch_requests": []}
    items = raw.get("dispatch_requests", [])
    if not isinstance(items, list):
        return []
    return [TeamDispatchRequest.model_validate(item) for item in items]


def _save(paths: TeamStatePaths, requests: list[TeamDispatchRequest]) -> None:
    atomic_json_save(
        paths.dispatch_path,
        {"dispatch_requests": [item.model_dump(mode="json") for item in requests]},
    )


def list_dispatch_requests(paths: TeamStatePaths, *, status: str | None = None) -> list[TeamDispatchRequest]:
    """List dispatch requests with an optional status filter."""
    items = _load(paths)
    if status is not None:
        items = [item for item in items if item.status == status]
    return items


def create_dispatch_request(paths: TeamStatePaths, request: TeamDispatchRequest) -> TeamDispatchRequest:
    """Create a new dispatch request."""
    validate_dispatch_request_creation(request)
    requests = _load(paths)
    if any(existing.request_id == request.request_id for existing in requests):
        msg = f"dispatch request '{request.request_id}' already exists"
        raise ValueError(msg)
    now = utc_now()
    persisted = request.model_copy(update={"created_at": request.created_at or now, "updated_at": now})
    requests.append(persisted)
    _save(paths, requests)
    return persisted


def get_dispatch_request(paths: TeamStatePaths, request_id: str) -> TeamDispatchRequest:
    """Read a dispatch request by ID."""
    for item in _load(paths):
        if item.request_id == request_id:
            return item
    msg = f"dispatch request '{request_id}' not found"
    raise FileNotFoundError(msg)


def transition_dispatch_request(
    paths: TeamStatePaths,
    request_id: str,
    to_status: str,
    *,
    error: str | None = None,
    metadata: dict[str, str | None] | None = None,
) -> TeamDispatchRequest:
    """Advance a dispatch request through its state-only lifecycle."""
    validate_dispatch_transition_metadata(metadata)
    requests = _load(paths)
    for index, item in enumerate(requests):
        if item.request_id != request_id:
            continue
        if to_status not in _ALLOWED_TRANSITIONS.get(item.status, frozenset()):
            msg = f"invalid dispatch transition: {item.status} -> {to_status}"
            raise ValueError(msg)
        now = utc_now()
        update: dict[str, str | None] = {"status": to_status, "updated_at": now}
        if metadata is not None:
            update.update(metadata)
        if to_status == "notified":
            update["notified_at"] = now
        if to_status == "delivered":
            update["delivered_at"] = now
            update["notified_at"] = item.notified_at or now
        if to_status == "failed":
            update["failed_at"] = now
            update["last_error"] = error
        requests[index] = item.model_copy(update=update)
        _save(paths, requests)
        return requests[index]
    msg = f"dispatch request '{request_id}' not found"
    raise FileNotFoundError(msg)


def record_dispatch_result(
    paths: TeamStatePaths,
    request_id: str,
    result: TeamDispatchResult,
) -> TeamDispatchRequest:
    """Record the latest worker-reported result for a delivered dispatch."""
    requests = _load(paths)
    for index, item in enumerate(requests):
        if item.request_id != request_id:
            continue
        if item.status != "delivered":
            msg = f"dispatch request '{request_id}' must be delivered before recording a result"
            raise ValueError(msg)
        now = utc_now()
        persisted_result = result.model_copy(update={"reported_at": result.reported_at or now})
        requests[index] = item.model_copy(update={"result": persisted_result, "updated_at": now})
        _save(paths, requests)
        return requests[index]
    msg = f"dispatch request '{request_id}' not found"
    raise FileNotFoundError(msg)
