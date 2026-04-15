"""Append-only JSONL transcript storage for frontstage-visible history."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from controlmesh.history.models import TranscriptTurn
from controlmesh.session.key import SessionKey
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


class TranscriptStore:
    """Persist and read visible transcript turns per frontstage session."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths

    def path_for(self, key: SessionKey) -> Path:
        """Return the per-session JSONL transcript path."""
        topic = str(key.topic_id) if key.topic_id is not None else "root"
        return self._paths.transcripts_dir / key.transport / str(key.chat_id) / f"{topic}.jsonl"

    def append_turn(self, turn: TranscriptTurn) -> TranscriptTurn:
        """Append one transcript turn to the per-session JSONL file."""
        path = self.path_for(SessionKey.parse(turn.session_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(turn.model_dump_json())
            fh.write("\n")
        return turn

    def read_recent(self, key: SessionKey, *, limit: int = 20) -> list[TranscriptTurn]:
        """Read the last *limit* transcript turns for a session."""
        path = self.path_for(key)
        if not path.exists():
            return []
        turns: list[TranscriptTurn] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                turns.append(TranscriptTurn.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("TranscriptStore: skipping unreadable line in %s", path)
        if limit <= 0:
            return turns
        return turns[-limit:]
