from __future__ import annotations

import pytest

from controlmesh_runtime import EscalationLevel, FailureClass, RecoveryContext, RecoveryDecision
from controlmesh_runtime.recovery import RecoveryIntent, RecoveryReason
from controlmesh_runtime.worker_state import WorkerStatus


def test_recovery_context_and_decision_create_with_valid_defaults() -> None:
    context = RecoveryContext(
        task_id="task-1",
        line="harness-runtime",
        worker_id="worker-1",
        current_status=WorkerStatus.DEGRADED,
        failure_class=FailureClass.TOOL_RUNTIME,
        recovery_reason=RecoveryReason.DEGRADED_RUNTIME,
    )
    decision = RecoveryDecision(
        intent=RecoveryIntent.RESTART_WORKER,
        escalation=EscalationLevel.AUTO_WITH_LIMIT,
        reason=RecoveryReason.DEGRADED_RUNTIME,
        next_step_token="restart_worker",
        retry_after_seconds=15,
    )

    assert context.retry_count == 0
    assert decision.intent is RecoveryIntent.RESTART_WORKER


def test_recovery_decision_rejects_auto_without_executable_intent() -> None:
    with pytest.raises(ValueError, match="auto escalation requires an executable intent"):
        RecoveryDecision(
            intent=RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            escalation=EscalationLevel.AUTO,
            reason=RecoveryReason.OPERATOR_SAFETY,
            next_step_token="require_operator_action",
        )


def test_recovery_decision_rejects_terminal_retry_delay() -> None:
    with pytest.raises(ValueError, match="terminal escalation cannot set retry_after_seconds"):
        RecoveryDecision(
            intent=RecoveryIntent.STOPLINE,
            escalation=EscalationLevel.TERMINAL,
            reason=RecoveryReason.SCHEMA_INVALID,
            next_step_token="stopline",
            retry_after_seconds=30,
        )


def test_recovery_decision_requires_gate_reason_for_human_gate() -> None:
    with pytest.raises(ValueError, match="human_gate escalation requires human_gate_reason"):
        RecoveryDecision(
            intent=RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            escalation=EscalationLevel.HUMAN_GATE,
            reason=RecoveryReason.OPERATOR_SAFETY,
            next_step_token="require_operator_action",
        )
