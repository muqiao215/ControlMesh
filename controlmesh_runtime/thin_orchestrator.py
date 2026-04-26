"""Thin runtime orchestrator for one bounded recovery execution pass."""

from __future__ import annotations

from contextlib import suppress
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.engine import (
    EngineExecution,
    EngineRequest,
    EngineState,
    EngineStopReason,
    EngineTraceEvent,
    build_first_engine_plan,
    execute_first_engine_plan,
)
from controlmesh_runtime.execution_payloads import build_execution_payload
from controlmesh_runtime.execution_runtime_events import build_runtime_event_from_execution_payload
from controlmesh_runtime.recovery import (
    RecoveryDecision,
    RecoveryExecutionAction,
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
    RecoveryPolicy,
)
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.worker_controller import WorkerController, WorkerControllerError
from controlmesh_runtime.worker_state import WorkerState


class OrchestratorRequest(BaseModel):
    """Thin orchestrator input over already-typed runtime objects."""

    model_config = ConfigDict(frozen=True)

    packet_id: str
    task_id: str
    line: str
    worker_id: str | None
    decision: RecoveryDecision
    policy_snapshot: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    runtime_stage: RuntimeStage | None = None

    @model_validator(mode="after")
    def validate_request(self) -> OrchestratorRequest:
        if not self.packet_id.strip():
            msg = "orchestrator request packet_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "orchestrator request task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "orchestrator request line must not be empty"
            raise ValueError(msg)
        return self


class OrchestratorRun(BaseModel):
    """Bounded orchestrator output: plan, result, and typed evidence only."""

    model_config = ConfigDict(frozen=True)

    plan_id: str
    plan: object
    result: RecoveryExecutionResult
    runtime_events: tuple[object, ...]
    final_worker_state: WorkerState | None = None
    stop_reason: EngineStopReason | None = None
    final_state: EngineState

    @property
    def completed(self) -> bool:
        return self.final_state is EngineState.COMPLETED


