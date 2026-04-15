"""Read-only admin catalog models backed by the derived history index."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from controlmesh.history.index import (
    HistoryIndex,
    IndexedRuntimeEvent,
    IndexedTaskCatalogRow,
    IndexedTranscriptTurn,
)
from controlmesh.workspace.paths import ControlMeshPaths

DEFAULT_CATALOG_LIMIT = 50
MAX_CATALOG_LIMIT = 100


@dataclass
class _SessionSummary:
    session_key: str
    transport: str
    chat_id: int
    topic_id: int | None
    transcript_count: int = 0
    runtime_count: int = 0
    transcript_last_seen: str = ""
    runtime_last_seen: str = ""

    @property
    def last_seen(self) -> str:
        return max(self.transcript_last_seen, self.runtime_last_seen)


@dataclass
class _TeamSummary:
    team_name: str
    entity_counts: Counter[str]
    status_counts: Counter[str]
    owner_ids: set[str]
    worker_ids: set[str]
    last_seen: str = ""


class AdminHistoryCatalogReader:
    """Compact read model for derived admin catalog HTTP endpoints."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._index = HistoryIndex(paths)

    def sessions(self, *, limit: int = DEFAULT_CATALOG_LIMIT) -> dict[str, Any]:
        """Return bounded session summaries with transcript/runtime kept distinct."""
        self._index.sync()
        summaries: dict[str, _SessionSummary] = {}
        for transcript_row in self._index.list_transcript_turns():
            summary = _session_summary_for_turn(summaries, transcript_row)
            summary.transcript_count += 1
            summary.transcript_last_seen = max(
                summary.transcript_last_seen,
                transcript_row.created_at,
            )

        for runtime_row in self._index.list_runtime_events():
            summary = _session_summary_for_event(summaries, runtime_row)
            summary.runtime_count += 1
            summary.runtime_last_seen = max(summary.runtime_last_seen, runtime_row.created_at)

        items = sorted(summaries.values(), key=lambda item: (item.last_seen, item.session_key), reverse=True)
        return {
            "items": [_session_summary_json(item) for item in items[:limit]],
            "limit": limit,
            "total": len(items),
        }

    def tasks(self, *, limit: int = DEFAULT_CATALOG_LIMIT) -> dict[str, Any]:
        """Return bounded task catalog rows from the derived index."""
        self._index.sync()
        rows = sorted(
            self._index.list_task_catalog_rows(),
            key=lambda row: (row.completed_at or row.created_at, row.created_at, row.task_id),
            reverse=True,
        )
        return {
            "items": [_task_row_json(row) for row in rows[:limit]],
            "limit": limit,
            "total": len(rows),
        }

    def teams(self, *, limit: int = DEFAULT_CATALOG_LIMIT) -> dict[str, Any]:
        """Return bounded team summaries with team-state entity kinds kept distinct."""
        self._index.sync()
        summaries: dict[str, _TeamSummary] = {}
        for row in self._index.list_team_entities():
            summary = summaries.setdefault(
                row.team_name,
                _TeamSummary(
                    team_name=row.team_name,
                    entity_counts=Counter(),
                    status_counts=Counter(),
                    owner_ids=set(),
                    worker_ids=set(),
                ),
            )
            summary.entity_counts[row.entity_kind] += 1
            if row.status:
                summary.status_counts[row.status] += 1
            if row.owner:
                summary.owner_ids.add(row.owner)
            if row.worker:
                summary.worker_ids.add(row.worker)
            summary.last_seen = max(summary.last_seen, row.updated_at or row.created_at or "")

        items = sorted(summaries.values(), key=lambda item: (item.last_seen, item.team_name), reverse=True)
        return {
            "items": [_team_summary_json(item) for item in items[:limit]],
            "limit": limit,
            "total": len(items),
        }


def parse_catalog_limit(raw_limit: str | None) -> int:
    """Parse and bound a catalog endpoint limit query parameter."""
    if raw_limit is None or raw_limit == "":
        return DEFAULT_CATALOG_LIMIT
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("invalid catalog limit") from exc
    if limit < 1:
        raise ValueError("invalid catalog limit")
    return min(limit, MAX_CATALOG_LIMIT)


def _session_summary_for_turn(
    summaries: dict[str, _SessionSummary],
    row: IndexedTranscriptTurn,
) -> _SessionSummary:
    return summaries.setdefault(
        row.session_key,
        _SessionSummary(
            session_key=row.session_key,
            transport=row.transport,
            chat_id=row.chat_id,
            topic_id=row.topic_id,
        ),
    )


def _session_summary_for_event(
    summaries: dict[str, _SessionSummary],
    row: IndexedRuntimeEvent,
) -> _SessionSummary:
    return summaries.setdefault(
        row.session_key,
        _SessionSummary(
            session_key=row.session_key,
            transport=row.transport,
            chat_id=row.chat_id,
            topic_id=row.topic_id,
        ),
    )


def _session_summary_json(summary: _SessionSummary) -> dict[str, Any]:
    return {
        "session_key": summary.session_key,
        "transport": summary.transport,
        "chat_id": summary.chat_id,
        "topic_id": summary.topic_id,
        "transcript": {
            "count": summary.transcript_count,
            "last_seen": summary.transcript_last_seen,
        },
        "runtime": {
            "count": summary.runtime_count,
            "last_seen": summary.runtime_last_seen,
        },
        "last_seen": summary.last_seen,
    }


def _task_row_json(row: IndexedTaskCatalogRow) -> dict[str, Any]:
    return {
        "task_id": row.task_id,
        "source_kind": row.source_kind,
        "chat_id": row.chat_id,
        "thread_id": row.thread_id,
        "parent_agent": row.parent_agent,
        "name": row.name,
        "provider": row.provider,
        "model": row.model,
        "status": row.status,
        "session_id": row.session_id,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
        "elapsed_seconds": row.elapsed_seconds,
        "result_preview": row.result_preview,
        "last_question": row.last_question,
        "prompt_preview": row.prompt_preview,
    }


def _team_summary_json(summary: _TeamSummary) -> dict[str, Any]:
    return {
        "team_name": summary.team_name,
        "source_kind": "team_state",
        "entity_counts": dict(sorted(summary.entity_counts.items())),
        "status_counts": dict(sorted(summary.status_counts.items())),
        "owner_ids": sorted(summary.owner_ids),
        "worker_ids": sorted(summary.worker_ids),
        "last_seen": summary.last_seen,
    }
