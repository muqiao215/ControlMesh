"""Append-only JSONL storage for dedicated runtime events."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from controlmesh.runtime.models import RuntimeEvent
from controlmesh.session.key import SessionKey
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


class RuntimeEventStore:
    """Persist and read backstage runtime events per session."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths

    def path_for(self, key: SessionKey) -> Path:
        """Return the runtime event path for one session."""
        topic = str(key.topic_id) if key.topic_id is not None else "root"
        return self._paths.runtime_events_dir / key.transport / str(key.chat_id) / f"{topic}.jsonl"

    def append_event(self, event: RuntimeEvent) -> RuntimeEvent:
        """Append one runtime event."""
        path = self.path_for(SessionKey.parse(event.session_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json())
            fh.write("\n")
        return event

    def read_recent(self, key: SessionKey, *, limit: int = 20) -> list[RuntimeEvent]:
        """Read recent runtime events for one session."""
        path = self.path_for(key)
        if not path.exists():
            return []
        events: list[RuntimeEvent] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                events.append(RuntimeEvent.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("RuntimeEventStore: skipping unreadable line in %s", path)
        if limit <= 0:
            return events
        return events[-limit:]
