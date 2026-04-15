"""Typed execution payloads and pure trace-to-payload conversion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.engine import EngineStopReason, EngineTraceEvent
from controlmesh_runtime.events import EventKind, FailureClass
from controlmesh_runtime.recovery import (
    RecoveryExecutionAction,
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryExecutionStep,
    RecoveryIntent,
)

ExecutionPayloadEventType = Literal[
    "execution.plan_created",
    "execution.plan_approved",
    "execution.step_started",
    "execution.step_completed",
    "execution.step_failed",
    "execution.result_recorded",
]

PlanPayloadEventType = Literal["execution.plan_created", "execution.plan_approved"]
StepPayloadEventType = Literal[
    "execution.step_started",
    "execution.step_completed",
    "execution.step_failed",
]
ResultPayloadEventType = Literal["execution.result_recorded"]


class ExecutionPlanPayload(BaseModel):
    """Typed execution evidence for plan-level events."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    execution_event_type: PlanPayloadEventType
    plan_id: str
    task_id: str
    line: str
    worker_id: str | None
    intent: RecoveryIntent
    requires_human_gate: bool
    next_step_token: str
    human_gate_reasons: tuple[str, ...] = ()
    step_count: int | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> ExecutionPlanPayload:
        """Keep plan payloads explicit and bounded."""
        if not self.plan_id.strip():
            msg = "execution plan payload plan_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "execution plan payload task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "execution plan payload line must not be empty"
            raise ValueError(msg)
        if not self.next_step_token.strip():
            msg = "execution plan payload next_step_token must not be empty"
            raise ValueError(msg)
        if self.step_count is not None and self.step_count < 0:
            msg = "execution plan payload step_count must be >= 0"
            raise ValueError(msg)
        if any(not reason.strip() for reason in self.human_gate_reasons):
            msg = "execution plan payload human_gate_reasons must not contain blank items"
            raise ValueError(msg)
        return self


class ExecutionStepPayload(BaseModel):
    """Typed execution evidence for one step event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    execution_event_type: StepPayloadEventType
    plan_id: str
    task_id: str
    line: str
    worker_id: str | None
    step_index: int
    action: RecoveryExecutionAction
    target: str
    requires_human_gate: bool
    failure_class: FailureClass | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> ExecutionStepPayload:
        """Keep step payloads linear and failure-aware."""
        if not self.plan_id.strip():
            msg = "execution step payload plan_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "execution step payload task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "execution step payload line must not be empty"
            raise ValueError(msg)
        if self.step_index < 0:
            msg = "execution step payload step_index must be >= 0"
            raise ValueError(msg)
        if not self.target.strip():
            msg = "execution step payload target must not be empty"
            raise ValueError(msg)
        if self.execution_event_type == "execution.step_failed" and self.failure_class is None:
            msg = "step_failed payloads require failure_class"
            raise ValueError(msg)
        if self.execution_event_type != "execution.step_failed" and self.failure_class is not None:
            msg = "only step_failed payloads may carry failure_class"
            raise ValueError(msg)
        return self


class ExecutionResultPayload(BaseModel):
    """Typed execution evidence for final result recording."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    execution_event_type: ResultPayloadEventType = "execution.result_recorded"
    plan_id: str
    task_id: str
    line: str
    worker_id: str | None
    result_status: RecoveryExecutionStatus
    completed_step_count: int
    requires_human_gate: bool
    failed_step_index: int | None = None
    failure_class: FailureClass | None = None
    next_review_outcome_hint: ReviewOutcome | None = None
    stop_reason: EngineStopReason | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> ExecutionResultPayload:
        """Keep result payloads explicit and consistent."""
        if not self.plan_id.strip():
            msg = "execution result payload plan_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "execution result payload task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "execution result payload line must not be empty"
            raise ValueError(msg)
        if self.completed_step_count < 0:
            msg = "execution result payload completed_step_count must be >= 0"
            raise ValueError(msg)
        if self.failed_step_index is not None and self.failed_step_index < 0:
            msg = "execution result payload failed_step_index must be >= 0"
            raise ValueError(msg)
        return self


