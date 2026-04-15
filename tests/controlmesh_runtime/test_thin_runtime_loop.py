from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.recovery import RecoveryContext, RecoveryPolicy, RecoveryReason
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.thin_runtime_loop import ThinRuntimeLoop, ThinRuntimeLoopRequest
from controlmesh_runtime.worker_state import WorkerState, WorkerStatus


@dataclass
class _FakeWorkerController:
    state: WorkerState | None = field(
        default_factory=lambda: WorkerState(worker_id="worker-1", status=WorkerStatus.READY)
    )

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def create(self, worker_id: str) -> WorkerState:
        self.calls.append(("create", worker_id))
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def await_ready(
        self,
        worker_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> WorkerState:
        del timeout_seconds, poll_interval_seconds
        self.calls.append(("await_ready", worker_id))
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def fetch_state(self, worker_id: str) -> WorkerState | None:
        self.calls.append(("fetch_state", worker_id))
        return self.state

    async def restart(self, worker_id: str) -> WorkerState:
        self.calls.append(("restart", worker_id))
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def terminate(self, worker_id: str) -> WorkerState:
        self.calls.append(("terminate", worker_id))
        return WorkerState(worker_id=worker_id, status=WorkerStatus.FINISHED)


def _context(reason: RecoveryReason) -> RecoveryContext:
    return RecoveryContext(
        task_id="task-1",
        line="harness-thin-runtime-loop-pack",
        worker_id="worker-1",
        current_status=WorkerStatus.DEGRADED,
        failure_class=FailureClass.TOOL_RUNTIME,
        recovery_reason=reason,
    )


@pytest.mark.asyncio
async def test_thin_runtime_loop_runs_restart_cycle_with_worker_controller() -> None:
    worker_controller = _FakeWorkerController()
    loop = ThinRuntimeLoop(worker_controller=worker_controller)

    outcome = await loop.run(
        ThinRuntimeLoopRequest(
            packet_id="packet-1",
            context=_context(RecoveryReason.DEGRADED_RUNTIME),
            runtime_stage=RuntimeStage.GREEN,
        )
    )

    assert outcome.runtime_runnable is True
    assert outcome.terminal is True
    assert outcome.result.status.value == "completed"
    assert outcome.final_worker_state is not None
    assert outcome.final_worker_state.status is WorkerStatus.READY
    assert outcome.plan_id is not None
    assert worker_controller.calls == [("restart", "worker-1")]


@pytest.mark.asyncio
async def test_thin_runtime_loop_marks_policy_auto_but_runtime_unrunnable_without_worker_calls() -> None:
    worker_controller = _FakeWorkerController()
    loop = ThinRuntimeLoop(worker_controller=worker_controller)

    outcome = await loop.run(
        ThinRuntimeLoopRequest(
            packet_id="packet-1",
            context=_context(RecoveryReason.STALE_BRANCH),
            policy_snapshot=RecoveryPolicy(),
        )
    )

    assert outcome.runtime_runnable is False
    assert outcome.terminal is True
    assert outcome.result.status.value == "aborted"
    assert outcome.stop_reason == "unsupported_first_cut_intent"
    assert outcome.final_worker_state is None
    assert worker_controller.calls == []
