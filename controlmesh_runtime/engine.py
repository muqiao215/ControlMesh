"""Engine-local first recovery executor for the ControlMesh runtime."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.events import EventKind
from controlmesh_runtime.recovery import (
    EscalationLevel,
    RecoveryDecision,
    RecoveryExecutionAction,
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryExecutionStep,
    RecoveryIntent,
    RecoveryPolicy,
)


class EngineState(StrEnum):
    """Linear first-engine execution states."""

    READY = auto()
    RUNNING = auto()
    STOPPED = auto()
    COMPLETED = auto()
    FAILED = auto()


class EngineStopReason(StrEnum):
    """Explicit reasons the first engine stops instead of executing."""

    HUMAN_GATE_REQUIRED = auto()
    DESTRUCTIVE_STEP_NOT_AUTHORIZED = auto()
    ADAPTER_SPECIFIC_ACTION_REQUIRED = auto()
    PROMOTION_REQUIRED_OUTSIDE_ENGINE = auto()
    STORE_DETAIL_LEAK = auto()
    EVENT_BUS_DETAIL_LEAK = auto()
    TRANSPORT_OR_PROVIDER_DETAIL_LEAK = auto()
    POLICY_RECALCULATION_REQUIRED = auto()
    MISSING_WORKER_ID = auto()
    UNSUPPORTED_FIRST_CUT_INTENT = auto()
    UNSUPPORTED_PLAN_METADATA = auto()
    UNSUPPORTED_STEP_ARGS = auto()


ExecutionEventType = Literal[
    "execution.plan_created",
    "execution.plan_approved",
    "execution.step_started",
    "execution.step_completed",
    "execution.step_failed",
    "execution.result_recorded",
]


class EngineTraceEvent(BaseModel):
    """One in-memory execution trace event."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    execution_event_type: ExecutionEventType
    plan_id: str
    task_id: str
    worker_id: str | None = None
    step_index: int | None = None
    action: RecoveryExecutionAction | None = None
    result_status: RecoveryExecutionStatus | None = None
    stop_reason: EngineStopReason | None = None


