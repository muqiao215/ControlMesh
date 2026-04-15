"""Autonomous runtime loop over checkpointing, summary triggers, and controlled promotion."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.execution_read_surface import ExecutionEvidenceReadSurface
from controlmesh_runtime.promotion_bridge import PromotionResult, PromotionSource
from controlmesh_runtime.promotion_controller import PromotionController
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.recovery import RecoveryContext, RecoveryPolicy
from controlmesh_runtime.review_handoff_packet import ReviewHandoffPacket
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.runtime_execution_checkpoint import (
    RuntimeExecutionCheckpointer,
    RuntimeExecutionCheckpointOutcome,
    RuntimeExecutionCheckpointRequest,
)
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary import (
    SummaryInput,
    SummaryKind,
    SummaryMaterializationRequest,
    SummaryMaterializationResult,
    SummaryRuntime,
    SummaryTrigger,
)
from controlmesh_runtime.tracing import root_trace
from controlmesh_runtime.worker_controller import WorkerController


class AutonomousPromotionApproval(BaseModel):
    """Controller-approved promotion payload for the autonomous loop."""

    model_config = ConfigDict(frozen=True)

    submitted_by: PromotionSource = PromotionSource.CONTROLLER
    review_outcome: ReviewOutcome
    review_reasons: tuple[str, ...] = Field(default_factory=tuple)
    latest_completed: str
    next_action: str

    @model_validator(mode="after")
    def validate_approval(self) -> AutonomousPromotionApproval:
        if self.submitted_by is not PromotionSource.CONTROLLER:
            msg = "autonomous promotion approval must remain controller-owned"
            raise ValueError(msg)
        if not self.latest_completed.strip():
            msg = "autonomous promotion approval latest_completed must not be empty"
            raise ValueError(msg)
        if not self.next_action.strip():
            msg = "autonomous promotion approval next_action must not be empty"
            raise ValueError(msg)
        if any(not reason.strip() for reason in self.review_reasons):
            msg = "autonomous promotion approval review_reasons must not contain blank items"
            raise ValueError(msg)
        return self


class AutonomousRuntimeLoopRequest(BaseModel):
    """One autonomous runtime job over an explicit runtime context."""

    model_config = ConfigDict(frozen=True)

    packet_id: str
    context: RecoveryContext
    policy_snapshot: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    runtime_stage: RuntimeStage | None = None
    summary_trigger: SummaryTrigger = SummaryTrigger.PHASE_BOUNDARY
    promotion_approval: AutonomousPromotionApproval | None = None
    trace_id: str | None = None


class AutonomousRuntimeLoopOutcome(BaseModel):
    """Observed result of one autonomous runtime job."""

    model_config = ConfigDict(frozen=True)

    checkpoint: RuntimeExecutionCheckpointOutcome
    summary: SummaryMaterializationResult | None = None
    review: ReviewRecord | None = None
    promotion: PromotionResult | None = None
    final_handoff: ReviewHandoffPacket
    applied_triggers: tuple[str, ...]


class AutonomousRuntimeLoop:
    """Run one bounded runtime job through checkpointing, summaries, and optional promotion."""

    def __init__(
        self,
        *,
        root: Path | str,
        worker_controller: WorkerController,
    ) -> None:
        self._store = RuntimeStore(root)
        self._checkpointer = RuntimeExecutionCheckpointer(root=root, worker_controller=worker_controller)
        self._summary_runtime = SummaryRuntime(root)
        self._promotion_controller = PromotionController(root)
        self._read_surface = ExecutionEvidenceReadSurface(root)

    async def run(self, request: AutonomousRuntimeLoopRequest) -> AutonomousRuntimeLoopOutcome:
        trace = root_trace(request.trace_id)
        applied_triggers = ["checkpoint"]
        checkpoint = await self._checkpointer.run(
            RuntimeExecutionCheckpointRequest(
                packet_id=request.packet_id,
                context=request.context,
                policy_snapshot=request.policy_snapshot,
                runtime_stage=request.runtime_stage,
            )
        )

        summary = self._summary_runtime.materialize(
            SummaryMaterializationRequest(
                trigger=request.summary_trigger,
                task_summary_input=_build_summary_input(
                    checkpoint=checkpoint,
                    request=request,
                    summary_kind=SummaryKind.TASK_HANDOFF,
                ),
                line_summary_input=_build_summary_input(
                    checkpoint=checkpoint,
                    request=request,
                    summary_kind=SummaryKind.LINE_CHECKPOINT,
                ),
                trace_id=trace.trace_id,
                parent_span_id=trace.span_id,
            )
        )
        applied_triggers.append("summary")

        review: ReviewRecord | None = None
        promotion: PromotionResult | None = None
        if request.promotion_approval is not None:
            reconcile = self._promotion_controller.reconcile(
                episode=summary.evidence_identity,
                review_outcome=request.promotion_approval.review_outcome,
                review_reason=request.promotion_approval.review_reasons,
                latest_completed=request.promotion_approval.latest_completed,
                next_action=request.promotion_approval.next_action,
                trace_id=trace.trace_id,
                parent_span_id=trace.span_id,
            )
            review = reconcile.review_record
            promotion = reconcile.promotion_result
            applied_triggers.append("promotion")

        final_handoff = self._read_surface.read_task_review_handoff(request.context.task_id, packet_limit=1)
        return AutonomousRuntimeLoopOutcome(
            checkpoint=checkpoint,
            summary=summary,
            review=review,
            promotion=promotion,
            final_handoff=final_handoff,
            applied_triggers=tuple(applied_triggers),
        )


class AutonomousRuntimeScheduler:
    """Minimal in-process scheduler that drains autonomous runtime jobs until idle."""

    def __init__(self, *, loop: AutonomousRuntimeLoop) -> None:
        self._loop = loop
        self._pending: deque[AutonomousRuntimeLoopRequest] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def enqueue(self, request: AutonomousRuntimeLoopRequest) -> None:
        self._pending.append(request)

    async def run_until_idle(self) -> tuple[AutonomousRuntimeLoopOutcome, ...]:
        outcomes: list[AutonomousRuntimeLoopOutcome] = []
        while self._pending:
            outcomes.append(await self._loop.run(self._pending.popleft()))
        return tuple(outcomes)


def _build_summary_input(
    *,
    checkpoint: RuntimeExecutionCheckpointOutcome,
    request: AutonomousRuntimeLoopRequest,
    summary_kind: SummaryKind,
) -> SummaryInput:
    evidence_identity = checkpoint.task_handoff.primary_identity or checkpoint.loop_outcome.result.evidence_identity
    return SummaryInput(
        task_id=request.context.task_id,
        line=request.context.line,
        evidence_identity=evidence_identity,
        summary_kind=summary_kind,
        source_refs=(f"execution_evidence:{request.packet_id}",),
        source_events=checkpoint.packet_view.execution_event_types,
        source_findings=checkpoint.loop_outcome.result.notes,
        current_worker_state=(
            None
            if checkpoint.loop_outcome.final_worker_state is None
            else checkpoint.loop_outcome.final_worker_state.status
        ),
    )


__all__ = [
    "AutonomousPromotionApproval",
    "AutonomousRuntimeLoop",
    "AutonomousRuntimeLoopOutcome",
    "AutonomousRuntimeLoopRequest",
    "AutonomousRuntimeScheduler",
]
