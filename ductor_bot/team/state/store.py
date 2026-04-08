"""High-level persistence wrapper for additive team state."""

from __future__ import annotations

from pathlib import Path

from ductor_bot.team.contracts import (
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_MAILBOX_MESSAGE_STATUSES,
    TEAM_TASK_STATUSES,
)
from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamEvent,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamTask,
    TeamTaskClaim,
)
from ductor_bot.team.state.base import TeamStatePaths
from ductor_bot.team.state.dispatch import (
    create_dispatch_request,
    list_dispatch_requests,
    transition_dispatch_request,
)
from ductor_bot.team.state.events import append_event, read_events
from ductor_bot.team.state.mailbox import (
    create_mailbox_message,
    list_mailbox_messages,
    mark_mailbox_message_delivered,
    mark_mailbox_message_notified,
)
from ductor_bot.team.state.manifest import read_manifest, write_manifest
from ductor_bot.team.state.phase import read_phase, write_phase
from ductor_bot.team.state.tasks import claim_task, get_task, list_tasks, release_task_claim, upsert_task


class TeamStateStore:
    """File-backed state store for additive team coordination."""

    def __init__(self, state_root: Path | str, team_name: str) -> None:
        self.paths = TeamStatePaths(state_root=Path(state_root), team_name=team_name)
        self.paths.team_dir.mkdir(parents=True, exist_ok=True)

    def write_manifest(self, manifest: TeamManifest) -> TeamManifest:
        return write_manifest(self.paths, manifest)

    def read_manifest(self) -> TeamManifest:
        return read_manifest(self.paths)

    def upsert_task(self, task: TeamTask) -> TeamTask:
        return upsert_task(self.paths, task)

    def list_tasks(self, *, status: str | None = None, owner: str | None = None) -> list[TeamTask]:
        return list_tasks(self.paths, status=status, owner=owner)

    def get_task(self, task_id: str) -> TeamTask:
        return get_task(self.paths, task_id)

    def claim_task(self, task_id: str, claim: TeamTaskClaim, *, now=None) -> TeamTask:  # type: ignore[no-untyped-def]
        return claim_task(self.paths, task_id, claim, now=now)

    def release_task_claim(self, task_id: str) -> TeamTask:
        return release_task_claim(self.paths, task_id)

    def create_dispatch_request(self, request: TeamDispatchRequest) -> TeamDispatchRequest:
        return create_dispatch_request(self.paths, request)

    def transition_dispatch_request(self, request_id: str, to_status: str, *, error: str | None = None) -> TeamDispatchRequest:
        return transition_dispatch_request(self.paths, request_id, to_status, error=error)

    def list_dispatch_requests(self, *, status: str | None = None) -> list[TeamDispatchRequest]:
        return list_dispatch_requests(self.paths, status=status)

    def create_mailbox_message(self, message: TeamMailboxMessage) -> TeamMailboxMessage:
        return create_mailbox_message(self.paths, message)

    def mark_mailbox_message_notified(self, message_id: str) -> TeamMailboxMessage:
        return mark_mailbox_message_notified(self.paths, message_id)

    def mark_mailbox_message_delivered(self, message_id: str) -> TeamMailboxMessage:
        return mark_mailbox_message_delivered(self.paths, message_id)

    def list_mailbox_messages(self, *, status: str | None = None) -> list[TeamMailboxMessage]:
        return list_mailbox_messages(self.paths, status=status)

    def append_event(self, event: TeamEvent) -> TeamEvent:
        return append_event(self.paths, event)

    def read_events(
        self,
        *,
        after_event_id: str | None = None,
        event_type: str | None = None,
        worker: str | None = None,
        task_id: str | None = None,
        limit: int | None = None,
    ) -> list[TeamEvent]:
        return read_events(
            self.paths,
            after_event_id=after_event_id,
            event_type=event_type,
            worker=worker,
            task_id=task_id,
            limit=limit,
        )

    def write_phase(self, phase: TeamPhaseState) -> TeamPhaseState:
        return write_phase(self.paths, phase)

    def read_phase(self) -> TeamPhaseState:
        return read_phase(self.paths)

    def build_summary(self) -> dict[str, object]:
        """Aggregate a read-only summary from the persisted state."""
        manifest = self.read_manifest()
        phase = self.read_phase()
        tasks = self.list_tasks()
        dispatch = self.list_dispatch_requests()
        mailbox = self.list_mailbox_messages()
        events = self.read_events()

        task_counts = {status: 0 for status in TEAM_TASK_STATUSES}
        for task in tasks:
            task_counts[task.status] += 1

        dispatch_counts = {status: 0 for status in TEAM_DISPATCH_REQUEST_STATUSES}
        for request in dispatch:
            dispatch_counts[request.status] += 1

        mailbox_counts = {status: 0 for status in TEAM_MAILBOX_MESSAGE_STATUSES}
        for message in mailbox:
            mailbox_counts[message.status] += 1

        return {
            "team_name": manifest.team_name,
            "task_description": manifest.task_description,
            "phase": phase.current_phase,
            "active": phase.active,
            "workers": [worker.model_dump(mode="json") for worker in manifest.workers],
            "task_counts": task_counts,
            "dispatch_counts": dispatch_counts,
            "mailbox_counts": mailbox_counts,
            "latest_event_id": events[-1].event_id if events else None,
            "current_repair_attempt": phase.current_repair_attempt,
            "max_repair_attempts": phase.max_repair_attempts,
        }
