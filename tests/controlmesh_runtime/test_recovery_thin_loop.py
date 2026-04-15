from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity
from controlmesh_runtime.recovery import (
    RecoveryContext,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryIntent,
    RecoveryPolicy,
    RecoveryReason,
)
from controlmesh_runtime.recovery_thin_loop import RecoveryLoopRequest, run_recovery_cycle
from controlmesh_runtime.worker_state import WorkerStatus


@dataclass
class _FakeOrchestrator:
    result: RecoveryExecutionResult

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, request: Any):
        self.calls.append((request.task_id, request.decision.intent.value))
        return type(
            "_Run",
            (),
            {
                "plan": type("_Plan", (), {"plan_id": "plan-1"})(),
                "result": self.result,
                "runtime_events": (),
                "stop_reason": None,
                "final_worker_state": None,
            },
        )()


def _context(reason: RecoveryReason) -> RecoveryContext:
    return RecoveryContext(
        task_id="task-1",
        line="harness-recovery-thin-loop",
        worker_id="worker-1",
        current_status=WorkerStatus.DEGRADED,
        failure_class=FailureClass.TOOL_RUNTIME,
        recovery_reason=reason,
    )


def _identity() -> RuntimeEvidenceIdentity:
    return RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-recovery-thin-loop",
        plan_id="plan-1",
    )


@pytest.mark.asyncio
async def test_recovery_thin_loop_runs_one_success_cycle_end_to_end() -> None:
    orchestrator = _FakeOrchestrator(
        RecoveryExecutionResult(
            plan_id="plan-1",
            evidence_identity=_identity(),
            status=RecoveryExecutionStatus.COMPLETED,
            completed_step_count=1,
        )
    )

    outcome = await run_recovery_cycle(
        RecoveryLoopRequest(context=_context(RecoveryReason.DEGRADED_RUNTIME)),
        orchestrator=orchestrator,
    )

    assert outcome.terminal is True
    assert outcome.result.status is RecoveryExecutionStatus.COMPLETED
    assert orchestrator.calls == [("task-1", RecoveryIntent.RESTART_WORKER.value)]


@pytest.mark.asyncio
async def test_recovery_thin_loop_preserves_gate_stop_as_terminal() -> None:
    orchestrator = _FakeOrchestrator(
        RecoveryExecutionResult(
            plan_id="plan-1",
            evidence_identity=_identity(),
            status=RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE,
            completed_step_count=0,
            requires_human_gate=True,
        )
    )
    policy = RecoveryPolicy(require_human_for_operator_safety=True)

    outcome = await run_recovery_cycle(
        RecoveryLoopRequest(context=_context(RecoveryReason.OPERATOR_SAFETY), policy_snapshot=policy),
        orchestrator=orchestrator,
    )

    assert outcome.terminal is True
    assert outcome.result.status is RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE


@pytest.mark.asyncio
async def test_recovery_thin_loop_preserves_unsupported_stop_as_terminal() -> None:
    orchestrator = _FakeOrchestrator(
        RecoveryExecutionResult(
            plan_id="plan-1",
            evidence_identity=_identity(),
            status=RecoveryExecutionStatus.ABORTED,
            completed_step_count=0,
            notes=("unsupported_first_cut_intent",),
        )
    )

    outcome = await run_recovery_cycle(
        RecoveryLoopRequest(context=_context(RecoveryReason.STALE_BRANCH)),
        orchestrator=orchestrator,
    )

    assert outcome.terminal is True
    assert outcome.result.status is RecoveryExecutionStatus.ABORTED


@pytest.mark.asyncio
async def test_recovery_thin_loop_preserves_failure_stop_as_terminal() -> None:
    orchestrator = _FakeOrchestrator(
        RecoveryExecutionResult(
            plan_id="plan-1",
            evidence_identity=_identity(),
            status=RecoveryExecutionStatus.FAILED,
            completed_step_count=0,
            failed_step_index=0,
            failure_class=FailureClass.INFRA,
        )
    )

    outcome = await run_recovery_cycle(
        RecoveryLoopRequest(context=_context(RecoveryReason.DEGRADED_RUNTIME)),
        orchestrator=orchestrator,
    )

    assert outcome.terminal is True
    assert outcome.result.status is RecoveryExecutionStatus.FAILED
    assert outcome.result.failure_class is FailureClass.INFRA
