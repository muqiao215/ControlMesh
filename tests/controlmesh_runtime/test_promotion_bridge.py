from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh_runtime.canonical_section_writer import (
    CanonicalSectionName,
    CanonicalSectionPatch,
    CanonicalTargetFile,
    CanonicalWriteShape,
)
from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.promotion_bridge import (
    PromotionBridge,
    PromotionEligibility,
    PromotionInput,
    PromotionSource,
    PromotionWriteIntent,
    SummaryPromotionInput,
)
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.recovery import (
    RecoveryExecutionAction,
    RecoveryExecutionStep,
    RecoveryIntent,
    RecoveryPolicy,
)
from controlmesh_runtime.recovery.execution import (
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
)
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary.contracts import SummaryKind, SummaryRecord


def _write_line_files(root: Path, line: str) -> None:
    line_dir = root / "plans" / line
    line_dir.mkdir(parents=True, exist_ok=True)
    (line_dir / "task_plan.md").write_text(
        "# Current Goal\nGoal.\n\n# Current Status\nnot_started\n\n# Notes\nnone\n",
        encoding="utf-8",
    )
    (line_dir / "progress.md").write_text(
        "# Latest Completed\nOpened.\n\n# Current State\nnot_started\n\n# Next Action\nDo thing.\n\n# Latest Checkpoint\ncheckpoint-opened\n\n# Notes\nnone\n",
        encoding="utf-8",
    )


def _identity(
    *,
    task_id: str = "task-1",
    line: str = "demo-line",
    packet_id: str = "packet-1",
    plan_id: str = "plan-1",
) -> RuntimeEvidenceIdentity:
    return RuntimeEvidenceIdentity(
        packet_id=packet_id,
        task_id=task_id,
        line=line,
        plan_id=plan_id,
    )


def _plan(identity: RuntimeEvidenceIdentity) -> RecoveryExecutionPlan:
    return RecoveryExecutionPlan(
        plan_id=identity.plan_id,
        packet_id=identity.packet_id,
        task_id=identity.task_id,
        line=identity.line,
        worker_id="worker-1",
        intent=RecoveryIntent.RESTART_WORKER,
        steps=(
            RecoveryExecutionStep(
                action=RecoveryExecutionAction.RESTART_WORKER,
                target="worker:worker-1",
                retryable=True,
            ),
        ),
        policy_snapshot=RecoveryPolicy(),
        next_step_token=RecoveryIntent.RESTART_WORKER.value,
    )


def _summary(
    identity: RuntimeEvidenceIdentity,
    *,
    subject: EvidenceSubject,
    key_facts: tuple[str, ...],
    summary_kind: SummaryKind | None = None,
    next_step_hint: str | None = None,
) -> SummaryRecord:
    return SummaryRecord(
        summary_kind=summary_kind
        or (SummaryKind.LINE_CHECKPOINT if subject is EvidenceSubject.LINE else SummaryKind.TASK_HANDOFF),
        subject=subject,
        evidence_identity=identity,
        entity_id=identity.entity_id_for(subject),
        token_budget=480,
        source_refs=(f"summary:{identity.packet_id}",),
        key_facts=key_facts,
        next_step_hint=next_step_hint or f"continue.{identity.line}.{identity.task_id}",
    )


