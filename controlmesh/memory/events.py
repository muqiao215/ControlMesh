"""Unified memory event schema for ControlMesh memory-v3.

This module defines the canonical event types used to capture chat turns,
task results, worker results, team events, and ask_parent/resume pairs
into a common structure suitable for later phases (daily note capture,
semantic indexing, frequency analysis).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryEventKind(StrEnum):
    """Unified event kinds for memory capture."""

    CHAT_TURN = "chat-turn"
    TASK_RESULT = "task-result"
    WORKER_RESULT = "worker-result"
    TEAM_EVENT = "team-event"
    ASK_PARENT = "ask-parent"
    RESUME = "resume"
    PROMOTION = "promotion"
    DAILY_NOTE = "daily-note"


class EvidenceRefKind(StrEnum):
    """Supported evidence reference types."""

    FILE = "file"
    URL = "url"
    MESSAGE = "message"
    MESSAGE_RANGE = "message-range"
    TASK_OUTPUT = "task-output"


class EvidenceRef(BaseModel):
    """Reference to a piece of evidence supporting a memory event."""

    ref_id: str = Field(default_factory=lambda: str(uuid4()))
    ref_kind: EvidenceRefKind
    path: str | None = None
    url: str | None = None
    message_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    snippet: str | None = None

    def model_post_init(self, _execution_context: Any | None = None) -> None:
        if self.ref_kind is EvidenceRefKind.FILE and not self.path:
            raise ValueError("path is required for FILE evidence refs")
        if self.ref_kind is EvidenceRefKind.URL and not self.url:
            raise ValueError("url is required for URL evidence refs")
        if self.ref_kind is EvidenceRefKind.MESSAGE and not self.message_id:
            raise ValueError("message_id is required for MESSAGE evidence refs")
        if self.ref_kind is EvidenceRefKind.MESSAGE_RANGE:
            if not self.message_id:
                raise ValueError("message_id is required for MESSAGE_RANGE evidence refs")
            if not self.line_start or not self.line_end:
                raise ValueError("line_start and line_end are required for MESSAGE_RANGE evidence refs")
        if self.ref_kind is EvidenceRefKind.TASK_OUTPUT and not self.path:
            raise ValueError("path is required for TASK_OUTPUT evidence refs")


class RoutingContext(BaseModel):
    """Routing fields for session/project/agent context.

    These fields help later phases route events to the correct
    session, project, or agent context without overfitting.
    """

    session_id: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
    parent_task_id: str | None = None
    team_id: str | None = None


class MemoryEvent(BaseModel):
    """Unified memory event covering all capture sources."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: MemoryEventKind
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    routing: RoutingContext = Field(default_factory=RoutingContext)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def stable_id(self) -> str:
        """Stable identifier for external reference."""
        return self.id

    @property
    def event_kind(self) -> MemoryEventKind:
        """Event kind accessor for consistency."""
        return self.kind

    @property
    def is_question(self) -> bool:
        """Whether this event represents a question (ask_parent)."""
        return self.kind == MemoryEventKind.ASK_PARENT

    @property
    def is_response(self) -> bool:
        """Whether this event represents a response (resume)."""
        return self.kind == MemoryEventKind.RESUME


class SignalConfidence(BaseModel):
    """Confidence scoring for signal candidates."""

    score: float = Field(ge=0.0, le=1.0, default=1.0)
    reasoning: str | None = None


class SignalCandidate(BaseModel):
    """A candidate signal prepared for capture to daily note.

    Produced by the capture pipeline from a MemoryEvent,
    this model holds everything needed to write a promotion
    candidate entry into the daily note.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    source_event_id: str
    kind: MemoryEventKind
    summary: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    routing: RoutingContext = Field(default_factory=RoutingContext)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: SignalConfidence = Field(default_factory=SignalConfidence)
    captured: bool = False
    capture_date: str | None = None

    @classmethod
    def from_event(cls, event: MemoryEvent, confidence: SignalConfidence | None = None) -> SignalCandidate:
        """Construct a SignalCandidate from a MemoryEvent."""
        return cls(
            source_event_id=event.id,
            kind=event.kind,
            summary=event.summary,
            content=event.content,
            tags=list(event.tags),
            routing=RoutingContext(
                session_id=event.routing.session_id,
                project_id=event.routing.project_id,
                agent_id=event.routing.agent_id,
                parent_task_id=event.routing.parent_task_id,
                team_id=event.routing.team_id,
            ),
            evidence=list(event.evidence),
            confidence=confidence or SignalConfidence(),
        )


class AskParentEvent(MemoryEvent):
    """Specialized MemoryEvent for ask_parent interactions."""

    question: str
    context_snippet: str | None = None

    def model_post_init(self, _execution_context: Any | None = None) -> None:
        if self.kind != MemoryEventKind.ASK_PARENT:
            raise ValueError("AskParentEvent must have kind ASK_PARENT")
        if not self.question:
            raise ValueError("question is required for AskParentEvent")


class ResumeEvent(MemoryEvent):
    """Specialized MemoryEvent for resume interactions."""

    response: str
    parent_question: str | None = None

    def model_post_init(self, _execution_context: Any | None = None) -> None:
        if self.kind != MemoryEventKind.RESUME:
            raise ValueError("ResumeEvent must have kind RESUME")
        if not self.response:
            raise ValueError("response is required for ResumeEvent")
