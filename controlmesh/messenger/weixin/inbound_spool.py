"""Durable inbound spool for Weixin long-poll delivery recovery."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials
from controlmesh.messenger.weixin.runtime_state import weixin_runtime_identity_fingerprint

_DEFAULT_CLAIM_TTL_SECONDS = 30.0
_DEFAULT_UNHEALTHY_BACKLOG_AGE_SECONDS = 90.0


@dataclass(frozen=True, slots=True)
class WeixinInboundSpoolEntry:
    """One persisted inbound envelope waiting for delivery."""

    spool_id: str
    lane_key: str
    dedupe_key: str
    message_id: str
    enqueued_at: float
    raw: dict[str, object]
    path: Path


@dataclass(frozen=True, slots=True)
class WeixinInboundClaim:
    """Lease-style claim for one pending spool entry."""

    lane_key: str
    spool_id: str
    owner: str
    claimed_at: float
    lease_expires_at: float
    path: Path
    entry: WeixinInboundSpoolEntry


@dataclass(frozen=True, slots=True)
class WeixinInboundSpoolStats:
    """Observable queue health facts for diagnostics."""

    pending_count: int = 0
    active_claim_count: int = 0
    blocked_lane_count: int = 0
    oldest_pending_age_seconds: float | None = None
    unhealthy_reason: str | None = None


class WeixinInboundSpool:
    """Filesystem-backed inbound queue with per-lane lease claims."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        credentials: StoredWeixinCredentials,
        *,
        relative_root: str = "weixin_store/inbound_spool",
        claim_ttl_seconds: float = _DEFAULT_CLAIM_TTL_SECONDS,
        unhealthy_backlog_age_seconds: float = _DEFAULT_UNHEALTHY_BACKLOG_AGE_SECONDS,
    ) -> None:
        self._claim_ttl_seconds = max(1.0, claim_ttl_seconds)
        self._unhealthy_backlog_age_seconds = max(1.0, unhealthy_backlog_age_seconds)
        fingerprint = weixin_runtime_identity_fingerprint(credentials)
        self.root = Path(controlmesh_home).expanduser() / relative_root / fingerprint
        self.pending_dir = self.root / "pending"
        self.claims_dir = self.root / "claims"

    def enqueue(self, raw_messages: list[dict[str, object]] | tuple[dict[str, object], ...]) -> int:
        """Persist inbound messages that are not already pending."""
        self._ensure_dirs()
        pending_keys = self._pending_dedupe_keys()
        enqueued = 0
        for raw in raw_messages:
            lane_key = _lane_key(raw)
            dedupe_key = _dedupe_key(raw, lane_key)
            if dedupe_key in pending_keys:
                continue
            entry = {
                "schema_version": 1,
                "spool_id": _spool_id(raw),
                "lane_key": lane_key,
                "dedupe_key": dedupe_key,
                "message_id": _message_id(raw),
                "enqueued_at": time.time(),
                "raw": raw,
            }
            path = self.pending_dir / f"{entry['spool_id']}.json"
            if path.exists():
                continue
            path.write_text(json.dumps(entry, ensure_ascii=True, sort_keys=True), encoding="utf-8")
            self._protect_file(path)
            pending_keys.add(dedupe_key)
            enqueued += 1
        return enqueued

    def claim_next(self, *, owner: str, now: float | None = None) -> WeixinInboundClaim | None:
        """Claim the next deliverable entry, recovering stale claims first."""
        current = time.time() if now is None else now
        self._ensure_dirs()
        entries = self._load_pending_entries()
        pending_ids = {entry.spool_id for entry in entries}
        claims = self._load_active_claims(now=current, pending_ids=pending_ids)
        seen_lanes: set[str] = set()
        for entry in entries:
            if entry.lane_key in claims or entry.lane_key in seen_lanes:
                continue
            seen_lanes.add(entry.lane_key)
            claimed = self._try_claim_entry(entry, owner=owner, now=current)
            if claimed is not None:
                return claimed
        return None

    def release(self, claim: WeixinInboundClaim) -> None:
        """Release a failed claim without removing the pending entry."""
        self._remove_claim_file(claim.path, spool_id=claim.spool_id)

    def ack(self, claim: WeixinInboundClaim) -> None:
        """Acknowledge successful delivery and remove queue state."""
        with contextlib.suppress(FileNotFoundError):
            claim.entry.path.unlink()
        self._remove_claim_file(claim.path, spool_id=claim.spool_id)

    def recover_stale_claims(self, *, now: float | None = None) -> int:
        """Drop expired or orphaned claims so backlog can resume."""
        current = time.time() if now is None else now
        pending_ids = {entry.spool_id for entry in self._load_pending_entries()}
        claims = self._load_claims()
        recovered = 0
        for claim in claims.values():
            if claim.spool_id not in pending_ids or claim.lease_expires_at <= current:
                with contextlib.suppress(FileNotFoundError):
                    claim.path.unlink()
                recovered += 1
        return recovered

    def stats(self, *, now: float | None = None) -> WeixinInboundSpoolStats:
        """Return backlog and claim health facts."""
        current = time.time() if now is None else now
        self._ensure_dirs()
        entries = self._load_pending_entries()
        pending_ids = {entry.spool_id for entry in entries}
        claims = self._load_active_claims(now=current, pending_ids=pending_ids)
        lanes_with_pending = {entry.lane_key for entry in entries}
        blocked_lane_count = sum(1 for lane in claims if lane in lanes_with_pending)
        oldest_pending_age = None
        if entries:
            oldest_pending_age = max(0.0, current - min(entry.enqueued_at for entry in entries))
        unhealthy_reason = None
        if (
            entries
            and blocked_lane_count > 0
            and oldest_pending_age is not None
            and oldest_pending_age >= self._unhealthy_backlog_age_seconds
        ):
            unhealthy_reason = "blocked_backlog"
        return WeixinInboundSpoolStats(
            pending_count=len(entries),
            active_claim_count=len(claims),
            blocked_lane_count=blocked_lane_count,
            oldest_pending_age_seconds=oldest_pending_age,
            unhealthy_reason=unhealthy_reason,
        )

    def clear(self) -> None:
        """Remove all pending entries and claims for this identity."""
        for directory in (self.pending_dir, self.claims_dir):
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()

    def _try_claim_entry(
        self,
        entry: WeixinInboundSpoolEntry,
        *,
        owner: str,
        now: float,
    ) -> WeixinInboundClaim | None:
        claim_path = self.claims_dir / f"{_lane_claim_name(entry.lane_key)}.json"
        payload = {
            "schema_version": 1,
            "lane_key": entry.lane_key,
            "spool_id": entry.spool_id,
            "owner": owner,
            "claimed_at": now,
            "lease_expires_at": now + self._claim_ttl_seconds,
        }
        try:
            fd = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = self._read_claim_file(claim_path)
            if existing is not None and existing.lease_expires_at <= now:
                with contextlib.suppress(FileNotFoundError):
                    claim_path.unlink()
                return self._try_claim_entry(entry, owner=owner, now=now)
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
        self._protect_file(claim_path)
        return WeixinInboundClaim(
            lane_key=entry.lane_key,
            spool_id=entry.spool_id,
            owner=owner,
            claimed_at=now,
            lease_expires_at=now + self._claim_ttl_seconds,
            path=claim_path,
            entry=entry,
        )

    def _pending_dedupe_keys(self) -> set[str]:
        return {entry.dedupe_key for entry in self._load_pending_entries()}

    def _load_pending_entries(self) -> list[WeixinInboundSpoolEntry]:
        if not self.pending_dir.exists():
            return []
        entries: list[WeixinInboundSpoolEntry] = []
        for path in sorted(self.pending_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            entry = _coerce_pending_entry(raw, path=path)
            if entry is not None:
                entries.append(entry)
        entries.sort(key=lambda item: item.spool_id)
        return entries

    def _load_claims(self) -> dict[str, WeixinInboundClaim]:
        if not self.claims_dir.exists():
            return {}
        claims: dict[str, WeixinInboundClaim] = {}
        for path in sorted(self.claims_dir.glob("*.json")):
            claim = self._read_claim_file(path)
            if claim is None:
                continue
            claims[claim.lane_key] = claim
        return claims

    def _load_active_claims(
        self,
        *,
        now: float,
        pending_ids: set[str],
    ) -> dict[str, WeixinInboundClaim]:
        claims = self._load_claims()
        active: dict[str, WeixinInboundClaim] = {}
        for lane_key, claim in claims.items():
            if claim.spool_id not in pending_ids or claim.lease_expires_at <= now:
                with contextlib.suppress(FileNotFoundError):
                    claim.path.unlink()
                continue
            active[lane_key] = claim
        return active

    def _read_claim_file(self, path: Path) -> WeixinInboundClaim | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        lane_key = raw.get("lane_key")
        spool_id = raw.get("spool_id")
        owner = raw.get("owner")
        claimed_at = raw.get("claimed_at")
        lease_expires_at = raw.get("lease_expires_at")
        if not all(isinstance(value, str) for value in (lane_key, spool_id, owner)):
            return None
        if not isinstance(claimed_at, (int, float)) or not isinstance(lease_expires_at, (int, float)):
            return None
        pending_path = self.pending_dir / f"{spool_id}.json"
        entry = None
        if pending_path.exists():
            entry = _coerce_pending_entry(
                json.loads(pending_path.read_text(encoding="utf-8")),
                path=pending_path,
            )
        if entry is None:
            entry = WeixinInboundSpoolEntry(
                spool_id=spool_id,
                lane_key=lane_key,
                dedupe_key="",
                message_id="",
                enqueued_at=0.0,
                raw={},
                path=pending_path,
            )
        return WeixinInboundClaim(
            lane_key=lane_key,
            spool_id=spool_id,
            owner=owner,
            claimed_at=float(claimed_at),
            lease_expires_at=float(lease_expires_at),
            path=path,
            entry=entry,
        )

    def _remove_claim_file(self, path: Path, *, spool_id: str) -> None:
        claim = self._read_claim_file(path)
        if claim is None or claim.spool_id != spool_id:
            return
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    def _ensure_dirs(self) -> None:
        self.pending_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.claims_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def _protect_file(path: Path) -> None:
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def _coerce_pending_entry(value: Any, *, path: Path) -> WeixinInboundSpoolEntry | None:
    if not isinstance(value, dict):
        return None
    spool_id = value.get("spool_id")
    lane_key = value.get("lane_key")
    dedupe_key = value.get("dedupe_key", "")
    message_id = value.get("message_id", "")
    enqueued_at = value.get("enqueued_at")
    raw = value.get("raw")
    if not isinstance(spool_id, str) or not isinstance(lane_key, str):
        return None
    if not isinstance(dedupe_key, str) or not isinstance(message_id, str):
        return None
    if not isinstance(enqueued_at, (int, float)) or not isinstance(raw, dict):
        return None
    return WeixinInboundSpoolEntry(
        spool_id=spool_id,
        lane_key=lane_key,
        dedupe_key=dedupe_key,
        message_id=message_id,
        enqueued_at=float(enqueued_at),
        raw=dict(raw),
        path=path,
    )


def _message_id(raw: dict[str, object]) -> str:
    message_id = raw.get("message_id")
    if isinstance(message_id, (int, str)):
        return str(message_id)
    return ""


def _lane_key(raw: dict[str, object]) -> str:
    user_id = raw.get("from_user_id")
    if isinstance(user_id, str) and user_id:
        return f"user:{user_id}"
    message_id = _message_id(raw)
    if message_id:
        return f"message:{message_id}"
    digest = hashlib.sha256(json.dumps(raw, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"fallback:{digest}"


def _dedupe_key(raw: dict[str, object], lane_key: str) -> str:
    message_id = _message_id(raw)
    if message_id:
        return f"{lane_key}:{message_id}"
    digest = hashlib.sha256(json.dumps(raw, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{lane_key}:{digest}"


def _spool_id(raw: dict[str, object]) -> str:
    message_id = _message_id(raw) or "msg"
    return f"{time.time_ns():020d}-{message_id}-{uuid4().hex[:8]}"


def _lane_claim_name(lane_key: str) -> str:
    return hashlib.sha256(lane_key.encode("utf-8")).hexdigest()[:24]