def test_summary_promotion_v1_promotes_review_and_latest_summaries_without_execution_result(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    store = RuntimeStore(tmp_path)
    bridge = PromotionBridge(tmp_path)
    identity = _identity()
    review = ReviewRecord(
        task_id="task-1",
        evidence_identity=identity,
        outcome=ReviewOutcome.PASS_WITH_NOTES,
        reasons=("controller verified summary snapshot",),
        source="controller",
    )
    task_summary = _summary(
        identity,
        subject=EvidenceSubject.TASK,
        key_facts=("task handoff is stable",),
        next_step_hint="open next runtime scope",
    )
    line_summary = _summary(
        identity,
        subject=EvidenceSubject.LINE,
        key_facts=("line checkpoint is stable",),
        next_step_hint="hold line closed",
    )
    store.save_summary_record(task_summary)
    store.save_summary_record(line_summary)

    eligibility = bridge.evaluate_summary_promotion(
        SummaryPromotionInput(
            line="demo-line",
            submitted_by=PromotionSource.CONTROLLER,
            review_record=review,
            latest_task_summary=task_summary,
            latest_line_summary=line_summary,
            latest_completed="Controller accepted the latest runtime closure.",
            next_action="Hold line closed until a new scope opens.",
        )
    )
    result = bridge.promote_summary(
        SummaryPromotionInput(
            line="demo-line",
            submitted_by=PromotionSource.CONTROLLER,
            review_record=review,
            latest_task_summary=task_summary,
            latest_line_summary=line_summary,
            latest_completed="Controller accepted the latest runtime closure.",
            next_action="Hold line closed until a new scope opens.",
        )
    )

    task_plan = (tmp_path / "plans" / "demo-line" / "task_plan.md").read_text(encoding="utf-8")
    progress = (tmp_path / "plans" / "demo-line" / "progress.md").read_text(encoding="utf-8")

    assert eligibility.eligible is True
    assert isinstance(eligibility, PromotionEligibility)
    assert eligibility.status_token == "completed"
    assert isinstance(eligibility.write_intent, PromotionWriteIntent)
    assert eligibility.write_intent.source_review_id == review.review_id
    assert eligibility.write_intent.source_task_summary_id == task_summary.summary_id
    assert eligibility.write_intent.source_line_summary_id == line_summary.summary_id
    assert result.updated_files == (
        str(tmp_path / "plans" / "demo-line" / "task_plan.md"),
        str(tmp_path / "plans" / "demo-line" / "progress.md"),
    )
    assert result.receipt_id is not None
    assert "Current Status\ncompleted" in task_plan
    assert "Controller accepted the latest runtime closure." in progress
    assert "Hold line closed until a new scope opens." in progress
    assert f"latest_task_summary_id={task_summary.summary_id}" in progress
    assert f"latest_line_summary_id={line_summary.summary_id}" in progress
    assert "execution_status=" not in progress
    assert "line checkpoint is stable" not in progress
    assert "# Notes\nnone" in progress
    receipt = store.load_promotion_receipt(result.receipt_id)
    assert receipt.review_id == review.review_id
    assert receipt.task_summary_id == task_summary.summary_id
    assert receipt.line_summary_id == line_summary.summary_id


def test_canonical_section_patch_rejects_out_of_contract_target() -> None:
    with pytest.raises(ValueError, match="task_plan patches may only target current_status"):
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.TASK_PLAN,
            section=CanonicalSectionName.NEXT_ACTION,
            shape=CanonicalWriteShape.SECTION_REPLACE,
            body="bad",
        )


