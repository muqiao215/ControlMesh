"""JSONL score events for future route calibration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RouteScoreEvent:
    """One completed WorkUnit outcome used for future scoring."""

    agent_slot: str
    workunit_kind: str
    success: bool
    elapsed_seconds: float = 0.0
    evidence_quality: float = 0.0
    needed_human_fix: bool = False
    scope_drift: bool = False
    cost_level: str = "unknown"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def append_score_event(path: str | Path, event: RouteScoreEvent) -> None:
    """Append one route score event as JSONL."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
