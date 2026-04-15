from __future__ import annotations

from pathlib import Path

from controlmesh_runtime.contracts import (
    QueryAction,
    SignalAction,
    UpdateAction,
)
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.promotion_controller import PromotionController
from controlmesh_runtime.runtime_message_api import query, signal, update
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary.contracts import SummaryKind, SummaryRecord


def _identity(*, plan_id: str = "plan-1") -> RuntimeEvidenceIdentity:
    return RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="demo-line",
        plan_id=plan_id,
    )


def _write_line_files(root: Path, line: str) -> None:
    line_dir = root / "plans" / line
    line_dir.mkdir(parents=True, exist_ok=True)
    (line_dir / "task_plan.md").write_text(
        "# Current Goal\nGoal.\n\n# Current Status\nactive\n\n# Notes\nnone\n",
        encoding="utf-8",
    )
    (line_dir / "progress.md").write_text(
        "# Latest Completed\nOpened.\n\n"
        "# Current State\nactive\n\n"
        "# Next Action\nContinue.\n\n"
        "# Latest Checkpoint\ncheckpoint-opened\n\n"
        "# Notes\nnone\n",
        encoding="utf-8",
    )


def _task_summary(identity: RuntimeEvidenceIdentity) -> SummaryRecord:
    return SummaryRecord(
        summary_kind=SummaryKind.TASK_HANDOFF,
        subject=EvidenceSubject.TASK,
        evidence_identity=identity,
        entity_id=identity.entity_id_for(EvidenceSubject.TASK),
        token_budget=480,
        source_refs=(f"summary:{identity.packet_id}",),
        key_facts=("task handoff",),
        next_step_hint="continue.demo-line.task-1",
    )


def _line_summary(identity: RuntimeEvidenceIdentity) -> SummaryRecord:
    return SummaryRecord(
        summary_kind=SummaryKind.LINE_CHECKPOINT,
        subject=EvidenceSubject.LINE,
        evidence_identity=identity,
        entity_id=identity.entity_id_for(EvidenceSubject.LINE),
        token_budget=480,
        source_refs=(f"summary:{identity.packet_id}",),
        key_facts=("line checkpoint",),
    )


def test_signal_request_summary_appends_control_event(tmp_path: Path) -> None:
    identity = _identity()

    result = signal(
        root=tmp_path,
        episode=identity,
        action=SignalAction.REQUEST_SUMMARY,
        payload={"requested_by": "controller"},
    )

    store = RuntimeStore(tmp_path)
    latest = store.latest_control_event(identity, "signal.request_summary")

    assert result["ok"] is True
    assert result["action"] == SignalAction.REQUEST_SUMMARY.value
    assert latest is not None
    assert latest.payload["requested_by"] == "controller"
    assert latest.trace_id
    assert latest.span_id


def test_query_latest_summary_reads_latest_task_and_line_snapshots(tmp_path: Path) -> None:
    identity = _identity()
    store = RuntimeStore(tmp_path)
    store.save_summary_record(_task_summary(identity))
    store.save_summary_record(_line_summary(identity))

    result = query(
        root=tmp_path,
        episode=identity,
        action=QueryAction.LATEST_SUMMARY,
    )

    assert result["ok"] is True
    assert result["task_summary_id"]
    assert result["line_summary_id"]


def test_update_promote_rejects_missing_summary(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    identity = _identity()

    result = update(
        root=tmp_path,
        episode=identity,
        action=UpdateAction.PROMOTE,
        payload={
            "review_outcome": "PASS_WITH_NOTES",
            "review_reason": ["controller-approved"],
            "latest_completed": "done",
            "next_action": "hold",
        },
    )

    assert result["ok"] is False
    assert result["reason"] == "missing_task_summary"


def test_update_promote_is_idempotent_for_same_latest_summaries(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    identity = _identity()
    store = RuntimeStore(tmp_path)
    store.save_summary_record(_task_summary(identity))
    store.save_summary_record(_line_summary(identity))

    first = update(
        root=tmp_path,
        episode=identity,
        action=UpdateAction.PROMOTE,
        payload={
            "review_outcome": "PASS_WITH_NOTES",
            "review_reason": ["controller-approved"],
            "latest_completed": "done",
            "next_action": "hold",
        },
    )
    second = update(
        root=tmp_path,
        episode=identity,
        action=UpdateAction.PROMOTE,
        payload={
            "review_outcome": "PASS_WITH_NOTES",
            "review_reason": ["controller-approved"],
            "latest_completed": "done",
            "next_action": "hold",
        },
    )

    assert first["ok"] is True
    assert first["reason"] == "written"
    assert second["ok"] is True
    assert second["reason"] == "already_promoted"
    assert second["receipt_id"] == first["receipt_id"]


def test_promotion_controller_rejects_cross_episode_summary_drift(tmp_path: Path) -> None:
    _write_line_files(tmp_path, "demo-line")
    store = RuntimeStore(tmp_path)
    controller = PromotionController(tmp_path)
    identity = _identity(plan_id="plan-1")
    drifted = _identity(plan_id="plan-2")
    store.save_summary_record(_task_summary(drifted))
    store.save_summary_record(_line_summary(identity))

    result = controller.reconcile(
        episode=identity,
        review_outcome="PASS_WITH_NOTES",
        review_reason=("controller-approved",),
        latest_completed="done",
        next_action="hold",
    )

    assert result.ok is False
    assert result.reason == "cross_episode_summary_drift"
