"""Narrow real worker runtime attachment and execution claim helpers."""

from __future__ import annotations

import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from controlmesh.session.named import NamedSessionRegistry
from controlmesh.team.models import TeamDispatchRequest, TeamManifest, TeamWorkerRuntimeState
from controlmesh.team.state import TeamStateStore
from controlmesh.workspace.paths import resolve_paths

_LEASE_TTL = timedelta(minutes=5)


def _utc_now(now: datetime | None = None) -> datetime:
    return now.astimezone(UTC) if now is not None else datetime.now(UTC)


def _lease_expires_at(now: datetime) -> str:
    return (now + _LEASE_TTL).isoformat()


@dataclass(frozen=True, slots=True)
class TeamNamedSessionAttachment:
    """Resolved real runtime unit backed by a persisted named session."""

    attachment_type: str
    name: str
    transport: str
    chat_id: int
    provider: str
    model: str
    session_id: str
    status: str


@dataclass(frozen=True, slots=True)
class TeamDispatchExecutionClaim:
    """Single active execution claim for a worker runtime."""

    runtime: TeamWorkerRuntimeState
    execution_id: str
    lease_id: str
    lease_expires_at: str
    attachment: TeamNamedSessionAttachment

    @property
    def dispatch_claim(self) -> dict[str, str | None]:
        return {
            "execution_id": self.execution_id,
            "runtime_lease_id": self.lease_id,
            "runtime_lease_expires_at": self.lease_expires_at,
            "runtime_attachment_type": self.attachment.attachment_type,
            "runtime_attachment_name": self.attachment.name,
        }


