"""Single-writer promotion bridge from reviewed runtime evidence to canonical files."""

from __future__ import annotations

from enum import StrEnum, auto
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.canonical_section_writer import (
    CanonicalSectionName,
    CanonicalSectionPatch,
    CanonicalSectionWriter,
    CanonicalTargetFile,
    CanonicalWriteShape,
)
from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.evidence_identity import EvidenceSubject
from controlmesh_runtime.promotion_receipt import PromotionReceipt
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.recovery.execution import (
    RecoveryExecutionPlan,
    RecoveryExecutionResult,
    RecoveryExecutionStatus,
)
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary.contracts import SummaryKind, SummaryRecord
from controlmesh_runtime.tracing import root_trace


class PromotionSource(StrEnum):
    """Allowed promotion submitters."""

    CONTROLLER = auto()
    WORKER = auto()


class PromotionInput(BaseModel):
    """Controller-side input contract for canonical promotion."""

    model_config = ConfigDict(frozen=True)

    line: str
    submitted_by: PromotionSource
    execution_plan: RecoveryExecutionPlan
    review_record: ReviewRecord
    execution_result: RecoveryExecutionResult
    summary_record: SummaryRecord | None = None
    latest_completed: str
    next_action: str

    @model_validator(mode="after")
    def validate_input(self) -> PromotionInput:
        _validate_promotion_text(self)
        _validate_promotion_authority(self)
        _validate_promotion_identity(self)
        _validate_promotion_completion(self)
        return self


class PromotionResult(BaseModel):
    """Result of one bounded canonical promotion."""

    model_config = ConfigDict(frozen=True)

    line: str
    status_token: str
    checkpoint_token: str
    updated_files: tuple[str, ...]
    receipt_id: str | None = None


class SummaryPromotionInput(BaseModel):
    """Narrow v1 promotion input sourced from review facts plus latest summaries."""

    model_config = ConfigDict(frozen=True)

    line: str
    submitted_by: PromotionSource
    review_record: ReviewRecord
    latest_task_summary: SummaryRecord
    latest_line_summary: SummaryRecord
    latest_completed: str
    next_action: str
    trace_id: str | None = None
    parent_span_id: str | None = None

    @model_validator(mode="after")
    def validate_input(self) -> SummaryPromotionInput:
        _validate_summary_promotion_text(self)
        _validate_summary_promotion_authority(self)
        _validate_summary_promotion_summary_shapes(self)
        _validate_summary_promotion_identity(self)
        return self


class PromotionEligibility(BaseModel):
    """Explicit gate result before any canonical write-back occurs."""

    model_config = ConfigDict(frozen=True)

    eligible: bool
    status_token: str
    checkpoint_token: str
    reasons: tuple[str, ...]
    write_targets: tuple[str, ...]
    write_intent: PromotionWriteIntent


class PromotionWriteIntent(BaseModel):
    """Structured canonical write intent for the promotion safety pack."""

    model_config = ConfigDict(frozen=True)

    intent_id: str = Field(default_factory=lambda: uuid4().hex)
    line: str
    submitted_by: PromotionSource
    source_review_id: str
    source_task_summary_id: str
    source_line_summary_id: str
    task_summary_entity_id: str
    line_summary_entity_id: str
    expected_task_summary_id: str
    expected_line_summary_id: str
    status_token: str
    checkpoint_token: str
    patches: tuple[CanonicalSectionPatch, ...]

    @model_validator(mode="after")
    def validate_intent(self) -> PromotionWriteIntent:
        if not self.line.strip():
            msg = "promotion write intent line must not be empty"
            raise ValueError(msg)
        if self.submitted_by is not PromotionSource.CONTROLLER:
            msg = "promotion write intent must remain controller-owned"
            raise ValueError(msg)
        for field_name in (
            "source_review_id",
            "source_task_summary_id",
            "source_line_summary_id",
            "task_summary_entity_id",
            "line_summary_entity_id",
            "expected_task_summary_id",
            "expected_line_summary_id",
            "status_token",
            "checkpoint_token",
        ):
            value = getattr(self, field_name)
            if not value.strip():
                msg = f"promotion write intent {field_name} must not be empty"
                raise ValueError(msg)
        if not self.patches:
            msg = "promotion write intent patches must not be empty"
            raise ValueError(msg)
        return self


