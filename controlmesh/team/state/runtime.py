"""Worker runtime state primitives."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.models import TeamWorkerRuntimeState
from controlmesh.team.state.base import TeamStatePaths, utc_now

_ALLOWED_RUNTIME_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"starting", "stopped", "lost"}),
    "starting": frozenset({"ready", "unhealthy", "stopped", "lost"}),
    "ready": frozenset({"busy", "unhealthy", "stopped", "lost"}),
    "busy": frozenset({"ready", "unhealthy", "stopped", "lost"}),
    "unhealthy": frozenset({"ready", "busy", "stopped", "lost"}),
    "stopped": frozenset({"starting"}),
    "lost": frozenset({"starting", "stopped"}),
}
_LIVE_RUNTIME_STATUSES = frozenset({"starting", "ready", "busy", "unhealthy"})
_HEALTHY_RUNTIME_STATUSES = frozenset({"starting", "ready", "busy"})
UNSET_RUNTIME_FIELD: object = object()


def _runtimes_dir(paths: TeamStatePaths) -> Path:
    return paths.team_dir / "worker-runtimes"


def _runtime_entity_path(paths: TeamStatePaths, worker: str) -> Path:
    return _runtimes_dir(paths) / f"{worker}.json"


def _load_aggregate(paths: TeamStatePaths) -> list[TeamWorkerRuntimeState]:
    raw = load_json(paths.worker_runtimes_path) or {"worker_runtimes": []}
    items = raw.get("worker_runtimes", [])
    if not isinstance(items, list):
        return []
    return [TeamWorkerRuntimeState.model_validate(item) for item in items]


def _load_entities(paths: TeamStatePaths) -> list[TeamWorkerRuntimeState]:
    entity_dir = _runtimes_dir(paths)
    if not entity_dir.exists():
        return []
    runtimes: list[TeamWorkerRuntimeState] = []
    for path in sorted(entity_dir.glob("*.json")):
        raw = load_json(path)
        if raw is None:
            continue
        runtimes.append(TeamWorkerRuntimeState.model_validate(raw))
    return runtimes


def _load(paths: TeamStatePaths) -> list[TeamWorkerRuntimeState]:
    merged: dict[str, TeamWorkerRuntimeState] = {runtime.worker: runtime for runtime in _load_aggregate(paths)}
    for runtime in _load_entities(paths):
        merged[runtime.worker] = runtime
    return list(merged.values())


def _save_snapshot(paths: TeamStatePaths, runtimes: list[TeamWorkerRuntimeState]) -> None:
    atomic_json_save(
        paths.worker_runtimes_path,
        {"worker_runtimes": [runtime.model_dump(mode="json") for runtime in runtimes]},
    )


def _save_entity(paths: TeamStatePaths, runtime: TeamWorkerRuntimeState) -> None:
    entity_dir = _runtimes_dir(paths)
    entity_dir.mkdir(parents=True, exist_ok=True)
    atomic_json_save(_runtime_entity_path(paths, runtime.worker), runtime.model_dump(mode="json"))


def _save(paths: TeamStatePaths, runtimes: list[TeamWorkerRuntimeState]) -> None:
    for runtime in runtimes:
        _save_entity(paths, runtime)
    _save_snapshot(paths, runtimes)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def list_worker_runtimes(
    paths: TeamStatePaths,
    *,
    status: str | None = None,
) -> list[TeamWorkerRuntimeState]:
    """List persisted worker runtime state records."""
    items = _load(paths)
    if status is not None:
        items = [item for item in items if item.status == status]
    return items


def get_worker_runtime(paths: TeamStatePaths, worker: str) -> TeamWorkerRuntimeState:
    """Read a persisted worker runtime by worker name."""
    for runtime in _load(paths):
        if runtime.worker == worker:
            return runtime
    msg = f"worker runtime '{worker}' not found"
    raise FileNotFoundError(msg)


def put_worker_runtime(paths: TeamStatePaths, runtime: TeamWorkerRuntimeState) -> TeamWorkerRuntimeState:
    """Insert or replace a worker runtime using per-worker entity files plus a compatibility snapshot."""
    existing = next((item for item in _load(paths) if item.worker == runtime.worker), None)
    if (
        existing is not None
        and runtime.updated_at is not None
        and existing.updated_at is not None
        and _parse_timestamp(runtime.updated_at) < _parse_timestamp(existing.updated_at)
    ):
        msg = f"stale worker runtime update for '{runtime.worker}'"
        raise ValueError(msg)

    now = utc_now()
    persisted = runtime.model_copy(update={"created_at": runtime.created_at or now, "updated_at": now})
    runtimes = _load(paths)
    for index, existing in enumerate(runtimes):
        if existing.worker == runtime.worker:
            persisted = persisted.model_copy(update={"created_at": existing.created_at or persisted.created_at})
            runtimes[index] = persisted
            _save(paths, runtimes)
            return persisted
    runtimes.append(persisted)
    _save(paths, runtimes)
    return persisted


def transition_worker_runtime(
    paths: TeamStatePaths,
    worker: str,
    to_status: str,
    *,
    updates: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> TeamWorkerRuntimeState:
    """Advance a worker runtime through the strict lifecycle."""
    runtimes = _load(paths)
    now_value = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    now_iso = now_value.isoformat()
    for index, runtime in enumerate(runtimes):
        if runtime.worker != worker:
            continue
        _ensure_allowed_transition(runtime.status, to_status)
        update = _build_transition_update(runtime, to_status, updates=updates, now_iso=now_iso)
        runtimes[index] = runtime.model_copy(update=update)
        _save(paths, runtimes)
        return runtimes[index]
    msg = f"worker runtime '{worker}' not found"
    raise FileNotFoundError(msg)


def record_worker_runtime_heartbeat(
    paths: TeamStatePaths,
    worker: str,
    *,
    lease_id: str,
    heartbeat_at: str,
    lease_expires_at: str | None = None,
) -> TeamWorkerRuntimeState:
    """Persist a heartbeat and optional lease renewal for a live worker runtime."""
    runtimes = _load(paths)
    now_iso = utc_now()
    for index, runtime in enumerate(runtimes):
        if runtime.worker != worker:
            continue
        if runtime.status not in _LIVE_RUNTIME_STATUSES:
            msg = f"worker runtime '{worker}' is not live while {runtime.status}"
            raise ValueError(msg)
        if runtime.lease_id != lease_id:
            msg = f"worker runtime '{worker}' is owned by lease '{runtime.lease_id}'"
            raise ValueError(msg)
        update: dict[str, str] = {"heartbeat_at": heartbeat_at, "updated_at": now_iso}
        if lease_expires_at is not None:
            update["lease_expires_at"] = lease_expires_at
        runtimes[index] = runtime.model_copy(update=update)
        _save(paths, runtimes)
        return runtimes[index]
    msg = f"worker runtime '{worker}' not found"
    raise FileNotFoundError(msg)


def classify_worker_runtime(
    runtime: TeamWorkerRuntimeState,
    *,
    now: datetime | None = None,
) -> TeamWorkerRuntimeState:
    """Classify runtime recovery state from persisted lease and heartbeat facts."""
    if runtime.status in {"created", "stopped", "lost"}:
        return runtime
    if runtime.lease_id is None or runtime.lease_expires_at is None:
        return runtime.model_copy(
            update={
                "status": "lost",
                "health_reason": "runtime lease missing",
                "dispatch_request_id": None,
            }
        )
    at = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    if _parse_timestamp(runtime.lease_expires_at) <= at:
        return runtime.model_copy(
            update={
                "status": "lost",
                "health_reason": "runtime lease expired",
                "dispatch_request_id": None,
            }
        )
    return runtime


def reconcile_worker_runtime(
    paths: TeamStatePaths,
    worker: str,
    *,
    now: datetime | None = None,
) -> TeamWorkerRuntimeState:
    """Reconcile a single worker runtime from persisted facts only."""
    runtimes = _load(paths)
    now_value = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    for index, runtime in enumerate(runtimes):
        if runtime.worker != worker:
            continue
        reconciled = classify_worker_runtime(runtime, now=now_value)
        if reconciled == runtime:
            return runtime
        runtimes[index] = reconciled.model_copy(update={"updated_at": now_value.isoformat()})
        _save(paths, runtimes)
        return runtimes[index]
    msg = f"worker runtime '{worker}' not found"
    raise FileNotFoundError(msg)


def reconcile_worker_runtimes(
    paths: TeamStatePaths,
    *,
    now: datetime | None = None,
) -> list[TeamWorkerRuntimeState]:
    """Reconcile all persisted worker runtimes from lease/heartbeat facts only."""
    runtimes = _load(paths)
    if not runtimes:
        return []
    now_value = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    changed = False
    reconciled: list[TeamWorkerRuntimeState] = []
    for runtime in runtimes:
        classified = classify_worker_runtime(runtime, now=now_value)
        if classified != runtime:
            classified = classified.model_copy(update={"updated_at": now_value.isoformat()})
            changed = True
        reconciled.append(classified)
    if changed:
        _save(paths, reconciled)
    return reconciled


def _ensure_allowed_transition(current_status: str, to_status: str) -> None:
    if to_status not in _ALLOWED_RUNTIME_TRANSITIONS.get(current_status, frozenset()):
        msg = f"invalid worker runtime transition: {current_status} -> {to_status}"
        raise ValueError(msg)


def _build_transition_update(
    runtime: TeamWorkerRuntimeState,
    to_status: str,
    *,
    updates: Mapping[str, object] | None,
    now_iso: str,
) -> dict[str, object]:
    update: dict[str, object] = {
        "status": to_status,
        "updated_at": now_iso,
        **{
            field_name: value
            for field_name, value in (updates or {}).items()
            if value is not UNSET_RUNTIME_FIELD
        },
    }
    if to_status in _LIVE_RUNTIME_STATUSES:
        update["started_at"] = runtime.started_at or now_iso
        update["stopped_at"] = None
    if to_status in _HEALTHY_RUNTIME_STATUSES:
        update["health_reason"] = None
    if to_status == "ready":
        update["execution_id"] = None
        update["dispatch_request_id"] = None
    if to_status == "stopped":
        update["attachment_type"] = None
        update["attachment_name"] = None
        update["attachment_transport"] = None
        update["attachment_chat_id"] = None
        update["attachment_session_id"] = None
        update["attached_at"] = None
        update["execution_id"] = None
        update["dispatch_request_id"] = None
        update["lease_id"] = None
        update["lease_expires_at"] = None
        update["heartbeat_at"] = None
        update["health_reason"] = None
        update["stopped_at"] = now_iso
    return update
