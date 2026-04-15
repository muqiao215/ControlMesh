"""Live team dispatch integration via the shared MessageBus."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from controlmesh.bus.envelope import DeliveryMode, Envelope, LockMode, Origin
from controlmesh.team.models import (
    TeamDispatchRequest,
    TeamDispatchResult,
    TeamEvent,
    TeamMailboxMessage,
    TeamManifest,
    TeamSessionRef,
    TeamWorkerRuntimeRef,
)
from controlmesh.team.runtime_attachment import (
    TeamDispatchExecutionClaim,
    TeamNamedSessionAttachment,
    TeamRuntimeAttachmentManager,
)
from controlmesh.team.state import TeamStateStore


class TeamBus(Protocol):
    """Minimal bus protocol needed by the live team dispatcher."""

    async def submit(self, envelope: Envelope) -> None:
        """Submit an envelope for injection and/or delivery."""
        ...


@dataclass(frozen=True, slots=True)
class TeamLiveRoute:
    """Resolved live bus target for a team dispatch or notification."""

    route: str
    session: TeamSessionRef

    @property
    def storage_key(self) -> str:
        return self.session.storage_key


def _require_live_session(session: TeamSessionRef, *, label: str) -> TeamSessionRef:
    if session.chat_id == 0:
        msg = f"{label} must resolve to a live chat before dispatch"
        raise ValueError(msg)
    return session

def _resolve_mailbox_live_route(manifest: TeamManifest) -> TeamLiveRoute:
    return TeamLiveRoute(
        route="leader_session",
        session=_require_live_session(manifest.leader.session, label="team leader session"),
    )


def _dispatch_metadata(
    *,
    route: str | None,
    target_session: str | None,
    claim: TeamDispatchExecutionClaim | None,
) -> dict[str, str | None] | None:
    metadata: dict[str, str | None] = {}
    if route is not None:
        metadata["live_route"] = route
    if target_session is not None:
        metadata["live_target_session"] = target_session
    if claim is not None:
        metadata.update(claim.dispatch_claim)
    return metadata or None


def build_dispatch_envelope(
    manifest: TeamManifest,
    request: TeamDispatchRequest,
    *,
    attachment: TeamNamedSessionAttachment | None = None,
    execution_id: str | None = None,
) -> Envelope:
    """Build a live injection envelope for a team dispatch request."""
    route, runtime_ref = _resolve_dispatch_live_route_with_attachment(
        manifest,
        request,
        attachment=attachment,
    )
    prompt = _render_dispatch_prompt(
        manifest,
        request,
        attachment=attachment,
        execution_id=execution_id,
    )
    metadata: dict[str, str] = {
        "team_name": manifest.team_name,
        "request_id": request.request_id,
        "task_id": request.task_id or "",
        "recipient": request.to_worker,
        "kind": request.kind,
        "live_route": route.route,
        "live_target_session": route.storage_key,
    }
    if runtime_ref.provider:
        metadata["worker_provider"] = runtime_ref.provider
    if runtime_ref.session_name:
        metadata["worker_session_name"] = runtime_ref.session_name
    if runtime_ref.provider_session_id:
        metadata["worker_provider_session_id"] = runtime_ref.provider_session_id
    if runtime_ref.routable_session is not None:
        metadata["worker_routable_session"] = runtime_ref.routable_session.storage_key
    if attachment is not None:
        metadata["worker_attachment_type"] = attachment.attachment_type
        metadata["worker_attachment_name"] = attachment.name
        metadata["worker_attachment_session_id"] = attachment.session_id
    if execution_id is not None:
        metadata["execution_id"] = execution_id

    return Envelope(
        origin=Origin.INTERAGENT,
        chat_id=route.session.chat_id,
        topic_id=route.session.topic_id,
        transport=route.session.transport,
        prompt=prompt,
        prompt_preview=f"team dispatch {request.request_id} -> {request.to_worker}",
        delivery=DeliveryMode.UNICAST,
        lock_mode=LockMode.REQUIRED,
        needs_injection=True,
        metadata=metadata,
    )


def build_mailbox_envelope(manifest: TeamManifest, message: TeamMailboxMessage) -> Envelope:
    """Build a leader-visible live mailbox notification envelope."""
    route = _resolve_mailbox_live_route(manifest)
    return Envelope(
        origin=Origin.INTERAGENT,
        chat_id=route.session.chat_id,
        topic_id=route.session.topic_id,
        transport=route.session.transport,
        result_text=_render_mailbox_message(manifest, message),
        status="success",
        delivery=DeliveryMode.UNICAST,
        lock_mode=LockMode.NONE,
        needs_injection=False,
        metadata={
            "team_name": manifest.team_name,
            "message_id": message.message_id,
            "recipient": message.to_worker,
            "sender": message.from_worker or "",
            "live_route": route.route,
            "live_target_session": route.storage_key,
        },
    )


class TeamLiveDispatcher:
    """Bridge team state transitions into the shared live delivery bus."""

    def __init__(
        self,
        store: TeamStateStore,
        bus: TeamBus,
        *,
        named_sessions_path: Path | str | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._attachments = TeamRuntimeAttachmentManager(named_sessions_path=named_sessions_path)

    async def dispatch_request(self, request_id: str) -> TeamDispatchRequest:
        """Execute a live dispatch request through the leader session."""
        manifest = self._store.read_manifest()
        request = self._store.get_dispatch_request(request_id)
        try:
            claim = self._attachments.claim_dispatch(self._store, manifest, request)
        except RuntimeError as exc:
            return self._mark_dispatch_failed(request, error=str(exc))

        envelope = build_dispatch_envelope(
            manifest,
            request,
            attachment=claim.attachment if claim is not None else None,
            execution_id=claim.execution_id if claim is not None else None,
        )
        route = envelope.metadata.get("live_route")
        target_session = envelope.metadata.get("live_target_session")

        try:
            await self._bus.submit(envelope)
        except Exception as exc:
            return self._mark_dispatch_failed(
                request,
                error=str(exc),
                route=route,
                target_session=target_session,
                claim=claim,
            )

        if envelope.is_error:
            error_text = envelope.result_text or "team dispatch injection failed"
            return self._mark_dispatch_failed(
                request,
                error=error_text,
                route=route,
                target_session=target_session,
                claim=claim,
            )

        notified = self._store.transition_dispatch_request(
            request.request_id,
            "notified",
            metadata=_dispatch_metadata(
                route=route,
                target_session=target_session,
                claim=claim,
            ),
        )
        self._append_event(
            self._new_event(
                event_type="dispatch_notified",
                payload={
                    "kind": request.kind,
                    "live_route": route,
                    "live_target_session": target_session,
                },
                refs={
                    "dispatch_request_id": request.request_id,
                    "worker": request.to_worker,
                    "task_id": request.task_id,
                },
            )
        )
        delivered = self._store.transition_dispatch_request(
            request.request_id,
            "delivered",
            metadata=_dispatch_metadata(
                route=route,
                target_session=target_session,
                claim=claim,
            ),
        )
        self._append_event(
            self._new_event(
                event_type="dispatch_delivered",
                payload={
                    "kind": request.kind,
                    "response_preview": (envelope.result_text or "")[:200],
                    "live_route": route,
                    "live_target_session": target_session,
                },
                refs={
                    "dispatch_request_id": request.request_id,
                    "worker": request.to_worker,
                    "task_id": request.task_id,
                },
            )
        )
        return delivered.model_copy(update={"notified_at": notified.notified_at})

    def record_dispatch_result(self, request_id: str, result: TeamDispatchResult) -> TeamDispatchRequest:
        """Record a worker-reported result for a delivered dispatch."""
        manifest = self._store.read_manifest()
        previous = self._store.get_dispatch_request(request_id)
        previous_task = None
        if previous.task_id is not None and result.task_status is not None:
            previous_task = self._store.get_task(previous.task_id)

        updated = self._store.record_dispatch_result(request_id, result)
        recorded = updated.result
        if recorded is None:  # pragma: no cover - defensive store contract
            msg = f"dispatch request '{request_id}' did not persist a result"
            raise RuntimeError(msg)

        self._append_event(
            self._new_event(
                event_type="dispatch_result_recorded",
                payload={
                    "outcome": recorded.outcome,
                    "summary": recorded.summary,
                    "reported_by": recorded.reported_by,
                    "reported_at": recorded.reported_at,
                    "task_status": recorded.task_status,
                    "live_route": updated.live_route,
                    "live_target_session": updated.live_target_session,
                },
                refs={
                    "dispatch_request_id": updated.request_id,
                    "worker": updated.to_worker,
                    "task_id": updated.task_id,
                },
            )
        )

        if updated.task_id is not None and result.task_status is not None:
            task = self._store.get_task(updated.task_id)
            previous_status = previous_task.status if previous_task is not None else None
            if previous_status != task.status:
                self._append_event(
                    self._new_event(
                        event_type="task_status_changed",
                        payload={
                            "status": task.status,
                            "previous_status": previous_status,
                            "dispatch_outcome": recorded.outcome,
                        },
                        refs={
                            "dispatch_request_id": updated.request_id,
                            "worker": task.owner or updated.to_worker,
                            "task_id": updated.task_id,
                        },
                    )
                )

        self._attachments.release_dispatch(self._store, manifest, updated)
        return updated

    async def deliver_mailbox_message(self, message_id: str) -> TeamMailboxMessage:
        """Send a live mailbox notification to the leader session."""
        manifest = self._store.read_manifest()
        message = self._store.get_mailbox_message(message_id)
        envelope = build_mailbox_envelope(manifest, message)
        await self._bus.submit(envelope)
        notified = self._store.mark_mailbox_message_notified(message.message_id)
        self._append_event(
            self._new_event(
                event_type="mailbox_message_notified",
                payload={"subject": message.subject, "from_worker": message.from_worker},
                refs={
                    "message_id": message.message_id,
                    "worker": message.to_worker,
                },
            )
        )
        return notified

    def _mark_dispatch_failed(
        self,
        request: TeamDispatchRequest,
        *,
        error: str,
        route: str | None = None,
        target_session: str | None = None,
        claim: TeamDispatchExecutionClaim | None = None,
    ) -> TeamDispatchRequest:
        failed = self._store.transition_dispatch_request(
            request.request_id,
            "failed",
            error=error,
            metadata=_dispatch_metadata(
                route=route,
                target_session=target_session,
                claim=claim,
            ),
        )
        if claim is not None:
            manifest = self._store.read_manifest()
            self._attachments.release_dispatch(self._store, manifest, failed)
        self._append_event(
            self._new_event(
                event_type="dispatch_failed",
                payload={
                    "kind": request.kind,
                    "error": error,
                    "live_route": route,
                    "live_target_session": target_session,
                },
                refs={
                    "dispatch_request_id": request.request_id,
                    "worker": request.to_worker,
                    "task_id": request.task_id,
                },
            )
        )
        return failed

    def _append_event(self, event: TeamEvent) -> TeamEvent:
        return self._store.append_event(event)

    def _new_event(
        self,
        *,
        event_type: str,
        payload: dict[str, str | None] | None = None,
        refs: dict[str, str | None] | None = None,
    ) -> TeamEvent:
        manifest = self._store.read_manifest()
        refs = refs or {}
        return TeamEvent(
            event_id=f"evt-{secrets.token_hex(6)}",
            team_name=manifest.team_name,
            event_type=event_type,
            worker=refs.get("worker"),
            task_id=refs.get("task_id"),
            dispatch_request_id=refs.get("dispatch_request_id"),
            message_id=refs.get("message_id"),
            payload=payload or {},
        )


def _resolve_dispatch_live_route_with_attachment(
    manifest: TeamManifest,
    request: TeamDispatchRequest,
    *,
    attachment: TeamNamedSessionAttachment | None,
) -> tuple[TeamLiveRoute, TeamWorkerRuntimeRef]:
    runtime_ref = manifest.worker_runtime_ref(request.to_worker)
    worker_session = runtime_ref.routable_session
    if attachment is not None and worker_session is not None and worker_session.chat_id != 0:
        return TeamLiveRoute(route="worker_session", session=worker_session), runtime_ref
    return TeamLiveRoute(
        route="leader_session",
        session=_require_live_session(manifest.leader.session, label="team leader session"),
    ), runtime_ref


def _render_dispatch_prompt(
    manifest: TeamManifest,
    request: TeamDispatchRequest,
    *,
    attachment: TeamNamedSessionAttachment | None,
    execution_id: str | None,
) -> str:
    runtime_ref = manifest.worker_runtime_ref(request.to_worker)
    lines = [
        "[TEAM LIVE DISPATCH]",
        f"Team: {manifest.team_name}",
        f"Task Description: {manifest.task_description}",
        f"Dispatch Request ID: {request.request_id}",
        f"Dispatch Kind: {request.kind}",
        f"Target Worker: {request.to_worker}",
    ]
    if request.task_id:
        lines.append(f"Task ID: {request.task_id}")
    if runtime_ref.provider:
        lines.append(f"Worker Provider: {runtime_ref.provider}")
    if runtime_ref.session_name:
        lines.append(f"Worker Runtime Session: {runtime_ref.session_name}")
    if runtime_ref.provider_session_id:
        lines.append(f"Worker Provider Session ID: {runtime_ref.provider_session_id}")
    if runtime_ref.routable_session is not None:
        lines.append(f"Worker Routable Session: {runtime_ref.routable_session.storage_key}")
    if attachment is not None:
        lines.append(f"Worker Attachment: {attachment.attachment_type}:{attachment.name}")
        lines.append(f"Worker Attachment Session ID: {attachment.session_id}")
    if execution_id is not None:
        lines.append(f"Execution ID: {execution_id}")
    lines.extend(
        [
            "",
            "Treat this as live team coordination state coming from ControlMesh's team layer.",
            "Respond with the next concrete coordination step for this dispatch.",
        ]
    )
    return "\n".join(lines)


def _render_mailbox_message(manifest: TeamManifest, message: TeamMailboxMessage) -> str:
    sender = message.from_worker or "system"
    return "\n".join(
        [
            "**Team Mailbox Notification**",
            "",
            f"Team: `{manifest.team_name}`",
            f"From: `{sender}`",
            f"To: `{message.to_worker}`",
            f"Subject: {message.subject}",
            "",
            message.body,
        ]
    )


__all__ = [
    "TeamLiveDispatcher",
    "build_dispatch_envelope",
    "build_mailbox_envelope",
]