ExecutionEventPayload = ExecutionPlanPayload | ExecutionStepPayload | ExecutionResultPayload


def build_execution_payload(
    trace_event: EngineTraceEvent,
    *,
    plan: RecoveryExecutionPlan,
    result: RecoveryExecutionResult | None = None,
    failure_class: FailureClass | None = None,
) -> ExecutionEventPayload:
    """Convert one engine-local trace event into a typed execution payload."""
    _validate_trace_matches_plan(trace_event, plan)

    event_type = trace_event.execution_event_type
    if event_type in {"execution.plan_created", "execution.plan_approved"}:
        return ExecutionPlanPayload(
            execution_event_type=event_type,
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            line=plan.line,
            worker_id=plan.worker_id,
            intent=plan.intent,
            requires_human_gate=plan.requires_human_gate,
            next_step_token=plan.next_step_token,
            human_gate_reasons=plan.human_gate_reasons,
            step_count=len(plan.steps),
        )

    if event_type in {
        "execution.step_started",
        "execution.step_completed",
        "execution.step_failed",
    }:
        step = _step_for_trace(trace_event, plan)
        effective_failure_class = failure_class if event_type == "execution.step_failed" else None
        return ExecutionStepPayload(
            execution_event_type=event_type,
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            line=plan.line,
            worker_id=plan.worker_id,
            step_index=trace_event.step_index,
            action=step.action,
            target=step.target,
            requires_human_gate=step.requires_human_gate,
            failure_class=effective_failure_class,
        )

    if result is None:
        msg = "result_recorded payload conversion requires result"
        raise ValueError(msg)
    if result.plan_id != plan.plan_id:
        msg = "result plan_id must match plan for payload conversion"
        raise ValueError(msg)
    return ExecutionResultPayload(
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        line=plan.line,
        worker_id=plan.worker_id,
        result_status=result.status,
        completed_step_count=result.completed_step_count,
        requires_human_gate=result.requires_human_gate,
        failed_step_index=result.failed_step_index,
        failure_class=result.failure_class,
        next_review_outcome_hint=result.next_review_outcome_hint,
        stop_reason=trace_event.stop_reason,
    )


def event_kind_for_execution_payload(payload: ExecutionEventPayload) -> EventKind:
    """Map a typed execution payload onto the coarse runtime event kind."""
    if payload.execution_event_type == "execution.result_recorded":
        return EventKind.TASK_RESULT_REPORTED
    if payload.execution_event_type == "execution.step_failed":
        return EventKind.TASK_FAILED
    return EventKind.TASK_PROGRESS


def _validate_trace_matches_plan(trace_event: EngineTraceEvent, plan: RecoveryExecutionPlan) -> None:
    if trace_event.plan_id != plan.plan_id:
        msg = "trace plan_id must match plan for payload conversion"
        raise ValueError(msg)
    if trace_event.task_id != plan.task_id:
        msg = "trace task_id must match plan for payload conversion"
        raise ValueError(msg)
    if trace_event.worker_id != plan.worker_id:
        msg = "trace worker_id must match plan for payload conversion"
        raise ValueError(msg)


def _step_for_trace(
    trace_event: EngineTraceEvent,
    plan: RecoveryExecutionPlan,
) -> RecoveryExecutionStep:
    step_index = trace_event.step_index
    if step_index is None:
        msg = "step payload conversion requires trace step_index"
        raise ValueError(msg)
    if step_index < 0 or step_index >= len(plan.steps):
        msg = "trace step_index is outside the plan step range"
        raise ValueError(msg)

    step = plan.steps[step_index]
    if trace_event.action is not None and trace_event.action is not step.action:
        msg = "trace action must match plan step action for payload conversion"
        raise ValueError(msg)
    return step
