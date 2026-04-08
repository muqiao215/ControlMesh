"""High-level persistence wrapper for additive team state."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ductor_bot.team.contracts import (
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_MAILBOX_MESSAGE_STATUSES,
    TEAM_TASK_STATUSES,
    TEAM_WORKER_RUNTIME_STATUSES,
)
from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamDispatchResult,
    TeamEvent,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamTask,
    TeamTaskClaim,
    TeamWorkerRuntimeState,
)
from ductor_bot.team.state.base import TeamStatePaths
from ductor_bot.team.state.dispatch import (
    create_dispatch_request,
    get_dispatch_request,
    list_dispatch_requests,
    record_dispatch_result,
    transition_dispatch_request,
)
from ductor_bot.team.state.events import append_event, read_events
from ductor_bot.team.state.mailbox import (
    create_mailbox_message,
    get_mailbox_message,
    list_mailbox_messages,
    mark_mailbox_message_delivered,
    mark_mailbox_message_notified,
)
from ductor_bot.team.state.manifest import read_manifest, write_manifest
from ductor_bot.team.state.phase import read_phase, write_phase
from ductor_bot.team.state.runtime import (
    get_worker_runtime,
    list_worker_runtimes,
    put_worker_runtime,
    reconcile_worker_runtime,
    reconcile_worker_runtimes,
    record_worker_runtime_heartbeat,
    transition_worker_runtime,
)
from ductor_bot.team.state.tasks import (
    claim_task,
    get_task,
    list_tasks,
    release_task_claim,
    update_task_status,
    upsert_task,
)


class TeamStateStore:
    """File-backed state store for additive team coordination."""

    def __init__(self, state_root: Path | str, team_name: str, *, create: bool = True) -> None:
        self.paths = TeamStatePaths(state_root=Path(state_root), team_name=team_name)
        if create:
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

    def put_worker_runtime(self, runtime: TeamWorkerRuntimeState) -> TeamWorkerRuntimeState:
        self.read_manifest().get_worker(runtime.worker)
        return put_worker_runtime(self.paths, runtime)

    def get_worker_runtime(self, worker: str) -> TeamWorkerRuntimeState:
        return get_worker_runtime(self.paths, worker)

    def list_worker_runtimes(self, *, status: str | None = None) -> list[TeamWorkerRuntimeState]:
        return list_worker_runtimes(self.paths, status=status)

    def transition_worker_runtime(
        self,
        worker: str,
        to_status: str,
        *,
        updates: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> TeamWorkerRuntimeState:
        self.read_manifest().get_worker(worker)
        return transition_worker_runtime(
            self.paths,
            worker,
            to_status,
            updates=updates,
            now=now,
        )

    def record_worker_runtime_heartbeat(
        self,
        worker: str,
        *,
        lease_id: str,
        heartbeat_at: str,
        lease_expires_at: str | None = None,
    ) -> TeamWorkerRuntimeState:
        self.read_manifest().get_worker(worker)
        return record_worker_runtime_heartbeat(
            self.paths,
            worker,
            lease_id=lease_id,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )

    def reconcile_worker_runtime(
        self,
        worker: str,
        *,
        now: datetime | None = None,
    ) -> TeamWorkerRuntimeState:
        self.read_manifest().get_worker(worker)
        return reconcile_worker_runtime(self.paths, worker, now=now)

    def reconcile_worker_runtimes(self, *, now: datetime | None = None) -> list[TeamWorkerRuntimeState]:
        self.read_manifest()
        return reconcile_worker_runtimes(self.paths, now=now)

    def claim_task(
        self,
        task_id: str,
        claim: TeamTaskClaim,
        *,
        now: datetime | None = None,
    ) -> TeamTask:
        return claim_task(self.paths, task_id, claim, now=now)

    def release_task_claim(self, task_id: str) -> TeamTask:
        return release_task_claim(self.paths, task_id)

    def create_dispatch_request(self, request: TeamDispatchRequest) -> TeamDispatchRequest:
        return create_dispatch_request(self.paths, request)

    def get_dispatch_request(self, request_id: str) -> TeamDispatchRequest:
        return get_dispatch_request(self.paths, request_id)

    def transition_dispatch_request(
        self,
        request_id: str,
        to_status: str,
        *,
        error: str | None = None,
        metadata: dict[str, str | None] | None = None,
    ) -> TeamDispatchRequest:
        return transition_dispatch_request(
            self.paths,
            request_id,
            to_status,
            error=error,
            metadata=metadata,
        )

    def list_dispatch_requests(self, *, status: str | None = None) -> list[TeamDispatchRequest]:
        return list_dispatch_requests(self.paths, status=status)

    def record_dispatch_result(self, request_id: str, result: TeamDispatchResult) -> TeamDispatchRequest:
        request = get_dispatch_request(self.paths, request_id)
        if request.status != "delivered":
            msg = f"dispatch request '{request_id}' must be delivered before recording a result"
            raise ValueError(msg)
        if result.task_status is not None:
            if request.task_id is None:
                msg = f"dispatch request '{request_id}' is not linked to a task"
                raise ValueError(msg)
            update_task_status(self.paths, request.task_id, result.task_status)
        return record_dispatch_result(self.paths, request_id, result)

    def create_mailbox_message(self, message: TeamMailboxMessage) -> TeamMailboxMessage:
        return create_mailbox_message(self.paths, message)

    def get_mailbox_message(self, message_id: str) -> TeamMailboxMessage:
        return get_mailbox_message(self.paths, message_id)

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
        runtimes = self.list_worker_runtimes()

        task_counts = dict.fromkeys(TEAM_TASK_STATUSES, 0)
        for task in tasks:
            task_counts[task.status] += 1

        dispatch_counts = dict.fromkeys(TEAM_DISPATCH_REQUEST_STATUSES, 0)
        for request in dispatch:
            dispatch_counts[request.status] += 1

        mailbox_counts = dict.fromkeys(TEAM_MAILBOX_MESSAGE_STATUSES, 0)
        for message in mailbox:
            mailbox_counts[message.status] += 1

        runtime_counts = dict.fromkeys(TEAM_WORKER_RUNTIME_STATUSES, 0)
        for runtime in runtimes:
            runtime_counts[runtime.status] += 1

        return {
            "team_name": manifest.team_name,
            "task_description": manifest.task_description,
            "phase": phase.current_phase,
            "active": phase.active,
            "workers": [worker.model_dump(mode="json") for worker in manifest.workers],
            "worker_runtimes": [worker.runtime_ref.model_dump(mode="json") for worker in manifest.workers],
            "worker_runtime_states": [runtime.model_dump(mode="json") for runtime in runtimes],
            "worker_runtime_counts": runtime_counts,
            "task_counts": task_counts,
            "dispatch_counts": dispatch_counts,
            "mailbox_counts": mailbox_counts,
            "latest_event_id": events[-1].event_id if events else None,
            "current_repair_attempt": phase.current_repair_attempt,
            "max_repair_attempts": phase.max_repair_attempts,
        }
