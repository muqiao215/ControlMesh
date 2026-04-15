"""Lightweight trace helpers for runtime control events."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TraceContext(BaseModel):
    """Minimal trace/span identity carried across one runtime episode."""

    model_config = ConfigDict(frozen=True)

    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_span_id: str | None = None

    @model_validator(mode="after")
    def validate_trace(self) -> TraceContext:
        if not self.trace_id.strip():
            msg = "trace_id must not be empty"
            raise ValueError(msg)
        if not self.span_id.strip():
            msg = "span_id must not be empty"
            raise ValueError(msg)
        return self


def root_trace(trace_id: str | None = None, parent_span_id: str | None = None) -> TraceContext:
    """Create a root trace context, optionally reusing an external trace id."""
    return TraceContext(trace_id=trace_id or uuid4().hex, parent_span_id=parent_span_id)


def child_trace(parent: TraceContext) -> TraceContext:
    """Create a child span under an existing trace."""
    return TraceContext(trace_id=parent.trace_id, parent_span_id=parent.span_id)


__all__ = ["TraceContext", "child_trace", "root_trace"]