def test_summary_promotion_v1_rejects_worker_submitter(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()

    with pytest.raises(ValueError, match="controller-owned"):
        bridge.promote_summary(
            SummaryPromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.WORKER,
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="worker",
                ),
                latest_task_summary=_summary(identity, subject=EvidenceSubject.TASK, key_facts=("task",)),
                latest_line_summary=_summary(identity, subject=EvidenceSubject.LINE, key_facts=("line",)),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_summary_promotion_v1_rejects_stale_task_summary_snapshot(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    store = RuntimeStore(tmp_path)
    bridge = PromotionBridge(tmp_path)
    identity = _identity()
    stale_task_summary = _summary(identity, subject=EvidenceSubject.TASK, key_facts=("old task",))
    latest_task_summary = _summary(identity, subject=EvidenceSubject.TASK, key_facts=("new task",))
    latest_line_summary = _summary(identity, subject=EvidenceSubject.LINE, key_facts=("line",))
    store.save_summary_record(stale_task_summary)
    store.save_summary_record(latest_line_summary)
    store.save_summary_record(latest_task_summary)

    with pytest.raises(ValueError, match="latest_task_summary is not the current stored summary snapshot"):
        bridge.promote_summary(
            SummaryPromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                latest_task_summary=stale_task_summary,
                latest_line_summary=latest_line_summary,
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_summary_promotion_v1_rejects_stale_line_summary_snapshot(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    store = RuntimeStore(tmp_path)
    bridge = PromotionBridge(tmp_path)
    identity = _identity()
    latest_task_summary = _summary(identity, subject=EvidenceSubject.TASK, key_facts=("task",))
    stale_line_summary = _summary(identity, subject=EvidenceSubject.LINE, key_facts=("old line",))
    latest_line_summary = _summary(identity, subject=EvidenceSubject.LINE, key_facts=("new line",))
    store.save_summary_record(latest_task_summary)
    store.save_summary_record(stale_line_summary)
    store.save_summary_record(latest_line_summary)

    with pytest.raises(ValueError, match="latest_line_summary is not the current stored summary snapshot"):
        bridge.promote_summary(
            SummaryPromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                latest_task_summary=latest_task_summary,
                latest_line_summary=stale_line_summary,
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_summary_promotion_v1_rejects_cross_summary_identity_drift(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()
    other_identity = _identity(packet_id="packet-2")

    with pytest.raises(ValueError, match="latest summaries must share review evidence identity"):
        bridge.promote_summary(
            SummaryPromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                latest_task_summary=_summary(identity, subject=EvidenceSubject.TASK, key_facts=("task",)),
                latest_line_summary=_summary(other_identity, subject=EvidenceSubject.LINE, key_facts=("line",)),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_summary_promotion_v1_rejects_unapproved_task_summary_kind(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()

    with pytest.raises(ValueError, match="latest_task_summary must use task_handoff kind"):
        bridge.promote_summary(
            SummaryPromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                latest_task_summary=_summary(
                    identity,
                    subject=EvidenceSubject.TASK,
                    summary_kind=SummaryKind.TASK_PROGRESS,
                    key_facts=("task",),
                ),
                latest_line_summary=_summary(identity, subject=EvidenceSubject.LINE, key_facts=("line",)),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_summary_promotion_v1_rechecks_freshness_at_write_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_line_files(tmp_path, "demo-line")
    store = RuntimeStore(tmp_path)
    bridge = PromotionBridge(tmp_path)
    identity = _identity()
    review = ReviewRecord(
        task_id="task-1",
        evidence_identity=identity,
        outcome=ReviewOutcome.PASS_WITH_NOTES,
        reasons=("verified",),
        source="controller",
    )
    task_summary = _summary(identity, subject=EvidenceSubject.TASK, key_facts=("task",))
    line_summary = _summary(identity, subject=EvidenceSubject.LINE, key_facts=("line",))
    store.save_summary_record(task_summary)
    store.save_summary_record(line_summary)
    inp = SummaryPromotionInput(
        line="demo-line",
        submitted_by=PromotionSource.CONTROLLER,
        review_record=review,
        latest_task_summary=task_summary,
        latest_line_summary=line_summary,
        latest_completed="Controller accepted the latest runtime closure.",
        next_action="Hold line closed until a new scope opens.",
    )
    original_write = bridge._writer.write

    def wrapped_write(*, line: str, patches: tuple[CanonicalSectionPatch, ...], pre_write_check=None):
        store.save_summary_record(
            _summary(identity, subject=EvidenceSubject.TASK, key_facts=("newest task",))
        )
        return original_write(line=line, patches=patches, pre_write_check=pre_write_check)

    monkeypatch.setattr(bridge._writer, "write", wrapped_write)

    with pytest.raises(ValueError, match="promotion write intent task summary freshness check failed"):
        bridge.promote_summary(inp)


def test_promotion_bridge_updates_canonical_line_files_from_controller_inputs(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()

    result = bridge.promote(
        PromotionInput(
            line="demo-line",
            submitted_by=PromotionSource.CONTROLLER,
            execution_plan=_plan(identity),
            review_record=ReviewRecord(
                task_id="task-1",
                evidence_identity=identity,
                outcome=ReviewOutcome.PASS_WITH_NOTES,
                reasons=("verified",),
                source="controller",
            ),
            execution_result=RecoveryExecutionResult(
                plan_id="plan-1",
                evidence_identity=identity,
                status=RecoveryExecutionStatus.COMPLETED,
                completed_step_count=1,
            ),
            summary_record=SummaryRecord(
                summary_kind=SummaryKind.LINE_CHECKPOINT,
                subject=EvidenceSubject.LINE,
                evidence_identity=identity,
                entity_id="line:demo-line",
                token_budget=480,
                source_refs=("progress:task-1",),
                key_facts=("worker controller landed",),
                next_step_hint="advance to next block",
            ),
            latest_completed="Promoted runtime closure for demo-line.",
            next_action="Advance to the next block.",
        )
    )

    task_plan = (tmp_path / "plans" / "demo-line" / "task_plan.md").read_text(encoding="utf-8")
    progress = (tmp_path / "plans" / "demo-line" / "progress.md").read_text(encoding="utf-8")

    assert result.status_token == "completed"
    assert "completed" in task_plan
    assert "Promoted runtime closure for demo-line." in progress
    assert "Current State\ncompleted" in progress
    assert "Latest Checkpoint\ncheckpoint-demo-line-completed" in progress
    assert "latest_summary_id" in progress
    assert "identity_packet_id=packet-1" in progress


def test_promotion_bridge_rejects_non_controller_submitter(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()

    with pytest.raises(ValueError, match="controller-owned"):
        bridge.promote(
            PromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.WORKER,
                execution_plan=_plan(identity),
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="worker",
                ),
                execution_result=RecoveryExecutionResult(
                    plan_id="plan-1",
                    evidence_identity=identity,
                    status=RecoveryExecutionStatus.COMPLETED,
                    completed_step_count=1,
                ),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_promotion_bridge_rejects_failed_execution_for_completed_review(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()

    with pytest.raises(ValueError, match="cannot promote a completed review from a non-completed execution result"):
        bridge.promote(
            PromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                execution_plan=_plan(identity),
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                execution_result=RecoveryExecutionResult(
                    plan_id="plan-1",
                    evidence_identity=identity,
                    status=RecoveryExecutionStatus.FAILED,
                    completed_step_count=0,
                    failed_step_index=0,
                ),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_promotion_bridge_rejects_identity_mismatch_between_review_and_plan(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    plan_identity = _identity()
    review_identity = _identity(packet_id="packet-2")

    with pytest.raises(ValueError, match="review record must match execution plan evidence identity"):
        bridge.promote(
            PromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                execution_plan=_plan(plan_identity),
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=review_identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                execution_result=RecoveryExecutionResult(
                    plan_id="plan-1",
                    evidence_identity=plan_identity,
                    status=RecoveryExecutionStatus.COMPLETED,
                    completed_step_count=1,
                ),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )


def test_promotion_bridge_rejects_identity_mismatch_between_result_and_plan(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    bridge = PromotionBridge(tmp_path)
    identity = _identity()
    result_identity = _identity(packet_id="packet-2")

    with pytest.raises(ValueError, match="execution result must match execution plan evidence identity"):
        bridge.promote(
            PromotionInput(
                line="demo-line",
                submitted_by=PromotionSource.CONTROLLER,
                execution_plan=_plan(identity),
                review_record=ReviewRecord(
                    task_id="task-1",
                    evidence_identity=identity,
                    outcome=ReviewOutcome.PASS,
                    reasons=("verified",),
                    source="controller",
                ),
                execution_result=RecoveryExecutionResult(
                    plan_id="plan-1",
                    evidence_identity=result_identity,
                    status=RecoveryExecutionStatus.COMPLETED,
                    completed_step_count=1,
                ),
                latest_completed="Should not write.",
                next_action="Should not write.",
            )
        )
