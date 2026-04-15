"""Typed promotion receipts for canonical write-back audit."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import utc_now_iso
from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity


class PromotionReceipt(BaseModel):
    """Audit receipt for one canonical promotion write."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    receipt_id: str = Field(default_factory=lambda: uuid4().hex)
    line: str
    evidence_identity: RuntimeEvidenceIdentity
    review_id: str
    task_summary_id: str
    line_summary_id: str
    checkpoint_token: str
    written_sections: tuple[str, ...]
    updated_files: tuple[str, ...]
    submitted_by: str
    write_result: Literal["written"] = "written"
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    span_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_span_id: str | None = None
    recorded_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def validate_receipt(self) -> PromotionReceipt:
        for field_name in (
            "line",
            "review_id",
            "task_summary_id",
            "line_summary_id",
            "checkpoint_token",
            "submitted_by",
            "trace_id",
            "span_id",
        ):
            if not getattr(self, field_name).strip():
                msg = f"promotion receipt {field_name} must not be empty"
                raise ValueError(msg)
        if not self.written_sections:
            msg = "promotion receipt written_sections must not be empty"
            raise ValueError(msg)
        if not self.updated_files:
            msg = "promotion receipt updated_files must not be empty"
            raise ValueError(msg)
        return self


__all__ = ["PromotionReceipt"]