class ThinOrchestrator:
    """Stitch decision -> plan -> worker action -> typed evidence without owning policy or truth."""

    def __init__(self, *, worker_controller: WorkerController) -> None:
        self._worker_controller = worker_controller

    async def run(self, request: OrchestratorRequest) -> OrchestratorRun:
        engine_request = EngineRequest(
            decision=request.decision,
            packet_id=request.packet_id,
            task_id=request.task_id,
            line=request.line,
            worker_id=request.worker_id,
            policy_snapshot=request.policy_snapshot,
        )
        plan = build_first_engine_plan(engine_request)
        probe = execute_first_engine_plan(plan)
        if probe.final_state is EngineState.STOPPED:
            return self._build_run_from_engine_execution(
                packet_id=request.packet_id,
                execution=probe,
                stage=request.runtime_stage,
            )

        trace: list[EngineTraceEvent] = [
            _trace("execution.plan_created", plan_id=plan.plan_id, task_id=plan.task_id, worker_id=plan.worker_id),
        ]
        completed_step_count = 0
        final_worker_state: WorkerState | None = None

        for step_index, step in enumerate(plan.steps):
            trace.append(
                _trace(
                    "execution.step_started",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    worker_id=plan.worker_id,
                    step_index=step_index,
                    action=step.action,
                )
            )
            try:
                final_worker_state = await self._execute_step(step.action, request.worker_id)
            except WorkerControllerError as exc:
                trace.append(
                    _trace(
                        "execution.step_failed",
                        plan_id=plan.plan_id,
                        task_id=plan.task_id,
                        worker_id=plan.worker_id,
                        step_index=step_index,
                        action=step.action,
                    )
                )
                result = RecoveryExecutionResult(
                    plan_id=plan.plan_id,
                    evidence_identity=plan.evidence_identity,
                    status=RecoveryExecutionStatus.FAILED,
                    completed_step_count=completed_step_count,
                    failed_step_index=step_index,
                    failure_class=exc.failure_class,
                )
                trace.append(
                    _trace(
                        "execution.result_recorded",
                        plan_id=plan.plan_id,
                        task_id=plan.task_id,
                        worker_id=plan.worker_id,
                        result_status=result.status,
                    )
                )
                return self._build_run(
                    packet_id=request.packet_id,
                    plan=plan,
                    result=result,
                    trace=tuple(trace),
                    stage=request.runtime_stage,
                    final_state=EngineState.FAILED,
                    final_worker_state=final_worker_state,
                )

            completed_step_count += 1
            trace.append(
                _trace(
                    "execution.step_completed",
                    plan_id=plan.plan_id,
                    task_id=plan.task_id,
                    worker_id=plan.worker_id,
                    step_index=step_index,
                    action=step.action,
                )
            )

        result = RecoveryExecutionResult(
            plan_id=plan.plan_id,
            evidence_identity=plan.evidence_identity,
            status=RecoveryExecutionStatus.COMPLETED,
            completed_step_count=completed_step_count,
        )
        trace.append(
            _trace(
                "execution.result_recorded",
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                worker_id=plan.worker_id,
                result_status=result.status,
            )
        )
        return self._build_run(
            packet_id=request.packet_id,
            plan=plan,
            result=result,
            trace=tuple(trace),
            stage=request.runtime_stage,
            final_state=EngineState.COMPLETED,
            final_worker_state=final_worker_state,
        )

    async def _execute_step(
        self,
        action: RecoveryExecutionAction,
        worker_id: str | None,
    ) -> WorkerState:
        if worker_id is None:
            msg = "worker-targeted orchestrator step requires worker_id"
            raise ValueError(msg)
        if action is RecoveryExecutionAction.RETRY_SAME_WORKER:
            return await self._worker_controller.await_ready(worker_id, timeout_seconds=5.0)
        if action is RecoveryExecutionAction.RESTART_WORKER:
            return await self._worker_controller.restart(worker_id)
        if action is RecoveryExecutionAction.RECREATE_WORKER:
            with suppress(WorkerControllerError):
                await self._worker_controller.terminate(worker_id)
            return await self._worker_controller.create(worker_id)
        msg = f"unsupported thin orchestrator action '{action.value}'"
        raise ValueError(msg)

    def _build_run_from_engine_execution(
        self,
        *,
        packet_id: str,
        execution: EngineExecution,
        stage: RuntimeStage | None,
    ) -> OrchestratorRun:
        return self._build_run(
            packet_id=packet_id,
            plan=execution.plan,
            result=execution.result,
            trace=execution.trace,
            stage=stage,
            final_state=execution.final_state,
            stop_reason=execution.stop_reason,
        )

    def _build_run(
        self,
        *,
        packet_id: str,
        plan: RecoveryExecutionPlan,
        result: RecoveryExecutionResult,
        trace: tuple[EngineTraceEvent, ...],
        stage: RuntimeStage | None,
        final_state: EngineState,
        final_worker_state: WorkerState | None = None,
        stop_reason: EngineStopReason | None = None,
    ) -> OrchestratorRun:
        runtime_events = []
        for trace_event in trace:
            failure_class = result.failure_class if trace_event.execution_event_type == "execution.step_failed" else None
            payload = build_execution_payload(
                trace_event,
                plan=plan,
                result=result if trace_event.execution_event_type == "execution.result_recorded" else None,
                failure_class=failure_class,
            )
            runtime_events.append(
                build_runtime_event_from_execution_payload(
                    payload,
                    packet_id=packet_id,
                    message=_message_for_trace_event(trace_event),
                    stage=stage,
                )
            )
        return OrchestratorRun(
            plan_id=plan.plan_id,
            plan=plan,
            result=result,
            runtime_events=tuple(runtime_events),
            final_worker_state=final_worker_state,
            stop_reason=stop_reason,
            final_state=final_state,
        )


def _trace(
    execution_event_type: Literal[
        "execution.plan_created",
        "execution.step_started",
        "execution.step_completed",
        "execution.step_failed",
        "execution.result_recorded",
    ],
    *,
    plan_id: str,
    task_id: str,
    worker_id: str | None,
    step_index: int | None = None,
    action: RecoveryExecutionAction | None = None,
    result_status: RecoveryExecutionStatus | None = None,
) -> EngineTraceEvent:
    return EngineTraceEvent(
        execution_event_type=execution_event_type,
        plan_id=plan_id,
        task_id=task_id,
        worker_id=worker_id,
        step_index=step_index,
        action=action,
        result_status=result_status,
    )


def _message_for_trace_event(trace_event: EngineTraceEvent) -> str:
    event_type = trace_event.execution_event_type
    if event_type == "execution.plan_created":
        return "Recovery execution plan created"
    if event_type == "execution.plan_approved":
        return "Recovery execution plan approved"
    if event_type == "execution.step_started":
        return "Recovery execution step started"
    if event_type == "execution.step_completed":
        return "Recovery execution step completed"
    if event_type == "execution.step_failed":
        return "Recovery execution step failed"
    return "Recovery execution result recorded"


__all__ = ["OrchestratorRequest", "OrchestratorRun", "ThinOrchestrator"]
