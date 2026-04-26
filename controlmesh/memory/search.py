"""Local SQLite FTS5 index for memory-v2 markdown artifacts."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from controlmesh.memory.models import (
    MemoryDocumentKind,
    MemoryIndexSyncResult,
    MemoryScope,
    MemorySearchHit,
    MemorySearchResult,
)
from controlmesh.memory.promotion import parse_authority_entry_metadata
from controlmesh.memory.store import initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

_SEARCH_SNIPPET_TOKENS = 12
_SCOPED_CANDIDATE_HEADERS = {"## Open Candidates", "## Promotion Candidates"}
_SCOPED_CANDIDATE_LINE_RE = re.compile(
    r"^- \[(?P<category>[a-z-]+)(?: (?P<scope>local|shared))?(?:\s+score=(?P<score>[0-9]+(?:\.[0-9]+)?))?\]\s+(?P<content>.+?)(?: \[(?P<ref>[^\]]+)\])?$"
)


@dataclass(frozen=True)
class _IndexedDocument:
    source_path: str
    kind: MemoryDocumentKind
    source_date: str | None
    content_hash: str
    content: str


def _get_authority_scope_for_hit(
    authority_path: Path,
    snippet: str,
) -> MemoryScope | None:
    """Extract scope for an authority hit from its snippet.

    Searches the authority file for an entry whose content (before metadata)
    matches the query term found in the FTS5 snippet, then parses the entry's
    metadata to extract scope.
    Returns None if the matching entry cannot be confidently determined
    (avoids mislabeling a local entry as shared).
    """
    if not authority_path.exists():
        return None

    authority_text = authority_path.read_text(encoding="utf-8")
    lines = authority_text.splitlines()

    # Extract the query term from the FTS5 snippet markup.
    # FTS5 returns snippets with matched terms wrapped in [...].
    # We extract the term(s) to identify which entry triggered the hit.
    snippet_clean = snippet.replace("[", "").replace("]", "").replace("...", "").strip()
    if len(snippet_clean) < 5:
        return None

    # Extract the primary matched term from the snippet.
    # The matched term is the text inside [...] in the snippet.
    matched_terms = re.findall(r"\[([^\]]+)\]", snippet)
    if not matched_terms:
        return None
    primary_term = matched_terms[0].lower()

    # Now find the authority entry whose content contains the matched term.
    # Iterate through entries and check if the term appears in the content.
    candidates: list[MemoryScope] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        content = _extract_entry_content_for_match(stripped)
        if not content:
            continue
        # Check if the primary matched term appears in this entry's content
        if primary_term in content.lower():
            meta = parse_authority_entry_metadata(stripped)
            if meta is not None:
                candidates.append(meta.scope)

    # If exactly one match, use its scope
    if len(candidates) == 1:
        return candidates[0]
    # Multiple matches or no match: conservative - return None rather than guess
    return None


def _get_daily_note_candidate_scope_for_hit(
    daily_note_path: Path,
    snippet: str,
) -> MemoryScope | None:
    """Extract scope for a daily-note hit when it can be tied to candidate sections.

    Exact search indexes whole daily-note files, so scope is only surfaced when
    the returned snippet can be conservatively matched back to a specific
    candidate line. Non-candidate daily-note hits remain unlabeled.
    """
    if not daily_note_path.exists():
        return None

    snippet_norm = _normalize_for_match(snippet.replace("...", " "))
    if not snippet_norm:
        return None

    candidates: list[MemoryScope] = []
    note_text = daily_note_path.read_text(encoding="utf-8")
    for content, scope in _iter_scoped_candidate_entries(note_text):
        if _candidate_content_matches_snippet(content, snippet_norm):
            candidates.append(scope)

    if len(candidates) == 1:
        return candidates[0]
    return None


def _iter_scoped_candidate_entries(note_text: str) -> list[tuple[str, MemoryScope]]:
    """Return parsed ``(content, scope)`` pairs from one daily note."""
    entries: list[tuple[str, MemoryScope]] = []
    in_scoped_candidates = False
    for raw_line in note_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            in_scoped_candidates = stripped in _SCOPED_CANDIDATE_HEADERS
            continue
        if not in_scoped_candidates or not stripped.startswith("- "):
            continue

        match = _SCOPED_CANDIDATE_LINE_RE.match(stripped)
        if match is None:
            continue

        scope_text = match.group("scope")
        scope = MemoryScope(scope_text) if scope_text else MemoryScope.LOCAL
        entries.append((match.group("content").strip(), scope))
    return entries


def _normalize_for_match(text: str) -> str:
    """Normalize text for conservative snippet-to-line matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _candidate_content_matches_snippet(content: str, snippet_norm: str) -> bool:
    """Return whether a candidate content string matches the FTS snippet."""
    content_norm = _normalize_for_match(content)
    if not content_norm:
        return False

    if content_norm in snippet_norm:
        return True
    if len(snippet_norm.split()) >= 3 and snippet_norm in content_norm:
        return True

    tokens = content_norm.split()
    max_window = min(5, len(tokens))
    for window_size in range(max_window, 1, -1):
        for start in range(len(tokens) - window_size + 1):
            phrase = " ".join(tokens[start : start + window_size])
            if phrase in snippet_norm:
                return True

    return False


def _extract_entry_content_for_match(line: str) -> str:
    """Extract the content portion of an authority entry line for matching.

    Authority entries end with a metadata block like:
        - Some content here. _(id: abc123; status: active; ...)_
    Returns the content before the '_(...)' metadata block, stripped of the
    leading '- ' list marker.  Returns the empty string if the line doesn't
    look like an authority entry.
    """
    meta_start = line.find(" _(")
    if meta_start == -1:
        return ""
    return line[:meta_start].strip().removeprefix("- ")


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

    authority_path = paths.authority_memory_path

    hits = []
    for row in rows:
        kind = MemoryDocumentKind(str(row[1]))
        snippet = str(row[3])
        hit = MemorySearchHit(
            source_path=str(row[0]),
            kind=kind,
            source_date=str(row[2]) if row[2] is not None else None,
            snippet=snippet,
            rank=float(row[4]),
        )
        # Populate scope for authority hits by matching snippet to entry in authority file
        if kind == MemoryDocumentKind.AUTHORITY:
            hit.scope = _get_authority_scope_for_hit(authority_path, snippet)
        elif kind == MemoryDocumentKind.DAILY_NOTE:
            hit.scope = _get_daily_note_candidate_scope_for_hit(
                paths.workspace / hit.source_path,
                snippet,
            )
        hits.append(hit)
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
