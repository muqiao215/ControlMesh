from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh_runtime import RuntimeStore, StoreDecodeError
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.summary import (
    CompressionPolicy,
    SummaryInput,
    SummaryKind,
    SummaryMaterializationRequest,
    SummaryMaterializationResult,
    SummaryRecord,
    SummaryRuntime,
    SummaryTrigger,
    build_summary_record,
)


def _summary_input(kind: SummaryKind = SummaryKind.TASK_HANDOFF) -> SummaryInput:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id="plan-1",
    )
    return SummaryInput(
        task_id="task-1",
        line="harness-runtime",
        evidence_identity=identity,
        summary_kind=kind,
        source_refs=("events/task-1.jsonl", "reviews/task-1.json"),
        source_events=("task result recorded",),
        source_findings=("worker controller landed",),
        source_progress=("completion pack active",),
    )


def test_build_summary_record_rejects_unapproved_summary_kind() -> None:
    with pytest.raises(ValueError, match="summary kind is not allowed"):
        build_summary_record(
            _summary_input(SummaryKind.WORKER_CONTEXT),
            trigger=SummaryTrigger.HUMAN_GATE_READABILITY,
            policy=CompressionPolicy(),
        )


def test_build_summary_record_enforces_trigger_discipline() -> None:
    with pytest.raises(ValueError, match="trigger is not allowed"):
        build_summary_record(
            _summary_input(SummaryKind.TASK_PROGRESS),
            trigger=SummaryTrigger.PHASE_BOUNDARY,
            policy=CompressionPolicy(),
        )


def test_build_summary_record_maps_subject_scope_to_task_or_line_only() -> None:
    task_record = build_summary_record(
        _summary_input(SummaryKind.TASK_HANDOFF),
        trigger=SummaryTrigger.PHASE_BOUNDARY,
        policy=CompressionPolicy(),
    )
    line_record = build_summary_record(
        _summary_input(SummaryKind.LINE_CHECKPOINT),
        trigger=SummaryTrigger.PHASE_BOUNDARY,
        policy=CompressionPolicy(),
    )

    assert task_record.entity_id == "task:task-1"
    assert task_record.subject is EvidenceSubject.TASK
    assert line_record.entity_id == "line:harness-runtime"
    assert line_record.subject is EvidenceSubject.LINE


def test_runtime_store_summary_snapshot_lands_under_summaries_namespace(tmp_path: Path) -> None:
    store = RuntimeStore(tmp_path)
    record = build_summary_record(
        _summary_input(SummaryKind.TASK_HANDOFF),
        trigger=SummaryTrigger.PHASE_BOUNDARY,
        policy=CompressionPolicy(),
    )

    store.save_summary_record(record)

    summary_path = store.paths.summary_path(record.entity_id)
    assert summary_path.parent == store.paths.summaries_dir / "task"
    assert store.load_summary_record(record.entity_id).summary_id == record.summary_id


def test_runtime_store_summary_keeps_latest_snapshot_for_same_subject(tmp_path: Path) -> None:
    store = RuntimeStore(tmp_path)
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id="plan-1",
    )
    first = SummaryRecord(
        summary_kind=SummaryKind.TASK_HANDOFF,
        subject=EvidenceSubject.TASK,
        evidence_identity=identity,
        entity_id="task:task-1",
        token_budget=320,
        source_refs=("events/task-1.jsonl",),
        key_facts=("first summary",),
        next_step_hint="step-1",
    )
    second = SummaryRecord(
        summary_kind=SummaryKind.TASK_HANDOFF,
        subject=EvidenceSubject.TASK,
        evidence_identity=identity,
        entity_id="task:task-1",
        token_budget=320,
        source_refs=("events/task-1.jsonl",),
        key_facts=("second summary",),
        next_step_hint="step-2",
    )

    store.save_summary_record(first)
    store.save_summary_record(second)

    loaded = store.load_summary_record("task:task-1")
    assert loaded.summary_id == second.summary_id
    assert loaded.key_facts == ("second summary",)


def test_runtime_store_raises_on_corrupt_summary_file(tmp_path: Path) -> None:
    store = RuntimeStore(tmp_path)
    path = store.paths.summary_path("task:task-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(StoreDecodeError, match="failed to decode"):
        store.load_summary_record("task:task-1")


def test_summary_runtime_materializes_task_and_line_latest_snapshots(tmp_path: Path) -> None:
    runtime = SummaryRuntime(tmp_path)
    request = SummaryMaterializationRequest(
        trigger=SummaryTrigger.PHASE_BOUNDARY,
        task_summary_input=_summary_input(SummaryKind.TASK_HANDOFF),
        line_summary_input=_summary_input(SummaryKind.LINE_CHECKPOINT),
    )

    result = runtime.materialize(request)

    assert isinstance(result, SummaryMaterializationResult)
    assert result.evidence_identity == request.task_summary_input.evidence_identity
    assert result.task_summary.entity_id == "task:task-1"
    assert result.task_summary.summary_kind is SummaryKind.TASK_HANDOFF
    assert result.line_summary.entity_id == "line:harness-runtime"
    assert result.line_summary.summary_kind is SummaryKind.LINE_CHECKPOINT
    assert runtime.store.load_summary_record("task:task-1") == result.task_summary
    assert runtime.store.load_summary_record("line:harness-runtime") == result.line_summary


def test_summary_runtime_rejects_cross_identity_drift_between_inputs(tmp_path: Path) -> None:
    runtime = SummaryRuntime(tmp_path)
    mismatched_line_input = SummaryInput(
        task_id="task-1",
        line="other-line",
        evidence_identity=RuntimeEvidenceIdentity(
            packet_id="packet-1",
            task_id="task-1",
            line="other-line",
            plan_id="plan-1",
        ),
        summary_kind=SummaryKind.LINE_CHECKPOINT,
        source_refs=("events/task-1.jsonl",),
    )

    with pytest.raises(ValueError, match="must share one runtime evidence identity"):
        runtime.materialize(
            SummaryMaterializationRequest(
                trigger=SummaryTrigger.PHASE_BOUNDARY,
                task_summary_input=_summary_input(SummaryKind.TASK_HANDOFF),
                line_summary_input=mismatched_line_input,
            )
        )


def test_summary_runtime_keeps_latest_snapshot_semantics_on_repeat_materialization(tmp_path: Path) -> None:
    runtime = SummaryRuntime(tmp_path)
    first = runtime.materialize(
        SummaryMaterializationRequest(
            trigger=SummaryTrigger.PHASE_BOUNDARY,
            task_summary_input=_summary_input(SummaryKind.TASK_HANDOFF),
            line_summary_input=_summary_input(SummaryKind.LINE_CHECKPOINT),
        )
    )
    second = runtime.materialize(
        SummaryMaterializationRequest(
            trigger=SummaryTrigger.PHASE_BOUNDARY,
            task_summary_input=_summary_input(SummaryKind.TASK_HANDOFF).model_copy(
                update={"source_events": ("task result recorded", "handoff prepared")}
            ),
            line_summary_input=_summary_input(SummaryKind.LINE_CHECKPOINT).model_copy(
                update={"source_events": ("line checkpoint refreshed",)}
            ),
        )
    )

    assert first.task_summary.summary_id != second.task_summary.summary_id
    assert first.line_summary.summary_id != second.line_summary.summary_id
    assert runtime.store.load_summary_record("task:task-1").summary_id == second.task_summary.summary_id
    assert runtime.store.load_summary_record("line:harness-runtime").summary_id == second.line_summary.summary_id
