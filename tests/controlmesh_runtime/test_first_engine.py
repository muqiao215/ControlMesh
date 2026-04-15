from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from controlmesh_runtime import (
    EngineExecution,
    EngineRequest,
    EngineState,
    EngineStopReason,
    EngineTraceEvent,
    EscalationLevel,
    ExecutionEventType,
    RecoveryDecision,
    RecoveryExecutionAction,
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryExecutionStep,
    RecoveryIntent,
    RecoveryPolicy,
    RecoveryReason,
    RuntimeEvidenceIdentity,
    can_transition_engine_state,
    execute_first_engine_plan,
    run_first_engine,
)


def _identity(plan_id: str = "plan-1") -> RuntimeEvidenceIdentity:
    return RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id=plan_id,
    )


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


def _request(
    intent: RecoveryIntent,
    *,
    worker_id: str | None = "worker-1",
    escalation: EscalationLevel = EscalationLevel.AUTO_WITH_LIMIT,
    human_gate_reason: str | None = None,
) -> EngineRequest:
    return EngineRequest(
        decision=_decision(
            intent,
            escalation=escalation,
            human_gate_reason=human_gate_reason,
        ),
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        worker_id=worker_id,
    )


def _plan(
    *,
    action: RecoveryExecutionAction = RecoveryExecutionAction.RESTART_WORKER,
    target: str = "worker:worker-1",
    intent: RecoveryIntent = RecoveryIntent.RESTART_WORKER,
    worker_id: str | None = "worker-1",
    args: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    destructive: bool = False,
    requires_human_gate: bool = False,
    human_gate_reasons: tuple[str, ...] = (),
) -> RecoveryExecutionPlan:
    return RecoveryExecutionPlan(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        worker_id=worker_id,
        intent=intent,
        steps=(
            RecoveryExecutionStep(
                action=action,
                target=target,
                args=args or {},
                destructive=destructive,
                requires_human_gate=requires_human_gate,
            ),
        ),
        requires_human_gate=requires_human_gate,
        human_gate_reasons=human_gate_reasons,
        policy_snapshot=RecoveryPolicy(),
        next_step_token=intent.value,
        metadata=metadata or {},
    )


def test_run_first_engine_completes_single_allowed_worker_action_with_minimal_trace() -> None:
    execution = run_first_engine(_request(RecoveryIntent.RESTART_WORKER))

    assert execution.final_state is EngineState.COMPLETED
    assert execution.stop_reason is None
    assert execution.plan.intent is RecoveryIntent.RESTART_WORKER
    assert execution.plan.steps == (
        RecoveryExecutionStep(
            action=RecoveryExecutionAction.RESTART_WORKER,
            target="worker:worker-1",
            retryable=True,
        ),
    )
    assert execution.result.status is RecoveryExecutionStatus.COMPLETED
    assert execution.result.completed_step_count == 1
    assert tuple(event.execution_event_type for event in execution.trace) == (
        "execution.plan_created",
        "execution.step_started",
        "execution.step_completed",
        "execution.result_recorded",
    )


