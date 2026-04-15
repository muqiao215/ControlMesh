"""Read-only review/handoff packet built from bounded execution evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from controlmesh_runtime.evidence_identity import EvidenceSubject, RuntimeEvidenceIdentity
from controlmesh_runtime.execution_evidence_replay_query import (
    ExecutionEvidenceReplayQuerySurface,
    ExecutionReplayValidation,
)
from controlmesh_runtime.records import ReviewRecord
from controlmesh_runtime.recovery import RecoveryExecutionStatus
from controlmesh_runtime.store import RuntimeStore
from controlmesh_runtime.summary import SummaryRecord

ReviewHandoffScope = Literal["packet", "task"]


class ReviewHandoffPacket(BaseModel):
    """Typed evidence packet for review or handoff preparation."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    scope: ReviewHandoffScope
    task_id: str
    line: str | None
    packet_ids: tuple[str, ...]
    primary_identity: RuntimeEvidenceIdentity | None
    episode_identities: tuple[RuntimeEvidenceIdentity, ...]
    event_count: int
    terminal_episode_count: int
    terminal_result_statuses: tuple[RecoveryExecutionStatus, ...]
    replay_valid: bool
    replay_anomalies: tuple[str, ...] = ()
    latest_review: ReviewRecord | None = None
    latest_task_summary: SummaryRecord | None = None
    latest_line_summary: SummaryRecord | None = None
    source_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_packet(self) -> ReviewHandoffPacket:
        self._validate_required_fields()
        self._validate_identity_alignment()
        self._validate_scope_shape()
        self._validate_terminal_shape()
        return self

    def _validate_required_fields(self) -> None:
        if not self.task_id.strip():
            msg = "review handoff packet task_id must not be empty"
            raise ValueError(msg)
        if self.line is not None and not self.line.strip():
            msg = "review handoff packet line must not be blank when provided"
            raise ValueError(msg)
        if not self.packet_ids:
            msg = "review handoff packet packet_ids must not be empty"
            raise ValueError(msg)
        if not self.episode_identities:
            msg = "review handoff packet episode_identities must not be empty"
            raise ValueError(msg)
        if not self.source_refs:
            msg = "review handoff packet source_refs must not be empty"
            raise ValueError(msg)

    def _validate_identity_alignment(self) -> None:
        if self.primary_identity is not None and self.primary_identity.task_id != self.task_id:
            msg = "review handoff packet primary identity task_id must match packet task_id"
            raise ValueError(msg)
        if self.primary_identity is not None and self.primary_identity.packet_id not in self.packet_ids:
            msg = "review handoff packet primary identity packet_id must be present in packet_ids"
            raise ValueError(msg)
        if any(identity.task_id != self.task_id for identity in self.episode_identities):
            msg = "review handoff packet episode identities must match packet task_id"
            raise ValueError(msg)
        episode_packet_ids = tuple(identity.packet_id for identity in self.episode_identities)
        if episode_packet_ids != self.packet_ids:
            msg = "review handoff packet episode identities must align with packet_ids"
            raise ValueError(msg)

    def _validate_scope_shape(self) -> None:
        if self.scope == "packet" and len(self.packet_ids) != 1:
            msg = "packet-scoped review handoff packets must contain exactly one packet_id"
            raise ValueError(msg)
        if self.scope == "packet" and len(self.episode_identities) != 1:
            msg = "packet-scoped review handoff packets must contain exactly one episode identity"
            raise ValueError(msg)

    def _validate_terminal_shape(self) -> None:
        if self.terminal_episode_count < 0 or self.terminal_episode_count > len(self.packet_ids):
            msg = "review handoff packet terminal_episode_count must be between 0 and packet count"
            raise ValueError(msg)
        if len(self.terminal_result_statuses) != self.terminal_episode_count:
            msg = "review handoff packet terminal result statuses must match terminal_episode_count"
            raise ValueError(msg)


