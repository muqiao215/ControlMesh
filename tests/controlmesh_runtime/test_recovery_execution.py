from __future__ import annotations

import pytest

from controlmesh_runtime import (
    EventKind,
    FailureClass,
    RecoveryExecutionAction,
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryExecutionStep,
    RecoveryIntent,
    RecoveryPolicy,
    ReviewOutcome,
    RuntimeEvidenceIdentity,
)


def _identity(plan_id: str = "plan-1") -> RuntimeEvidenceIdentity:
    return RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id=plan_id,
    )


def test_recovery_execution_plan_creates_with_valid_defaults() -> None:
    plan = RecoveryExecutionPlan(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        worker_id="worker-1",
        intent=RecoveryIntent.RESTART_WORKER,
        steps=(
            RecoveryExecutionStep(
                action=RecoveryExecutionAction.RESTART_WORKER,
                target="worker:worker-1",
                retryable=True,
            ),
        ),
        policy_snapshot=RecoveryPolicy(),
        next_step_token="restart_worker",
    )

    assert plan.steps[0].action is RecoveryExecutionAction.RESTART_WORKER
    assert plan.requires_human_gate is False


def test_destructive_recovery_step_must_be_explicit() -> None:
    with pytest.raises(ValueError, match="destructive recovery actions must set destructive=True"):
        RecoveryExecutionStep(
            action=RecoveryExecutionAction.CLEAR_RUNTIME_STATE,
            target="runtime:task-1",
        )


def test_plan_with_human_gate_requires_reasons() -> None:
    with pytest.raises(ValueError, match="human-gated plans require human_gate_reasons"):
        RecoveryExecutionPlan(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-runtime",
            worker_id="worker-1",
            intent=RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            steps=(
                RecoveryExecutionStep(
                    action=RecoveryExecutionAction.EMIT_HUMAN_GATE,
                    target="gate:operator",
                    requires_human_gate=True,
                ),
            ),
            requires_human_gate=True,
            policy_snapshot=RecoveryPolicy(),
            next_step_token="emit_human_gate",
        )


def test_plan_with_gated_step_must_mark_human_gate() -> None:
    with pytest.raises(ValueError, match="plans with human-gated steps must set requires_human_gate"):
        RecoveryExecutionPlan(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-runtime",
            worker_id="worker-1",
            intent=RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            steps=(
                RecoveryExecutionStep(
                    action=RecoveryExecutionAction.EMIT_HUMAN_GATE,
                    target="gate:operator",
                    requires_human_gate=True,
                ),
            ),
            policy_snapshot=RecoveryPolicy(),
            next_step_token="emit_human_gate",
        )


def test_partial_result_is_representable() -> None:
    result = RecoveryExecutionResult(
        plan_id="plan-1",
        evidence_identity=_identity(),
        status=RecoveryExecutionStatus.PARTIALLY_COMPLETED,
        completed_step_count=1,
        failed_step_index=1,
        failure_class=FailureClass.INFRA,
        emitted_event_types=(EventKind.TASK_FAILED,),
    )

    assert result.status is RecoveryExecutionStatus.PARTIALLY_COMPLETED
    assert result.failed_step_index == 1


def test_failed_result_requires_failure_details() -> None:
    with pytest.raises(ValueError, match="failed results require failure_class or failed_step_index"):
        RecoveryExecutionResult(
            plan_id="plan-1",
            evidence_identity=_identity(),
            status=RecoveryExecutionStatus.FAILED,
            completed_step_count=0,
        )


def test_blocked_by_human_gate_requires_gate_flag() -> None:
    with pytest.raises(ValueError, match="blocked_by_human_gate results must set requires_human_gate"):
        RecoveryExecutionResult(
            plan_id="plan-1",
            evidence_identity=_identity(),
            status=RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE,
            completed_step_count=0,
        )


def test_result_can_hint_next_review_outcome() -> None:
    result = RecoveryExecutionResult(
        plan_id="plan-1",
        evidence_identity=_identity(),
        status=RecoveryExecutionStatus.COMPLETED,
        completed_step_count=2,
        next_review_outcome_hint=ReviewOutcome.PASS_WITH_NOTES,
        emitted_event_types=(EventKind.TASK_PROGRESS, EventKind.TASK_RESULT_REPORTED),
    )

    assert result.next_review_outcome_hint is ReviewOutcome.PASS_WITH_NOTES


def test_core_recovery_actions_are_stable() -> None:
    assert {action.value for action in RecoveryExecutionAction} == {
        "retry_same_worker",
        "restart_worker",
        "recreate_worker",
        "clear_runtime_state",
        "mark_reauth_required",
        "emit_human_gate",
        "split_scope",
        "defer_line",
        "stopline",
    }
