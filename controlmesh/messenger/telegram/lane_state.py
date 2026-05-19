"""Durable latest-intent lane state for Telegram."""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.messenger.telegram.runtime_state import (
    TelegramLaneState,
    telegram_runtime_identity_fingerprint,
)


class TelegramLaneStateStore:
    """JSON-backed latest-intent state for one Telegram bot identity."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        token: str,
        bot_id: int | None,
        bot_username: str | None,
        relative_root: str = "telegram_store/inbound_spool",
    ) -> None:
        fingerprint = telegram_runtime_identity_fingerprint(
            token=token,
            bot_id=bot_id,
            bot_username=bot_username,
        )
        self.root = Path(controlmesh_home).expanduser() / relative_root / fingerprint / "lane_state"

    def snapshot(self, lane_key: str) -> TelegramLaneState:
        raw = load_json(self._path(lane_key))
        if raw is None:
            return TelegramLaneState(lane_key=lane_key, latest_message_id=0, latest_spool_id=None, generation=0, updated_at=0.0)
        try:
            return _coerce_state(raw, lane_key=lane_key)
        except (TypeError, ValueError):
            return TelegramLaneState(lane_key=lane_key, latest_message_id=0, latest_spool_id=None, generation=0, updated_at=0.0)

    def update_latest(self, lane_key: str, message_id: int, spool_id: str | None) -> TelegramLaneState:
        state = self.snapshot(lane_key)
        updated = TelegramLaneState(
            lane_key=lane_key,
            latest_message_id=max(state.latest_message_id, message_id),
            latest_spool_id=spool_id,
            generation=state.generation + 1,
            updated_at=time.time(),
        )
        self._save(updated)
        return updated

    def bump_generation(self, lane_key: str, reason: str | None = None) -> TelegramLaneState:
        state = self.snapshot(lane_key)
        updated = TelegramLaneState(
            lane_key=lane_key,
            latest_message_id=state.latest_message_id,
            latest_spool_id=state.latest_spool_id,
            generation=state.generation + 1,
            updated_at=time.time(),
        )
        self._save(updated)
        return updated

    def is_current(self, lane_key: str, message_id: int, generation: int) -> bool:
        state = self.snapshot(lane_key)
        return state.generation == generation and state.latest_message_id == message_id

    def _save(self, state: TelegramLaneState) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(
            self._path(state.lane_key),
            {
                "schema_version": 1,
                "lane_key": state.lane_key,
                "latest_message_id": state.latest_message_id,
                "latest_spool_id": state.latest_spool_id,
                "generation": state.generation,
                "updated_at": state.updated_at,
            },
        )
        self._protect_file(self._path(state.lane_key))

    def _path(self, lane_key: str) -> Path:
        return self.root / f"{_lane_hash(lane_key)}.json"

    @staticmethod
    def _protect_file(path: Path) -> None:
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def _coerce_state(value: dict[str, object], *, lane_key: str) -> TelegramLaneState:
    latest_message_id = value.get("latest_message_id")
    latest_spool_id = value.get("latest_spool_id")
    generation = value.get("generation")
    updated_at = value.get("updated_at")
    if not isinstance(latest_message_id, int):
        raise TypeError("latest_message_id must be int")
    if latest_spool_id is not None and not isinstance(latest_spool_id, str):
        raise TypeError("latest_spool_id must be str or null")
    if not isinstance(generation, int):
        raise TypeError("generation must be int")
    if not isinstance(updated_at, (int, float)):
        raise TypeError("updated_at must be numeric")
    return TelegramLaneState(
        lane_key=lane_key,
        latest_message_id=latest_message_id,
        latest_spool_id=latest_spool_id,
        generation=generation,
        updated_at=float(updated_at),
    )


def _lane_hash(lane_key: str) -> str:
    import hashlib

    return hashlib.sha256(lane_key.encode("utf-8")).hexdigest()[:24]
