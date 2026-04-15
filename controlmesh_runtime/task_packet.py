"""Typed task packets for the ControlMesh harness runtime."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.contracts import utc_now_iso
from controlmesh_runtime.runtime import RuntimeStage


class TaskPacketMode(StrEnum):
    """Bounded task packet modes for the runtime control plane."""

    IMPLEMENTATION = auto()
    VERIFICATION = auto()
    INVESTIGATION = auto()
    DESIGN = auto()


class TaskPacket(BaseModel):
    """One typed task request inside the harness runtime."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    packet_id: str = Field(default_factory=lambda: uuid4().hex)
    objective: str
    scope: str
    mode: TaskPacketMode = TaskPacketMode.IMPLEMENTATION
    runtime_stage: RuntimeStage | None = None
    assigned_worker: str | None = None
    acceptance_criteria: tuple[str, ...]
    constraints: tuple[str, ...] = Field(default_factory=tuple)
    reporting_contract: tuple[str, ...] = Field(default_factory=tuple)
    escalation_policy: tuple[str, ...] = Field(default_factory=tuple)
    created_at: str = Field(default_factory=utc_now_iso)

    @model_validator(mode="after")
    def validate_packet(self) -> TaskPacket:
        """Keep task packets small, explicit, and non-empty."""
        if not self.objective.strip():
            msg = "task packet objective must not be empty"
            raise ValueError(msg)
        if not self.scope.strip():
            msg = "task packet scope must not be empty"
            raise ValueError(msg)
        if not self.acceptance_criteria:
            msg = "task packet acceptance_criteria must not be empty"
            raise ValueError(msg)
        if any(not item.strip() for item in self.acceptance_criteria):
            msg = "task packet acceptance_criteria must not contain blank items"
            raise ValueError(msg)
        if self.reporting_contract and any(not item.strip() for item in self.reporting_contract):
            msg = "task packet reporting_contract must not contain blank items"
            raise ValueError(msg)
        if self.escalation_policy and any(not item.strip() for item in self.escalation_policy):
            msg = "task packet escalation_policy must not contain blank items"
            raise ValueError(msg)
        return self