class EngineRequest(BaseModel):
    """Narrow input accepted by the first engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: RecoveryDecision
    packet_id: str
    task_id: str
    line: str
    worker_id: str | None
    policy_snapshot: RecoveryPolicy = Field(default_factory=RecoveryPolicy)

    @model_validator(mode="after")
    def validate_request(self) -> EngineRequest:
        """Reject malformed engine-local requests."""
        if not self.packet_id.strip():
            msg = "engine request packet_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "engine request task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "engine request line must not be empty"
            raise ValueError(msg)
        if self.worker_id is not None and not self.worker_id.strip():
            msg = "engine request worker_id must not be blank"
            raise ValueError(msg)
        return self


class EngineExecution(BaseModel):
    """Engine-local output for one first-engine run."""

    model_config = ConfigDict(frozen=True)

    plan: RecoveryExecutionPlan
    result: RecoveryExecutionResult
    trace: tuple[EngineTraceEvent, ...]
    final_state: EngineState
    stop_reason: EngineStopReason | None = None

    @model_validator(mode="after")
    def validate_execution(self) -> EngineExecution:
        """Keep engine execution truth linear and terminally well-formed."""
        if self.final_state is EngineState.COMPLETED and self.result.status is not RecoveryExecutionStatus.COMPLETED:
            msg = "completed engine executions require completed results"
            raise ValueError(msg)
        if self.final_state is EngineState.FAILED and self.result.status is not RecoveryExecutionStatus.FAILED:
            msg = "failed engine executions require failed results"
            raise ValueError(msg)
        if self.final_state is EngineState.STOPPED and self.stop_reason is None:
            msg = "stopped engine executions require stop_reason"
            raise ValueError(msg)
        if self.result.plan_id != self.plan.plan_id:
            msg = "engine execution result plan_id must match the plan"
            raise ValueError(msg)
        if self.result.evidence_identity != self.plan.evidence_identity:
            msg = "engine execution result evidence identity must match the plan"
            raise ValueError(msg)

        result_recorded_indexes = [
            index
            for index, event in enumerate(self.trace)
            if event.execution_event_type == "execution.result_recorded"
        ]
        if len(result_recorded_indexes) != 1:
            msg = "trace must contain exactly one result_recorded event"
            raise ValueError(msg)
        if result_recorded_indexes[0] != len(self.trace) - 1:
            msg = "trace must not contain events after result_recorded"
            raise ValueError(msg)
        return self


_ALLOWED_TRANSITIONS: dict[EngineState, frozenset[EngineState]] = {
    EngineState.READY: frozenset({EngineState.RUNNING}),
    EngineState.RUNNING: frozenset(
        {
            EngineState.STOPPED,
            EngineState.COMPLETED,
            EngineState.FAILED,
        }
    ),
    EngineState.STOPPED: frozenset(),
    EngineState.COMPLETED: frozenset(),
    EngineState.FAILED: frozenset(),
}

_WORKER_TARGETED_INTENTS: frozenset[RecoveryIntent] = frozenset(
    {
        RecoveryIntent.RETRY_SAME_WORKER,
        RecoveryIntent.RESTART_WORKER,
        RecoveryIntent.RECREATE_WORKER,
    }
)

_RUNNABLE_INTENT_ACTIONS: dict[RecoveryIntent, RecoveryExecutionAction] = {
    RecoveryIntent.RETRY_SAME_WORKER: RecoveryExecutionAction.RETRY_SAME_WORKER,
    RecoveryIntent.RESTART_WORKER: RecoveryExecutionAction.RESTART_WORKER,
    RecoveryIntent.RECREATE_WORKER: RecoveryExecutionAction.RECREATE_WORKER,
}

_RUNNABLE_ACTIONS: frozenset[RecoveryExecutionAction] = frozenset(_RUNNABLE_INTENT_ACTIONS.values())

_PROMOTION_ACTIONS: frozenset[RecoveryExecutionAction] = frozenset(
    {
        RecoveryExecutionAction.SPLIT_SCOPE,
        RecoveryExecutionAction.DEFER_LINE,
        RecoveryExecutionAction.STOPLINE,
    }
)

_PROMOTION_INTENT_ACTIONS: dict[RecoveryIntent, RecoveryExecutionAction] = {
    RecoveryIntent.SPLIT_SCOPE: RecoveryExecutionAction.SPLIT_SCOPE,
    RecoveryIntent.DEFER_LINE: RecoveryExecutionAction.DEFER_LINE,
    RecoveryIntent.STOPLINE: RecoveryExecutionAction.STOPLINE,
}

_HANDOFF_INTENT_STOP_REASONS: dict[RecoveryIntent, EngineStopReason] = {
    RecoveryIntent.REQUIRE_REAUTH: EngineStopReason.ADAPTER_SPECIFIC_ACTION_REQUIRED,
    RecoveryIntent.REQUIRE_OPERATOR_ACTION: EngineStopReason.HUMAN_GATE_REQUIRED,
    RecoveryIntent.SPLIT_SCOPE: EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE,
    RecoveryIntent.DEFER_LINE: EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE,
    RecoveryIntent.STOPLINE: EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE,
    RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE: EngineStopReason.UNSUPPORTED_FIRST_CUT_INTENT,
}


def can_transition_engine_state(from_state: EngineState, to_state: EngineState) -> bool:
    """Return whether a first-engine state transition is allowed."""
    return to_state in _ALLOWED_TRANSITIONS[from_state]


def run_first_engine(request: EngineRequest) -> EngineExecution:
    """Derive and execute one engine-local recovery plan."""
    return execute_first_engine_plan(build_first_engine_plan(request))


def build_first_engine_plan(request: EngineRequest) -> RecoveryExecutionPlan:
    """Derive one first-engine plan without performing step execution."""
    if request.decision.intent in _WORKER_TARGETED_INTENTS and not _has_explicit_worker_id(request.worker_id):
        return _stop_plan(request)
    if _requires_human_gate(request.decision):
        return _human_gate_plan(request)
    if request.decision.intent is RecoveryIntent.REFRESH_BRANCH_OR_WORKTREE:
        return _stop_plan(request)
    return _derive_plan(request)


def execute_first_engine_plan(plan: RecoveryExecutionPlan) -> EngineExecution:
    """Execute one already-derived plan through the engine-local guardrails."""
    trace = [_trace("execution.plan_created", plan)]

    preflight_stop = _preflight_stop(plan)
    if preflight_stop is not None:
        stop_reason, status, requires_human_gate, trace_approved = preflight_stop
        if trace_approved:
            trace.append(_trace("execution.plan_approved", plan))
        return _stopped_execution(
            plan,
            stop_reason,
            trace=tuple(trace),
            status=status,
            requires_human_gate=requires_human_gate,
        )

    completed_step_count = 0
    for step_index, step in enumerate(plan.steps):
        stop_reason = _stop_reason_for_step(step)
        if stop_reason is not None:
            return _stopped_execution(plan, stop_reason, trace=tuple(trace))
        trace.append(_trace("execution.step_started", plan, step_info=(step_index, step)))
        completed_step_count += 1
        trace.append(_trace("execution.step_completed", plan, step_info=(step_index, step)))

    result = RecoveryExecutionResult(
        plan_id=plan.plan_id,
        evidence_identity=plan.evidence_identity,
        status=RecoveryExecutionStatus.COMPLETED,
        completed_step_count=completed_step_count,
        emitted_event_types=(EventKind.TASK_PROGRESS, EventKind.TASK_RESULT_REPORTED),
    )
    trace.append(
        _trace(
            "execution.result_recorded",
            plan,
            result_status=result.status,
        )
    )
    return EngineExecution(
        plan=plan,
        result=result,
        trace=tuple(trace),
        final_state=EngineState.COMPLETED,
    )


def _requires_human_gate(decision: RecoveryDecision) -> bool:
    return decision.escalation is EscalationLevel.HUMAN_GATE or decision.human_gate_reason is not None


def _preflight_stop(
    plan: RecoveryExecutionPlan,
) -> tuple[EngineStopReason, RecoveryExecutionStatus, bool, bool] | None:
    if plan.metadata:
        return (EngineStopReason.UNSUPPORTED_PLAN_METADATA, RecoveryExecutionStatus.ABORTED, False, False)
    if any(step.args for step in plan.steps):
        return (EngineStopReason.UNSUPPORTED_STEP_ARGS, RecoveryExecutionStatus.ABORTED, False, False)
    if plan.intent in _WORKER_TARGETED_INTENTS and not _has_explicit_worker_id(plan.worker_id):
        return (EngineStopReason.MISSING_WORKER_ID, RecoveryExecutionStatus.ABORTED, False, False)
    if plan.requires_human_gate or any(step.requires_human_gate for step in plan.steps):
        return (
            EngineStopReason.HUMAN_GATE_REQUIRED,
            RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE,
            True,
            True,
        )

    intent_stop_reason = _HANDOFF_INTENT_STOP_REASONS.get(plan.intent)
    if intent_stop_reason is not None:
        return (intent_stop_reason, RecoveryExecutionStatus.ABORTED, False, False)
    return None


def _has_explicit_worker_id(worker_id: str | None) -> bool:
    if worker_id is None:
        return False
    normalized = worker_id.strip()
    return bool(normalized) and normalized.lower() != "default"


def _derive_plan(request: EngineRequest) -> RecoveryExecutionPlan:
    action = _RUNNABLE_INTENT_ACTIONS.get(request.decision.intent)
    if action is not None:
        return RecoveryExecutionPlan(
            packet_id=request.packet_id,
            task_id=request.task_id,
            line=request.line,
            worker_id=request.worker_id,
            intent=request.decision.intent,
            steps=(
                RecoveryExecutionStep(
                    action=action,
                    target=f"worker:{request.worker_id}",
                    retryable=True,
                ),
            ),
            policy_snapshot=request.policy_snapshot,
            next_step_token=request.decision.next_step_token,
        )

    if request.decision.intent is RecoveryIntent.REQUIRE_REAUTH:
        return RecoveryExecutionPlan(
            packet_id=request.packet_id,
            task_id=request.task_id,
            line=request.line,
            worker_id=request.worker_id,
            intent=request.decision.intent,
            steps=(
                RecoveryExecutionStep(
                    action=RecoveryExecutionAction.MARK_REAUTH_REQUIRED,
                    target="engine:reauth-handoff",
                ),
            ),
            policy_snapshot=request.policy_snapshot,
            next_step_token=request.decision.next_step_token,
        )

    promotion_action = _PROMOTION_INTENT_ACTIONS.get(request.decision.intent)
    if promotion_action is not None:
        return RecoveryExecutionPlan(
            packet_id=request.packet_id,
            task_id=request.task_id,
            line=request.line,
            worker_id=request.worker_id,
            intent=request.decision.intent,
            steps=(
                RecoveryExecutionStep(
                    action=promotion_action,
                    target=f"canonical:{request.line}",
                    destructive=True,
                ),
            ),
            policy_snapshot=request.policy_snapshot,
            next_step_token=request.decision.next_step_token,
        )

    return _human_gate_plan(request)


def _human_gate_plan(request: EngineRequest) -> RecoveryExecutionPlan:
    human_gate_reason = request.decision.human_gate_reason or "engine handoff requires human gate"
    return RecoveryExecutionPlan(
        packet_id=request.packet_id,
        task_id=request.task_id,
        line=request.line,
        worker_id=request.worker_id,
        intent=request.decision.intent,
        steps=(
            RecoveryExecutionStep(
                action=RecoveryExecutionAction.EMIT_HUMAN_GATE,
                target="gate:operator",
                requires_human_gate=True,
            ),
        ),
        requires_human_gate=True,
        human_gate_reasons=(human_gate_reason,),
        policy_snapshot=request.policy_snapshot,
        next_step_token=request.decision.next_step_token,
    )


def _stop_plan(request: EngineRequest) -> RecoveryExecutionPlan:
    return RecoveryExecutionPlan(
        packet_id=request.packet_id,
        task_id=request.task_id,
        line=request.line,
        worker_id=request.worker_id,
        intent=request.decision.intent,
        steps=(
            RecoveryExecutionStep(
                action=RecoveryExecutionAction.EMIT_HUMAN_GATE,
                target="engine:stop",
            ),
        ),
        policy_snapshot=request.policy_snapshot,
        next_step_token=request.decision.next_step_token,
    )


def _stop_reason_for_step(step: RecoveryExecutionStep) -> EngineStopReason | None:
    stop_reason: EngineStopReason | None = None
    if step.args:
        stop_reason = EngineStopReason.UNSUPPORTED_STEP_ARGS
    elif step.action in _PROMOTION_ACTIONS or step.target.startswith("canonical:"):
        stop_reason = EngineStopReason.PROMOTION_REQUIRED_OUTSIDE_ENGINE
    elif step.action is RecoveryExecutionAction.MARK_REAUTH_REQUIRED:
        stop_reason = EngineStopReason.ADAPTER_SPECIFIC_ACTION_REQUIRED
    elif step.action is RecoveryExecutionAction.EMIT_HUMAN_GATE or step.requires_human_gate:
        stop_reason = EngineStopReason.HUMAN_GATE_REQUIRED
    elif step.target.startswith("store:"):
        stop_reason = EngineStopReason.STORE_DETAIL_LEAK
    elif step.target.startswith("event_bus:"):
        stop_reason = EngineStopReason.EVENT_BUS_DETAIL_LEAK
    elif step.target.startswith(("transport:", "provider:")):
        stop_reason = EngineStopReason.TRANSPORT_OR_PROVIDER_DETAIL_LEAK
    elif step.destructive or step.action is RecoveryExecutionAction.CLEAR_RUNTIME_STATE:
        stop_reason = EngineStopReason.DESTRUCTIVE_STEP_NOT_AUTHORIZED
    elif step.action not in _RUNNABLE_ACTIONS:
        stop_reason = EngineStopReason.ADAPTER_SPECIFIC_ACTION_REQUIRED
    return stop_reason


def _stopped_execution(
    plan: RecoveryExecutionPlan,
    reason: EngineStopReason,
    *,
    trace: tuple[EngineTraceEvent, ...] | None = None,
    status: RecoveryExecutionStatus = RecoveryExecutionStatus.ABORTED,
    requires_human_gate: bool = False,
) -> EngineExecution:
    trace_items = list(trace or (_trace("execution.plan_created", plan),))
    result = RecoveryExecutionResult(
        plan_id=plan.plan_id,
        evidence_identity=plan.evidence_identity,
        status=status,
        completed_step_count=0,
        requires_human_gate=requires_human_gate,
        emitted_event_types=(EventKind.TASK_RESULT_REPORTED,),
        notes=(reason.value,),
    )
    trace_items.append(
        _trace(
            "execution.result_recorded",
            plan,
            result_status=result.status,
            stop_reason=reason,
        )
    )
    return EngineExecution(
        plan=plan,
        result=result,
        trace=tuple(trace_items),
        final_state=EngineState.STOPPED,
        stop_reason=reason,
    )


def _trace(
    execution_event_type: ExecutionEventType,
    plan: RecoveryExecutionPlan,
    *,
    step_info: tuple[int, RecoveryExecutionStep] | None = None,
    result_status: RecoveryExecutionStatus | None = None,
    stop_reason: EngineStopReason | None = None,
) -> EngineTraceEvent:
    step_index = None if step_info is None else step_info[0]
    step = None if step_info is None else step_info[1]
    return EngineTraceEvent(
        execution_event_type=execution_event_type,
        plan_id=plan.plan_id,
        task_id=plan.task_id,
        worker_id=plan.worker_id,
        step_index=step_index,
        action=step.action if step is not None else None,
        result_status=result_status,
        stop_reason=stop_reason,
    )
