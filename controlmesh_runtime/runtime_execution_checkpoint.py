"""Persist one thin runtime cycle as a bounded execution checkpoint."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from controlmesh_runtime.execution_read_surface import (
    ExecutionEvidenceReadSurface,
    PacketExecutionEpisodeView,
)
from controlmesh_runtime.recovery import RecoveryContext, RecoveryPolicy
from controlmesh_runtime.review_handoff_packet import ReviewHandoffPacket
from controlmesh_runtime.runtime import RuntimeStage
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.thin_runtime_loop import (
    ThinRuntimeLoop,
    ThinRuntimeLoopOutcome,
    ThinRuntimeLoopRequest,
)
from controlmesh_runtime.worker_controller import WorkerController


class RuntimeExecutionCheckpointRequest(BaseModel):
    """Input for one persisted thin-runtime execution checkpoint."""

    model_config = ConfigDict(frozen=True)

    packet_id: str
    context: RecoveryContext
    policy_snapshot: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    runtime_stage: RuntimeStage | None = None


class RuntimeExecutionCheckpointOutcome(BaseModel):
    """Persisted runtime checkpoint plus read-only packet views."""

    model_config = ConfigDict(frozen=True)

    loop_outcome: ThinRuntimeLoopOutcome
    persisted_event_count: int
    packet_view: PacketExecutionEpisodeView
    task_handoff: ReviewHandoffPacket


class RuntimeExecutionCheckpointer:
    """Run one bounded thin runtime cycle and persist its execution evidence."""

    def __init__(self, root: Path | str, *, worker_controller: WorkerController) -> None:
        self._store = RuntimeStore(root)
        self._loop = ThinRuntimeLoop(worker_controller=worker_controller)
        self._read_surface = ExecutionEvidenceReadSurface(root)

    async def run(self, request: RuntimeExecutionCheckpointRequest) -> RuntimeExecutionCheckpointOutcome:
        evidence_path = self._store.paths.execution_evidence_path(request.packet_id)
        if evidence_path.exists():
            msg = f"execution checkpoint packet '{request.packet_id}' already exists"
            raise FileExistsError(msg)

        loop_outcome = await self._loop.run(
            ThinRuntimeLoopRequest(
                packet_id=request.packet_id,
                context=request.context,
                policy_snapshot=request.policy_snapshot,
                runtime_stage=request.runtime_stage,
            )
        )
        for event in loop_outcome.runtime_events:
            self._store.append_execution_evidence(event)
        if loop_outcome.final_worker_state is not None:
            self._store.save_worker_state(loop_outcome.final_worker_state)

        packet_view = self._read_surface.read_packet_execution_episode(request.packet_id)
        task_handoff = self._read_surface.read_task_review_handoff(request.context.task_id, packet_limit=1)
        return RuntimeExecutionCheckpointOutcome(
            loop_outcome=loop_outcome,
            persisted_event_count=packet_view.event_count,
            packet_view=packet_view,
            task_handoff=task_handoff,
        )


__all__ = [
    "RuntimeExecutionCheckpointOutcome",
    "RuntimeExecutionCheckpointRequest",
    "RuntimeExecutionCheckpointer",
]
