"""Typed runtime evidence identity shared across review/result/summary promotion."""

from __future__ import annotations

from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict, model_validator


class EvidenceSubject(StrEnum):
    """Bounded summary subjects allowed in the first identity-hardening cut."""

    TASK = auto()
    LINE = auto()


class RuntimeEvidenceIdentity(BaseModel):
    """Canonical bounded identity tuple for one reviewed execution episode."""

    model_config = ConfigDict(frozen=True)

    packet_id: str
    task_id: str
    line: str
    plan_id: str

    @model_validator(mode="after")
    def validate_identity(self) -> RuntimeEvidenceIdentity:
        if not self.packet_id.strip():
            msg = "runtime evidence identity packet_id must not be empty"
            raise ValueError(msg)
        if not self.task_id.strip():
            msg = "runtime evidence identity task_id must not be empty"
            raise ValueError(msg)
        if not self.line.strip():
            msg = "runtime evidence identity line must not be empty"
            raise ValueError(msg)
        if not self.plan_id.strip():
            msg = "runtime evidence identity plan_id must not be empty"
            raise ValueError(msg)
        return self

    def entity_id_for(self, subject: EvidenceSubject) -> str:
        if subject is EvidenceSubject.TASK:
            return f"{subject.value}:{self.task_id}"
        return f"{subject.value}:{self.line}"


# Compatibility aliases for partially landed local changes during the hardening cut.
CrossEvidenceIdentity = RuntimeEvidenceIdentity
SummarySubject = EvidenceSubject


__all__ = [
    "CrossEvidenceIdentity",
    "EvidenceSubject",
    "RuntimeEvidenceIdentity",
    "SummarySubject",
]
