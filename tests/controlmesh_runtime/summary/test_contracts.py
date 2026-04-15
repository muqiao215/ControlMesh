from __future__ import annotations

import pytest

from controlmesh_runtime import (
    CompressionDecision,
    EscalationLevel,
    EvidenceSubject,
    RecoveryIntent,
    ReviewOutcome,
    RuntimeEvidenceIdentity,
    SummaryInput,
    SummaryKind,
    SummaryRecord,
    WorkerStatus,
)


def test_summary_contracts_create_valid_objects() -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id="plan-1",
    )
    summary_input = SummaryInput(
        task_id="task-1",
        line="harness-runtime",
        evidence_identity=identity,
        summary_kind=SummaryKind.TASK_HANDOFF,
        source_refs=("events/task-1.jsonl", "reviews/task-1.json"),
        source_events=("task finished tests",),
        source_findings=("store layer is green",),
        source_progress=("phase 5 ready",),
        current_worker_state=WorkerStatus.READY,
        current_review_outcome=ReviewOutcome.PASS_WITH_NOTES,
    )
    summary_record = SummaryRecord(
        summary_kind=SummaryKind.TASK_HANDOFF,
        subject=EvidenceSubject.TASK,
        evidence_identity=identity,
        entity_id="task:task-1",
        token_budget=320,
        source_refs=("events/task-1.jsonl",),
        key_facts=("runtime contracts are green",),
        next_step_hint="open Phase 6 summary compression",
    )
    decision = CompressionDecision(
        should_compress=True,
        target_kind=SummaryKind.TASK_HANDOFF,
        target_budget=320,
        preserve_failure_detail=False,
        preserve_next_step=True,
        preserve_operator_constraints=True,
        next_step_token="summary.compress.task_handoff",
    )

    assert summary_input.summary_kind is SummaryKind.TASK_HANDOFF
    assert summary_record.next_step_hint == "open Phase 6 summary compression"
    assert decision.preserve_key_facts is True


def test_task_handoff_requires_next_step_hint() -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id="plan-1",
    )
    with pytest.raises(ValueError, match="task_handoff summaries require next_step_hint"):
        SummaryRecord(
            summary_kind=SummaryKind.TASK_HANDOFF,
            subject=EvidenceSubject.TASK,
            evidence_identity=identity,
            entity_id="task:task-1",
            token_budget=320,
            source_refs=("events/task-1.jsonl",),
            key_facts=("handoff attempted",),
        )


def test_failure_capsule_requires_failure_detail() -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="harness-runtime",
        plan_id="plan-1",
    )
    with pytest.raises(ValueError, match="failure_capsule summaries require failure_class"):
        SummaryRecord(
            summary_kind=SummaryKind.FAILURE_CAPSULE,
            subject=EvidenceSubject.TASK,
            evidence_identity=identity,
            entity_id="task:task-1",
            token_budget=400,
            source_refs=("events/task-1.jsonl",),
            key_facts=("task failed",),
            recovery_intent=RecoveryIntent.REQUIRE_OPERATOR_ACTION,
            escalation_level=EscalationLevel.HUMAN_GATE,
        )


def test_summary_requires_source_refs_and_key_facts() -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="line-1",
        plan_id="plan-1",
    )
    with pytest.raises(ValueError, match="source_refs must not be empty"):
        SummaryRecord(
            summary_kind=SummaryKind.LINE_CHECKPOINT,
            subject=EvidenceSubject.LINE,
            evidence_identity=identity,
            entity_id="line:line-1",
            token_budget=480,
            source_refs=(),
            key_facts=("checkpoint exists",),
        )


def test_line_checkpoint_can_carry_deferred_items() -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="line-1",
        plan_id="plan-1",
    )
    record = SummaryRecord(
        summary_kind=SummaryKind.LINE_CHECKPOINT,
        subject=EvidenceSubject.LINE,
        evidence_identity=identity,
        entity_id="line:line-1",
        token_budget=480,
        source_refs=("plans/harness-runtime/task_plan.md",),
        key_facts=("Phase 5 is complete",),
        deferred_items=("SQLite backend decision",),
    )

    assert record.deferred_items == ("SQLite backend decision",)


def test_summary_record_rejects_subject_identity_mismatch() -> None:
    identity = RuntimeEvidenceIdentity(
        packet_id="packet-1",
        task_id="task-1",
        line="line-1",
        plan_id="plan-1",
    )

    with pytest.raises(ValueError, match="entity_id must match typed subject identity"):
        SummaryRecord(
            summary_kind=SummaryKind.LINE_CHECKPOINT,
            subject=EvidenceSubject.LINE,
            evidence_identity=identity,
            entity_id="task:task-1",
            token_budget=480,
            source_refs=("plans/harness-runtime/task_plan.md",),
            key_facts=("Phase 5 is complete",),
        )
