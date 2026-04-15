from __future__ import annotations

import pytest

from controlmesh_runtime import (
    EngineRequest,
    EscalationLevel,
    EventKind,
    ExecutionPlanPayload,
    FailureClass,
    RecoveryDecision,
    RecoveryIntent,
    RuntimeEvent,
    RuntimeStage,
    build_execution_payload,
    build_runtime_event_from_execution_payload,
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


def test_build_runtime_event_from_plan_payload_uses_runtime_shell_without_new_semantics() -> None:
    execution = run_first_engine(_request())
    payload = build_execution_payload(execution.trace[0], plan=execution.plan, result=execution.result)

    event = build_runtime_event_from_execution_payload(
        payload,
        packet_id="packet-1",
        message="execution.plan_created",
    )

    assert isinstance(event, RuntimeEvent)
    assert event.packet_id == "packet-1"
    assert event.kind is EventKind.TASK_PROGRESS
    assert event.message == "execution.plan_created"
    assert event.worker_id == execution.plan.worker_id
    assert event.stage is None
    assert event.outcome is None
    assert event.failure_class is None
    assert event.payload == payload.model_dump(mode="json")


def test_build_runtime_event_from_failed_step_payload_routes_failure_class() -> None:
    execution = run_first_engine(_request())
    payload = build_execution_payload(
        execution.trace[2].model_copy(update={"execution_event_type": "execution.step_failed"}),
        plan=execution.plan,
        result=execution.result,
        failure_class=FailureClass.INFRA,
    )

    event = build_runtime_event_from_execution_payload(
        payload,
        packet_id="packet-1",
        message="execution.step_failed",
        stage=RuntimeStage.LIVE,
    )

    assert event.kind is EventKind.TASK_FAILED
    assert event.failure_class is FailureClass.INFRA
    assert event.stage is RuntimeStage.LIVE
    assert event.payload["execution_event_type"] == "execution.step_failed"


def test_build_runtime_event_from_result_payload_routes_to_result_reported() -> None:
    execution = run_first_engine(_request())
    payload = build_execution_payload(
        execution.trace[-1],
        plan=execution.plan,
        result=execution.result,
    )

    event = build_runtime_event_from_execution_payload(
        payload,
        packet_id="packet-1",
        message="execution.result_recorded",
    )

    assert event.kind is EventKind.TASK_RESULT_REPORTED
    assert event.failure_class is None
    assert event.payload["result_status"] == execution.result.status.value


def test_build_runtime_event_from_execution_payload_rejects_unsupported_payload_object() -> None:
    with pytest.raises(TypeError, match="execution payload wrapping requires a typed execution payload instance"):
        build_runtime_event_from_execution_payload(  # type: ignore[arg-type]
            {"execution_event_type": "execution.plan_created"},
            packet_id="packet-1",
            message="execution.plan_created",
        )


def test_build_runtime_event_from_execution_payload_does_not_mutate_payload() -> None:
    execution = run_first_engine(_request())
    payload = build_execution_payload(execution.trace[0], plan=execution.plan, result=execution.result)
    original = payload.model_dump(mode="json")

    event = build_runtime_event_from_execution_payload(
        payload,
        packet_id="packet-1",
        message="execution.plan_created",
    )

    assert payload.model_dump(mode="json") == original
    assert event.payload == original


def test_build_runtime_event_from_execution_payload_lets_runtime_event_reject_blank_message() -> None:
    execution = run_first_engine(_request())
    payload = ExecutionPlanPayload(
        execution_event_type="execution.plan_created",
        plan_id=execution.plan.plan_id,
        task_id=execution.plan.task_id,
        line=execution.plan.line,
        worker_id=execution.plan.worker_id,
        intent=execution.plan.intent,
        requires_human_gate=execution.plan.requires_human_gate,
        next_step_token=execution.plan.next_step_token,
        step_count=len(execution.plan.steps),
    )

    with pytest.raises(ValueError, match="runtime event message must not be empty"):
        build_runtime_event_from_execution_payload(
            payload,
            packet_id="packet-1",
            message="",
        )
