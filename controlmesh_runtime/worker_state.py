"""Typed worker lifecycle state for the ControlMesh harness runtime."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from controlmesh_runtime.contracts import utc_now_iso


class WorkerStatus(StrEnum):
    """Minimal worker lifecycle statuses for the runtime foundation."""

    SPAWNING = auto()
    READY = auto()
    RUNNING = auto()
    BLOCKED = auto()
    DEGRADED = auto()
    FINISHED = auto()
    FAILED = auto()


NORMAL_WORKER_STATUSES: frozenset[WorkerStatus] = frozenset(
    {
        WorkerStatus.SPAWNING,
        WorkerStatus.READY,
        WorkerStatus.RUNNING,
    }
)
DEGRADED_WORKER_STATUSES: frozenset[WorkerStatus] = frozenset(
    {
        WorkerStatus.BLOCKED,
        WorkerStatus.DEGRADED,
    }
)
TERMINAL_WORKER_STATUSES: frozenset[WorkerStatus] = frozenset(
    {
        WorkerStatus.FINISHED,
        WorkerStatus.FAILED,
    }
)

_ALLOWED_TRANSITIONS: dict[WorkerStatus, frozenset[WorkerStatus]] = {
    WorkerStatus.SPAWNING: frozenset({WorkerStatus.READY, WorkerStatus.BLOCKED, WorkerStatus.FAILED}),
    WorkerStatus.READY: frozenset({WorkerStatus.RUNNING, WorkerStatus.BLOCKED, WorkerStatus.FAILED}),
    WorkerStatus.RUNNING: frozenset(
        {
            WorkerStatus.DEGRADED,
            WorkerStatus.BLOCKED,
            WorkerStatus.FINISHED,
            WorkerStatus.FAILED,
        }
    ),
    WorkerStatus.BLOCKED: frozenset({WorkerStatus.READY, WorkerStatus.FAILED}),
    WorkerStatus.DEGRADED: frozenset({WorkerStatus.RUNNING, WorkerStatus.BLOCKED, WorkerStatus.FAILED}),
    WorkerStatus.FINISHED: frozenset(),
    WorkerStatus.FAILED: frozenset(),
}


class WorkerState(BaseModel):
    """One worker lifecycle snapshot."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    worker_id: str
    status: WorkerStatus
    status_reason: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)


def can_transition(from_status: WorkerStatus, to_status: WorkerStatus) -> bool:
    """Return whether a worker status transition is allowed."""
    return to_status in _ALLOWED_TRANSITIONS[from_status]


def transition_worker_state(
    state: WorkerState,
    to_status: WorkerStatus,
    *,
    reason: str | None = None,
) -> WorkerState:
    """Return a new worker state after a validated transition."""
    if not can_transition(state.status, to_status):
        msg = f"invalid worker transition: {state.status} -> {to_status}"
        raise ValueError(msg)
    return state.model_copy(update={"status": to_status, "status_reason": reason, "updated_at": utc_now_iso()})
