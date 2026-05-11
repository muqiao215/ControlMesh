"""Runtime-event models for the dedicated backstage event substrate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from controlmesh.messenger.address import ChatRef, TopicRef


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
    chat_id: ChatRef
    topic_id: TopicRef = None


class AgentInboxItem(BaseModel):
    """One runtime-owned backstage item addressed to an agent inbox."""

    schema_version: str = "controlmesh.agent_inbox.v1"
    inbox_id: str = Field(default_factory=lambda: uuid4().hex)
    to_agent: str
    kind: str
    summary: str
    created_at: str = Field(default_factory=utc_now_iso)
    session_id: str = ""
    task_id: str = ""
    tool_use_id: str = ""
    tool_result_ref: str = ""
    projection: str = ""
    status: str = "pending"
    delivered_at: str | None = None
    consumed_at: str | None = None
    consumed_by: str = ""
    next_action: str = ""
    from_task: str = ""
    source_agent: str = ""
    result_ref: str = ""
    requires_attention: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
