"""Persistence for restart-safe Telegram polling and outbound echo continuity."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json

logger = logging.getLogger(__name__)

_DEFAULT_OUTBOUND_TTL_SECONDS = 600.0
_OUTBOUND_MAX_ENTRIES = 256


@dataclass(frozen=True, slots=True)
class TelegramRuntimeState:
    """Persisted Telegram runtime continuity state scoped to one bot identity."""

    cursor: int | None = None
    recent_outbound: tuple[tuple[str, float], ...] = ()


def telegram_runtime_identity_fingerprint(
    *,
    token: str,
    bot_id: int | None,
    bot_username: str | None,
) -> str:
    """Return a stable fingerprint for one persisted Telegram bot identity."""
    payload = "\n".join(
        (
            token,
            str(bot_id or ""),
            (bot_username or "").strip().lower(),
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


class TelegramOutboundEchoStore:
    """Small TTL-bounded store for outbound Telegram message identifiers."""

    def __init__(
        self,
        entries: tuple[tuple[str, float], ...] = (),
        *,
        ttl_seconds: float = _DEFAULT_OUTBOUND_TTL_SECONDS,
        max_entries: int = _OUTBOUND_MAX_ENTRIES,
    ) -> None:
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._max_entries = max(1, max_entries)
        self._entries: dict[str, float] = {}
        for message_key, seen_at in entries:
            self._entries[message_key] = float(seen_at)

    def remember(self, message_key: str, *, now: float | None = None) -> None:
        if not message_key:
            return
        current = time.time() if now is None else now
        self._entries.pop(message_key, None)
        self._entries[message_key] = current
        self._prune(now=current)

    def consume(self, message_key: str, *, now: float | None = None) -> bool:
        if not message_key:
            return False
        current = time.time() if now is None else now
        seen_at = self._entries.get(message_key)
        if seen_at is None:
            return False
        if self._ttl_seconds > 0 and current - seen_at > self._ttl_seconds:
            self._entries.pop(message_key, None)
            return False
        self._entries.pop(message_key, None)
        self._prune(now=current)
        return True

    def snapshot(self, *, now: float | None = None) -> tuple[tuple[str, float], ...]:
        current = time.time() if now is None else now
        self._prune(now=current)
        return tuple(self._entries.items())

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self, *, now: float) -> None:
        if self._ttl_seconds > 0:
            cutoff = now - self._ttl_seconds
            expired = [key for key, seen_at in self._entries.items() if seen_at < cutoff]
            for key in expired:
                self._entries.pop(key, None)
        while len(self._entries) > self._max_entries:
            oldest = next(iter(self._entries))
            self._entries.pop(oldest, None)


class TelegramRuntimeStateStore:
    """JSON-backed Telegram continuity state."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "telegram_store/runtime_state.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_state(
        self,
        *,
        token: str,
        bot_id: int | None,
        bot_username: str | None,
    ) -> TelegramRuntimeState:
        raw = load_json(self.path)
        if raw is None:
            return TelegramRuntimeState()
        try:
            state = _coerce_state(raw)
        except (TypeError, ValueError):
            logger.warning("Invalid Telegram runtime state format in %s", self.path)
            return TelegramRuntimeState()

        fingerprint = telegram_runtime_identity_fingerprint(
            token=token,
            bot_id=bot_id,
            bot_username=bot_username,
        )
        if raw.get("identity_fingerprint") != fingerprint:
            logger.info("Discarding Telegram runtime state with stale identity fingerprint at %s", self.path)
            self.clear()
            return TelegramRuntimeState()
        return state

    def save_state(
        self,
        *,
        token: str,
        bot_id: int | None,
        bot_username: str | None,
        state: TelegramRuntimeState,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(
            self.path,
            {
                "identity_fingerprint": telegram_runtime_identity_fingerprint(
                    token=token,
                    bot_id=bot_id,
                    bot_username=bot_username,
                ),
                "cursor": state.cursor,
                "recent_outbound": [
                    {"message_key": message_key, "seen_at": seen_at}
                    for message_key, seen_at in state.recent_outbound
                ],
            },
        )
        self._protect_file()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)


def _coerce_state(value: dict[str, object]) -> TelegramRuntimeState:
    cursor = value.get("cursor")
    if cursor is not None and not isinstance(cursor, int):
        raise TypeError("cursor must be an int when present")

    recent_outbound_raw = value.get("recent_outbound", [])
    if not isinstance(recent_outbound_raw, list):
        raise TypeError("recent_outbound must be a list")
    recent_outbound: list[tuple[str, float]] = []
    for item in recent_outbound_raw:
        if not isinstance(item, dict):
            raise TypeError("recent_outbound entries must be objects")
        message_key = item.get("message_key")
        seen_at = item.get("seen_at")
        if not isinstance(message_key, str) or not isinstance(seen_at, (int, float)):
            raise TypeError("recent_outbound entries must contain message_key and numeric seen_at")
        recent_outbound.append((message_key, float(seen_at)))

    return TelegramRuntimeState(
        cursor=cursor,
        recent_outbound=tuple(recent_outbound),
    )
