"""Task state primitives for additive team coordination."""

from __future__ import annotations

from datetime import UTC, datetime

from ductor_bot.infra.json_store import atomic_json_save, load_json
from ductor_bot.team.contracts import CLAIMABLE_TEAM_TASK_STATUSES
from ductor_bot.team.models import TeamTask, TeamTaskClaim
from ductor_bot.team.state.base import TeamStatePaths, utc_now


def _load(paths: TeamStatePaths) -> list[TeamTask]:
    raw = load_json(paths.tasks_path) or {"tasks": []}
    tasks = raw.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    return [TeamTask.model_validate(item) for item in tasks]


def _save(paths: TeamStatePaths, tasks: list[TeamTask]) -> None:
    atomic_json_save(
        paths.tasks_path,
        {"tasks": [task.model_dump(mode="json") for task in tasks]},
    )


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
    """Insert or replace a task."""
    now = utc_now()
    persisted = task.model_copy(
        update={
            "created_at": task.created_at or now,
            "updated_at": now,
            "completed_at": now if task.status == "completed" and task.completed_at is None else task.completed_at,
        }
    )
    tasks = _load(paths)
    replaced = False
    for index, existing in enumerate(tasks):
        if existing.task_id == task.task_id:
            tasks[index] = persisted
            replaced = True
            break
    if not replaced:
        tasks.append(persisted)
    _save(paths, tasks)
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