class PromotionBridge:
    """Apply single-writer canonical line updates through one bounded surface."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._store = RuntimeStore(root)
        self._writer = CanonicalSectionWriter(root)

    def promote(self, inp: PromotionInput) -> PromotionResult:
        status_token = _status_token_for_outcome(inp.review_record.outcome)
        checkpoint_token = f"checkpoint-{inp.line}-{status_token}"
        progress_notes = [
            f"review_outcome={inp.review_record.outcome.plan_token}",
            f"execution_status={inp.execution_result.status.value}",
            f"identity_packet_id={inp.execution_plan.packet_id}",
            f"identity_task_id={inp.execution_plan.task_id}",
            f"identity_plan_id={inp.execution_plan.plan_id}",
        ]
        if inp.summary_record is not None:
            progress_notes.append(f"latest_summary_id={inp.summary_record.summary_id}")
            progress_notes.append(f"latest_summary_kind={inp.summary_record.summary_kind.value}")
        updated_files = self._writer.write(
            line=inp.line,
            patches=(
                CanonicalSectionPatch(
                    target_file=CanonicalTargetFile.TASK_PLAN,
                    section=CanonicalSectionName.CURRENT_STATUS,
                    shape=CanonicalWriteShape.SECTION_REPLACE,
                    body=status_token,
                ),
                CanonicalSectionPatch(
                    target_file=CanonicalTargetFile.PROGRESS,
                    section=CanonicalSectionName.LATEST_COMPLETED,
                    shape=CanonicalWriteShape.SECTION_REPLACE,
                    body=inp.latest_completed,
                ),
                CanonicalSectionPatch(
                    target_file=CanonicalTargetFile.PROGRESS,
                    section=CanonicalSectionName.CURRENT_STATE,
                    shape=CanonicalWriteShape.SECTION_REPLACE,
                    body=status_token,
                ),
                CanonicalSectionPatch(
                    target_file=CanonicalTargetFile.PROGRESS,
                    section=CanonicalSectionName.NEXT_ACTION,
                    shape=CanonicalWriteShape.SECTION_REPLACE,
                    body=inp.next_action,
                ),
                CanonicalSectionPatch(
                    target_file=CanonicalTargetFile.PROGRESS,
                    section=CanonicalSectionName.LATEST_CHECKPOINT,
                    shape=CanonicalWriteShape.SECTION_REPLACE,
                    body=checkpoint_token,
                ),
                CanonicalSectionPatch(
                    target_file=CanonicalTargetFile.PROGRESS,
                    section=CanonicalSectionName.NOTES,
                    shape=CanonicalWriteShape.MARKER_BLOCK_UPSERT,
                    body="\n".join(progress_notes),
                    marker="promotion-bridge:legacy",
                ),
            ),
        )

        return PromotionResult(
            line=inp.line,
            status_token=status_token,
            checkpoint_token=checkpoint_token,
            updated_files=updated_files,
        )

    def evaluate_summary_promotion(self, inp: SummaryPromotionInput) -> PromotionEligibility:
        self._validate_current_summary_snapshots(inp)
        status_token = _status_token_for_outcome(inp.review_record.outcome)
        checkpoint_token = f"checkpoint-{inp.line}-{status_token}"
        reasons = [f"review_outcome={inp.review_record.outcome.plan_token}"]
        if inp.review_record.reasons:
            reasons.extend(inp.review_record.reasons)
        write_intent = _build_summary_promotion_write_intent(
            inp,
            status_token=status_token,
            checkpoint_token=checkpoint_token,
        )
        return PromotionEligibility(
            eligible=True,
            status_token=status_token,
            checkpoint_token=checkpoint_token,
            reasons=tuple(reasons),
            write_targets=(
                str(self._root / "plans" / inp.line / "task_plan.md"),
                str(self._root / "plans" / inp.line / "progress.md"),
            ),
            write_intent=write_intent,
        )

    def promote_summary(self, inp: SummaryPromotionInput) -> PromotionResult:
        gate = self.evaluate_summary_promotion(inp)
        updated_files = self._writer.write(
            line=inp.line,
            patches=gate.write_intent.patches,
            pre_write_check=lambda: self._validate_write_intent_summary_snapshots(gate.write_intent),
        )
        trace = root_trace(inp.trace_id)
        receipt = self._store.save_promotion_receipt(
            PromotionReceipt(
                line=inp.line,
                evidence_identity=inp.review_record.evidence_identity,
                review_id=inp.review_record.review_id,
                task_summary_id=inp.latest_task_summary.summary_id,
                line_summary_id=inp.latest_line_summary.summary_id,
                checkpoint_token=gate.checkpoint_token,
                written_sections=tuple(
                    f"{patch.target_file.value}:{patch.section.value}"
                    for patch in gate.write_intent.patches
                ),
                updated_files=updated_files,
                submitted_by=inp.submitted_by.value,
                trace_id=trace.trace_id,
                span_id=trace.span_id,
                parent_span_id=inp.parent_span_id,
            )
        )

        return PromotionResult(
            line=inp.line,
            status_token=gate.status_token,
            checkpoint_token=gate.checkpoint_token,
            updated_files=updated_files,
            receipt_id=receipt.receipt_id,
        )

    def _validate_current_summary_snapshots(self, inp: SummaryPromotionInput) -> None:
        current_task_summary = self._store.load_summary_record(inp.latest_task_summary.entity_id)
        if current_task_summary.summary_id != inp.latest_task_summary.summary_id:
            msg = "latest_task_summary is not the current stored summary snapshot"
            raise ValueError(msg)
        current_line_summary = self._store.load_summary_record(inp.latest_line_summary.entity_id)
        if current_line_summary.summary_id != inp.latest_line_summary.summary_id:
            msg = "latest_line_summary is not the current stored summary snapshot"
            raise ValueError(msg)

    def _validate_write_intent_summary_snapshots(self, intent: PromotionWriteIntent) -> None:
        current_task_summary = self._store.load_summary_record(intent.task_summary_entity_id)
        if current_task_summary.summary_id != intent.expected_task_summary_id:
            msg = "promotion write intent task summary freshness check failed"
            raise ValueError(msg)
        current_line_summary = self._store.load_summary_record(intent.line_summary_entity_id)
        if current_line_summary.summary_id != intent.expected_line_summary_id:
            msg = "promotion write intent line summary freshness check failed"
            raise ValueError(msg)


def _validate_promotion_text(inp: PromotionInput) -> None:
    if not inp.line.strip():
        msg = "promotion line must not be empty"
        raise ValueError(msg)
    if not inp.latest_completed.strip():
        msg = "promotion latest_completed must not be empty"
        raise ValueError(msg)
    if not inp.next_action.strip():
        msg = "promotion next_action must not be empty"
        raise ValueError(msg)


def _validate_promotion_authority(inp: PromotionInput) -> None:
    if inp.submitted_by is not PromotionSource.CONTROLLER:
        msg = "promotion bridge is controller-owned and rejects non-controller submissions"
        raise ValueError(msg)


def _validate_promotion_identity(inp: PromotionInput) -> None:
    if inp.execution_plan.line != inp.line:
        msg = "promotion line must match execution plan line"
        raise ValueError(msg)
    if inp.review_record.evidence_identity != inp.execution_plan.evidence_identity:
        msg = "promotion review record must match execution plan evidence identity"
        raise ValueError(msg)
    if inp.execution_result.plan_id != inp.execution_plan.plan_id:
        msg = "promotion execution result must match execution plan"
        raise ValueError(msg)
    if inp.execution_result.evidence_identity != inp.execution_plan.evidence_identity:
        msg = "promotion execution result must match execution plan evidence identity"
        raise ValueError(msg)
    if inp.summary_record is None:
        return
    if inp.summary_record.evidence_identity != inp.execution_plan.evidence_identity:
        msg = "promotion summary record must match execution plan evidence identity"
        raise ValueError(msg)
    if inp.summary_record.subject is EvidenceSubject.LINE and inp.summary_record.evidence_identity.line != inp.line:
        msg = "promotion line summary must match target line"
        raise ValueError(msg)


def _validate_promotion_completion(inp: PromotionInput) -> None:
    if inp.review_record.outcome in {ReviewOutcome.PASS, ReviewOutcome.PASS_WITH_NOTES} and inp.execution_result.status is not RecoveryExecutionStatus.COMPLETED:
        msg = "cannot promote a completed review from a non-completed execution result"
        raise ValueError(msg)


def _status_token_for_outcome(outcome: ReviewOutcome) -> str:
    return {
        ReviewOutcome.PASS: "completed",
        ReviewOutcome.PASS_WITH_NOTES: "completed",
        ReviewOutcome.RETURN_FOR_HARDENING: "in_progress",
        ReviewOutcome.BLOCKED_BY_ENVIRONMENT: "blocked_by_environment",
        ReviewOutcome.BLOCKED_BY_OPERATOR_SAFETY: "blocked_by_operator_safety",
        ReviewOutcome.STOPLINE: "stopline",
        ReviewOutcome.SPLIT_INTO_NEW_SCOPE: "split_into_new_scope",
        ReviewOutcome.DEFERRED_WITH_REASON: "deferred_with_reason",
    }[outcome]


def _validate_summary_promotion_text(inp: SummaryPromotionInput) -> None:
    if not inp.line.strip():
        msg = "promotion line must not be empty"
        raise ValueError(msg)
    if not inp.latest_completed.strip():
        msg = "promotion latest_completed must not be empty"
        raise ValueError(msg)
    if not inp.next_action.strip():
        msg = "promotion next_action must not be empty"
        raise ValueError(msg)


def _validate_summary_promotion_authority(inp: SummaryPromotionInput) -> None:
    if inp.submitted_by is not PromotionSource.CONTROLLER:
        msg = "promotion bridge is controller-owned and rejects non-controller submissions"
        raise ValueError(msg)


def _validate_summary_promotion_summary_shapes(inp: SummaryPromotionInput) -> None:
    if inp.latest_task_summary.subject is not EvidenceSubject.TASK:
        msg = "latest_task_summary must use task subject"
        raise ValueError(msg)
    if inp.latest_task_summary.summary_kind is not SummaryKind.TASK_HANDOFF:
        msg = "latest_task_summary must use task_handoff kind"
        raise ValueError(msg)
    if inp.latest_line_summary.subject is not EvidenceSubject.LINE:
        msg = "latest_line_summary must use line subject"
        raise ValueError(msg)
    if inp.latest_line_summary.summary_kind is not SummaryKind.LINE_CHECKPOINT:
        msg = "latest_line_summary must use line_checkpoint kind"
        raise ValueError(msg)


def _validate_summary_promotion_identity(inp: SummaryPromotionInput) -> None:
    if inp.review_record.evidence_identity.line != inp.line:
        msg = "promotion review record line must match target line"
        raise ValueError(msg)
    if inp.latest_task_summary.evidence_identity != inp.review_record.evidence_identity:
        msg = "latest summaries must share review evidence identity"
        raise ValueError(msg)
    if inp.latest_line_summary.evidence_identity != inp.review_record.evidence_identity:
        msg = "latest summaries must share review evidence identity"
        raise ValueError(msg)
    if inp.latest_line_summary.evidence_identity.line != inp.line:
        msg = "latest line summary must match target line"
        raise ValueError(msg)


def _build_summary_promotion_write_intent(
    inp: SummaryPromotionInput,
    *,
    status_token: str,
    checkpoint_token: str,
) -> PromotionWriteIntent:
    progress_notes = [
        f"review_id={inp.review_record.review_id}",
        f"review_outcome={inp.review_record.outcome.plan_token}",
        f"identity_packet_id={inp.review_record.evidence_identity.packet_id}",
        f"identity_task_id={inp.review_record.evidence_identity.task_id}",
        f"identity_plan_id={inp.review_record.evidence_identity.plan_id}",
        f"latest_task_summary_id={inp.latest_task_summary.summary_id}",
        f"latest_task_summary_kind={inp.latest_task_summary.summary_kind.value}",
        f"latest_line_summary_id={inp.latest_line_summary.summary_id}",
        f"latest_line_summary_kind={inp.latest_line_summary.summary_kind.value}",
    ]
    progress_notes.extend(f"review_reason={reason}" for reason in inp.review_record.reasons)
    patches = (
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.TASK_PLAN,
            section=CanonicalSectionName.CURRENT_STATUS,
            shape=CanonicalWriteShape.SECTION_REPLACE,
            body=status_token,
        ),
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.PROGRESS,
            section=CanonicalSectionName.LATEST_COMPLETED,
            shape=CanonicalWriteShape.SECTION_REPLACE,
            body=inp.latest_completed,
        ),
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.PROGRESS,
            section=CanonicalSectionName.CURRENT_STATE,
            shape=CanonicalWriteShape.SECTION_REPLACE,
            body=status_token,
        ),
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.PROGRESS,
            section=CanonicalSectionName.NEXT_ACTION,
            shape=CanonicalWriteShape.SECTION_REPLACE,
            body=inp.next_action,
        ),
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.PROGRESS,
            section=CanonicalSectionName.LATEST_CHECKPOINT,
            shape=CanonicalWriteShape.SECTION_REPLACE,
            body=checkpoint_token,
        ),
        CanonicalSectionPatch(
            target_file=CanonicalTargetFile.PROGRESS,
            section=CanonicalSectionName.NOTES,
            shape=CanonicalWriteShape.MARKER_BLOCK_UPSERT,
            body="\n".join(progress_notes),
            marker="promotion-bridge:v1",
        ),
    )
    return PromotionWriteIntent(
        line=inp.line,
        submitted_by=inp.submitted_by,
        source_review_id=inp.review_record.review_id,
        source_task_summary_id=inp.latest_task_summary.summary_id,
        source_line_summary_id=inp.latest_line_summary.summary_id,
        task_summary_entity_id=inp.latest_task_summary.entity_id,
        line_summary_entity_id=inp.latest_line_summary.entity_id,
        expected_task_summary_id=inp.latest_task_summary.summary_id,
        expected_line_summary_id=inp.latest_line_summary.summary_id,
        status_token=status_token,
        checkpoint_token=checkpoint_token,
        patches=patches,
    )


__all__ = [
    "PromotionBridge",
    "PromotionEligibility",
    "PromotionInput",
    "PromotionResult",
    "PromotionSource",
    "PromotionWriteIntent",
    "SummaryPromotionInput",
]
