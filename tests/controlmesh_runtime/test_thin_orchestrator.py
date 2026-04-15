from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.recovery import (
    EscalationLevel,
    RecoveryDecision,
    RecoveryIntent,
    RecoveryReason,
)
from controlmesh_runtime.recovery.execution import RecoveryExecutionStatus
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.thin_orchestrator import OrchestratorRequest, ThinOrchestrator
from controlmesh_runtime.worker_controller import WorkerControllerError, WorkerControllerErrorCode
from controlmesh_runtime.worker_state import WorkerState, WorkerStatus


def _decision(
    intent: RecoveryIntent,
    *,
    escalation: EscalationLevel = EscalationLevel.AUTO_WITH_LIMIT,
    human_gate_reason: str | None = None,
) -> RecoveryDecision:
    return RecoveryDecision(
        intent=intent,
        escalation=escalation,
        reason=RecoveryReason.DEGRADED_RUNTIME,
        next_step_token=intent.value,
        human_gate_reason=human_gate_reason,
    )


@dataclass
class _FakeWorkerController:
    state: WorkerState | None = field(
        default_factory=lambda: WorkerState(worker_id="worker-1", status=WorkerStatus.READY)
    )
    error: WorkerControllerError | None = None

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def create(self, worker_id: str) -> WorkerState:
        self.calls.append(("create", worker_id))
        if self.error is not None:
            raise self.error
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def await_ready(self, worker_id: str, *, timeout_seconds: float | None = None, poll_interval_seconds: float | None = None) -> WorkerState:
        del timeout_seconds, poll_interval_seconds
        self.calls.append(("await_ready", worker_id))
        if self.error is not None:
            raise self.error
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def fetch_state(self, worker_id: str) -> WorkerState | None:
        self.calls.append(("fetch_state", worker_id))
        return self.state

    async def restart(self, worker_id: str) -> WorkerState:
        self.calls.append(("restart", worker_id))
        if self.error is not None:
            raise self.error
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def terminate(self, worker_id: str) -> WorkerState:
        self.calls.append(("terminate", worker_id))
        if self.error is not None:
            raise self.error
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.FINISHED)


@pytest.mark.asyncio
async def test_thin_orchestrator_runs_restart_worker_and_emits_typed_runtime_events() -> None:
    worker_controller = _FakeWorkerController()
    orchestrator = ThinOrchestrator(worker_controller=worker_controller)

    run = await orchestrator.run(
        OrchestratorRequest(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-thin-orchestrator",
            worker_id="worker-1",
            decision=_decision(RecoveryIntent.RESTART_WORKER),
            runtime_stage=RuntimeStage.GREEN,
        )
    )

    assert worker_controller.calls == [("restart", "worker-1")]
    assert run.result.status is RecoveryExecutionStatus.COMPLETED
    assert len(run.runtime_events) == 4
    assert run.runtime_events[-1].payload["result_status"] == "completed"
    assert run.final_worker_state is not None
    assert run.final_worker_state.status is WorkerStatus.READY


@pytest.mark.asyncio
async def test_thin_orchestrator_stops_human_gate_without_worker_controller_calls() -> None:
    worker_controller = _FakeWorkerController()
    orchestrator = ThinOrchestrator(worker_controller=worker_controller)

    run = await orchestrator.run(
        OrchestratorRequest(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-thin-orchestrator",
            worker_id="worker-1",
            decision=_decision(
                RecoveryIntent.REQUIRE_OPERATOR_ACTION,
                escalation=EscalationLevel.HUMAN_GATE,
                human_gate_reason="operator review required",
            ),
        )
    )

    assert worker_controller.calls == []
    assert run.result.status is RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE
    assert run.stop_reason is not None
    assert run.runtime_events[-1].payload["result_status"] == "blocked_by_human_gate"


@pytest.mark.asyncio
async def test_thin_orchestrator_stops_unsupported_reauth_handoff_without_worker_call() -> None:
    worker_controller = _FakeWorkerController()
    orchestrator = ThinOrchestrator(worker_controller=worker_controller)

    run = await orchestrator.run(
        OrchestratorRequest(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-thin-orchestrator",
            worker_id="worker-1",
            decision=_decision(RecoveryIntent.REQUIRE_REAUTH),
        )
    )

    assert worker_controller.calls == []
    assert run.result.status is RecoveryExecutionStatus.ABORTED
    assert run.stop_reason is not None


@pytest.mark.asyncio
async def test_thin_orchestrator_surfaces_worker_controller_failure_as_failed_result() -> None:
    worker_controller = _FakeWorkerController(
        error=WorkerControllerError(
            code=WorkerControllerErrorCode.TIMEOUT,
            failure_class=FailureClass.INFRA,
            message="worker timeout",
            worker_id="worker-1",
            operation="restart",
        )
    )
    orchestrator = ThinOrchestrator(worker_controller=worker_controller)

    run = await orchestrator.run(
        OrchestratorRequest(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-thin-orchestrator",
            worker_id="worker-1",
            decision=_decision(RecoveryIntent.RESTART_WORKER),
        )
    )

    assert worker_controller.calls == [("restart", "worker-1")]
    assert run.result.status is RecoveryExecutionStatus.FAILED
    assert run.result.failure_class is FailureClass.INFRA
    assert any(event.payload["execution_event_type"] == "execution.step_failed" for event in run.runtime_events)
