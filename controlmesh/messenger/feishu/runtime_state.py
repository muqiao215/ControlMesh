"""Persistence for restart-safe Feishu replay and self-echo continuity."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json

logger = logging.getLogger(__name__)

_DEFAULT_INBOUND_TTL_SECONDS = 86400.0
_DEFAULT_CONTENT_TTL_SECONDS = 300.0
_DEFAULT_OUTBOUND_TTL_SECONDS = 600.0
_INBOUND_MAX_ENTRIES = 10000
_CONTENT_MAX_ENTRIES = 4000
_OUTBOUND_MAX_ENTRIES = 512


@dataclass(frozen=True, slots=True)
class FeishuRuntimeState:
    """Persisted Feishu replay continuity scoped to one bot identity."""

    recent_inbound: tuple[tuple[str, float], ...] = ()
    recent_content: tuple[tuple[str, float], ...] = ()
    recent_outbound: tuple[tuple[str, float], ...] = ()


def feishu_runtime_identity_fingerprint(
    *,
    app_id: str | None,
    brand: str | None,
    domain: str | None,
) -> str:
    """Return a stable fingerprint for one persisted Feishu bot identity."""
    payload = "\n".join(
        (
            (app_id or "").strip(),
            (brand or "").strip().lower(),
            (domain or "").rstrip("/").lower(),
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


class FeishuReplayStore:
    """Small TTL-bounded store for replay-sensitive Feishu identifiers."""

    def __init__(
        self,
        entries: tuple[tuple[str, float], ...] = (),
        *,
        ttl_seconds: float,
        max_entries: int,
    ) -> None:
        self._ttl_seconds = max(0.0, ttl_seconds)
        self._max_entries = max(1, max_entries)
        self._entries: dict[str, float] = {}
        for key, seen_at in entries:
            self._entries[key] = float(seen_at)

    def remember(self, key: str, *, now: float | None = None) -> None:
        if not key:
            return
        current = time.time() if now is None else now
        self._entries.pop(key, None)
        self._entries[key] = current
        self._prune(now=current)

    def contains(self, key: str, *, now: float | None = None, refresh: bool = False) -> bool:
        if not key:
            return False
        current = time.time() if now is None else now
        seen_at = self._entries.get(key)
        if seen_at is None:
            return False
        if self._ttl_seconds > 0 and current - seen_at > self._ttl_seconds:
            self._entries.pop(key, None)
            return False
        if refresh:
            self._entries.pop(key, None)
            self._entries[key] = current
            self._prune(now=current)
        return True

    def consume(self, key: str, *, now: float | None = None) -> bool:
        if not key:
            return False
        current = time.time() if now is None else now
        seen_at = self._entries.get(key)
        if seen_at is None:
            return False
        if self._ttl_seconds > 0 and current - seen_at > self._ttl_seconds:
            self._entries.pop(key, None)
            return False
        self._entries.pop(key, None)
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


class FeishuRuntimeStateStore:
    """JSON-backed Feishu replay continuity state."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "feishu_store/runtime_state.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_state(
        self,
        *,
        app_id: str | None,
        brand: str | None,
        domain: str | None,
    ) -> FeishuRuntimeState:
        raw = load_json(self.path)
        if raw is None:
            return FeishuRuntimeState()
        try:
            state = _coerce_state(raw)
        except (TypeError, ValueError):
            logger.warning("Invalid Feishu runtime state format in %s", self.path)
            return FeishuRuntimeState()

        fingerprint = feishu_runtime_identity_fingerprint(
            app_id=app_id,
            brand=brand,
            domain=domain,
        )
        if raw.get("identity_fingerprint") != fingerprint:
            logger.info("Discarding Feishu runtime state with stale identity fingerprint at %s", self.path)
            self.clear()
            return FeishuRuntimeState()
        return state

    def save_state(
        self,
        *,
        app_id: str | None,
        brand: str | None,
        domain: str | None,
        state: FeishuRuntimeState,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(
            self.path,
            {
                "identity_fingerprint": feishu_runtime_identity_fingerprint(
                    app_id=app_id,
                    brand=brand,
                    domain=domain,
                ),
                "recent_inbound": [
                    {"key": key, "seen_at": seen_at}
                    for key, seen_at in state.recent_inbound
                ],
                "recent_content": [
                    {"key": key, "seen_at": seen_at}
                    for key, seen_at in state.recent_content
                ],
                "recent_outbound": [
                    {"key": key, "seen_at": seen_at}
                    for key, seen_at in state.recent_outbound
                ],
            },
        )
        self._protect_file()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)


def default_feishu_inbound_store(entries: tuple[tuple[str, float], ...] = ()) -> FeishuReplayStore:
    return FeishuReplayStore(
        entries,
        ttl_seconds=_DEFAULT_INBOUND_TTL_SECONDS,
        max_entries=_INBOUND_MAX_ENTRIES,
    )


def default_feishu_content_store(entries: tuple[tuple[str, float], ...] = ()) -> FeishuReplayStore:
    return FeishuReplayStore(
        entries,
        ttl_seconds=_DEFAULT_CONTENT_TTL_SECONDS,
        max_entries=_CONTENT_MAX_ENTRIES,
    )


def default_feishu_outbound_store(entries: tuple[tuple[str, float], ...] = ()) -> FeishuReplayStore:
    return FeishuReplayStore(
        entries,
        ttl_seconds=_DEFAULT_OUTBOUND_TTL_SECONDS,
        max_entries=_OUTBOUND_MAX_ENTRIES,
    )


def _coerce_state(value: dict[str, object]) -> FeishuRuntimeState:
    return FeishuRuntimeState(
        recent_inbound=_coerce_entries(value.get("recent_inbound", []), field_name="recent_inbound"),
        recent_content=_coerce_entries(value.get("recent_content", []), field_name="recent_content"),
        recent_outbound=_coerce_entries(value.get("recent_outbound", []), field_name="recent_outbound"),
    )


def _coerce_entries(value: object, *, field_name: str) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    entries: list[tuple[str, float]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{field_name} entries must be objects")
        key = item.get("key")
        seen_at = item.get("seen_at")
        if not isinstance(key, str) or not isinstance(seen_at, (int, float)):
            raise TypeError(f"{field_name} entries must contain key and numeric seen_at")
        entries.append((key, float(seen_at)))
    return tuple(entries)
