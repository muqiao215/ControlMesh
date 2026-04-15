"""Persisted record types for the ControlMesh runtime store."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import ReviewOutcome, utc_now_iso
from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity


class ReviewRecord(BaseModel):
    """One persisted review fact for a task packet."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    review_id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    evidence_identity: RuntimeEvidenceIdentity
    outcome: ReviewOutcome
    score: float | None = None
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    source: str
    recorded_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def validate_record(self) -> ReviewRecord:
        """Keep persisted review facts explicit and non-empty."""
        if not self.review_id.strip():
            msg = "review record review_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "review record task_id must not be empty"
            raise ValueError(msg)
        if self.evidence_identity.task_id != self.task_id:
            msg = "review record task_id must match evidence identity task_id"
            raise ValueError(msg)
        if not self.source.strip():
            msg = "review record source must not be empty"
            raise ValueError(msg)
        if any(not item.strip() for item in self.reasons):
            msg = "review record reasons must not contain blank items"
            raise ValueError(msg)
        return self
