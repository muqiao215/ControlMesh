"""Narrow execution-evidence read surface for packet/task bounded views."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from controlmesh_runtime.events import RuntimeEvent
from controlmesh_runtime.execution_runtime_events import (
    extract_execution_payload_from_runtime_event,
)
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.review_handoff_packet import (
    ReviewHandoffPacket,
    ReviewHandoffPacketBuilder,
)
from controlmesh_runtime.serde import read_json_model
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary import SummaryRecord


class PacketExecutionEpisodeView(BaseModel):
    """Bounded packet-level execution evidence view."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    packet_id: str
    task_id: str
    event_count: int
    execution_event_types: tuple[str, ...]
    events: tuple[RuntimeEvent, ...]


class TaskExecutionReadView(BaseModel):
    """Bounded task-level aggregation over packet execution episodes."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    task_id: str
    packet_ids: tuple[str, ...]
    packet_count: int
    total_event_count: int
    latest_review: ReviewRecord | None = None
    latest_task_summary: SummaryRecord | None = None
    latest_line_summary: SummaryRecord | None = None


class ExecutionEvidenceReadSurface:
    """Read-only execution evidence access for packet and task scopes."""

    def __init__(self, root: Path | str) -> None:
        self._store = RuntimeStore(root)
        self._review_handoff = ReviewHandoffPacketBuilder(root)

    def read_packet_execution_episode(self, packet_id: str) -> PacketExecutionEpisodeView:
        events = tuple(self._store.load_execution_evidence(packet_id))
        if not events:
            msg = f"execution evidence packet '{packet_id}' not found"
            raise FileNotFoundError(msg)
        task_ids = {extract_execution_payload_from_runtime_event(event).task_id for event in events}
        if len(task_ids) != 1:
            msg = "packet execution evidence must reference exactly one task_id"
            raise ValueError(msg)
        execution_event_types = tuple(extract_execution_payload_from_runtime_event(event).execution_event_type for event in events)
        return PacketExecutionEpisodeView(
            packet_id=packet_id,
            task_id=next(iter(task_ids)),
            event_count=len(events),
            execution_event_types=execution_event_types,
            events=events,
        )

    def read_task_evidence(
        self,
        task_id: str,
        *,
        line: str | None = None,
        packet_limit: int = 20,
    ) -> TaskExecutionReadView:
        if packet_limit <= 0:
            msg = "packet_limit must be > 0"
            raise ValueError(msg)
        packet_views = self._task_packet_views(task_id, packet_limit=packet_limit)
        packet_ids = tuple(view.packet_id for view in packet_views)
        total_event_count = sum(view.event_count for view in packet_views)
        return TaskExecutionReadView(
            task_id=task_id,
            packet_ids=packet_ids,
            packet_count=len(packet_ids),
            total_event_count=total_event_count,
            latest_review=self._load_latest_review(task_id),
            latest_task_summary=self._load_summary(subject="task", entity_id=task_id),
            latest_line_summary=self._load_summary(subject="line", entity_id=line) if line else None,
        )

    def read_packet_review_handoff(self, packet_id: str) -> ReviewHandoffPacket:
        return self._review_handoff.build_for_packet(packet_id)

    def read_task_review_handoff(
        self,
        task_id: str,
        *,
        packet_limit: int = 20,
    ) -> ReviewHandoffPacket:
        return self._review_handoff.build_for_task(task_id, packet_limit=packet_limit)

    def _task_packet_views(self, task_id: str, *, packet_limit: int) -> tuple[PacketExecutionEpisodeView, ...]:
        evidence_dir = self._store.paths.execution_evidence_dir
        if not evidence_dir.exists():
            return ()
        matches: list[PacketExecutionEpisodeView] = []
        for path in sorted(evidence_dir.glob("*.jsonl"), key=lambda item: item.name):
            packet_id = path.stem
            try:
                packet_view = self.read_packet_execution_episode(packet_id)
            except FileNotFoundError:
                continue
            if packet_view.task_id != task_id:
                continue
            matches.append(packet_view)
        matches.sort(
            key=lambda view: (
                view.events[-1].created_at if view.events else "",
                view.packet_id,
            ),
            reverse=True,
        )
        return tuple(matches[:packet_limit])

    def _load_latest_review(self, task_id: str) -> ReviewRecord | None:
        try:
            return self._store.load_review_record(task_id)
        except FileNotFoundError:
            return None

    def _load_summary(self, *, subject: str, entity_id: str | None) -> SummaryRecord | None:
        if entity_id is None:
            return None
        path = self._store.paths.state_root / "summaries" / subject / f"{entity_id}.json"
        try:
            return read_json_model(path, SummaryRecord)
        except FileNotFoundError:
            try:
                return self._store.load_summary_record(f"{subject}:{entity_id}")
            except FileNotFoundError:
                return None


__all__ = [
    "ExecutionEvidenceReadSurface",
    "PacketExecutionEpisodeView",
    "TaskExecutionReadView",
]
