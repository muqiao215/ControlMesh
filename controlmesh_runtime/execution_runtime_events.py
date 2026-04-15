"""Pure wrapping from typed execution payloads into RuntimeEvent shells."""

from __future__ import annotations

from controlmesh_runtime.events import FailureClass, RuntimeEvent
from controlmesh_runtime.execution_payloads import (
    ExecutionEventPayload,
    ExecutionPlanPayload,
    ExecutionResultPayload,
    ExecutionStepPayload,
    event_kind_for_execution_payload,
)
from controlmesh_runtime.runtime import RuntimeStage


def build_runtime_event_from_execution_payload(
    payload: ExecutionEventPayload,
    *,
    packet_id: str,
    message: str,
    stage: RuntimeStage | None = None,
) -> RuntimeEvent:
    """Wrap one typed execution payload in the shared runtime event shell."""
    if not isinstance(payload, (ExecutionPlanPayload, ExecutionStepPayload, ExecutionResultPayload)):
        msg = "execution payload wrapping requires a typed execution payload instance"
        raise TypeError(msg)

    return RuntimeEvent(
        packet_id=packet_id,
        kind=event_kind_for_execution_payload(payload),
        message=message,
        worker_id=payload.worker_id,
        stage=stage,
        failure_class=_failure_class_for_payload(payload),
        payload=payload.model_dump(mode="json"),
    )


def extract_execution_payload_from_runtime_event(event: RuntimeEvent) -> ExecutionEventPayload:
    """Validate and decode typed execution payload evidence from a RuntimeEvent."""
    payload = _payload_from_runtime_event(event)
    expected_kind = event_kind_for_execution_payload(payload)
    if event.kind is not expected_kind:
        msg = "runtime event execution payload kind does not match coarse event routing"
        raise ValueError(msg)
    if event.worker_id != payload.worker_id:
        msg = "runtime event worker_id must match execution payload worker_id"
        raise ValueError(msg)
    if event.failure_class is not _failure_class_for_payload(payload):
        msg = "runtime event failure_class must match execution payload failure_class"
        raise ValueError(msg)
    return payload


def _failure_class_for_payload(payload: ExecutionEventPayload) -> FailureClass | None:
    if isinstance(payload, ExecutionStepPayload):
        return payload.failure_class
    if isinstance(payload, ExecutionResultPayload):
        return payload.failure_class
    return None


def _payload_from_runtime_event(event: RuntimeEvent) -> ExecutionEventPayload:
    if not isinstance(event.payload, dict):
        msg = "runtime event does not carry typed execution payload evidence"
        raise TypeError(msg)
    raw_event_type = event.payload.get("execution_event_type")
    if not isinstance(raw_event_type, str) or raw_event_type not in _PAYLOAD_MODELS:
        msg = "runtime event does not carry typed execution payload evidence"
        raise ValueError(msg)
    payload_model = _PAYLOAD_MODELS[raw_event_type]
    return payload_model.model_validate(event.payload)


_PAYLOAD_MODELS = {
    "execution.plan_created": ExecutionPlanPayload,
    "execution.plan_approved": ExecutionPlanPayload,
    "execution.step_started": ExecutionStepPayload,
    "execution.step_completed": ExecutionStepPayload,
    "execution.step_failed": ExecutionStepPayload,
    "execution.result_recorded": ExecutionResultPayload,
}
