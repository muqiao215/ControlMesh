"""Transcript models for frontstage-visible interaction history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


class TranscriptAttachment(BaseModel):
    """Minimal visible attachment metadata for transcript turns."""

    kind: str = ""
    label: str = ""
    path: str = ""


class TranscriptTurn(BaseModel):
    """One visible frontstage turn in the transcript timeline."""

    turn_id: str = Field(default_factory=lambda: uuid4().hex)
    session_key: str
    surface_session_id: str
    role: Literal["user", "assistant", "system_visible"]
    visible_content: str
    attachments: list[TranscriptAttachment] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_iso)
    reply_to_turn_id: str | None = None
    source: str = "normal_chat"
    transport: str
    chat_id: int
    topic_id: int | None = None