class TeamRuntimeAttachmentManager:
    """Resolve and claim narrow real worker runtime attachments."""

    def __init__(self, *, named_sessions_path: Path | str | None = None) -> None:
        if named_sessions_path is None:
            named_sessions_path = resolve_paths().named_sessions_path
        self._named_sessions_path = Path(named_sessions_path)

    def resolve_attachment(
        self,
        manifest: TeamManifest,
        worker: str,
    ) -> TeamNamedSessionAttachment | None:
        runtime_ref = manifest.worker_runtime_ref(worker)
        if runtime_ref.session_name is None:
            return None
        chat_id = (
            runtime_ref.routable_session.chat_id
            if runtime_ref.routable_session is not None
            else manifest.leader.session.chat_id
        )
        registry = NamedSessionRegistry(self._named_sessions_path)
        session = registry.get(chat_id, runtime_ref.session_name)
        if session is None or session.status == "ended" or not session.session_id:
            return None
        return TeamNamedSessionAttachment(
            attachment_type="named_session",
            name=session.name,
            transport=session.transport,
            chat_id=session.chat_id,
            provider=session.provider,
            model=session.model,
            session_id=session.session_id,
            status=session.status,
        )

    def claim_dispatch(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        request: TeamDispatchRequest,
        *,
        now: datetime | None = None,
    ) -> TeamDispatchExecutionClaim | None:
        with suppress(FileNotFoundError):
            self.reconcile_runtime_owner(
                store,
                manifest,
                request.to_worker,
                now=now,
            )
        attachment = self.resolve_attachment(manifest, request.to_worker)
        if attachment is None:
            return None
        at = _utc_now(now)
        runtime = self._ensure_worker_ready(
            store,
            manifest,
            request.to_worker,
            attachment,
            now=at,
        )
        if runtime.status == "busy":
            owner = runtime.dispatch_request_id or runtime.execution_id or "<unknown>"
            msg = f"worker runtime '{request.to_worker}' is already busy with '{owner}'"
            raise RuntimeError(msg)
        if runtime.status != "ready":
            msg = f"worker runtime '{request.to_worker}' is not ready while {runtime.status}"
            raise RuntimeError(msg)

        execution_id = f"exec-{secrets.token_hex(6)}"
        lease_expires_at = _lease_expires_at(at)
        busy = store.transition_worker_runtime(
            request.to_worker,
            "busy",
            updates={
                "execution_id": execution_id,
                "dispatch_request_id": request.request_id,
                "heartbeat_at": at.isoformat(),
                "lease_expires_at": lease_expires_at,
                "attachment_session_id": attachment.session_id,
            },
            now=at,
        )
        return TeamDispatchExecutionClaim(
            runtime=busy,
            execution_id=execution_id,
            lease_id=busy.lease_id or runtime.lease_id or "",
            lease_expires_at=busy.lease_expires_at or lease_expires_at,
            attachment=attachment,
        )

    def ensure_attached_runtime(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
        *,
        now: datetime | None = None,
    ) -> TeamWorkerRuntimeState | None:
        """Resolve the worker attachment and persist the matching runtime state."""
        attachment = self.resolve_attachment(manifest, worker)
        if attachment is None:
            return None
        return self._ensure_worker_ready(
            store,
            manifest,
            worker,
            attachment,
            now=_utc_now(now),
        )

    def reconcile_runtime_owner(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
        *,
        now: datetime | None = None,
    ) -> TeamWorkerRuntimeState:
        """Reconcile persisted runtime state against the live named-session owner."""
        runtime = store.reconcile_worker_runtime(worker, now=now)
        reason = self._owner_binding_failure(runtime)
        if reason is None:
            return runtime
        return store.transition_worker_runtime(
            worker,
            "lost",
            updates={
                "health_reason": reason,
                "dispatch_request_id": None,
            },
            now=_utc_now(now),
        )

    def release_dispatch(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        request: TeamDispatchRequest,
        *,
        now: datetime | None = None,
    ) -> TeamWorkerRuntimeState | None:
        if request.execution_id is None or request.runtime_lease_id is None:
            return None
        try:
            runtime = self.reconcile_runtime_owner(
                store,
                manifest,
                request.to_worker,
                now=now,
            )
        except FileNotFoundError:
            return None
        if runtime.status != "busy" or runtime.dispatch_request_id != request.request_id:
            return runtime

        attachment = self.resolve_attachment(manifest, request.to_worker)
        if attachment is None:
            return store.transition_worker_runtime(
                request.to_worker,
                "lost",
                updates={
                    "health_reason": "runtime attachment missing during release",
                    "dispatch_request_id": None,
                },
                now=now,
            )

        at = _utc_now(now)
        return store.transition_worker_runtime(
            request.to_worker,
            "ready",
            updates={
                "heartbeat_at": at.isoformat(),
                "lease_expires_at": _lease_expires_at(at),
                "attachment_type": attachment.attachment_type,
                "attachment_name": attachment.name,
                "attachment_transport": attachment.transport,
                "attachment_chat_id": attachment.chat_id,
                "attachment_session_id": attachment.session_id,
            },
            now=at,
        )

    def renew_runtime_heartbeat(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
        *,
        owner_session_id: str,
        now: datetime | None = None,
    ) -> TeamWorkerRuntimeState:
        """Renew heartbeat/lease facts only for the current live runtime owner."""
        at = _utc_now(now)
        runtime = self.reconcile_runtime_owner(store, manifest, worker, now=at)
        if runtime.status not in {"starting", "ready", "busy", "unhealthy"}:
            msg = f"worker runtime '{worker}' is not live while {runtime.status}"
            raise ValueError(msg)
        attachment = self.resolve_attachment(manifest, worker)
        if attachment is None:
            msg = f"worker runtime '{worker}' attachment is not available"
            raise ValueError(msg)
        if attachment.session_id != owner_session_id:
            msg = (
                f"worker runtime '{worker}' is owned by session "
                f"'{attachment.session_id}' not '{owner_session_id}'"
            )
            raise ValueError(msg)
        if runtime.lease_id is None:
            msg = f"worker runtime '{worker}' is missing lease ownership"
            raise ValueError(msg)
        return store.record_worker_runtime_heartbeat(
            worker,
            lease_id=runtime.lease_id,
            heartbeat_at=at.isoformat(),
            lease_expires_at=_lease_expires_at(at),
        )

    def _ensure_worker_ready(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
        attachment: TeamNamedSessionAttachment,
        *,
        now: datetime,
    ) -> TeamWorkerRuntimeState:
        runtime = self._get_or_create_runtime(store, worker)
        runtime = self.reconcile_runtime_owner(store, manifest, worker, now=now)

        if runtime.status in {"ready", "busy"} and self._matches_attachment(runtime, attachment):
            return runtime

        if runtime.status in {"starting", "unhealthy"} and self._matches_attachment(runtime, attachment):
            store.record_worker_runtime_heartbeat(
                worker,
                lease_id=runtime.lease_id or self._new_lease_id(),
                heartbeat_at=now.isoformat(),
                lease_expires_at=runtime.lease_expires_at or _lease_expires_at(now),
            )
            return store.transition_worker_runtime(
                worker,
                "ready" if runtime.status != "busy" else "busy",
                updates={"attachment_session_id": attachment.session_id},
                now=now,
            )

        if runtime.status not in {"created", "stopped", "lost"}:
            runtime = store.transition_worker_runtime(
                worker,
                "lost",
                updates={
                    "health_reason": "runtime attachment changed",
                    "dispatch_request_id": None,
                },
                now=now,
            )

        lease_id = self._new_lease_id()
        lease_expires_at = _lease_expires_at(now)
        starting = store.transition_worker_runtime(
            worker,
            "starting",
            updates={
                "attachment_type": attachment.attachment_type,
                "attachment_name": attachment.name,
                "attachment_transport": attachment.transport,
                "attachment_chat_id": attachment.chat_id,
                "attachment_session_id": attachment.session_id,
                "attached_at": now.isoformat(),
                "lease_id": lease_id,
                "lease_expires_at": lease_expires_at,
            },
            now=now,
        )
        store.record_worker_runtime_heartbeat(
            worker,
            lease_id=starting.lease_id or lease_id,
            heartbeat_at=now.isoformat(),
            lease_expires_at=lease_expires_at,
        )
        return store.transition_worker_runtime(
            worker,
            "ready",
            updates={
                "attachment_type": attachment.attachment_type,
                "attachment_name": attachment.name,
                "attachment_transport": attachment.transport,
                "attachment_chat_id": attachment.chat_id,
                "attachment_session_id": attachment.session_id,
                "attached_at": now.isoformat(),
                "lease_id": starting.lease_id or lease_id,
                "lease_expires_at": lease_expires_at,
                "heartbeat_at": now.isoformat(),
            },
            now=now,
        )

    def _get_or_create_runtime(self, store: TeamStateStore, worker: str) -> TeamWorkerRuntimeState:
        try:
            return store.get_worker_runtime(worker)
        except FileNotFoundError:
            return store.put_worker_runtime(TeamWorkerRuntimeState(worker=worker))

    def _matches_attachment(
        self,
        runtime: TeamWorkerRuntimeState,
        attachment: TeamNamedSessionAttachment,
    ) -> bool:
        return (
            runtime.attachment_type == attachment.attachment_type
            and runtime.attachment_name == attachment.name
            and runtime.attachment_transport == attachment.transport
            and runtime.attachment_chat_id == attachment.chat_id
            and runtime.attachment_session_id == attachment.session_id
        )

    def _new_lease_id(self) -> str:
        return f"lease-{secrets.token_hex(6)}"

    def _owner_binding_failure(self, runtime: TeamWorkerRuntimeState) -> str | None:
        if runtime.status in {"created", "stopped", "lost"}:
            return None
        if runtime.attachment_type != "named_session":
            return None
        if runtime.attachment_chat_id is None or runtime.attachment_name is None:
            failure = "runtime owner facts missing"
        else:
            session = NamedSessionRegistry(self._named_sessions_path).get(
                runtime.attachment_chat_id,
                runtime.attachment_name,
            )
            if session is None:
                failure = "runtime owner missing"
            elif session.status == "ended":
                failure = "runtime owner ended"
            elif session.transport != runtime.attachment_transport:
                failure = "runtime owner changed"
            elif not session.session_id:
                failure = "runtime owner missing session id"
            elif runtime.attachment_session_id != session.session_id:
                failure = "runtime owner changed"
            else:
                failure = None
        return failure