@pytest.mark.parametrize(
    ("intent", "expected_stop_reason"),
    [
        (RecoveryIntent.REQUIRE_REAUTH, EngineStopReason.ADAPTER_SPECIFIC_ACTION_REQUIRED),
        (RecoveryIntent.SPLIT_SCOPE, EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
        (RecoveryIntent.DEFER_LINE, EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
        (RecoveryIntent.STOPLINE, EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
        (RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE, EngineStopReason.UNSUPPORTED_FIRST_CUT_INTENT),
    ],
)
def test_handoff_only_and_unsupported_intents_stop_without_step_execution(
    intent: RecoveryIntent,
    expected_stop_reason: EngineStopReason,
) -> None:
    escalation = (
        EscalationLevel.AUTO_WITH_LIMIT
        if intent
        in {
            RecoveryIntent.REQUIRE_REAUTH,
            RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE,
        }
        else EscalationLevel.TERMINAL
    )

    execution = run_first_engine(_request(intent, escalation=escalation))

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is expected_stop_reason
    assert execution.result.status is RecoveryExecutionStatus.ABORTED
    assert "execution.step_started" not in {
        event.execution_event_type for event in execution.trace
    }


def test_engine_request_rejects_args_and_metadata_backdoors() -> None:
    request_args = {
        "decision": _decision(RecoveryIntent.RESTART_WORKER),
        "packet_id": "packet-1",
        "task_id": "task-1",
        "line": "harness-runtime",
        "worker_id": "worker-1",
    }

    with pytest.raises(ValidationError):
        EngineRequest(**request_args, args={"shell": "echo unsafe"})

    with pytest.raises(ValidationError):
        EngineRequest(**request_args, metadata={"canonical_write": True})


@pytest.mark.parametrize("worker_id", [None, "default"])
def test_worker_targeted_actions_missing_or_default_worker_id_stop_without_step_execution(
    worker_id: str | None,
) -> None:
    execution = run_first_engine(_request(RecoveryIntent.RECREATE_WORKER, worker_id=worker_id))

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is EngineStopReason.MISSING_WORKER_ID
    assert execution.result.status is RecoveryExecutionStatus.ABORTED
    assert "execution.step_started" not in {
        event.execution_event_type for event in execution.trace
    }


@pytest.mark.parametrize("worker_id", ["", "   "])
def test_engine_request_rejects_blank_worker_id(worker_id: str) -> None:
    with pytest.raises(ValidationError):
        _request(RecoveryIntent.RECREATE_WORKER, worker_id=worker_id)


def test_human_gate_stops_without_executing_worker_step() -> None:
    execution = run_first_engine(
        _request(
            RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            escalation=EscalationLevel.HUMAN_GATE,
            human_gate_reason="operator review required",
        )
    )

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is EngineStopReason.HUMAN_GATE_REQUIRED
    assert execution.result.status is RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE
    assert execution.result.requires_human_gate is True
    assert tuple(event.execution_event_type for event in execution.trace) == (
        "execution.plan_created",
        "execution.plan_approved",
        "execution.result_recorded",
    )


def test_step_args_keep_stable_stop_reason_even_on_human_gate_step() -> None:
    execution = execute_first_engine_plan(
        _plan(
            action=RecoveryExecutionAction.EMIT_HUMAN_GATE,
            target="gate:operator",
            args={"unexpected": True},
            requires_human_gate=True,
            human_gate_reasons=("operator review required",),
        )
    )

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is EngineStopReason.UNSUPPORTED_STEP_ARGS
    assert execution.result.status is RecoveryExecutionStatus.ABORTED
    assert "execution.step_started" not in {
        event.execution_event_type for event in execution.trace
    }


@pytest.mark.parametrize(
    ("plan", "expected_stop_reason"),
    [
        (_plan(args={"unknown": True}), EngineStopReason.UNSUPPORTED_STEP_ARGS),
        (_plan(metadata={"unknown": True}), EngineStopReason.UNSUPPORTED_PLAN_METADATA),
        (
            _plan(action=RecoveryExecutionAction.CLEAR_RUNTIME_STATE, target="runtime:task-1", destructive=True),
            EngineStopReason.DESTRUCTIVE_STEP_NOT_AUTHORIZED,
        ),
        (_plan(target="store:runtime"), EngineStopReason.STORE_DETAIL_LEAK),
        (_plan(target="event_bus:runtime"), EngineStopReason.EVENT_BUS_DETAIL_LEAK),
        (_plan(target="transport:feishu"), EngineStopReason.TRANSPORT_OR_PROVIDER_DETAIL_LEAK),
        (_plan(target="provider:codex"), EngineStopReason.TRANSPORT_OR_PROVIDER_DETAIL_LEAK),
        (_plan(target="canonical:plan-file"), EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
    ],
)
def test_plan_backdoors_and_forbidden_integration_needs_stop_before_execution(
    plan: RecoveryExecutionPlan,
    expected_stop_reason: EngineStopReason,
) -> None:
    execution = execute_first_engine_plan(plan)

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is expected_stop_reason
    assert execution.result.status is RecoveryExecutionStatus.ABORTED
    assert "execution.step_started" not in {
        event.execution_event_type for event in execution.trace
    }


def test_engine_state_transitions_are_linear_and_terminal_states_are_sticky() -> None:
    assert can_transition_engine_state(EngineState.READY, EngineState.RUNNING) is True
    assert can_transition_engine_state(EngineState.RUNNING, EngineState.COMPLETED) is True
    assert can_transition_engine_state(EngineState.RUNNING, EngineState.FAILED) is True
    assert can_transition_engine_state(EngineState.RUNNING, EngineState.STOPPED) is True
    assert can_transition_engine_state(EngineState.READY, EngineState.COMPLETED) is False
    assert can_transition_engine_state(EngineState.COMPLETED, EngineState.RUNNING) is False
    assert can_transition_engine_state(EngineState.FAILED, EngineState.RUNNING) is False
    assert can_transition_engine_state(EngineState.STOPPED, EngineState.RUNNING) is False


@pytest.mark.parametrize("worker_id", [None, "", "   ", "default"])
def test_direct_plan_worker_targeted_action_cannot_bypass_missing_worker_id(
    worker_id: str | None,
) -> None:
    execution = execute_first_engine_plan(
        _plan(
            worker_id=worker_id,
            target=f"worker:{worker_id or 'missing'}",
        )
    )

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is EngineStopReason.MISSING_WORKER_ID
    assert execution.result.status is RecoveryExecutionStatus.ABORTED
    assert "execution.step_started" not in {
        event.execution_event_type for event in execution.trace
    }


@pytest.mark.parametrize(
    ("intent", "expected_stop_reason"),
    [
        (RecoveryIntent.REQUIRE_REAUTH, EngineStopReason.ADAPTER_SPECIFIC_ACTION_REQUIRED),
        (RecoveryIntent.SPLIT_SCOPE, EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
        (RecoveryIntent.DEFER_LINE, EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
        (RecoveryIntent.STOPLINE, EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE),
        (RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE, EngineStopReason.UNSUPPORTED_FIRST_CUT_INTENT),
    ],
)
def test_handoff_only_intents_cannot_be_downgraded_to_runnable_worker_action(
    intent: RecoveryIntent,
    expected_stop_reason: EngineStopReason,
) -> None:
    execution = execute_first_engine_plan(_plan(intent=intent))

    assert execution.final_state is EngineState.STOPPED
    assert execution.stop_reason is expected_stop_reason
    assert execution.result.status is RecoveryExecutionStatus.ABORTED
    assert "execution.step_started" not in {
        event.execution_event_type for event in execution.trace
    }


def test_stopped_execution_trace_ends_at_result_recorded() -> None:
    execution = run_first_engine(_request(RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE))

    assert execution.trace[-1].execution_event_type == "execution.result_recorded"
    assert "execution.step_completed" not in {
        event.execution_event_type for event in execution.trace
    }


def test_engine_trace_event_rejects_unknown_execution_event_type() -> None:
    with pytest.raises(ValidationError):
        EngineTraceEvent(
            execution_event_type="execution.custom",
            plan_id="plan-1",
            task_id="task-1",
        )


def test_engine_trace_event_token_set_is_exactly_the_approved_six() -> None:
    assert set(get_args(ExecutionEventType)) == {
        "execution.plan_created",
        "execution.plan_approved",
        "execution.step_started",
        "execution.step_completed",
        "execution.step_failed",
        "execution.result_recorded",
    }


def test_engine_execution_rejects_trace_events_after_terminal_result() -> None:
    plan = _plan()
    result = run_first_engine(_request(RecoveryIntent.RESTART_WORKER)).result.model_copy(
        update={
            "plan_id": plan.plan_id,
            "evidence_identity": _identity(plan.plan_id),
        }
    )

    with pytest.raises(ValidationError, match="trace must not contain events after result_recorded"):
        EngineExecution(
            plan=plan,
            result=result,
            trace=(
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=RecoveryExecutionStatus.COMPLETED,
                ),
                EngineTraceEvent(
                    execution_event_type="execution.step_completed",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                ),
            ),
            final_state=EngineState.COMPLETED,
        )


def test_engine_execution_rejects_multiple_terminal_result_events() -> None:
    plan = _plan()
    result = run_first_engine(_request(RecoveryIntent.RESTART_WORKER)).result.model_copy(
        update={
            "plan_id": plan.plan_id,
            "evidence_identity": _identity(plan.plan_id),
        }
    )

    with pytest.raises(ValidationError, match="trace must contain exactly one result_recorded event"):
        EngineExecution(
            plan=plan,
            result=result,
            trace=(
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=RecoveryExecutionStatus.COMPLETED,
                ),
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=RecoveryExecutionStatus.COMPLETED,
                ),
            ),
            final_state=EngineState.COMPLETED,
        )


def test_engine_execution_completed_requires_completed_result() -> None:
    plan = _plan()
    result = run_first_engine(_request(RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE)).result.model_copy(
        update={
            "plan_id": plan.plan_id,
            "evidence_identity": _identity(plan.plan_id),
        }
    )

    with pytest.raises(ValidationError, match="completed engine executions require completed results"):
        EngineExecution(
            plan=plan,
            result=result,
            trace=(
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=result.status,
                ),
            ),
            final_state=EngineState.COMPLETED,
        )


def test_engine_execution_failed_requires_failed_result() -> None:
    plan = _plan()
    result = RecoveryExecutionResult(
        plan_id=plan.plan_id,
        evidence_identity=_identity(plan.plan_id),
        status=RecoveryExecutionStatus.ABORTED,
    )

    with pytest.raises(ValidationError, match="failed engine executions require failed results"):
        EngineExecution(
            plan=plan,
            result=result,
            trace=(
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=result.status,
                ),
            ),
            final_state=EngineState.FAILED,
        )


def test_engine_execution_stopped_requires_stop_reason() -> None:
    plan = _plan()
    result = run_first_engine(_request(RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE)).result.model_copy(
        update={
            "plan_id": plan.plan_id,
            "evidence_identity": _identity(plan.plan_id),
        }
    )

    with pytest.raises(ValidationError, match="stopped engine executions require stop_reason"):
        EngineExecution(
            plan=plan,
            result=result,
            trace=(
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=result.status,
                ),
            ),
            final_state=EngineState.STOPPED,
        )


def test_engine_execution_result_plan_id_must_match_plan() -> None:
    plan = _plan()
    result = RecoveryExecutionResult(
        plan_id="different-plan",
        evidence_identity=_identity("different-plan"),
        status=RecoveryExecutionStatus.COMPLETED,
    )

    with pytest.raises(ValidationError, match="engine execution result plan_id must match the plan"):
        EngineExecution(
            plan=plan,
            result=result,
            trace=(
                EngineTraceEvent(
                    execution_event_type="execution.result_recorded",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    result_status=result.status,
                ),
            ),
            final_state=EngineState.COMPLETED,
        )
