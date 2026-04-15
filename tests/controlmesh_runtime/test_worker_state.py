from __future__ import annotations

import pytest

from controlmesh_runtime import (
    DEGRADED_WORKER_STATUSES,
    NORMAL_WORKER_STATUSES,
    TERMINAL_WORKER_STATUSES,
    WorkerState,
    WorkerStatus,
    can_transition,
    transition_worker_state,
)


def test_worker_status_sets_keep_normal_degraded_and_terminal_distinct() -> None:
    assert WorkerStatus.BLOCKED in DEGRADED_WORKER_STATUSES
    assert WorkerStatus.DEGRADED in DEGRADED_WORKER_STATUSES
    assert WorkerStatus.BLOCKED not in NORMAL_WORKER_STATUSES
    assert WorkerStatus.FINISHED in TERMINAL_WORKER_STATUSES
    assert WorkerStatus.FAILED in TERMINAL_WORKER_STATUSES
    assert WorkerStatus.FINISHED != WorkerStatus.FAILED


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (WorkerStatus.SPAWNING, WorkerStatus.READY),
        (WorkerStatus.READY, WorkerStatus.RUNNING),
        (WorkerStatus.RUNNING, WorkerStatus.BLOCKED),
        (WorkerStatus.RUNNING, WorkerStatus.DEGRADED),
        (WorkerStatus.RUNNING, WorkerStatus.FINISHED),
        (WorkerStatus.DEGRADED, WorkerStatus.RUNNING),
        (WorkerStatus.BLOCKED, WorkerStatus.READY),
    ],
)
def test_can_transition_allows_expected_paths(from_status: WorkerStatus, to_status: WorkerStatus) -> None:
    assert can_transition(from_status, to_status) is True


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (WorkerStatus.SPAWNING, WorkerStatus.RUNNING),
        (WorkerStatus.READY, WorkerStatus.FINISHED),
        (WorkerStatus.BLOCKED, WorkerStatus.FINISHED),
        (WorkerStatus.FINISHED, WorkerStatus.RUNNING),
        (WorkerStatus.FAILED, WorkerStatus.READY),
    ],
)
def test_can_transition_rejects_invalid_paths(from_status: WorkerStatus, to_status: WorkerStatus) -> None:
    assert can_transition(from_status, to_status) is False


def test_transition_worker_state_returns_updated_snapshot() -> None:
    state = WorkerState(worker_id="worker-1", status=WorkerStatus.READY)

    next_state = transition_worker_state(
        state,
        WorkerStatus.RUNNING,
        reason="task packet dispatched",
    )

    assert next_state.worker_id == "worker-1"
    assert next_state.status is WorkerStatus.RUNNING
    assert next_state.status_reason == "task packet dispatched"
    assert next_state.updated_at != state.updated_at


def test_transition_worker_state_rejects_terminal_reentry() -> None:
    state = WorkerState(worker_id="worker-1", status=WorkerStatus.FINISHED)

    with pytest.raises(ValueError, match="invalid worker transition"):
        transition_worker_state(state, WorkerStatus.RUNNING)
