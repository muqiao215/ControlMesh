"""Typed review contracts for the ControlMesh runtime foundation."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class ReviewOutcome(StrEnum):
    """Canonical review outcomes for the harness runtime."""

    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        del start, count, last_values
        return name

    PASS = auto()
    PASS_WITH_NOTES = auto()
    RETURN_FOR_HARDENING = auto()
    BLOCKED_BY_ENVIRONMENT = auto()
    BLOCKED_BY_OPERATOR_SAFETY = auto()
    STOPLINE = auto()
    SPLIT_INTO_NEW_SCOPE = auto()
    DEFERRED_WITH_REASON = auto()

    @property
    def plan_token(self) -> str:
        """Bridge runtime enum names to existing plan-file tokens."""
        return self.name.lower()


class ReviewInput(BaseModel):
    """Evidence-backed input for one bounded review decision."""

    model_config = ConfigDict(frozen=True)

    evidence_complete: bool = True
    schema_valid: bool = True
    contract_matches_observed_result: bool = True
    minimal_working_loop_present: bool = True
    scope_breached: bool = False
    canonical_write_breached: bool = False
    live_regression: bool = False

    score: float | None = None
    notes: tuple[str, ...] = Field(default_factory=tuple)
    hardening_reasons: tuple[str, ...] = Field(default_factory=tuple)

    blocked_by_environment_reason: str | None = None
    blocked_by_operator_safety_reason: str | None = None
    stopline_reason: str | None = None
    split_scope_reason: str | None = None
    deferred_reason: str | None = None

    @model_validator(mode="after")
    def validate_terminal_signals(self) -> ReviewInput:
        """Reject contradictory top-level outcomes."""
        exclusive_reasons = [
            self.blocked_by_environment_reason,
            self.blocked_by_operator_safety_reason,
            self.stopline_reason,
            self.split_scope_reason,
            self.deferred_reason,
        ]
        selected = sum(reason is not None for reason in exclusive_reasons)
        if selected > 1:
            msg = "review input cannot carry multiple terminal outcome reasons"
            raise ValueError(msg)
        return self


class SignalAction(StrEnum):
    """Asynchronous runtime control-plane signals."""

    REQUEST_SUMMARY = "request_summary"


class QueryAction(StrEnum):
    """Read-only runtime control-plane queries."""

    LATEST_SUMMARY = "latest_summary"


class UpdateAction(StrEnum):
    """Synchronous runtime control-plane updates."""

    PROMOTE = "promote"


class ControlEventKind(StrEnum):
    """Append-only control-plane event kinds."""

    SIGNAL_REQUEST_SUMMARY = "signal.request_summary"
    OBSERVATION_TASK_SUMMARY = "observation.task_summary"
    OBSERVATION_LINE_SUMMARY = "observation.line_summary"
    MATERIALIZATION_PROMOTION_RECEIPT = "materialization.promotion_receipt"


class ControlEvent(BaseModel):
    """Traceable append-only runtime control event."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    recorded_at: str = Field(default_factory=utc_now_iso)
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    kind: ControlEventKind
    evidence_identity: RuntimeEvidenceIdentity
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make(
        cls,
        *,
        kind: ControlEventKind,
        evidence_identity: RuntimeEvidenceIdentity,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> ControlEvent:
        return cls(
            trace_id=trace_id or uuid4().hex,
            span_id=uuid4().hex,
            parent_span_id=parent_span_id,
            kind=kind,
            evidence_identity=evidence_identity,
            payload=payload or {},
        )

    @model_validator(mode="after")
    def validate_event(self) -> ControlEvent:
        if not self.event_id.strip():
            msg = "control event event_id must not be empty"
            raise ValueError(msg)
        if not self.trace_id.strip():
            msg = "control event trace_id must not be empty"
            raise ValueError(msg)
        if not self.span_id.strip():
            msg = "control event span_id must not be empty"
            raise ValueError(msg)
        return self
