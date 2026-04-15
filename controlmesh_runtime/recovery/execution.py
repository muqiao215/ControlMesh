"""Typed recovery execution plan and result contracts."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.events import EventKind, FailureClass
from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity
from controlmesh_runtime.recovery.contracts import RecoveryIntent, RecoveryPolicy


class RecoveryExecutionAction(StrEnum):
    """Generic recovery actions that the runtime may execute later."""

    RETRY_SAME_WORKER = auto()
    RESTART_WORKER = auto()
    RECREATE_WORKER = auto()
    CLEAR_RUNTIME_STATE = auto()
    MARK_REAUTH_REQUIRED = auto()
    EMIT_HUMAN_GATE = auto()
    SPLIT_SCOPE = auto()
    DEFER_LINE = auto()
    STOPLINE = auto()


class RecoveryExecutionStep(BaseModel):
    """One generic recovery step within an execution plan."""

    model_config = ConfigDict(frozen=True)

    action: RecoveryExecutionAction
    target: str
    args: dict[str, Any] = Field(default_factory=dict)
    destructive: bool = False
    retryable: bool = False
    requires_human_gate: bool = False
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_step(self) -> RecoveryExecutionStep:
        """Keep step contracts explicit and safe by default."""
        if not self.target.strip():
            msg = "recovery execution step target must not be empty"
            raise ValueError(msg)
        if self.action in _DESTRUCTIVE_ACTIONS and not self.destructive:
            msg = "destructive recovery actions must set destructive=True"
            raise ValueError(msg)
        if any(not note.strip() for note in self.notes):
            msg = "recovery execution step notes must not contain blank items"
            raise ValueError(msg)
        return self


class RecoveryExecutionPlan(BaseModel):
    """A bounded recovery plan produced from an already-authorized decision."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    plan_id: str = Field(default_factory=lambda: uuid4().hex)
    packet_id: str
    task_id: str
    line: str
    worker_id: str | None
    intent: RecoveryIntent
    steps: tuple[RecoveryExecutionStep, ...]
    requires_human_gate: bool = False
    human_gate_reasons: tuple[str, ...] = Field(default_factory=tuple)
    policy_snapshot: RecoveryPolicy
    next_step_token: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_plan(self) -> RecoveryExecutionPlan:
        """Reject incomplete plans and unstable human-gate semantics."""
        if not self.packet_id.strip():
            msg = "recovery execution plan packet_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "recovery execution plan task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "recovery execution plan line must not be empty"
            raise ValueError(msg)
        if not self.steps:
            msg = "recovery execution plan steps must not be empty"
            raise ValueError(msg)
        if not self.next_step_token.strip():
            msg = "recovery execution plan next_step_token must not be empty"
            raise ValueError(msg)
        if self.requires_human_gate and not self.human_gate_reasons:
            msg = "human-gated plans require human_gate_reasons"
            raise ValueError(msg)
        if any(step.requires_human_gate for step in self.steps) and not self.requires_human_gate:
            msg = "plans with human-gated steps must set requires_human_gate"
            raise ValueError(msg)
        if any(not reason.strip() for reason in self.human_gate_reasons):
            msg = "recovery execution plan human_gate_reasons must not contain blank items"
            raise ValueError(msg)
        return self

    @property
    def evidence_identity(self) -> RuntimeEvidenceIdentity:
        """Return the canonical bounded identity tuple for this plan."""
        return RuntimeEvidenceIdentity(
            packet_id=self.packet_id,
            task_id=self.task_id,
            line=self.line,
            plan_id=self.plan_id,
        )


class RecoveryExecutionStatus(StrEnum):
    """Observed execution status for a recovery plan."""

    PENDING = auto()
    APPROVED = auto()
    RUNNING = auto()
    PARTIALLY_COMPLETED = auto()
    COMPLETED = auto()
    FAILED = auto()
    ABORTED = auto()
    BLOCKED_BY_HUMAN_GATE = auto()


class RecoveryExecutionResult(BaseModel):
    """One typed recovery execution result without side-effect semantics."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    plan_id: str
    evidence_identity: RuntimeEvidenceIdentity
    status: RecoveryExecutionStatus
    completed_step_count: int = 0
    failed_step_index: int | None = None
    failure_class: FailureClass | None = None
    requires_human_gate: bool = False
    next_review_outcome_hint: ReviewOutcome | None = None
    emitted_event_types: tuple[EventKind, ...] = Field(default_factory=tuple)
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_result(self) -> RecoveryExecutionResult:
        """Keep execution results explicit and reviewable."""
        if not self.plan_id.strip():
            msg = "recovery execution result plan_id must not be empty"
            raise ValueError(msg)
        if self.evidence_identity.plan_id != self.plan_id:
            msg = "recovery execution result plan_id must match evidence identity plan_id"
            raise ValueError(msg)
        if self.completed_step_count < 0:
            msg = "recovery execution result completed_step_count must be >= 0"
            raise ValueError(msg)
        if self.failed_step_index is not None and self.failed_step_index < 0:
            msg = "recovery execution result failed_step_index must be >= 0"
            raise ValueError(msg)
        if self.status is RecoveryExecutionStatus.PARTIALLY_COMPLETED and self.completed_step_count <= 0:
            msg = "partially_completed results must complete at least one step"
            raise ValueError(msg)
        if self.status is RecoveryExecutionStatus.FAILED and self.failure_class is None and self.failed_step_index is None:
            msg = "failed results require failure_class or failed_step_index"
            raise ValueError(msg)
        if self.status is RecoveryExecutionStatus.BLOCKED_BY_HUMAN_GATE and not self.requires_human_gate:
            msg = "blocked_by_human_gate results must set requires_human_gate"
            raise ValueError(msg)
        if any(not note.strip() for note in self.notes):
            msg = "recovery execution result notes must not contain blank items"
            raise ValueError(msg)
        return self


_DESTRUCTIVE_ACTIONS: frozenset[RecoveryExecutionAction] = frozenset(
    {
        RecoveryExecutionAction.CLEAR_RUNTIME_STATE,
        RecoveryExecutionAction.SPLIT_SCOPE,
        RecoveryExecutionAction.DEFER_LINE,
        RecoveryExecutionAction.STOPLINE,
    }
)
