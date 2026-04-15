from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from controlmesh_runtime import (
    EngineRequest,
    EngineTraceEvent,
    EscalationLevel,
    ExecutionPayloadEventType,
    ExecutionPlanPayload,
    ExecutionResultPayload,
    ExecutionStepPayload,
    FailureClass,
    RecoveryDecision,
    RecoveryIntent,
    build_execution_payload,
    run_first_engine,
)


def _request(intent: RecoveryIntent = RecoveryIntent.RESTART_WORKER) -> EngineRequest:
    return EngineRequest(
        decision=RecoveryDecision(
            intent=intent,
            escalation=EscalationLevel.AUTO_WITH_LIMIT,
            reason="degraded_runtime",
            next_step_token=intent.value,
        ),
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        worker_id="worker-1",
    )


def test_execution_payload_event_token_set_is_exactly_the_approved_six() -> None:
    assert set(get_args(ExecutionPayloadEventType)) == {
        "execution.plan_created",
        "execution.plan_approved",
        "execution.step_started",
        "execution.step_completed",
        "execution.step_failed",
        "execution.result_recorded",
    }


def test_build_execution_payload_converts_plan_created_trace_to_plan_payload() -> None:
    execution = run_first_engine(_request())

    payload = build_execution_payload(
        execution.trace[0],
        plan=execution.plan,
        result=execution.result,
    )

    assert isinstance(payload, ExecutionPlanPayload)
    assert payload.execution_event_type == "execution.plan_created"
    assert payload.plan_id == execution.plan.plan_id
    assert payload.line == execution.plan.line
    assert payload.intent is execution.plan.intent
    assert payload.step_count == len(execution.plan.steps)
    assert payload.next_step_token == execution.plan.next_step_token


def test_build_execution_payload_converts_step_trace_to_step_payload() -> None:
    execution = run_first_engine(_request())

    payload = build_execution_payload(
        execution.trace[2],
        plan=execution.plan,
        result=execution.result,
    )

    assert isinstance(payload, ExecutionStepPayload)
    assert payload.execution_event_type == "execution.step_completed"
    assert payload.line == execution.plan.line
    assert payload.step_index == 0
    assert payload.action is execution.plan.steps[0].action
    assert payload.target == execution.plan.steps[0].target
    assert payload.requires_human_gate is False


def test_build_execution_payload_converts_result_trace_to_result_payload() -> None:
    execution = run_first_engine(_request())

    payload = build_execution_payload(
        execution.trace[-1],
        plan=execution.plan,
        result=execution.result,
    )

    assert isinstance(payload, ExecutionResultPayload)
    assert payload.execution_event_type == "execution.result_recorded"
    assert payload.line == execution.plan.line
    assert payload.result_status is execution.result.status
    assert payload.completed_step_count == execution.result.completed_step_count
    assert payload.requires_human_gate is execution.result.requires_human_gate
    assert payload.stop_reason is None


def test_build_execution_payload_rejects_step_failed_without_failure_class() -> None:
    execution = run_first_engine(_request())
    failed_trace = EngineTraceEvent(
        execution_event_type="execution.step_failed",
        plan_id=execution.plan.plan_id,
        task_id=execution.plan.task_id,
        worker_id=execution.plan.worker_id,
        step_index=0,
        action=execution.plan.steps[0].action,
    )

    with pytest.raises(ValueError, match="step_failed payloads require failure_class"):
        build_execution_payload(
            failed_trace,
            plan=execution.plan,
            result=execution.result,
        )


def test_build_execution_payload_rejects_result_recorded_without_result_object() -> None:
    execution = run_first_engine(_request())

    with pytest.raises(ValueError, match="result_recorded payload conversion requires result"):
        build_execution_payload(
            execution.trace[-1],
            plan=execution.plan,
        )


def test_execution_step_payload_rejects_unknown_failure_shape() -> None:
    with pytest.raises(ValidationError, match="step_failed payloads require failure_class"):
        ExecutionStepPayload(
            execution_event_type="execution.step_failed",
            plan_id="plan-1",
            task_id="task-1",
            line="harness-runtime",
            worker_id="worker-1",
            step_index=0,
            action="restart_worker",
            target="worker:worker-1",
            requires_human_gate=False,
        )


def test_build_execution_payload_rejects_trace_step_index_out_of_bounds() -> None:
    execution = run_first_engine(_request())
    bad_trace = EngineTraceEvent(
        execution_event_type="execution.step_completed",
        plan_id=execution.plan.plan_id,
        task_id=execution.plan.task_id,
        worker_id=execution.plan.worker_id,
        step_index=9,
        action=execution.plan.steps[0].action,
    )

    with pytest.raises(ValueError, match="trace step_index is outside the plan step range"):
        build_execution_payload(
            bad_trace,
            plan=execution.plan,
            result=execution.result,
        )


def test_build_execution_payload_carries_failure_class_on_step_failed() -> None:
    execution = run_first_engine(_request())
    failed_trace = EngineTraceEvent(
        execution_event_type="execution.step_failed",
        plan_id=execution.plan.plan_id,
        task_id=execution.plan.task_id,
        worker_id=execution.plan.worker_id,
        step_index=0,
        action=execution.plan.steps[0].action,
    )

    payload = build_execution_payload(
        failed_trace,
        plan=execution.plan,
        result=execution.result,
        failure_class=FailureClass.INFRA,
    )

    assert isinstance(payload, ExecutionStepPayload)
    assert payload.execution_event_type == "execution.step_failed"
    assert payload.failure_class is FailureClass.INFRA
