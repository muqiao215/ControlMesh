"""Typed models for the additive ControlMesh memory-v2 layer."""

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


class MemoryDocumentKind(StrEnum):
    """Indexed memory-v2 document kinds."""

    AUTHORITY = "authority"
    DREAM_DIARY = "dream-diary"
    DAILY_NOTE = "daily-note"


class PromotionSourceKind(StrEnum):
    """Explicit origins for promotion candidates."""

    DAILY_NOTE = "daily-note"
    DREAMING_SWEEP = "dreaming-sweep"
    MANUAL = "manual"


class MemoryScope(StrEnum):
    """Scope of a memory entry: local (private) or shared (explicitly shared).

    Entries default to LOCAL to preserve backward compatibility with existing
    authority entries. SHARED entries are explicitly opted-in and represent
    information intended for cross-agent or shared contexts.
    """

    LOCAL = "local"
    SHARED = "shared"


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
    scope: MemoryScope = MemoryScope.LOCAL

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
    last_run_mode: str | None = None
    last_started_at: str | None = None
    last_completed_at: str | None = None
    last_processed_day: str | None = None
    last_error: str | None = None
    last_changed_notes: int = 0
    last_selected_count: int = 0
    last_applied_count: int = 0
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


class MemoryIndexSyncResult(BaseModel):
    """Deterministic SQLite index sync counters."""

    indexed_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    unchanged_count: int = 0


class MemorySearchHit(BaseModel):
    """One ranked local memory search match."""

    source_path: str
    kind: MemoryDocumentKind
    source_date: str | None = None
    snippet: str
    rank: float


class MemorySearchResult(BaseModel):
    """Ranked search results from the local FTS5 index."""

    query: str
    hits: list[MemorySearchHit] = Field(default_factory=list)


class SemanticSearchHit(BaseModel):
    """One trigram-similarity match from the non-authoritative semantic index.

    Always includes a source reference so users can inspect the original
    markdown entry directly.  The similarity score is an approximation
    (character trigram Jaccard) and is not authoritative.
    """

    entry_id: str = ""
    kind: MemoryDocumentKind = MemoryDocumentKind.AUTHORITY
    source_path: str = ""
    section: str | None = None
    content: str = ""
    authority_entry_id: str | None = None
    line_number: int | None = None
    similarity: float = 0.0


class SemanticSearchResult(BaseModel):
    """Trigram-similarity search results from the non-authoritative semantic index.

    The semantic index is a derived/cache-like sidecar.  Markdown files remain
    the sole source of truth.
    """

    query: str = ""
    hits: list[SemanticSearchHit] = Field(default_factory=list)
    index_available: bool = True
    indexed_at: str | None = None
    total_indexed: int = 0


class LifecycleStatus(StrEnum):
    """Lifecycle state for promoted authority memory entries."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"


class AuthorityEntryMetadata(BaseModel):
    """Lightweight lifecycle metadata for authority memory entries.

    Carried inline in MEMORY.md entries to support reversible promotion
    without requiring a database or semantic index.
    """

    entry_id: str | None = None
    status: LifecycleStatus = LifecycleStatus.ACTIVE
    scope: MemoryScope = MemoryScope.LOCAL
    promoted_at: str | None = None
    source_ref: str | None = None
    superseded_by: str | None = None
    evidence_count: int | None = None


class DreamingSweepMode(StrEnum):
    """Supported sweep execution modes."""

    PREVIEW = "preview"
    APPLY = "apply"


class DreamingSweepNoteResult(BaseModel):
    """Per-note result from a dreaming sweep run."""

    note_date: str
    note_path: str
    note_hash: str
    changed: bool
    candidate_count: int = 0
    selected_count: int = 0
    applied_count: int = 0
    skipped_existing: int = 0
    skipped_low_score: int = 0


class DreamingSweepResult(BaseModel):
    """Aggregate dreaming sweep output."""

    mode: DreamingSweepMode
    owner: str
    started_at: str
    completed_at: str
    processed_notes: int = 0
    changed_notes: int = 0
    skipped_unchanged_notes: int = 0
    selected_count: int = 0
    applied_count: int = 0
    last_processed_day: str | None = None
    promoted_candidate_keys: list[str] = Field(default_factory=list)
    note_results: list[DreamingSweepNoteResult] = Field(default_factory=list)
