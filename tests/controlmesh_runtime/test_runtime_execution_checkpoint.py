from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.recovery import RecoveryContext, RecoveryPolicy, RecoveryReason
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.runtime_execution_checkpoint import (
    RuntimeExecutionCheckpointer,
    RuntimeExecutionCheckpointRequest,
)
from controlmesh_runtime.store import RuntimeStore
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
        line="harness-runtime-execution-checkpoint-pack",
        worker_id="worker-1",
        current_status=WorkerStatus.DEGRADED,
        failure_class=FailureClass.TOOL_RUNTIME,
        recovery_reason=reason,
    )


@pytest.mark.asyncio
async def test_checkpoint_runner_persists_runtime_events_as_execution_evidence(tmp_path) -> None:
    worker_controller = _FakeWorkerController()
    runner = RuntimeExecutionCheckpointer(root=tmp_path, worker_controller=worker_controller)

    outcome = await runner.run(
        RuntimeExecutionCheckpointRequest(
            packet_id="packet-1",
            context=_context(RecoveryReason.DEGRADED_RUNTIME),
            runtime_stage=RuntimeStage.GREEN,
        )
    )

    store = RuntimeStore(tmp_path)
    persisted = store.load_execution_evidence("packet-1")
    assert outcome.persisted_event_count == len(persisted)
    assert outcome.packet_view.packet_id == "packet-1"
    assert outcome.packet_view.event_count == len(persisted)
    assert outcome.task_handoff.packet_ids == ("packet-1",)
    assert outcome.task_handoff.primary_identity is not None
    assert outcome.task_handoff.primary_identity.packet_id == "packet-1"
    assert store.load_worker_state("worker-1").status is WorkerStatus.READY
    assert worker_controller.calls == [("restart", "worker-1")]


@pytest.mark.asyncio
async def test_checkpoint_runner_persists_unrunnable_stop_without_worker_calls(tmp_path) -> None:
    worker_controller = _FakeWorkerController()
    runner = RuntimeExecutionCheckpointer(root=tmp_path, worker_controller=worker_controller)

    outcome = await runner.run(
        RuntimeExecutionCheckpointRequest(
            packet_id="packet-1",
            context=_context(RecoveryReason.STALE_BRANCH),
            policy_snapshot=RecoveryPolicy(),
        )
    )

    persisted = RuntimeStore(tmp_path).load_execution_evidence("packet-1")
    assert outcome.loop_outcome.runtime_runnable is False
    assert outcome.loop_outcome.stop_reason == "unsupported_first_cut_intent"
    assert outcome.persisted_event_count == len(persisted)
    assert outcome.packet_view.execution_event_types[-1] == "execution.result_recorded"
    assert outcome.task_handoff.terminal_result_statuses == ("aborted",)
    assert worker_controller.calls == []


@pytest.mark.asyncio
async def test_checkpoint_runner_rejects_duplicate_packet_checkpoint(tmp_path) -> None:
    worker_controller = _FakeWorkerController()
    runner = RuntimeExecutionCheckpointer(root=tmp_path, worker_controller=worker_controller)
    request = RuntimeExecutionCheckpointRequest(
        packet_id="packet-1",
        context=_context(RecoveryReason.DEGRADED_RUNTIME),
    )

    _ = await runner.run(request)

    with pytest.raises(FileExistsError, match="already exists"):
        await runner.run(request)
