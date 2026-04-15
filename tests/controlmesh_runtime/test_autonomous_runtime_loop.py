from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from controlmesh_runtime.autonomous_runtime_loop import (
    AutonomousPromotionApproval,
    AutonomousRuntimeLoop,
    AutonomousRuntimeLoopRequest,
    AutonomousRuntimeScheduler,
)
from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.recovery import RecoveryContext, RecoveryReason
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary import SummaryTrigger
from controlmesh_runtime.worker_state import WorkerState, WorkerStatus


@dataclass
class _FakeWorkerController:
    state: WorkerState | None = field(
        default_factory=lambda: WorkerState(worker_id="worker-1", status=WorkerStatus.READY)
    )

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def create(self, worker_id: str) -> WorkerState:
        self.calls.append(("create", worker_id))
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def await_ready(
        self,
        worker_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> WorkerState:
        del timeout_seconds, poll_interval_seconds
        self.calls.append(("await_ready", worker_id))
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def fetch_state(self, worker_id: str) -> WorkerState | None:
        self.calls.append(("fetch_state", worker_id))
        return self.state

    async def restart(self, worker_id: str) -> WorkerState:
        self.calls.append(("restart", worker_id))
        return self.state or WorkerState(worker_id=worker_id, status=WorkerStatus.READY)

    async def terminate(self, worker_id: str) -> WorkerState:
        self.calls.append(("terminate", worker_id))
        return WorkerState(worker_id=worker_id, status=WorkerStatus.FINISHED)


def _context(*, task_id: str = "task-1") -> RecoveryContext:
    return RecoveryContext(
        task_id=task_id,
        line="harness-autonomous-runtime-loop-pack",
        worker_id="worker-1",
        current_status=WorkerStatus.DEGRADED,
        failure_class=FailureClass.TOOL_RUNTIME,
        recovery_reason=RecoveryReason.DEGRADED_RUNTIME,
    )


def _write_line_files(root: Path, line: str) -> None:
    line_dir = root / "plans" / line
    line_dir.mkdir(parents=True)
    (line_dir / "task_plan.md").write_text(
        "# Current Goal\nInitial goal\n\n# Current Status\nactive\n\n# Ready Queue\n1. continue\n",
        encoding="utf-8",
    )
    (line_dir / "progress.md").write_text(
        "# Latest Completed\nNone\n\n"
        "# Current State\nactive\n\n"
        "# Next Action\nContinue\n\n"
        "# Latest Checkpoint\ncheckpoint-initial\n\n"
        "# Notes\nHuman note stays.\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_autonomous_loop_checkpoints_and_materializes_summaries(tmp_path: Path) -> None:
    loop = AutonomousRuntimeLoop(root=tmp_path, worker_controller=_FakeWorkerController())

    outcome = await loop.run(
        AutonomousRuntimeLoopRequest(
            packet_id="packet-1",
            context=_context(),
            summary_trigger=SummaryTrigger.PHASE_BOUNDARY,
        )
    )

    store = RuntimeStore(tmp_path)
    assert outcome.checkpoint.persisted_event_count > 0
    assert outcome.summary is not None
    assert outcome.promotion is None
    assert outcome.final_handoff.latest_task_summary == outcome.summary.task_summary
    assert outcome.final_handoff.latest_line_summary == outcome.summary.line_summary
    assert store.load_summary_record("task:task-1") == outcome.summary.task_summary
    assert store.load_summary_record("line:harness-autonomous-runtime-loop-pack") == outcome.summary.line_summary
    assert outcome.applied_triggers == ("checkpoint", "summary")


@pytest.mark.asyncio
async def test_autonomous_loop_runs_controlled_promotion_after_summary(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "harness-autonomous-runtime-loop-pack")
    loop = AutonomousRuntimeLoop(root=tmp_path, worker_controller=_FakeWorkerController())

    outcome = await loop.run(
        AutonomousRuntimeLoopRequest(
            packet_id="packet-1",
            context=_context(),
            promotion_approval=AutonomousPromotionApproval(
                review_outcome=ReviewOutcome.PASS_WITH_NOTES,
                review_reasons=("controller-approved",),
                latest_completed="Autonomous runtime loop checkpoint completed.",
                next_action="Hold until the next bounded packet arrives.",
            ),
        )
    )

    progress = (tmp_path / "plans" / "harness-autonomous-runtime-loop-pack" / "progress.md").read_text(
        encoding="utf-8"
    )
    assert outcome.review is not None
    assert outcome.summary is not None
    assert outcome.promotion is not None
    assert outcome.promotion.receipt_id is not None
    assert "Autonomous runtime loop checkpoint completed." in progress
    assert "Hold until the next bounded packet arrives." in progress
    assert RuntimeStore(tmp_path).load_review_record("task-1") == outcome.review
    assert outcome.applied_triggers == ("checkpoint", "summary", "promotion")


@pytest.mark.asyncio
async def test_autonomous_scheduler_drains_jobs_until_idle(tmp_path: Path) -> None:
    loop = AutonomousRuntimeLoop(root=tmp_path, worker_controller=_FakeWorkerController())
    scheduler = AutonomousRuntimeScheduler(loop=loop)
    scheduler.enqueue(AutonomousRuntimeLoopRequest(packet_id="packet-1", context=_context(task_id="task-1")))
    scheduler.enqueue(AutonomousRuntimeLoopRequest(packet_id="packet-2", context=_context(task_id="task-2")))

    outcomes = await scheduler.run_until_idle()

    store = RuntimeStore(tmp_path)
    assert len(outcomes) == 2
    assert scheduler.pending_count == 0
    assert store.load_execution_evidence("packet-1")
    assert store.load_execution_evidence("packet-2")
    assert store.load_summary_record("task:task-1") == outcomes[0].summary.task_summary
    assert store.load_summary_record("task:task-2") == outcomes[1].summary.task_summary
