"""Typed models for the additive Ductor memory-v2 layer."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class MemoryCategory(StrEnum):
    """Durable authority sections in ``MEMORY.md``."""

    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    PROJECT = "project"
    PERSON = "person"


class PromotionSourceKind(StrEnum):
    """Explicit origins for promotion candidates."""

    DAILY_NOTE = "daily-note"
    DREAMING_SWEEP = "dreaming-sweep"
    MANUAL = "manual"


class PromotionCandidate(BaseModel):
    """A deterministic promotion candidate ready for preview/apply."""

    key: str
    category: MemoryCategory
    content: str
    source_kind: PromotionSourceKind = PromotionSourceKind.DAILY_NOTE
    source_path: str
    source_date: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    score: float = 1.0

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        return value.strip()


class PromotionPreview(BaseModel):
    """Preview of candidates selected for promotion."""

    selected: list[PromotionCandidate] = Field(default_factory=list)
    skipped_existing: int = 0
    skipped_low_score: int = 0


class PromotionApplyResult(BaseModel):
    """Result from applying promotion candidates into ``MEMORY.md``."""

    applied_count: int = 0
    skipped_existing: int = 0
    skipped_low_score: int = 0
    applied_keys: list[str] = Field(default_factory=list)


class DreamingSweepState(BaseModel):
    """Persistent machine state for dreaming sweep progression."""

    status: str = "idle"
    last_started_at: str | None = None
    last_completed_at: str | None = None
    last_processed_day: str | None = None
    last_error: str | None = None
    promoted_candidate_keys: list[str] = Field(default_factory=list)


class DreamingCheckpoint(BaseModel):
    """Checkpoint for a processed daily memory note."""

    note_date: str
    note_path: str
    note_hash: str
    candidate_keys: list[str] = Field(default_factory=list)
    processed_at: str


class DreamingLock(BaseModel):
    """Exclusive dreaming sweep lock file."""

    owner: str
    acquired_at: str
    expires_at: str
