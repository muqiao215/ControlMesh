"""Typed summary compression contracts for the ControlMesh runtime."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import ReviewOutcome, utc_now_iso
from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.recovery import EscalationLevel, RecoveryIntent
from controlmesh_runtime.worker_state import WorkerStatus


class SummaryKind(StrEnum):
    """Kinds of runtime summaries that may be generated later."""

    TASK_PROGRESS = auto()
    TASK_HANDOFF = auto()
    LINE_CHECKPOINT = auto()
    WORKER_CONTEXT = auto()
    FAILURE_CAPSULE = auto()
    RECOVERY_CAPSULE = auto()


class SummaryInput(BaseModel):
    """Compression input describing the source context to be summarized."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    line: str
    evidence_identity: RuntimeEvidenceIdentity
    summary_kind: SummaryKind
    source_refs: tuple[str, ...]
    source_events: tuple[str, ...] = Field(default_factory=tuple)
    source_findings: tuple[str, ...] = Field(default_factory=tuple)
    source_progress: tuple[str, ...] = Field(default_factory=tuple)
    current_worker_state: WorkerStatus | None = None
    current_review_outcome: ReviewOutcome | None = None
    failure_class: FailureClass | None = None
    recovery_intent: RecoveryIntent | None = None
    escalation_level: EscalationLevel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_input(self) -> SummaryInput:
        """Keep summary inputs explicit and structurally complete."""
        if not self.task_id.strip():
            msg = "summary input task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "summary input line must not be empty"
            raise ValueError(msg)
        if self.evidence_identity.task_id != self.task_id:
            msg = "summary input task_id must match evidence identity task_id"
            raise ValueError(msg)
        if self.evidence_identity.line != self.line:
            msg = "summary input line must match evidence identity line"
            raise ValueError(msg)
        if not self.source_refs:
            msg = "summary input source_refs must not be empty"
            raise ValueError(msg)
        if self.summary_kind is SummaryKind.FAILURE_CAPSULE and self.failure_class is None:
            msg = "failure_capsule inputs require failure_class"
            raise ValueError(msg)
        return self


class SummaryRecord(BaseModel):
    """One typed summary record that can later be persisted or consumed."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    summary_id: str = Field(default_factory=lambda: uuid4().hex)
    summary_kind: SummaryKind
    subject: EvidenceSubject
    evidence_identity: RuntimeEvidenceIdentity
    entity_id: str
    token_budget: int
    source_refs: tuple[str, ...]
    key_facts: tuple[str, ...]
    open_questions: tuple[str, ...] = Field(default_factory=tuple)
    deferred_items: tuple[str, ...] = Field(default_factory=tuple)
    next_step_hint: str | None = None
    failure_class: FailureClass | None = None
    recovery_intent: RecoveryIntent | None = None
    escalation_level: EscalationLevel | None = None
    generated_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def validate_record(self) -> SummaryRecord:
        """Reject incomplete or semantically invalid summary records."""
        _validate_summary_record_identity(self)
        _validate_summary_record_content(self)
        _validate_summary_record_kind(self)
        return self


class CompressionDecision(BaseModel):
    """Pure decision describing how summary compression should behave."""

    model_config = ConfigDict(frozen=True)

    should_compress: bool
    target_kind: SummaryKind
    target_budget: int
    preserve_failure_detail: bool
    preserve_next_step: bool
    preserve_operator_constraints: bool
    preserve_key_facts: bool = True
    next_step_token: str

    @model_validator(mode="after")
    def validate_decision(self) -> CompressionDecision:
        """Keep compression decisions executable and stable."""
        if self.should_compress and self.target_budget <= 0:
            msg = "compression decision target_budget must be > 0"
            raise ValueError(msg)
        if not self.next_step_token.strip():
            msg = "compression decision next_step_token must not be empty"
            raise ValueError(msg)
        return self


def _validate_summary_record_identity(record: SummaryRecord) -> None:
    expected_entity_id = record.evidence_identity.entity_id_for(record.subject)
    if not record.entity_id.strip():
        msg = "summary record entity_id must not be empty"
        raise ValueError(msg)
    if record.entity_id != expected_entity_id:
        msg = "summary record entity_id must match typed subject identity"
        raise ValueError(msg)


def _validate_summary_record_content(record: SummaryRecord) -> None:
    if record.token_budget <= 0:
        msg = "summary record token_budget must be > 0"
        raise ValueError(msg)
    if not record.source_refs:
        msg = "summary record source_refs must not be empty"
        raise ValueError(msg)
    if not record.key_facts:
        msg = "summary record key_facts must not be empty"
        raise ValueError(msg)
    if record.summary_kind is SummaryKind.TASK_HANDOFF and not record.next_step_hint:
        msg = "task_handoff summaries require next_step_hint"
        raise ValueError(msg)


def _validate_summary_record_kind(record: SummaryRecord) -> None:
    if record.summary_kind is SummaryKind.LINE_CHECKPOINT and record.subject is not EvidenceSubject.LINE:
        msg = "line_checkpoint summaries require line subject"
        raise ValueError(msg)
    if record.summary_kind is not SummaryKind.LINE_CHECKPOINT and record.subject is not EvidenceSubject.TASK:
        msg = "non-line summaries require task subject"
        raise ValueError(msg)
    if record.summary_kind is SummaryKind.FAILURE_CAPSULE:
        if record.failure_class is None:
            msg = "failure_capsule summaries require failure_class"
            raise ValueError(msg)
        if record.recovery_intent is None:
            msg = "failure_capsule summaries require recovery_intent"
            raise ValueError(msg)
        if record.escalation_level is None:
            msg = "failure_capsule summaries require escalation_level"
            raise ValueError(msg)
