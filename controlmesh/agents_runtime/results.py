"""Typed result envelopes returned by runtime tool adapters."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolErrorDetail(BaseModel):
    """Structured error payload for recoverable runtime tool failures."""

    code: str
    message: str
    recoverable: bool = True


class ToolResultEnvelope(BaseModel):
    """Normalized runtime tool response for the optional agents backend."""

    ok: bool
    operation: str
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolErrorDetail | None = None

    @classmethod
    def success(
        cls,
        operation: str,
        *,
        summary: str = "",
        data: dict[str, Any] | None = None,
    ) -> ToolResultEnvelope:
        return cls(
            ok=True,
            operation=operation,
            summary=summary,
            data=data or {},
        )

    @classmethod
    def failure(  # noqa: PLR0913
        cls,
        operation: str,
        *,
        code: str,
        message: str,
        summary: str = "",
        recoverable: bool = True,
        data: dict[str, Any] | None = None,
    ) -> ToolResultEnvelope:
        return cls(
            ok=False,
            operation=operation,
            summary=summary or message,
            data=data or {},
            error=ToolErrorDetail(code=code, message=message, recoverable=recoverable),
        )
