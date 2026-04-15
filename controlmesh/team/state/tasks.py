"""Task state primitives for additive team coordination."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.contracts import CLAIMABLE_TEAM_TASK_STATUSES
from controlmesh.team.models import TeamTask, TeamTaskClaim
from controlmesh.team.state.base import TeamStatePaths, utc_now


def _tasks_dir(paths: TeamStatePaths) -> Path:
    return paths.team_dir / "tasks"


def _task_entity_path(paths: TeamStatePaths, task_id: str) -> Path:
    return _tasks_dir(paths) / f"{task_id}.json"


def _load_aggregate(paths: TeamStatePaths) -> list[TeamTask]:
    raw = load_json(paths.tasks_path) or {"tasks": []}
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    return [TeamTask.model_validate(item) for item in tasks]


def _load_entities(paths: TeamStatePaths) -> list[TeamTask]:
    entity_dir = _tasks_dir(paths)
    if not entity_dir.exists():
        return []
    tasks: list[TeamTask] = []
    for path in sorted(entity_dir.glob("*.json")):
        raw = load_json(path)
        if raw is None:
            continue
        tasks.append(TeamTask.model_validate(raw))
    return tasks


def _load(paths: TeamStatePaths) -> list[TeamTask]:
    merged: dict[str, TeamTask] = {task.task_id: task for task in _load_aggregate(paths)}
    for task in _load_entities(paths):
        merged[task.task_id] = task
    return list(merged.values())


def _save_snapshot(paths: TeamStatePaths, tasks: list[TeamTask]) -> None:
    atomic_json_save(
        paths.tasks_path,
        {"tasks": [task.model_dump(mode="json") for task in tasks]},
    )


def _save_entity(paths: TeamStatePaths, task: TeamTask) -> None:
    entity_dir = _tasks_dir(paths)
    entity_dir.mkdir(parents=True, exist_ok=True)
    atomic_json_save(_task_entity_path(paths, task.task_id), task.model_dump(mode="json"))


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def list_tasks(
    paths: TeamStatePaths,
    *,
    status: str | None = None,
    owner: str | None = None,
) -> list[TeamTask]:
    """List tasks with optional filters."""
    items = _load(paths)
    if status is not None:
        items = [task for task in items if task.status == status]
    if owner is not None:
        items = [task for task in items if task.owner == owner]
    return items


def upsert_task(paths: TeamStatePaths, task: TeamTask) -> TeamTask:
    """Insert or replace a task using per-task entity files plus a compatibility snapshot."""
    existing = next((item for item in _load(paths) if item.task_id == task.task_id), None)
    if (
        existing is not None
        and task.updated_at is not None
        and existing.updated_at is not None
        and _parse_timestamp(task.updated_at) < _parse_timestamp(existing.updated_at)
    ):
        msg = f"stale task update for '{task.task_id}'"
        raise ValueError(msg)

    now = utc_now()
    completed_at = task.completed_at
    if task.status == "completed" and completed_at is None:
        completed_at = now
    if task.status != "completed":
        completed_at = None
    persisted = task.model_copy(
        update={
            "created_at": task.created_at or now,
            "updated_at": now,
            "completed_at": completed_at,
        }
    )
    if existing is not None:
        persisted = persisted.model_copy(update={"created_at": existing.created_at or persisted.created_at})

    tasks = _load(paths)
    replaced = False
    for index, existing in enumerate(tasks):
        if existing.task_id == task.task_id:
            tasks[index] = persisted
            replaced = True
            break
    if not replaced:
        tasks.append(persisted)
    _save_entity(paths, persisted)
    _save_snapshot(paths, tasks)
    return persisted


def get_task(paths: TeamStatePaths, task_id: str) -> TeamTask:
    """Read a task by ID."""
    for task in _load(paths):
        if task.task_id == task_id:
            return task
    msg = f"task '{task_id}' not found"
    raise FileNotFoundError(msg)


def _claim_is_active(claim: TeamTaskClaim, *, now: datetime) -> bool:
    expires = datetime.fromisoformat(claim.lease_expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires > now.astimezone(UTC)


def claim_task(
    paths: TeamStatePaths,
    task_id: str,
    claim: TeamTaskClaim,
    *,
    now: datetime | None = None,
) -> TeamTask:
    """Lease a task claim, replacing expired claims only."""
    at = now or datetime.now(UTC)
    task = get_task(paths, task_id)
    if task.status not in CLAIMABLE_TEAM_TASK_STATUSES:
        msg = f"task '{task_id}' is not claimable while {task.status}"
        raise ValueError(msg)
    if task.claim and _claim_is_active(task.claim, now=at) and task.claim.token != claim.token:
        msg = f"task '{task_id}' is already claimed by {task.claim.worker}"
        raise ValueError(msg)
    claimed = task.model_copy(
        update={
            "claim": claim,
            "owner": claim.worker,
            "updated_at": utc_now(),
        }
    )
    return upsert_task(paths, claimed)


def release_task_claim(paths: TeamStatePaths, task_id: str) -> TeamTask:
    """Release any active claim for a task."""
    task = get_task(paths, task_id)
    released = task.model_copy(update={"claim": None, "updated_at": utc_now()})
    return upsert_task(paths, released)


def update_task_status(paths: TeamStatePaths, task_id: str, status: str) -> TeamTask:
    """Persist a status change for an existing task."""
    task = get_task(paths, task_id)
    updated = task.model_copy(update={"status": status})
    return upsert_task(paths, updated)
