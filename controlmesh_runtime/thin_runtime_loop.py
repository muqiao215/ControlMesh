"""Controller-owned thin runtime loop over one bounded recovery cycle."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from controlmesh_runtime.recovery import (
    EscalationLevel,
    RecoveryContext,
    RecoveryDecision,
    RecoveryExecutionResult,
    RecoveryIntent,
    RecoveryPolicy,
    evaluate_recovery_policy,
)
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.thin_orchestrator import OrchestratorRequest, ThinOrchestrator
from controlmesh_runtime.worker_controller import WorkerController
from controlmesh_runtime.worker_state import WorkerState

_RUNTIME_RUNNABLE_INTENTS = frozenset(
    {
        RecoveryIntent.RETRY_SAME_WORKER,
        RecoveryIntent.RESTART_WORKER,
        RecoveryIntent.RECREATE_WORKER,
    }
)


class ThinRuntimeLoopRequest(BaseModel):
    """Input for one controller-owned thin runtime loop pass."""

    model_config = ConfigDict(frozen=True)

    packet_id: str = "runtime-cycle"
    context: RecoveryContext
    policy_snapshot: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    runtime_stage: RuntimeStage | None = None


class ThinRuntimeLoopOutcome(BaseModel):
    """Output for one bounded thin runtime loop pass."""

    model_config = ConfigDict(frozen=True)

    decision: RecoveryDecision
    plan_id: str | None
    result: RecoveryExecutionResult
    terminal: bool = True
    runtime_runnable: bool
    runtime_events: tuple[object, ...] = ()
    stop_reason: str | None = None
    final_worker_state: WorkerState | None = None


class ThinRuntimeLoop:
    """Compose policy evaluation and thin orchestration without owning truth."""

    def __init__(self, *, worker_controller: WorkerController) -> None:
        self._orchestrator = ThinOrchestrator(worker_controller=worker_controller)

    async def run(self, request: ThinRuntimeLoopRequest) -> ThinRuntimeLoopOutcome:
        decision = evaluate_recovery_policy(request.context, request.policy_snapshot)
        run = await self._orchestrator.run(
            OrchestratorRequest(
                packet_id=request.packet_id,
                task_id=request.context.task_id,
                line=request.context.line,
                worker_id=request.context.worker_id,
                decision=decision,
                policy_snapshot=request.policy_snapshot,
                runtime_stage=request.runtime_stage,
            )
        )
        return ThinRuntimeLoopOutcome(
            decision=decision,
            plan_id=run.plan_id,
            result=run.result,
            terminal=True,
            runtime_runnable=_is_runtime_runnable(decision),
            runtime_events=run.runtime_events,
            stop_reason=None if run.stop_reason is None else run.stop_reason.value,
            final_worker_state=run.final_worker_state,
        )


def _is_runtime_runnable(decision: RecoveryDecision) -> bool:
    return (
        decision.escalation is not EscalationLevel.HUMAN_GATE
        and decision.intent in _RUNTIME_RUNNABLE_INTENTS
    )


__all__ = ["ThinRuntimeLoop", "ThinRuntimeLoopOutcome", "ThinRuntimeLoopRequest"]
