from __future__ import annotations

from controlmesh_runtime import (
    CompressionPolicy,
    EscalationLevel,
    FailureClass,
    RecoveryIntent,
    ReviewOutcome,
    RuntimeEvidenceIdentity,
    SummaryInput,
    SummaryKind,
    WorkerStatus,
    evaluate_compression_policy,
)


def _summary_input(kind: SummaryKind) -> SummaryInput:
    return SummaryInput(
        task_id="task-1",
        line="harness-runtime",
        evidence_identity=RuntimeEvidenceIdentity(
            packet_id="packet-1",
            task_id="task-1",
            line="harness-runtime",
            plan_id="plan-1",
        ),
        summary_kind=kind,
        source_refs=("events/task-1.jsonl", "reviews/task-1.json"),
        source_events=("worker reported status",),
        source_findings=("contracts are typed",),
        source_progress=("phase active",),
        current_worker_state=WorkerStatus.RUNNING,
        current_review_outcome=ReviewOutcome.PASS_WITH_NOTES,
        failure_class=FailureClass.TOOL_RUNTIME if kind is SummaryKind.FAILURE_CAPSULE else None,
        recovery_intent=RecoveryIntent.RESTART_WORKER if kind is SummaryKind.FAILURE_CAPSULE else None,
        escalation_level=EscalationLevel.AUTO_WITH_LIMIT if kind is SummaryKind.FAILURE_CAPSULE else None,
    )


def test_failure_capsule_preserves_failure_detail() -> None:
    decision = evaluate_compression_policy(
        _summary_input(SummaryKind.FAILURE_CAPSULE),
        CompressionPolicy(),
    )

    assert decision.preserve_failure_detail is True
    assert decision.preserve_key_facts is True


def test_task_handoff_preserves_next_step() -> None:
    decision = evaluate_compression_policy(
        _summary_input(SummaryKind.TASK_HANDOFF),
        CompressionPolicy(),
    )

    assert decision.preserve_next_step is True


def test_line_checkpoint_keeps_operator_constraints() -> None:
    decision = evaluate_compression_policy(
        _summary_input(SummaryKind.LINE_CHECKPOINT),
        CompressionPolicy(),
    )

    assert decision.preserve_operator_constraints is True


def test_next_step_token_is_stable() -> None:
    decision = evaluate_compression_policy(
        _summary_input(SummaryKind.TASK_PROGRESS),
        CompressionPolicy(),
    )

    assert decision.next_step_token == "summary.compress.task_progress"


def test_target_budget_is_positive_and_kind_specific() -> None:
    handoff = evaluate_compression_policy(
        _summary_input(SummaryKind.TASK_HANDOFF),
        CompressionPolicy(),
    )
    checkpoint = evaluate_compression_policy(
        _summary_input(SummaryKind.LINE_CHECKPOINT),
        CompressionPolicy(),
    )

    assert handoff.target_budget > 0
    assert checkpoint.target_budget > 0
    assert handoff.target_budget != checkpoint.target_budget
