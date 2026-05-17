"""Persistence for restart-safe Weixin runtime continuity state."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WeixinRuntimeState:
    """Persisted runtime continuity state scoped to one Weixin account identity."""

    cursor: str = ""
    context_tokens: tuple[tuple[str, str], ...] = ()
    recent_outbound: tuple[tuple[str, float], ...] = ()
    last_inbound_drain_at: float | None = None


_DEFAULT_OUTBOUND_TTL_SECONDS = 600.0
_OUTBOUND_MAX_ENTRIES = 256


def weixin_runtime_identity_fingerprint(credentials: StoredWeixinCredentials) -> str:
    """Return a stable fingerprint for one persisted Weixin runtime identity."""
    payload = "\n".join(
        (
            credentials.account_id,
            credentials.user_id,
            credentials.base_url.rstrip("/"),
            credentials.token,
        )
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


class WeixinOutboundEchoStore:
    """Small TTL-bounded store for outbound client ids that may echo back."""

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
        for client_id, seen_at in entries:
            self._entries[client_id] = float(seen_at)

    def remember(self, client_id: str, *, now: float | None = None) -> None:
        if not client_id:
            return
        current = time.time() if now is None else now
        self._entries.pop(client_id, None)
        self._entries[client_id] = current
        self._prune(now=current)

    def consume(self, client_id: str, *, now: float | None = None) -> bool:
        if not client_id:
            return False
        current = time.time() if now is None else now
        seen_at = self._entries.get(client_id)
        if seen_at is None:
            return False
        if self._ttl_seconds > 0 and current - seen_at > self._ttl_seconds:
            self._entries.pop(client_id, None)
            return False
        self._entries.pop(client_id, None)
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
            expired = [client_id for client_id, seen_at in self._entries.items() if seen_at < cutoff]
            for client_id in expired:
                self._entries.pop(client_id, None)
        while len(self._entries) > self._max_entries:
            oldest = next(iter(self._entries))
            self._entries.pop(oldest, None)


class WeixinRuntimeStateStore:
    """JSON-backed continuity state separate from QR credentials."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "weixin_store/runtime_state.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_state(self, credentials: StoredWeixinCredentials) -> WeixinRuntimeState:
        raw = load_json(self.path)
        if raw is None:
            return WeixinRuntimeState()
        try:
            state = _coerce_state(raw)
        except (TypeError, ValueError):
            logger.warning("Invalid Weixin runtime state format in %s", self.path)
            return WeixinRuntimeState()

        fingerprint = weixin_runtime_identity_fingerprint(credentials)
        if raw.get("identity_fingerprint") != fingerprint:
            logger.info("Discarding Weixin runtime state with stale identity fingerprint at %s", self.path)
            self.clear()
            return WeixinRuntimeState()
        return state

    def save_state(
        self,
        credentials: StoredWeixinCredentials,
        state: WeixinRuntimeState,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(
            self.path,
            {
                "identity_fingerprint": weixin_runtime_identity_fingerprint(credentials),
                "cursor": state.cursor,
                "context_tokens": [
                    {"user_id": user_id, "context_token": context_token}
                    for user_id, context_token in state.context_tokens
                ],
                "recent_outbound": [
                    {"client_id": client_id, "seen_at": seen_at}
                    for client_id, seen_at in state.recent_outbound
                ],
                "last_inbound_drain_at": state.last_inbound_drain_at,
            },
        )
        self._protect_file()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)


def _coerce_state(value: dict[str, object]) -> WeixinRuntimeState:
    cursor = value.get("cursor", "")
    if not isinstance(cursor, str):
        raise TypeError("cursor must be a string")

    context_tokens_raw = value.get("context_tokens", [])
    if not isinstance(context_tokens_raw, list):
        raise TypeError("context_tokens must be a list")

    context_tokens: list[tuple[str, str]] = []
    for item in context_tokens_raw:
        if not isinstance(item, dict):
            raise TypeError("context_tokens entries must be objects")
        user_id = item.get("user_id")
        context_token = item.get("context_token")
        if not isinstance(user_id, str) or not isinstance(context_token, str):
            raise TypeError("context_tokens entries must contain user_id/context_token strings")
        context_tokens.append((user_id, context_token))

    recent_outbound_raw = value.get("recent_outbound", [])
    if not isinstance(recent_outbound_raw, list):
        raise TypeError("recent_outbound must be a list")
    recent_outbound: list[tuple[str, float]] = []
    for item in recent_outbound_raw:
        if not isinstance(item, dict):
            raise TypeError("recent_outbound entries must be objects")
        client_id = item.get("client_id")
        seen_at = item.get("seen_at")
        if not isinstance(client_id, str) or not isinstance(seen_at, (int, float)):
            raise TypeError("recent_outbound entries must contain client_id and numeric seen_at")
        recent_outbound.append((client_id, float(seen_at)))
    last_inbound_drain_at = value.get("last_inbound_drain_at")
    if last_inbound_drain_at is not None and not isinstance(last_inbound_drain_at, (int, float)):
        raise TypeError("last_inbound_drain_at must be numeric when present")
    return WeixinRuntimeState(
        cursor=cursor,
        context_tokens=tuple(context_tokens),
        recent_outbound=tuple(recent_outbound),
        last_inbound_drain_at=float(last_inbound_drain_at) if last_inbound_drain_at is not None else None,
    )
