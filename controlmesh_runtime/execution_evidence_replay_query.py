"""Bounded replay/query surface over archived execution evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from controlmesh_runtime.events import FailureClass, RuntimeEvent
from controlmesh_runtime.evidence_identity import RuntimeEvidenceIdentity
from controlmesh_runtime.execution_runtime_events import (
    extract_execution_payload_from_runtime_event,
)
from controlmesh_runtime.recovery import RecoveryExecutionStatus
from controlmesh_runtime.store import RuntimeStore


class ExecutionEpisodeQueryView(BaseModel):
    """One bounded execution episode view keyed by typed runtime identity."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    identity: RuntimeEvidenceIdentity
    worker_id: str | None
    event_count: int
    execution_event_types: tuple[str, ...]
    terminal_result_status: RecoveryExecutionStatus | None = None
    terminal_failure_class: FailureClass | None = None
    events: tuple[RuntimeEvent, ...]


class ExecutionReplayValidation(BaseModel):
    """Replay validation result over one archived execution episode."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    identity: RuntimeEvidenceIdentity
    valid: bool
    event_count: int
    anomalies: tuple[str, ...] = ()
    terminal_result_status: RecoveryExecutionStatus | None = None


class TaskExecutionReplayQueryView(BaseModel):
    """Bounded task-level replay/query aggregation over execution episodes."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    task_id: str
    episode_identities: tuple[RuntimeEvidenceIdentity, ...]
    episode_count: int
    total_event_count: int
    terminal_episode_count: int
    episodes: tuple[ExecutionEpisodeQueryView, ...]


class ExecutionEvidenceReplayQuerySurface:
    """Read-only replay/query surface for packet and bounded task scopes."""

    def __init__(self, root: Path | str) -> None:
        self._store = RuntimeStore(root)

    def query_packet_episode(self, packet_id: str) -> ExecutionEpisodeQueryView:
        events = tuple(self._store.load_execution_evidence(packet_id))
        if not events:
            msg = f"execution evidence packet '{packet_id}' not found"
            raise FileNotFoundError(msg)
        return _build_episode_view(events)

    def validate_packet_replay(self, packet_id: str) -> ExecutionReplayValidation:
        episode = self.query_packet_episode(packet_id)
        anomalies = _validate_episode(episode)
        return ExecutionReplayValidation(
            identity=episode.identity,
            valid=not anomalies,
            event_count=episode.event_count,
            anomalies=anomalies,
            terminal_result_status=episode.terminal_result_status,
        )

    def query_task_episodes(
        self,
        task_id: str,
        *,
        packet_limit: int = 20,
    ) -> TaskExecutionReplayQueryView:
        if packet_limit <= 0:
            msg = "packet_limit must be > 0"
            raise ValueError(msg)
        evidence_dir = self._store.paths.execution_evidence_dir
        if not evidence_dir.exists():
            return TaskExecutionReplayQueryView(
                task_id=task_id,
                episode_identities=(),
                episode_count=0,
                total_event_count=0,
                terminal_episode_count=0,
                episodes=(),
            )
        episodes: list[ExecutionEpisodeQueryView] = []
        for path in sorted(evidence_dir.glob("*.jsonl"), key=lambda item: item.name):
            episode = self.query_packet_episode(path.stem)
            if episode.identity.task_id != task_id:
                continue
            episodes.append(episode)
        episodes.sort(
            key=lambda episode: (
                episode.events[-1].created_at if episode.events else "",
                episode.identity.packet_id,
            ),
            reverse=True,
        )
        episodes = episodes[:packet_limit]
        return TaskExecutionReplayQueryView(
            task_id=task_id,
            episode_identities=tuple(episode.identity for episode in episodes),
            episode_count=len(episodes),
            total_event_count=sum(episode.event_count for episode in episodes),
            terminal_episode_count=sum(1 for episode in episodes if episode.terminal_result_status is not None),
            episodes=tuple(episodes),
        )


def _build_episode_view(events: tuple[RuntimeEvent, ...]) -> ExecutionEpisodeQueryView:
    identities = { _identity_from_event(event) for event in events }
    if len(identities) != 1:
        msg = "packet execution evidence must reference exactly one runtime evidence identity"
        raise ValueError(msg)
    identity = next(iter(identities))
    worker_ids = {event.worker_id for event in events}
    if len(worker_ids) > 1:
        msg = "packet execution evidence must reference at most one worker_id"
        raise ValueError(msg)
    payloads = tuple(extract_execution_payload_from_runtime_event(event) for event in events)
    terminal_payloads = tuple(
        payload for payload in payloads if payload.execution_event_type == "execution.result_recorded"
    )
    terminal_result_status = terminal_payloads[-1].result_status if terminal_payloads else None
    terminal_failure_class = terminal_payloads[-1].failure_class if terminal_payloads else None
    return ExecutionEpisodeQueryView(
        identity=identity,
        worker_id=next(iter(worker_ids)),
        event_count=len(events),
        execution_event_types=tuple(payload.execution_event_type for payload in payloads),
        terminal_result_status=terminal_result_status,
        terminal_failure_class=terminal_failure_class,
        events=events,
    )


def _identity_from_event(event: RuntimeEvent) -> RuntimeEvidenceIdentity:
    payload = extract_execution_payload_from_runtime_event(event)
    return RuntimeEvidenceIdentity(
        packet_id=event.packet_id,
        task_id=payload.task_id,
        line=payload.line,
        plan_id=payload.plan_id,
    )


def _validate_episode(episode: ExecutionEpisodeQueryView) -> tuple[str, ...]:
    anomalies: list[str] = []
    event_types = episode.execution_event_types
    if not event_types:
        anomalies.append("missing_execution_events")
    if "execution.plan_created" not in event_types:
        anomalies.append("missing_plan_created")
    result_count = sum(1 for item in event_types if item == "execution.result_recorded")
    if result_count == 0:
        anomalies.append("missing_terminal_result")
    elif result_count > 1:
        anomalies.append("multiple_terminal_results")
    if event_types and event_types[-1] != "execution.result_recorded":
        anomalies.append("terminal_result_not_last")
    return tuple(anomalies)


__all__ = [
    "ExecutionEpisodeQueryView",
    "ExecutionEvidenceReplayQuerySurface",
    "ExecutionReplayValidation",
    "TaskExecutionReplayQueryView",
]