class ReviewHandoffPacketBuilder:
    """Build review/handoff packets without owning review decisions or promotion."""

    def __init__(self, root: Path | str) -> None:
        self._store = RuntimeStore(root)
        self._replay_query = ExecutionEvidenceReplayQuerySurface(root)

    def build_for_packet(self, packet_id: str) -> ReviewHandoffPacket:
        episode = self._replay_query.query_packet_episode(packet_id)
        validation = self._replay_query.validate_packet_replay(packet_id)
        return ReviewHandoffPacket(
            scope="packet",
            task_id=episode.identity.task_id,
            line=episode.identity.line,
            packet_ids=(packet_id,),
            primary_identity=episode.identity,
            episode_identities=(episode.identity,),
            event_count=episode.event_count,
            terminal_episode_count=1 if episode.terminal_result_status is not None else 0,
            terminal_result_statuses=_terminal_statuses((episode.terminal_result_status,)),
            replay_valid=validation.valid,
            replay_anomalies=validation.anomalies,
            latest_review=self._load_review(episode.identity.task_id),
            latest_task_summary=self._load_summary(episode.identity, EvidenceSubject.TASK),
            latest_line_summary=self._load_summary(episode.identity, EvidenceSubject.LINE),
            source_refs=_source_refs_for_validation(validation),
        )

    def build_for_task(
        self,
        task_id: str,
        *,
        packet_limit: int = 20,
    ) -> ReviewHandoffPacket:
        task_view = self._replay_query.query_task_episodes(task_id, packet_limit=packet_limit)
        if not task_view.episodes:
            msg = f"execution evidence task '{task_id}' not found"
            raise FileNotFoundError(msg)
        validations = tuple(
            self._replay_query.validate_packet_replay(identity.packet_id)
            for identity in task_view.episode_identities
        )
        identities = task_view.episode_identities
        lines = {identity.line for identity in identities}
        line = next(iter(lines)) if len(lines) == 1 else None
        primary_identity = identities[0]
        return ReviewHandoffPacket(
            scope="task",
            task_id=task_id,
            line=line,
            packet_ids=tuple(identity.packet_id for identity in identities),
            primary_identity=primary_identity,
            episode_identities=identities,
            event_count=task_view.total_event_count,
            terminal_episode_count=task_view.terminal_episode_count,
            terminal_result_statuses=_terminal_statuses(
                tuple(episode.terminal_result_status for episode in task_view.episodes)
            ),
            replay_valid=all(validation.valid for validation in validations),
            replay_anomalies=tuple(
                anomaly
                for validation in validations
                for anomaly in validation.anomalies
            ),
            latest_review=self._load_review(task_id),
            latest_task_summary=self._load_summary(primary_identity, EvidenceSubject.TASK),
            latest_line_summary=self._load_summary(primary_identity, EvidenceSubject.LINE) if line else None,
            source_refs=tuple(
                source_ref
                for validation in validations
                for source_ref in _source_refs_for_validation(validation)
            ),
        )

    def _load_review(self, task_id: str) -> ReviewRecord | None:
        try:
            return self._store.load_review_record(task_id)
        except FileNotFoundError:
            return None

    def _load_summary(
        self,
        identity: RuntimeEvidenceIdentity,
        subject: EvidenceSubject,
    ) -> SummaryRecord | None:
        try:
            return self._store.load_summary_record(identity.entity_id_for(subject))
        except FileNotFoundError:
            return None


def _source_refs_for_validation(validation: ExecutionReplayValidation) -> tuple[str, ...]:
    return (f"execution_evidence:{validation.identity.packet_id}",)


def _terminal_statuses(
    statuses: tuple[RecoveryExecutionStatus | None, ...],
) -> tuple[RecoveryExecutionStatus, ...]:
    return tuple(status for status in statuses if status is not None)


__all__ = ["ReviewHandoffPacket", "ReviewHandoffPacketBuilder", "ReviewHandoffScope"]
