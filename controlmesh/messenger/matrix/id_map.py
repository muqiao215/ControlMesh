"""Bidirectional mapping between Matrix room_id strings and integer chat_ids.

The ControlMesh core (sessions, envelopes, bus) uses ``int`` chat IDs internally.
Matrix rooms are identified by opaque strings like ``!abc123:server``.
This module provides a persistent, collision-safe mapping between the two.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save

logger = logging.getLogger(__name__)


class MatrixIdMap:
    """Bidirectional room_id ↔ int mapping with collision detection."""

    def __init__(self, store_path: Path) -> None:
        self._room_to_int: dict[str, int] = {}
        self._int_to_room: dict[int, str] = {}
        self._path = store_path / "room_id_map.json"
        self._load()

    def room_to_int(self, room_id: str) -> int:
        """Get or create a deterministic int for a Matrix room_id."""
        if room_id in self._room_to_int:
            return self._room_to_int[room_id]

        h = int.from_bytes(hashlib.sha256(room_id.encode()).digest()[:8], "big")
        # Collision guard: rehash with salt until unique.
        # The final (possibly rehashed) value is persisted,
        # so _load() restores it without recomputing.
        while h in self._int_to_room and self._int_to_room[h] != room_id:
            h = int.from_bytes(
                hashlib.sha256(f"{room_id}:{h}".encode()).digest()[:8],
                "big",
            )

        self._room_to_int[room_id] = h
        self._int_to_room[h] = room_id
        self._save()
        return h

    def int_to_room(self, chat_id: int) -> str | None:
        """Resolve an int chat_id back to a Matrix room_id."""
        return self._int_to_room.get(chat_id)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for room_id, int_id in data.items():
                self._room_to_int[room_id] = int_id
                self._int_to_room[int_id] = room_id
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load room_id_map.json, starting fresh")

    def _save(self) -> None:
        """Persist mappings to disk atomically."""
        atomic_text_save(
            self._path,
            json.dumps(self._room_to_int, indent=2),
        )
