"""Minimal runtime-stage placeholders for future ControlMesh runtime cuts."""

from __future__ import annotations

from enum import StrEnum, auto


class RuntimeStage(StrEnum):
    """Bounded lifecycle stages used by the harness progression model."""

    DESIGN = auto()
    RED = auto()
    GREEN = auto()
    LIVE = auto()
    CHECKPOINT = auto()
