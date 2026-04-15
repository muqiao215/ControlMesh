"""Event persistence for additive team coordination."""

from __future__ import annotations

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.models import TeamEvent
from controlmesh.team.state.base import TeamStatePaths, utc_now


def _load(paths: TeamStatePaths) -> list[TeamEvent]:
    raw = load_json(paths.events_path) or {"events": []}
    items = raw.get("events", [])
    if not isinstance(items, list):
        return []
    return [TeamEvent.model_validate(item) for item in items]


def _save(paths: TeamStatePaths, events: list[TeamEvent]) -> None:
    atomic_json_save(
        paths.events_path,
        {"events": [event.model_dump(mode="json") for event in events]},
    )


def append_event(paths: TeamStatePaths, event: TeamEvent) -> TeamEvent:
    """Append an event to the additive team event stream."""
    events = _load(paths)
    if any(existing.event_id == event.event_id for existing in events):
        msg = f"event '{event.event_id}' already exists"
        raise ValueError(msg)
    persisted = event.model_copy(update={"created_at": event.created_at or utc_now()})
    events.append(persisted)
    _save(paths, events)
    return persisted


def read_events(  # noqa: PLR0913
    paths: TeamStatePaths,
    *,
    after_event_id: str | None = None,
    event_type: str | None = None,
    worker: str | None = None,
    task_id: str | None = None,
    limit: int | None = None,
) -> list[TeamEvent]:
    """Read events with optional cursor and filter fields."""
    events = _load(paths)
    if after_event_id is not None:
        seen = False
        filtered: list[TeamEvent] = []
        for event in events:
            if seen:
                filtered.append(event)
            elif event.event_id == after_event_id:
                seen = True
        events = filtered
    if event_type is not None:
        events = [event for event in events if event.event_type == event_type]
    if worker is not None:
        events = [event for event in events if event.worker == worker]
    if task_id is not None:
        events = [event for event in events if event.task_id == task_id]
    if limit is not None:
        events = events[:limit]
    return events
