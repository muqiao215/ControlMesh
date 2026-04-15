"""Derived SQLite index for transcript, runtime, task, and team-state sources."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from controlmesh.history.models import TranscriptAttachment, TranscriptTurn
from controlmesh.runtime.models import RuntimeEvent
from controlmesh.tasks.models import TaskEntry
from controlmesh.team.models import (
    TeamDispatchRequest,
    TeamEvent,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamTask,
    TeamWorkerRuntimeState,
)
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)

SourceKind = Literal["runtime", "task_registry", "team_state", "transcript"]
TeamEntityKind = Literal[
    "dispatch_request",
    "event",
    "mailbox_message",
    "manifest",
    "phase",
    "task",
    "worker_runtime",
]

_TEAM_STATE_FILENAMES = frozenset(
    {
        "dispatch.json",
        "events.json",
        "mailbox.json",
        "manifest.json",
        "phase.json",
        "tasks.json",
        "worker-runtimes.json",
    }
)
_TEAM_ENTITY_KINDS = frozenset(
    {
        "dispatch_request",
        "event",
        "mailbox_message",
        "manifest",
        "phase",
        "task",
        "worker_runtime",
    }
)


@dataclass(frozen=True)
class HistoryIndexedSource:
    """One indexed source file tracked by the derived history catalog."""

    source_key: str
    source_kind: SourceKind
    source_path: str
    content_hash: str
    row_count: int


@dataclass(frozen=True)
class IndexedTranscriptTurn:
    """One transcript turn materialized into the derived index."""

    turn_id: str
    source_key: str
    source_kind: SourceKind
    source_path: str
    line_no: int
    session_key: str
    surface_session_id: str
    transport: str
    chat_id: int
    topic_id: int | None
    role: str
    created_at: str
    visible_content: str
    reply_to_turn_id: str | None
    turn_source: str
    attachments_json: str


@dataclass(frozen=True)
class IndexedRuntimeEvent:
    """One runtime event materialized into the derived index."""

    event_id: str
    source_key: str
    source_kind: SourceKind
    source_path: str
    line_no: int
    session_key: str
    transport: str
    chat_id: int
    topic_id: int | None
    event_type: str
    created_at: str
    payload_json: str


@dataclass(frozen=True)
class IndexedTaskCatalogRow:
    """One task-registry row materialized into the derived index."""

    task_key: str
    task_id: str
    source_key: str
    source_kind: SourceKind
    source_path: str
    line_no: int
    chat_id: int
    parent_agent: str
    name: str
    provider: str
    model: str
    status: str
    session_id: str
    created_at: float
    completed_at: float
    elapsed_seconds: float
    result_preview: str
    last_question: str
    prompt_preview: str
    thread_id: int | None


@dataclass(frozen=True)
class IndexedTeamEntity:
    """One team-state entity materialized into the derived index."""

    entity_key: str
    entity_kind: TeamEntityKind
    entity_id: str
    source_key: str
    source_kind: SourceKind
    source_path: str
    line_no: int
    team_name: str
    status: str | None
    owner: str | None
    worker: str | None
    created_at: str | None
    updated_at: str | None
    payload_json: str


@dataclass(frozen=True)
class HistoryIndexSnapshot:
    """Stable snapshot of the derived catalog for rebuild/equivalence tests."""

    sources: tuple[HistoryIndexedSource, ...]
    transcript_turns: tuple[IndexedTranscriptTurn, ...]
    runtime_events: tuple[IndexedRuntimeEvent, ...]
    task_catalog_rows: tuple[IndexedTaskCatalogRow, ...]
    team_entities: tuple[IndexedTeamEntity, ...]


@dataclass(frozen=True)
class HistoryIndexSyncResult:
    """Summary counters for one sync or rebuild run."""

    indexed_sources: int
    transcript_rows: int
    runtime_rows: int
    task_rows: int
    team_entity_rows: int
    inserted_sources: int
    updated_sources: int
    deleted_sources: int
    unchanged_sources: int


@dataclass(frozen=True)
class _IndexedTranscriptRow:
    line_no: int
    turn: TranscriptTurn


@dataclass(frozen=True)
class _IndexedRuntimeRow:
    line_no: int
    event: RuntimeEvent


@dataclass(frozen=True)
class _IndexedTaskRow:
    line_no: int
    entry: TaskEntry


@dataclass(frozen=True)
class _IndexedTeamRow:
    line_no: int
    entity_kind: TeamEntityKind
    entity_id: str
    team_name: str
    status: str | None
    owner: str | None
    worker: str | None
    created_at: str | None
    updated_at: str | None
    payload_json: str


@dataclass(frozen=True)
class _IndexedSourceDocument:
    source_key: str
    source_kind: SourceKind
    source_path: str
    content_hash: str
    transcript_rows: tuple[_IndexedTranscriptRow, ...] = ()
    runtime_rows: tuple[_IndexedRuntimeRow, ...] = ()
    task_rows: tuple[_IndexedTaskRow, ...] = ()
    team_rows: tuple[_IndexedTeamRow, ...] = ()

    @property
    def row_count(self) -> int:
        return (
            len(self.transcript_rows)
            + len(self.runtime_rows)
            + len(self.task_rows)
            + len(self.team_rows)
        )


class HistoryIndex:
    """Rebuildable SQLite catalog for transcript, runtime, task, and team-state files."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths
        self._sync_lock = threading.Lock()

    def sync(self) -> HistoryIndexSyncResult:
        """Synchronize the derived index with canonical source files."""
        with self._sync_lock:
            return self._sync(force_reindex=False)

    def rebuild(self) -> HistoryIndexSyncResult:
        """Drop derived rows and rebuild the catalog from canonical files."""
        with self._sync_lock:
            return self._sync(force_reindex=True)

    def list_sources(self) -> list[HistoryIndexedSource]:
        """Return indexed source files tracked by the derived catalog."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_key, source_kind, source_path, content_hash, row_count
                FROM history_sources
                ORDER BY source_kind ASC, source_path ASC
                """
            ).fetchall()
        return [
            HistoryIndexedSource(
                source_key=str(row["source_key"]),
                source_kind=_coerce_source_kind(str(row["source_kind"])),
                source_path=str(row["source_path"]),
                content_hash=str(row["content_hash"]),
                row_count=int(row["row_count"]),
            )
            for row in rows
        ]

    def list_transcript_turns(
        self,
        *,
        session_key: str | None = None,
    ) -> list[IndexedTranscriptTurn]:
        """Return indexed transcript turns, optionally filtered to one session."""
        query = """
            SELECT
                turns.turn_id,
                turns.source_key,
                sources.source_kind,
                sources.source_path,
                turns.line_no,
                turns.session_key,
                turns.surface_session_id,
                turns.transport,
                turns.chat_id,
                turns.topic_id,
                turns.role,
                turns.created_at,
                turns.visible_content,
                turns.reply_to_turn_id,
                turns.turn_source,
                turns.attachments_json
            FROM transcript_turns AS turns
            JOIN history_sources AS sources ON sources.source_key = turns.source_key
        """
        params: tuple[str, ...] | tuple[()] = ()
        if session_key is not None:
            query += " WHERE turns.session_key = ?"
            params = (session_key,)
        query += " ORDER BY sources.source_path ASC, turns.line_no ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            IndexedTranscriptTurn(
                turn_id=str(row["turn_id"]),
                source_key=str(row["source_key"]),
                source_kind=_coerce_source_kind(str(row["source_kind"])),
                source_path=str(row["source_path"]),
                line_no=int(row["line_no"]),
                session_key=str(row["session_key"]),
                surface_session_id=str(row["surface_session_id"]),
                transport=str(row["transport"]),
                chat_id=int(row["chat_id"]),
                topic_id=int(row["topic_id"]) if row["topic_id"] is not None else None,
                role=str(row["role"]),
                created_at=str(row["created_at"]),
                visible_content=str(row["visible_content"]),
                reply_to_turn_id=(
                    str(row["reply_to_turn_id"]) if row["reply_to_turn_id"] is not None else None
                ),
                turn_source=str(row["turn_source"]),
                attachments_json=str(row["attachments_json"]),
            )
            for row in rows
        ]

    def list_runtime_events(
        self,
        *,
        session_key: str | None = None,
    ) -> list[IndexedRuntimeEvent]:
        """Return indexed runtime events, optionally filtered to one session."""
        query = """
            SELECT
                events.event_id,
                events.source_key,
                sources.source_kind,
                sources.source_path,
                events.line_no,
                events.session_key,
                events.transport,
                events.chat_id,
                events.topic_id,
                events.event_type,
                events.created_at,
                events.payload_json
            FROM runtime_events AS events
            JOIN history_sources AS sources ON sources.source_key = events.source_key
        """
        params: tuple[str, ...] | tuple[()] = ()
        if session_key is not None:
            query += " WHERE events.session_key = ?"
            params = (session_key,)
        query += " ORDER BY sources.source_path ASC, events.line_no ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            IndexedRuntimeEvent(
                event_id=str(row["event_id"]),
                source_key=str(row["source_key"]),
                source_kind=_coerce_source_kind(str(row["source_kind"])),
                source_path=str(row["source_path"]),
                line_no=int(row["line_no"]),
                session_key=str(row["session_key"]),
                transport=str(row["transport"]),
                chat_id=int(row["chat_id"]),
                topic_id=int(row["topic_id"]) if row["topic_id"] is not None else None,
                event_type=str(row["event_type"]),
                created_at=str(row["created_at"]),
                payload_json=str(row["payload_json"]),
            )
            for row in rows
        ]

    def list_task_catalog_rows(self) -> list[IndexedTaskCatalogRow]:
        """Return indexed task-registry rows."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    tasks.task_key,
                    tasks.task_id,
                    tasks.source_key,
                    sources.source_kind,
                    sources.source_path,
                    tasks.line_no,
                    tasks.chat_id,
                    tasks.parent_agent,
                    tasks.name,
                    tasks.provider,
                    tasks.model,
                    tasks.status,
                    tasks.session_id,
                    tasks.created_at,
                    tasks.completed_at,
                    tasks.elapsed_seconds,
                    tasks.result_preview,
                    tasks.last_question,
                    tasks.prompt_preview,
                    tasks.thread_id
                FROM task_catalog AS tasks
                JOIN history_sources AS sources ON sources.source_key = tasks.source_key
                ORDER BY sources.source_path ASC, tasks.line_no ASC
                """
            ).fetchall()
        return [
            IndexedTaskCatalogRow(
                task_key=str(row["task_key"]),
                task_id=str(row["task_id"]),
                source_key=str(row["source_key"]),
                source_kind=_coerce_source_kind(str(row["source_kind"])),
                source_path=str(row["source_path"]),
                line_no=int(row["line_no"]),
                chat_id=int(row["chat_id"]),
                parent_agent=str(row["parent_agent"]),
                name=str(row["name"]),
                provider=str(row["provider"]),
                model=str(row["model"]),
                status=str(row["status"]),
                session_id=str(row["session_id"]),
                created_at=float(row["created_at"]),
                completed_at=float(row["completed_at"]),
                elapsed_seconds=float(row["elapsed_seconds"]),
                result_preview=str(row["result_preview"]),
                last_question=str(row["last_question"]),
                prompt_preview=str(row["prompt_preview"]),
                thread_id=int(row["thread_id"]) if row["thread_id"] is not None else None,
            )
            for row in rows
        ]

    def list_team_entities(self, *, team_name: str | None = None) -> list[IndexedTeamEntity]:
        """Return indexed team-state entities, optionally filtered to one team."""
        query = """
            SELECT
                entities.entity_key,
                entities.entity_kind,
                entities.entity_id,
                entities.source_key,
                sources.source_kind,
                sources.source_path,
                entities.line_no,
                entities.team_name,
                entities.status,
                entities.owner,
                entities.worker,
                entities.created_at,
                entities.updated_at,
                entities.payload_json
            FROM team_entities AS entities
            JOIN history_sources AS sources ON sources.source_key = entities.source_key
        """
        params: tuple[str, ...] | tuple[()] = ()
        if team_name is not None:
            query += " WHERE entities.team_name = ?"
            params = (team_name,)
        query += " ORDER BY sources.source_path ASC, entities.line_no ASC, entities.entity_kind ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            IndexedTeamEntity(
                entity_key=str(row["entity_key"]),
                entity_kind=_coerce_team_entity_kind(str(row["entity_kind"])),
                entity_id=str(row["entity_id"]),
                source_key=str(row["source_key"]),
                source_kind=_coerce_source_kind(str(row["source_kind"])),
                source_path=str(row["source_path"]),
                line_no=int(row["line_no"]),
                team_name=str(row["team_name"]),
                status=str(row["status"]) if row["status"] is not None else None,
                owner=str(row["owner"]) if row["owner"] is not None else None,
                worker=str(row["worker"]) if row["worker"] is not None else None,
                created_at=str(row["created_at"]) if row["created_at"] is not None else None,
                updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
                payload_json=str(row["payload_json"]),
            )
            for row in rows
        ]

    def snapshot(self) -> HistoryIndexSnapshot:
        """Return a stable snapshot of the current derived catalog."""
        return HistoryIndexSnapshot(
            sources=tuple(self.list_sources()),
            transcript_turns=tuple(self.list_transcript_turns()),
            runtime_events=tuple(self.list_runtime_events()),
            task_catalog_rows=tuple(self.list_task_catalog_rows()),
            team_entities=tuple(self.list_team_entities()),
        )

    def _sync(self, *, force_reindex: bool) -> HistoryIndexSyncResult:
        documents = self._collect_documents()
        with self._connect() as connection:
            if force_reindex:
                self._clear_schema(connection)

            existing = {
                str(row["source_key"]): str(row["content_hash"])
                for row in connection.execute(
                    "SELECT source_key, content_hash FROM history_sources"
                ).fetchall()
            }
            desired_keys = {document.source_key for document in documents}

            inserted_sources = 0
            updated_sources = 0
            unchanged_sources = 0

            for document in documents:
                current_hash = existing.get(document.source_key)
                if current_hash == document.content_hash:
                    unchanged_sources += 1
                    continue

                if current_hash is None:
                    inserted_sources += 1
                else:
                    connection.execute(
                        "DELETE FROM history_sources WHERE source_key = ?",
                        (document.source_key,),
                    )
                    updated_sources += 1

                self._insert_document(connection, document)

            stale_keys = sorted(
                source_key for source_key in existing if source_key not in desired_keys
            )
            for source_key in stale_keys:
                connection.execute(
                    "DELETE FROM history_sources WHERE source_key = ?", (source_key,)
                )

            transcript_rows = self._count_rows(connection, "transcript_turns")
            runtime_rows = self._count_rows(connection, "runtime_events")
            task_rows = self._count_rows(connection, "task_catalog")
            team_entity_rows = self._count_rows(connection, "team_entities")

        return HistoryIndexSyncResult(
            indexed_sources=len(documents),
            transcript_rows=transcript_rows,
            runtime_rows=runtime_rows,
            task_rows=task_rows,
            team_entity_rows=team_entity_rows,
            inserted_sources=inserted_sources,
            updated_sources=updated_sources,
            deleted_sources=len(stale_keys),
            unchanged_sources=unchanged_sources,
        )

    def _connect(self) -> sqlite3.Connection:
        self._paths.history_index_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._paths.history_index_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema(connection)
        return connection

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS history_sources (
                source_key TEXT PRIMARY KEY,
                source_kind TEXT NOT NULL,
                source_path TEXT NOT NULL UNIQUE,
                content_hash TEXT NOT NULL,
                row_count INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_turns (
                turn_id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                session_key TEXT NOT NULL,
                surface_session_id TEXT NOT NULL,
                transport TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                topic_id INTEGER,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                visible_content TEXT NOT NULL,
                reply_to_turn_id TEXT,
                turn_source TEXT NOT NULL,
                attachments_json TEXT NOT NULL,
                FOREIGN KEY(source_key) REFERENCES history_sources(source_key) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS transcript_turns_session_idx
            ON transcript_turns(session_key, created_at, line_no)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_events (
                event_id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                session_key TEXT NOT NULL,
                transport TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                topic_id INTEGER,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(source_key) REFERENCES history_sources(source_key) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS runtime_events_session_idx
            ON runtime_events(session_key, created_at, line_no)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS task_catalog (
                task_key TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                parent_agent TEXT NOT NULL,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                completed_at REAL NOT NULL,
                elapsed_seconds REAL NOT NULL,
                result_preview TEXT NOT NULL,
                last_question TEXT NOT NULL,
                prompt_preview TEXT NOT NULL,
                thread_id INTEGER,
                FOREIGN KEY(source_key) REFERENCES history_sources(source_key) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS task_catalog_status_idx
            ON task_catalog(status, created_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS team_entities (
                entity_key TEXT PRIMARY KEY,
                entity_kind TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                status TEXT,
                owner TEXT,
                worker TEXT,
                created_at TEXT,
                updated_at TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(source_key) REFERENCES history_sources(source_key) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS team_entities_lookup_idx
            ON team_entities(team_name, entity_kind, status, updated_at)
            """
        )

    def _clear_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM transcript_turns")
        connection.execute("DELETE FROM runtime_events")
        connection.execute("DELETE FROM task_catalog")
        connection.execute("DELETE FROM team_entities")
        connection.execute("DELETE FROM history_sources")

    def _collect_documents(self) -> list[_IndexedSourceDocument]:
        documents: list[_IndexedSourceDocument] = []
        documents.extend(self._collect_transcript_documents())
        documents.extend(self._collect_runtime_documents())
        documents.extend(self._collect_task_registry_documents())
        documents.extend(self._collect_team_state_documents())
        return sorted(documents, key=lambda document: (document.source_kind, document.source_path))

    def _collect_transcript_documents(self) -> list[_IndexedSourceDocument]:
        documents: list[_IndexedSourceDocument] = []
        if not self._paths.transcripts_dir.exists():
            return documents
        for path in sorted(self._paths.transcripts_dir.rglob("*.jsonl")):
            raw_text = path.read_text(encoding="utf-8")
            rows: list[_IndexedTranscriptRow] = []
            for line_no, raw_line in enumerate(raw_text.splitlines(), start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    turn = TranscriptTurn.model_validate(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.warning("HistoryIndex: skipping unreadable transcript line in %s", path)
                    continue
                rows.append(_IndexedTranscriptRow(line_no=line_no, turn=turn))
            documents.append(
                _IndexedSourceDocument(
                    source_key=self._source_key_for(path),
                    source_kind="transcript",
                    source_path=self._source_path_for(path),
                    content_hash=self._hash_text(raw_text),
                    transcript_rows=tuple(rows),
                )
            )
        return documents

    def _collect_runtime_documents(self) -> list[_IndexedSourceDocument]:
        documents: list[_IndexedSourceDocument] = []
        if not self._paths.runtime_events_dir.exists():
            return documents
        for path in sorted(self._paths.runtime_events_dir.rglob("*.jsonl")):
            raw_text = path.read_text(encoding="utf-8")
            rows: list[_IndexedRuntimeRow] = []
            for line_no, raw_line in enumerate(raw_text.splitlines(), start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = RuntimeEvent.model_validate(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.warning("HistoryIndex: skipping unreadable runtime line in %s", path)
                    continue
                rows.append(_IndexedRuntimeRow(line_no=line_no, event=event))
            documents.append(
                _IndexedSourceDocument(
                    source_key=self._source_key_for(path),
                    source_kind="runtime",
                    source_path=self._source_path_for(path),
                    content_hash=self._hash_text(raw_text),
                    runtime_rows=tuple(rows),
                )
            )
        return documents

    def _collect_task_registry_documents(self) -> list[_IndexedSourceDocument]:
        path = self._paths.tasks_registry_path
        if not path.exists():
            return []
        raw_text = path.read_text(encoding="utf-8")
        payload = _load_json_text(raw_text, path=path, default={"tasks": []})
        rows: list[_IndexedTaskRow] = []
        tasks = payload.get("tasks", [])
        if isinstance(tasks, list):
            for line_no, raw_task in enumerate(tasks, start=1):
                if not isinstance(raw_task, dict):
                    logger.warning("HistoryIndex: skipping unreadable task row in %s", path)
                    continue
                try:
                    entry = TaskEntry.from_dict(raw_task)
                except (KeyError, TypeError):
                    logger.warning("HistoryIndex: skipping unreadable task row in %s", path)
                    continue
                rows.append(_IndexedTaskRow(line_no=line_no, entry=entry))
        return [
            _IndexedSourceDocument(
                source_key=self._source_key_for(path),
                source_kind="task_registry",
                source_path=self._source_path_for(path),
                content_hash=self._hash_text(raw_text),
                task_rows=tuple(rows),
            )
        ]

    def _collect_team_state_documents(self) -> list[_IndexedSourceDocument]:
        documents: list[_IndexedSourceDocument] = []
        if not self._paths.team_state_dir.exists():
            return documents
        for path in sorted(self._paths.team_state_dir.rglob("*.json")):
            if path.name not in _TEAM_STATE_FILENAMES:
                continue
            raw_text = path.read_text(encoding="utf-8")
            team_name = self._team_name_for(path)
            rows = self._collect_team_rows_for_path(
                path=path, raw_text=raw_text, team_name=team_name
            )
            documents.append(
                _IndexedSourceDocument(
                    source_key=self._source_key_for(path),
                    source_kind="team_state",
                    source_path=self._source_path_for(path),
                    content_hash=self._hash_text(raw_text),
                    team_rows=tuple(rows),
                )
            )
        return documents

    def _collect_team_rows_for_path(
        self,
        *,
        path: Path,
        raw_text: str,
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        payload = _load_json_text(raw_text, path=path, default={})
        collectors = {
            "dispatch.json": self._collect_team_dispatch_rows,
            "events.json": self._collect_team_event_rows,
            "mailbox.json": self._collect_team_mailbox_rows,
            "manifest.json": self._collect_team_manifest_rows,
            "phase.json": self._collect_team_phase_rows,
            "tasks.json": self._collect_team_task_rows,
            "worker-runtimes.json": self._collect_team_runtime_rows,
        }
        collector = collectors.get(path.name)
        if collector is not None:
            return collector(path=path, payload=payload, team_name=team_name)
        return []

    def _collect_team_manifest_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        if not payload:
            return []
        try:
            manifest = TeamManifest.model_validate(payload)
        except (TypeError, ValueError):
            logger.warning("HistoryIndex: skipping unreadable team manifest in %s", path)
            return []
        return [
            _IndexedTeamRow(
                line_no=1,
                entity_kind="manifest",
                entity_id=manifest.team_name,
                team_name=manifest.team_name,
                status=None,
                owner=None,
                worker=None,
                created_at=manifest.created_at,
                updated_at=manifest.updated_at,
                payload_json=_canonical_json(manifest.model_dump(mode="json")),
            )
        ]

    def _collect_team_phase_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        if not payload:
            return []
        try:
            phase = TeamPhaseState.model_validate(payload)
        except (TypeError, ValueError):
            logger.warning("HistoryIndex: skipping unreadable team phase in %s", path)
            return []
        return [
            _IndexedTeamRow(
                line_no=1,
                entity_kind="phase",
                entity_id=team_name,
                team_name=team_name,
                status=phase.current_phase,
                owner=None,
                worker=None,
                created_at=phase.created_at,
                updated_at=phase.updated_at,
                payload_json=_canonical_json(phase.model_dump(mode="json")),
            )
        ]

    def _collect_team_task_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        rows: list[_IndexedTeamRow] = []
        tasks = payload.get("tasks", [])
        if not isinstance(tasks, list):
            return rows
        for line_no, raw_task in enumerate(tasks, start=1):
            if not isinstance(raw_task, dict):
                logger.warning("HistoryIndex: skipping unreadable team task row in %s", path)
                continue
            try:
                task = TeamTask.model_validate(raw_task)
            except (TypeError, ValueError):
                logger.warning("HistoryIndex: skipping unreadable team task row in %s", path)
                continue
            rows.append(
                _IndexedTeamRow(
                    line_no=line_no,
                    entity_kind="task",
                    entity_id=task.task_id,
                    team_name=team_name,
                    status=task.status,
                    owner=task.owner,
                    worker=task.claim.worker if task.claim is not None else None,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                    payload_json=_canonical_json(task.model_dump(mode="json")),
                )
            )
        return rows

    def _collect_team_dispatch_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        rows: list[_IndexedTeamRow] = []
        requests = payload.get("dispatch_requests", [])
        if not isinstance(requests, list):
            return rows
        for line_no, raw_request in enumerate(requests, start=1):
            if not isinstance(raw_request, dict):
                logger.warning("HistoryIndex: skipping unreadable dispatch row in %s", path)
                continue
            try:
                request = TeamDispatchRequest.model_validate(raw_request)
            except (TypeError, ValueError):
                logger.warning("HistoryIndex: skipping unreadable dispatch row in %s", path)
                continue
            rows.append(
                _IndexedTeamRow(
                    line_no=line_no,
                    entity_kind="dispatch_request",
                    entity_id=request.request_id,
                    team_name=request.team_name,
                    status=request.status,
                    owner=None,
                    worker=request.to_worker,
                    created_at=request.created_at,
                    updated_at=request.updated_at,
                    payload_json=_canonical_json(request.model_dump(mode="json")),
                )
            )
        return rows

    def _collect_team_runtime_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        rows: list[_IndexedTeamRow] = []
        runtimes = payload.get("worker_runtimes", [])
        if not isinstance(runtimes, list):
            return rows
        for line_no, raw_runtime in enumerate(runtimes, start=1):
            if not isinstance(raw_runtime, dict):
                logger.warning("HistoryIndex: skipping unreadable worker runtime row in %s", path)
                continue
            try:
                runtime = TeamWorkerRuntimeState.model_validate(raw_runtime)
            except (TypeError, ValueError):
                logger.warning("HistoryIndex: skipping unreadable worker runtime row in %s", path)
                continue
            rows.append(
                _IndexedTeamRow(
                    line_no=line_no,
                    entity_kind="worker_runtime",
                    entity_id=runtime.worker,
                    team_name=team_name,
                    status=runtime.status,
                    owner=None,
                    worker=runtime.worker,
                    created_at=runtime.created_at,
                    updated_at=runtime.updated_at,
                    payload_json=_canonical_json(runtime.model_dump(mode="json")),
                )
            )
        return rows

    def _collect_team_mailbox_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        rows: list[_IndexedTeamRow] = []
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            return rows
        for line_no, raw_message in enumerate(messages, start=1):
            if not isinstance(raw_message, dict):
                logger.warning("HistoryIndex: skipping unreadable mailbox row in %s", path)
                continue
            try:
                message = TeamMailboxMessage.model_validate(raw_message)
            except (TypeError, ValueError):
                logger.warning("HistoryIndex: skipping unreadable mailbox row in %s", path)
                continue
            rows.append(
                _IndexedTeamRow(
                    line_no=line_no,
                    entity_kind="mailbox_message",
                    entity_id=message.message_id,
                    team_name=message.team_name,
                    status=message.status,
                    owner=None,
                    worker=message.to_worker,
                    created_at=message.created_at,
                    updated_at=message.updated_at,
                    payload_json=_canonical_json(message.model_dump(mode="json")),
                )
            )
        return rows

    def _collect_team_event_rows(
        self,
        *,
        path: Path,
        payload: dict[str, Any],
        team_name: str,
    ) -> list[_IndexedTeamRow]:
        rows: list[_IndexedTeamRow] = []
        events = payload.get("events", [])
        if not isinstance(events, list):
            return rows
        for line_no, raw_event in enumerate(events, start=1):
            if not isinstance(raw_event, dict):
                logger.warning("HistoryIndex: skipping unreadable event row in %s", path)
                continue
            try:
                event = TeamEvent.model_validate(raw_event)
            except (TypeError, ValueError):
                logger.warning("HistoryIndex: skipping unreadable event row in %s", path)
                continue
            rows.append(
                _IndexedTeamRow(
                    line_no=line_no,
                    entity_kind="event",
                    entity_id=event.event_id,
                    team_name=event.team_name,
                    status=None,
                    owner=None,
                    worker=event.worker,
                    created_at=event.created_at,
                    updated_at=None,
                    payload_json=_canonical_json(event.model_dump(mode="json")),
                )
            )
        return rows

    def _insert_document(
        self, connection: sqlite3.Connection, document: _IndexedSourceDocument
    ) -> None:
        connection.execute(
            """
            INSERT INTO history_sources (source_key, source_kind, source_path, content_hash, row_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                document.source_key,
                document.source_kind,
                document.source_path,
                document.content_hash,
                document.row_count,
            ),
        )
        if document.source_kind == "transcript":
            self._insert_transcript_rows(connection, document)
            return
        if document.source_kind == "runtime":
            self._insert_runtime_rows(connection, document)
            return
        if document.source_kind == "task_registry":
            self._insert_task_rows(connection, document)
            return
        self._insert_team_rows(connection, document)

    def _insert_transcript_rows(
        self,
        connection: sqlite3.Connection,
        document: _IndexedSourceDocument,
    ) -> None:
        for row in document.transcript_rows:
            connection.execute(
                """
                INSERT INTO transcript_turns (
                    turn_id,
                    source_key,
                    line_no,
                    session_key,
                    surface_session_id,
                    transport,
                    chat_id,
                    topic_id,
                    role,
                    created_at,
                    visible_content,
                    reply_to_turn_id,
                    turn_source,
                    attachments_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.turn.turn_id,
                    document.source_key,
                    row.line_no,
                    row.turn.session_key,
                    row.turn.surface_session_id,
                    row.turn.transport,
                    row.turn.chat_id,
                    row.turn.topic_id,
                    row.turn.role,
                    row.turn.created_at,
                    row.turn.visible_content,
                    row.turn.reply_to_turn_id,
                    row.turn.source,
                    _attachments_json(row.turn.attachments),
                ),
            )

    def _insert_runtime_rows(
        self,
        connection: sqlite3.Connection,
        document: _IndexedSourceDocument,
    ) -> None:
        for event_row in document.runtime_rows:
            connection.execute(
                """
                INSERT INTO runtime_events (
                    event_id,
                    source_key,
                    line_no,
                    session_key,
                    transport,
                    chat_id,
                    topic_id,
                    event_type,
                    created_at,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_row.event.event_id,
                    document.source_key,
                    event_row.line_no,
                    event_row.event.session_key,
                    event_row.event.transport,
                    event_row.event.chat_id,
                    event_row.event.topic_id,
                    event_row.event.event_type,
                    event_row.event.created_at,
                    _canonical_json(event_row.event.payload),
                ),
            )

    def _insert_task_rows(
        self,
        connection: sqlite3.Connection,
        document: _IndexedSourceDocument,
    ) -> None:
        for task_row in document.task_rows:
            connection.execute(
                """
                INSERT INTO task_catalog (
                    task_key,
                    task_id,
                    source_key,
                    line_no,
                    chat_id,
                    parent_agent,
                    name,
                    provider,
                    model,
                    status,
                    session_id,
                    created_at,
                    completed_at,
                    elapsed_seconds,
                    result_preview,
                    last_question,
                    prompt_preview,
                    thread_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _task_key(document.source_key, task_row.entry.task_id),
                    task_row.entry.task_id,
                    document.source_key,
                    task_row.line_no,
                    task_row.entry.chat_id,
                    task_row.entry.parent_agent,
                    task_row.entry.name,
                    task_row.entry.provider,
                    task_row.entry.model,
                    task_row.entry.status,
                    task_row.entry.session_id,
                    task_row.entry.created_at,
                    task_row.entry.completed_at,
                    task_row.entry.elapsed_seconds,
                    task_row.entry.result_preview,
                    task_row.entry.last_question,
                    task_row.entry.prompt_preview,
                    task_row.entry.thread_id,
                ),
            )

    def _insert_team_rows(
        self,
        connection: sqlite3.Connection,
        document: _IndexedSourceDocument,
    ) -> None:
        for team_row in document.team_rows:
            connection.execute(
                """
                INSERT INTO team_entities (
                    entity_key,
                    entity_kind,
                    entity_id,
                    source_key,
                    line_no,
                    team_name,
                    status,
                    owner,
                    worker,
                    created_at,
                    updated_at,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _team_entity_key(document.source_key, team_row.entity_kind, team_row.entity_id),
                    team_row.entity_kind,
                    team_row.entity_id,
                    document.source_key,
                    team_row.line_no,
                    team_row.team_name,
                    team_row.status,
                    team_row.owner,
                    team_row.worker,
                    team_row.created_at,
                    team_row.updated_at,
                    team_row.payload_json,
                ),
            )

    def _count_rows(self, connection: sqlite3.Connection, table_name: str) -> int:
        if table_name == "transcript_turns":
            row = connection.execute("SELECT COUNT(*) AS count FROM transcript_turns").fetchone()
        elif table_name == "runtime_events":
            row = connection.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()
        elif table_name == "task_catalog":
            row = connection.execute("SELECT COUNT(*) AS count FROM task_catalog").fetchone()
        else:
            row = connection.execute("SELECT COUNT(*) AS count FROM team_entities").fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def _source_key_for(self, path: Path) -> str:
        return self._source_path_for(path)

    def _source_path_for(self, path: Path) -> str:
        return path.relative_to(self._paths.controlmesh_home).as_posix()

    def _team_name_for(self, path: Path) -> str:
        relative_path = path.relative_to(self._paths.team_state_dir)
        if len(relative_path.parts) >= 2:
            return relative_path.parts[0]
        return path.parent.name

    def _hash_text(self, raw_text: str) -> str:
        return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _attachments_json(attachments: list[TranscriptAttachment]) -> str:
    return _canonical_json([attachment.model_dump(mode="json") for attachment in attachments])


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _task_key(source_key: str, task_id: str) -> str:
    return f"{source_key}#{task_id}"


def _team_entity_key(source_key: str, entity_kind: TeamEntityKind, entity_id: str) -> str:
    return f"{source_key}#{entity_kind}:{entity_id}"


def _load_json_text(raw_text: str, *, path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not raw_text.strip():
        return default
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("HistoryIndex: skipping unreadable JSON document in %s", path)
        return default
    if not isinstance(payload, dict):
        logger.warning("HistoryIndex: expected JSON object in %s", path)
        return default
    return payload


def _coerce_source_kind(raw_value: str) -> SourceKind:
    if raw_value == "runtime":
        return "runtime"
    if raw_value == "task_registry":
        return "task_registry"
    if raw_value == "team_state":
        return "team_state"
    return "transcript"


def _coerce_team_entity_kind(raw_value: str) -> TeamEntityKind:
    if raw_value in _TEAM_ENTITY_KINDS:
        return cast("TeamEntityKind", raw_value)
    return "task"
