"""Typed event schema for the ControlMesh harness runtime."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import ReviewOutcome, utc_now_iso
from controlmesh_runtime.runtime import RuntimeStage


class EventKind(StrEnum):
    """Machine-readable event kinds for task/runtime progression."""

    TASK_PACKET_CREATED = auto()
    TASK_DISPATCHED = auto()
    TASK_PROGRESS = auto()
    TASK_BLOCKED = auto()
    TASK_FAILED = auto()
    TASK_RESULT_REPORTED = auto()
    REVIEW_RECORDED = auto()

    @property
    def event_token(self) -> str:
        """Bridge enum names into a stable dotted event token."""
        return self.name.lower().replace("_", ".")


class FailureClass(StrEnum):
    """Normalized failure classes for runtime routing and escalation."""

    ENVIRONMENT = auto()
    OPERATOR_SAFETY = auto()
    SCHEMA = auto()
    SCOPE = auto()
    CONTRACT = auto()
    LIVE_REGRESSION = auto()
    TOOL_RUNTIME = auto()
    INFRA = auto()
    UNKNOWN = auto()


class RuntimeEvent(BaseModel):
    """One typed event emitted by the harness runtime."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    packet_id: str
    kind: EventKind
    message: str
    created_at: str = Field(default_factory=utc_now_iso)
    worker_id: str | None = None
    stage: RuntimeStage | None = None
    outcome: ReviewOutcome | None = None
    failure_class: FailureClass | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> RuntimeEvent:
        """Require explicit structure for terminal and review events."""
        if not self.packet_id.strip():
            msg = "runtime event packet_id must not be empty"
            raise ValueError(msg)
        if not self.message.strip():
            msg = "runtime event message must not be empty"
            raise ValueError(msg)
        if self.kind in {EventKind.TASK_BLOCKED, EventKind.TASK_FAILED} and self.failure_class is None:
            msg = "blocked and failed events require a failure_class"
            raise ValueError(msg)
        if self.kind == EventKind.REVIEW_RECORDED and self.outcome is None:
            msg = "review events require an outcome"
            raise ValueError(msg)
        return self
