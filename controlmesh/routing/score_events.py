"""JSONL score events for future route calibration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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


def read_score_events(path: str | Path, *, limit: int = 500) -> tuple[RouteScoreEvent, ...]:
    """Read recent route score events from JSONL."""
    target = Path(path).expanduser()
    if not target.is_file():
        return ()

    events: list[RouteScoreEvent] = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()

    for raw in lines[-limit:]:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event = _event_from_mapping(payload)
        if event is not None:
            events.append(event)
    return tuple(events)


@dataclass(frozen=True, slots=True)
class RouteScoreStats:
    """Recent historical score summary for one routable slot."""

    count: int = 0
    success_rate: float = 0.5
    evidence_quality: float = 0.5
    needed_human_fix_rate: float = 0.0


def summarize_score_events(
    events: tuple[RouteScoreEvent, ...],
) -> dict[str, RouteScoreStats]:
    """Aggregate score events by agent slot for routing."""
    grouped: dict[str, list[RouteScoreEvent]] = {}
    for event in events:
        grouped.setdefault(event.agent_slot, []).append(event)

    stats: dict[str, RouteScoreStats] = {}
    for slot_name, slot_events in grouped.items():
        count = len(slot_events)
        successes = sum(1 for event in slot_events if event.success)
        human_fix = sum(1 for event in slot_events if event.needed_human_fix)
        evidence = sum(event.evidence_quality for event in slot_events) / count
        stats[slot_name] = RouteScoreStats(
            count=count,
            success_rate=successes / count,
            evidence_quality=evidence,
            needed_human_fix_rate=human_fix / count,
        )
    return stats


def _event_from_mapping(payload: dict[str, Any]) -> RouteScoreEvent | None:
    try:
        return RouteScoreEvent(
            agent_slot=str(payload.get("agent_slot", "")),
            workunit_kind=str(payload.get("workunit_kind", "")),
            success=bool(payload.get("success", False)),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0) or 0.0),
            evidence_quality=float(payload.get("evidence_quality", 0.0) or 0.0),
            needed_human_fix=bool(payload.get("needed_human_fix", False)),
            scope_drift=bool(payload.get("scope_drift", False)),
            cost_level=str(payload.get("cost_level", "unknown")),
            created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat()),
        )
    except (TypeError, ValueError):
        return None
