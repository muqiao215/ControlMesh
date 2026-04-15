"""Runtime-event models for the dedicated backstage event substrate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


class RuntimeEvent(BaseModel):
    """One backstage runtime event for a single session timeline."""

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    session_key: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)
    transport: str
    chat_id: int
    topic_id: int | None = None
