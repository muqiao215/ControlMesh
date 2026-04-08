"""Live team dispatch integration via the shared MessageBus."""

from __future__ import annotations

import secrets
from typing import Protocol

from ductor_bot.bus.envelope import DeliveryMode, Envelope, LockMode, Origin
from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamEvent,
    TeamMailboxMessage,
    TeamManifest,
)
from ductor_bot.team.state import TeamStateStore


class TeamBus(Protocol):
    """Minimal bus protocol needed by the live team dispatcher."""

    async def submit(self, envelope: Envelope) -> None:
        """Submit an envelope for injection and/or delivery."""
        ...


def _require_routable_leader(manifest: TeamManifest) -> None:
    if manifest.leader.session.chat_id == 0:
        msg = "team leader session must resolve to a live chat before dispatch"
        raise ValueError(msg)


def build_dispatch_envelope(manifest: TeamManifest, request: TeamDispatchRequest) -> Envelope:
    """Build a leader-session injection envelope for a team dispatch request."""
    _require_routable_leader(manifest)
    prompt = _render_dispatch_prompt(manifest, request)
    return Envelope(
        origin=Origin.INTERAGENT,
        chat_id=manifest.leader.session.chat_id,
        topic_id=manifest.leader.session.topic_id,
        transport=manifest.leader.session.transport,
        prompt=prompt,
        prompt_preview=f"team dispatch {request.request_id} -> {request.to_worker}",
        delivery=DeliveryMode.UNICAST,
        lock_mode=LockMode.REQUIRED,
        needs_injection=True,
        metadata={
            "team_name": manifest.team_name,
            "request_id": request.request_id,
            "task_id": request.task_id,
            "recipient": request.to_worker,
            "kind": request.kind,
        },
    )


def build_mailbox_envelope(manifest: TeamManifest, message: TeamMailboxMessage) -> Envelope:
    """Build a leader-visible live mailbox notification envelope."""
    _require_routable_leader(manifest)
    return Envelope(
        origin=Origin.INTERAGENT,
        chat_id=manifest.leader.session.chat_id,
        topic_id=manifest.leader.session.topic_id,
        transport=manifest.leader.session.transport,
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
        },
    )


class TeamLiveDispatcher:
    """Bridge team state transitions into the shared live delivery bus."""

    def __init__(self, store: TeamStateStore, bus: TeamBus) -> None:
        self._store = store
        self._bus = bus

    async def dispatch_request(self, request_id: str) -> TeamDispatchRequest:
        """Execute a live dispatch request through the leader session."""
        manifest = self._store.read_manifest()
        request = self._store.get_dispatch_request(request_id)
        envelope = build_dispatch_envelope(manifest, request)

        try:
            await self._bus.submit(envelope)
        except Exception as exc:
            return self._mark_dispatch_failed(request, error=str(exc))

        if envelope.is_error:
            error_text = envelope.result_text or "team dispatch injection failed"
            return self._mark_dispatch_failed(request, error=error_text)

        notified = self._store.transition_dispatch_request(request.request_id, "notified")
        self._append_event(
            self._new_event(
                event_type="dispatch_notified",
                payload={"kind": request.kind},
                refs={
                    "dispatch_request_id": request.request_id,
                    "worker": request.to_worker,
                    "task_id": request.task_id,
                },
            )
        )
        delivered = self._store.transition_dispatch_request(request.request_id, "delivered")
        self._append_event(
            self._new_event(
                event_type="dispatch_delivered",
                payload={"kind": request.kind, "response_preview": envelope.result_text[:200]},
                refs={
                    "dispatch_request_id": request.request_id,
                    "worker": request.to_worker,
                    "task_id": request.task_id,
                },
            )
        )
        return delivered.model_copy(update={"notified_at": notified.notified_at})

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
    ) -> TeamDispatchRequest:
        failed = self._store.transition_dispatch_request(
            request.request_id,
            "failed",
            error=error,
        )
        self._append_event(
            self._new_event(
                event_type="dispatch_failed",
                payload={"kind": request.kind, "error": error},
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


def _render_dispatch_prompt(manifest: TeamManifest, request: TeamDispatchRequest) -> str:
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
    lines.extend(
        [
            "",
            "Treat this as live team coordination state coming from Ductor's team layer.",
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
