"""Local SQLite FTS5 index for memory-v2 markdown artifacts."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from controlmesh.memory.models import (
    MemoryDocumentKind,
    MemoryIndexSyncResult,
    MemorySearchHit,
    MemorySearchResult,
)
from controlmesh.memory.store import initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

_SEARCH_SNIPPET_TOKENS = 12


@dataclass(frozen=True)
class _IndexedDocument:
    source_path: str
    kind: MemoryDocumentKind
    source_date: str | None
    content_hash: str
    content: str


def sync_memory_index(paths: ControlMeshPaths) -> MemoryIndexSyncResult:
    """Synchronize the local SQLite FTS5 index with memory-v2 files."""
    initialize_memory_v2(paths)
    documents = _collect_documents(paths)
    paths.memory_search_index_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(paths.memory_search_index_path) as connection:
        _initialize_schema(connection)
        existing = {
            str(row["source_path"]): (int(row["id"]), str(row["content_hash"]))
            for row in connection.execute(
                "SELECT id, source_path, content_hash FROM memory_documents"
            ).fetchall()
        }

        inserted_count = 0
        updated_count = 0
        unchanged_count = 0

        for document in documents:
            existing_row = existing.get(document.source_path)
            if existing_row is None:
                row_id = _insert_document(connection, document)
                _upsert_fts_row(connection, row_id=row_id, content=document.content)
                inserted_count += 1
                continue

            row_id, current_hash = existing_row
            if current_hash == document.content_hash:
                unchanged_count += 1
                continue

            connection.execute(
                """
                UPDATE memory_documents
                SET kind = ?, source_date = ?, content_hash = ?, content = ?
                WHERE id = ?
                """,
                (
                    document.kind.value,
                    document.source_date,
                    document.content_hash,
                    document.content,
                    row_id,
                ),
            )
            _upsert_fts_row(connection, row_id=row_id, content=document.content)
            updated_count += 1

        desired_paths = {document.source_path for document in documents}
        stale_rows = [
            (row_id, source_path)
            for source_path, (row_id, _content_hash) in existing.items()
            if source_path not in desired_paths
        ]
        for row_id, _source_path in stale_rows:
            connection.execute("DELETE FROM memory_documents WHERE id = ?", (row_id,))
            connection.execute("DELETE FROM memory_documents_fts WHERE rowid = ?", (row_id,))

    return MemoryIndexSyncResult(
        indexed_count=len(documents),
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=len(stale_rows),
        unchanged_count=unchanged_count,
    )


def search_memory_index(
    paths: ControlMeshPaths,
    query: str,
    *,
    limit: int = 10,
    refresh: bool = True,
) -> MemorySearchResult:
    """Search indexed memory-v2 content through SQLite FTS5."""
    initialize_memory_v2(paths)
    if refresh:
        sync_memory_index(paths)

    try:
        with sqlite3.connect(paths.memory_search_index_path) as connection:
            _initialize_schema(connection)
            rows = connection.execute(
                """
                SELECT
                    docs.source_path,
                    docs.kind,
                    docs.source_date,
                    snippet(memory_documents_fts, 0, '[', ']', '...', ?) AS snippet,
                    bm25(memory_documents_fts, 10.0) AS rank
                FROM memory_documents_fts
                JOIN memory_documents AS docs ON docs.id = memory_documents_fts.rowid
                WHERE memory_documents_fts MATCH ?
                ORDER BY
                    rank ASC,
                    CASE docs.kind
                        WHEN 'authority' THEN 0
                        WHEN 'dream-diary' THEN 1
                        ELSE 2
                    END ASC,
                    docs.source_date DESC,
                    docs.source_path ASC
                LIMIT ?
                """,
                (_SEARCH_SNIPPET_TOKENS, query, limit),
            ).fetchall()
    except sqlite3.OperationalError:
        return MemorySearchResult(query=query, hits=[])

    hits = [
        MemorySearchHit(
            source_path=str(row[0]),
            kind=MemoryDocumentKind(str(row[1])),
            source_date=str(row[2]) if row[2] is not None else None,
            snippet=str(row[3]),
            rank=float(row[4]),
        )
        for row in rows
    ]
    return MemorySearchResult(query=query, hits=hits)


def _initialize_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            source_date TEXT,
            content_hash TEXT NOT NULL,
            content TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_documents_fts
        USING fts5(content, tokenize = 'unicode61')
        """
    )


def _collect_documents(paths: ControlMeshPaths) -> list[_IndexedDocument]:
    documents = [
        _build_document(paths, paths.authority_memory_path, kind=MemoryDocumentKind.AUTHORITY),
        _build_document(paths, paths.dream_diary_path, kind=MemoryDocumentKind.DREAM_DIARY),
    ]
    daily_paths = sorted(
        path for path in paths.memory_v2_daily_dir.glob("*.md") if path.is_file()
    )
    for daily_path in daily_paths:
        note_date = _parse_note_date(daily_path)
        documents.append(
            _build_document(
                paths,
                daily_path,
                kind=MemoryDocumentKind.DAILY_NOTE,
                source_date=note_date.isoformat(),
            )
        )
    return documents


def _build_document(
    paths: ControlMeshPaths,
    source_path: Path,
    *,
    kind: MemoryDocumentKind,
    source_date: str | None = None,
) -> _IndexedDocument:
    content = source_path.read_text(encoding="utf-8")
    return _IndexedDocument(
        source_path=source_path.relative_to(paths.workspace).as_posix(),
        kind=kind,
        source_date=source_date,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
    )


def _insert_document(connection: sqlite3.Connection, document: _IndexedDocument) -> int:
    cursor = connection.execute(
        """
        INSERT INTO memory_documents (source_path, kind, source_date, content_hash, content)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            document.source_path,
            document.kind.value,
            document.source_date,
            document.content_hash,
            document.content,
        ),
    )
    row_id = cursor.lastrowid
    if row_id is None:
        msg = f"failed to allocate rowid for {document.source_path}"
        raise RuntimeError(msg)
    return int(row_id)


def _upsert_fts_row(connection: sqlite3.Connection, *, row_id: int, content: str) -> None:
    connection.execute("DELETE FROM memory_documents_fts WHERE rowid = ?", (row_id,))
    connection.execute(
        "INSERT INTO memory_documents_fts (rowid, content) VALUES (?, ?)",
        (row_id, content),
    )


def _parse_note_date(path: Path) -> date:
    return date.fromisoformat(path.stem)
