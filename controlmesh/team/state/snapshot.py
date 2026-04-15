"""Derived compact control-plane snapshots for team state."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.contracts import (
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_MAILBOX_MESSAGE_STATUSES,
    TEAM_TASK_STATUSES,
    TEAM_WORKER_RUNTIME_STATUSES,
    TERMINAL_TEAM_TASK_STATUSES,
)
from controlmesh.team.state import TeamStateStore
from controlmesh.team.state.base import utc_now
from controlmesh.workspace.paths import ControlMeshPaths

TEAM_CONTROL_SNAPSHOT_SCHEMA_VERSION = 1


class _StatusLike(Protocol):
    status: str


class TeamControlSnapshotManifestSummary(BaseModel):
    task_description: str
    leader_agent_name: str
    leader_session_key: str
    worker_count: int
    worker_ids: list[str]


class TeamControlSnapshotPhaseSummary(BaseModel):
    current_phase: str
    active: bool
    current_repair_attempt: int
    max_repair_attempts: int


class TeamControlSnapshotTaskSummary(BaseModel):
    counts: dict[str, int]
    active_task_ids: list[str]


class TeamControlSnapshotRuntimeSummary(BaseModel):
    counts: dict[str, int]
    busy_workers: list[str]
    lost_workers: list[str]


class TeamControlSnapshotDispatchSummary(BaseModel):
    counts: dict[str, int]
    active_request_ids: list[str]
    pending_request_ids: list[str]


class TeamControlSnapshotMailboxSummary(BaseModel):
    counts: dict[str, int]
    pending_message_ids: list[str]


class TeamControlSnapshot(BaseModel):
    schema_version: int = TEAM_CONTROL_SNAPSHOT_SCHEMA_VERSION
    generated_at: str
    team_name: str
    manifest: TeamControlSnapshotManifestSummary
    phase: TeamControlSnapshotPhaseSummary
    tasks: TeamControlSnapshotTaskSummary
    runtimes: TeamControlSnapshotRuntimeSummary
    dispatch: TeamControlSnapshotDispatchSummary
    mailbox: TeamControlSnapshotMailboxSummary
    latest_event_id: str | None = None


class TeamControlSnapshotReadStatus(BaseModel):
    snapshot: TeamControlSnapshot
    stale: bool


class TeamControlSnapshotManager:
    """Build and persist compact derived snapshots from canonical team state files."""

    def __init__(self, paths: ControlMeshPaths, *, state_root: Path | str | None = None) -> None:
        self._paths = paths
        self._state_root = Path(state_root) if state_root is not None else paths.team_state_dir

    def path_for(self, team_name: str) -> Path:
        return self._paths.team_control_snapshots_dir / f"{team_name}.json"

    def build(
        self,
        team_name: str,
        *,
        generated_at: str | None = None,
    ) -> TeamControlSnapshot:
        store = TeamStateStore(self._state_root, team_name, create=False)
        manifest = store.read_manifest()
        phase = store.read_phase()
        tasks = store.list_tasks()
        runtimes = store.list_worker_runtimes()
        dispatch = store.list_dispatch_requests()
        mailbox = store.list_mailbox_messages()
        events = store.read_events()

        return TeamControlSnapshot(
            generated_at=generated_at or utc_now(),
            team_name=manifest.team_name,
            manifest=TeamControlSnapshotManifestSummary(
                task_description=manifest.task_description,
                leader_agent_name=manifest.leader.agent_name,
                leader_session_key=manifest.leader.session.storage_key,
                worker_count=len(manifest.workers),
                worker_ids=sorted(worker.name for worker in manifest.workers),
            ),
            phase=TeamControlSnapshotPhaseSummary(
                current_phase=phase.current_phase,
                active=phase.active,
                current_repair_attempt=phase.current_repair_attempt,
                max_repair_attempts=phase.max_repair_attempts,
            ),
            tasks=TeamControlSnapshotTaskSummary(
                counts=_count_by_status(tasks, TEAM_TASK_STATUSES),
                active_task_ids=sorted(task.task_id for task in tasks if task.status not in TERMINAL_TEAM_TASK_STATUSES),
            ),
            runtimes=TeamControlSnapshotRuntimeSummary(
                counts=_count_by_status(runtimes, TEAM_WORKER_RUNTIME_STATUSES),
                busy_workers=sorted(runtime.worker for runtime in runtimes if runtime.status == "busy"),
                lost_workers=sorted(runtime.worker for runtime in runtimes if runtime.status == "lost"),
            ),
            dispatch=TeamControlSnapshotDispatchSummary(
                counts=_count_by_status(dispatch, TEAM_DISPATCH_REQUEST_STATUSES),
                active_request_ids=sorted(
                    request.request_id
                    for request in dispatch
                    if request.status in {"pending", "notified", "delivered"}
                ),
                pending_request_ids=sorted(
                    request.request_id for request in dispatch if request.status == "pending"
                ),
            ),
            mailbox=TeamControlSnapshotMailboxSummary(
                counts=_count_by_status(mailbox, TEAM_MAILBOX_MESSAGE_STATUSES),
                pending_message_ids=sorted(message.message_id for message in mailbox if message.status == "pending"),
            ),
            latest_event_id=events[-1].event_id if events else None,
        )

    def write(
        self,
        team_name: str,
        *,
        generated_at: str | None = None,
    ) -> TeamControlSnapshot:
        snapshot = self.build(team_name, generated_at=generated_at)
        path = self.path_for(team_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_save(path, snapshot.model_dump(mode="json"))
        return snapshot

    def read(self, team_name: str) -> TeamControlSnapshot:
        raw = load_json(self.path_for(team_name))
        if raw is None:
            msg = f"team control snapshot not found for '{team_name}'"
            raise FileNotFoundError(msg)
        return TeamControlSnapshot.model_validate(raw)

    def read_status(
        self,
        team_name: str,
        *,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> TeamControlSnapshotReadStatus:
        snapshot = self.read(team_name)
        checked_at = _resolve_status_check_time(now)
        generated_at = _parse_timezone_aware_iso8601(
            snapshot.generated_at,
            field_name="generated_at",
        )
        return TeamControlSnapshotReadStatus(
            snapshot=snapshot,
            stale=(checked_at - generated_at).total_seconds() > _validate_max_age_seconds(max_age_seconds),
        )


def _count_by_status(items: Iterable[_StatusLike], statuses: tuple[str, ...]) -> dict[str, int]:
    counts = dict.fromkeys(statuses, 0)
    for item in items:
        counts[item.status] += 1
    return counts


def _validate_max_age_seconds(max_age_seconds: int) -> int:
    if max_age_seconds < 0:
        msg = "max_age_seconds must be a non-negative integer"
        raise ValueError(msg)
    return max_age_seconds


def _resolve_status_check_time(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        msg = "now must be timezone-aware when provided"
        raise ValueError(msg)
    return now.astimezone(UTC)


def _parse_timezone_aware_iso8601(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"{field_name} must be a timezone-aware ISO-8601 timestamp"
        raise ValueError(msg) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        msg = f"{field_name} must be a timezone-aware ISO-8601 timestamp"
        raise ValueError(msg)
    return parsed.astimezone(UTC)
