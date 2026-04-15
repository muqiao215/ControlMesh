"""One bounded recovery thin loop over decision -> orchestrator -> result."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from controlmesh_runtime.recovery import (
    RecoveryContext,
    RecoveryDecision,
    RecoveryExecutionResult,
    RecoveryPolicy,
    evaluate_recovery_policy,
)
from controlmesh_runtime.thin_orchestrator import OrchestratorRequest


class RecoveryLoopRequest(BaseModel):
    """Input for one straight-line recovery cycle."""

    model_config = ConfigDict(frozen=True)

    packet_id: str = "recovery-cycle"
    context: RecoveryContext
    policy_snapshot: RecoveryPolicy = Field(default_factory=RecoveryPolicy)


class RecoveryLoopOutcome(BaseModel):
    """Output for one bounded recovery cycle."""

    model_config = ConfigDict(frozen=True)

    decision: RecoveryDecision
    result: RecoveryExecutionResult
    terminal: bool = True
    runtime_events: tuple[object, ...] = ()
    stop_reason: str | None = None


async def run_recovery_cycle(
    request: RecoveryLoopRequest,
    *,
    orchestrator: Any,
) -> RecoveryLoopOutcome:
    """Run one bounded recovery cycle and stop after the first typed result."""
    decision = evaluate_recovery_policy(request.context, request.policy_snapshot)
    run = await orchestrator.run(
        OrchestratorRequest(
            packet_id=request.packet_id,
            task_id=request.context.task_id,
            line=request.context.line,
            worker_id=request.context.worker_id,
            decision=decision,
            policy_snapshot=request.policy_snapshot,
        )
    )
    return RecoveryLoopOutcome(
        decision=decision,
        result=run.result,
        terminal=True,
        runtime_events=run.runtime_events,
        stop_reason=None if run.stop_reason is None else run.stop_reason.value,
    )


__all__ = ["RecoveryLoopOutcome", "RecoveryLoopRequest", "run_recovery_cycle"]
