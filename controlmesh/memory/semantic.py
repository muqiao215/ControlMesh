"""Non-authoritative semantic-style retrieval for memory-v2 using trigram similarity.

Phase 7 scope:
- Additive retrieval layer only; no authority-memory mutation.
- Character trigram Jaccard similarity (pure Python stdlib, no external deps).
- Derived/cache-like index rebuildable from markdown source of truth.
- Semantic hits always point back to concrete source text/paths for inspection.
- Never overrides or competes with the FTS5 keyword index.

This module is intentionally conservative: no embeddings, no daemon loop,
no hosted vector DB.  If the semantic index is missing or stale it degrades
gracefully and can be rebuilt on demand.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from controlmesh.memory.models import (
    MemoryDocumentKind,
    MemoryScope,
    SemanticSearchHit,
    SemanticSearchResult,
)
from controlmesh.memory.store import initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INDEX_VERSION = 1
_TRIGRAM_SIZE = 3
_MIN_NGRAM_LENGTH = 3  # skip texts shorter than this after normalization
_DEFAULT_LIMIT = 10

# Authority entry line pattern: "- {content} _(metadata)_"
_AUTHORITY_ENTRY_RE = re.compile(
    r"^- (?P<content>[^_].*?) _\((?P<meta>[^)]+)\)_$"
)
_AUTHORITY_META_RE = re.compile(r"\bid:\s*(?P<eid>[^;]+)")
_SCOPE_RE = re.compile(r"\bscope:\s*(?P<scope>local|shared)\b", re.IGNORECASE)

# Daily note section header
_SECTION_RE = re.compile(r"^##\s+(.+)$")
_ITEM_RE = re.compile(r"^- \[(?P<kind>[^\]]+)\] (?P<content>.+?)(?: \[(?P<ref>[^\]]+)\])?$")

# ---------------------------------------------------------------------------
# Entry models (used only in this module, not persisted)
# ---------------------------------------------------------------------------


@dataclass
class _SourceEntry:
    entry_id: str  # stable opaque id
    kind: MemoryDocumentKind
    source_path: str
    section: str | None
    content: str
    authority_entry_id: str | None = None  # only for authority entries
    line_number: int | None = None
    scope: MemoryScope = MemoryScope.LOCAL


# ---------------------------------------------------------------------------
# N-gram helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _trigrams(text: str) -> set[str]:
    """Return the set of character trigrams (size `_TRIGRAM_SIZE`) for `text`."""
    if len(text) < _MIN_NGRAM_LENGTH:
        return set()
    return {text[i : i + _TRIGRAM_SIZE] for i in range(len(text) - _TRIGRAM_SIZE + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Index path helpers
# ---------------------------------------------------------------------------


def _semantic_index_path(paths: ControlMeshPaths) -> Path:
    """Path to the semantic index sidecar file."""
    return paths.memory_v2_machine_state_dir / "semantic_index.json"


# ---------------------------------------------------------------------------
# Entry extraction from authority memory
# ---------------------------------------------------------------------------


def _extract_authority_entries(paths: ControlMeshPaths) -> list[_SourceEntry]:
    """Parse individual entries from MEMORY.md grouped by section."""
    authority_path = paths.authority_memory_path
    if not authority_path.exists():
        return []

    text = authority_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    entries: list[_SourceEntry] = []
    current_section: str | None = None

    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()

        # Track current authority section (### Fact, etc.)
        if stripped.startswith("### "):
            current_section = stripped[4:].strip().lower()
            continue

        # Skip non-entry lines
        if not stripped.startswith("- "):
            continue

        # Parse entry content
        m = _AUTHORITY_ENTRY_RE.match(stripped)
        if m is None:
            continue

        content = m.group("content").strip()
        if not content:
            continue

        # Extract authority entry id from metadata
        authority_id: str | None = None
        scope: MemoryScope = MemoryScope.LOCAL
        meta_str = m.group("meta")
        id_m = _AUTHORITY_META_RE.search(meta_str)
        if id_m:
            authority_id = id_m.group("eid").strip()
        # Extract scope from metadata (defaults to LOCAL for backward compat)
        scope_m = _SCOPE_RE.search(meta_str)
        if scope_m:
            scope = MemoryScope(scope_m.group("scope").lower())

        # Stable entry_id derived from path + line number
        seed = f"authority:{authority_path.relative_to(paths.workspace).as_posix()}:{lineno}".encode()
        entry_id = hashlib.sha256(seed).hexdigest()[:16]

        entries.append(
            _SourceEntry(
                entry_id=entry_id,
                kind=MemoryDocumentKind.AUTHORITY,
                source_path=authority_path.relative_to(paths.workspace).as_posix(),
                section=current_section,
                content=content,
                authority_entry_id=authority_id,
                line_number=lineno,
                scope=scope,
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Entry extraction from daily notes
# ---------------------------------------------------------------------------


def _split_sections_with_offset(
    text: str,
) -> list[tuple[str, str, int]]:
    """Split a daily note into (section_name, section_body, start_lineno) tuples.

    ``start_lineno`` is the 1-based line number of the ``## Section`` header
    within the file, which is used to compute real (not section-local) line
    numbers for each entry.
    """
    lines = text.splitlines()
    sections: list[tuple[str, str, int]] = []
    current_header: str | None = None
    current_lines: list[str] = []
    section_start: int = 0

    for lineno, raw_line in enumerate(lines, start=1):
        m = _SECTION_RE.match(raw_line)
        if m:
            if current_header is not None:
                sections.append((current_header, "\n".join(current_lines), section_start))
            current_header = m.group(1)
            current_lines = []
            section_start = lineno
        elif current_header is not None:
            current_lines.append(raw_line)

    if current_header is not None:
        sections.append((current_header, "\n".join(current_lines), section_start))

    return sections


def _extract_daily_note_entries(paths: ControlMeshPaths) -> list[_SourceEntry]:
    """Parse entries from all daily notes (Events, Signals, Open Candidates, Promotion Candidates)."""
    daily_dir = paths.memory_v2_daily_dir
    if not daily_dir.exists():
        return []

    entries: list[_SourceEntry] = []
    daily_paths = sorted(path for path in daily_dir.glob("*.md") if path.is_file())

    for daily_path in daily_paths:
        note_text = daily_path.read_text(encoding="utf-8")
        sections = _split_sections_with_offset(note_text)

        for section_name, section_body, section_start in sections:
            body_lines = section_body.splitlines()
            # Skip leading blank lines so that local_lineno is relative to the first non-blank content line
            first_content_idx = next((i for i, ln in enumerate(body_lines) if ln.strip()), 0)
            nonblank_lines = body_lines[first_content_idx:]

            for local_lineno, raw_line in enumerate(nonblank_lines, start=1):
                line = raw_line.strip()
                if not line.startswith("- "):
                    continue

                m = _ITEM_RE.match(line)
                if m is None:
                    continue

                content = m.group("content").strip()
                if not content:
                    continue

                # Compute real file line: section header line + 1 (the header itself) + (first_content_idx + local_lineno - 1)
                # = section_start + first_content_idx + local_lineno
                real_lineno = section_start + first_content_idx + local_lineno

                seed = f"daily:{daily_path.relative_to(paths.workspace).as_posix()}:{section_name}:{real_lineno}".encode()
                entry_id = hashlib.sha256(seed).hexdigest()[:16]

                entries.append(
                    _SourceEntry(
                        entry_id=entry_id,
                        kind=MemoryDocumentKind.DAILY_NOTE,
                        source_path=daily_path.relative_to(paths.workspace).as_posix(),
                        section=section_name,
                        content=content,
                        authority_entry_id=None,
                        line_number=real_lineno,
                    )
                )

    return entries


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


def _build_entry_record(entry: _SourceEntry, trigram_set: set[str]) -> dict[str, Any]:
    """Serialize one indexed entry to a dict for JSON storage."""
    return {
        "entry_id": entry.entry_id,
        "kind": entry.kind.value,
        "source_path": entry.source_path,
        "section": entry.section,
        "content": entry.content,
        "authority_entry_id": entry.authority_entry_id,
        "line_number": entry.line_number,
        "scope": entry.scope.value,
        "trigram_count": len(trigram_set),
    }


def sync_semantic_index(paths: ControlMeshPaths) -> SemanticIndexSyncResult:
    """Build or rebuild the semantic index from authority and daily note markdown.

    This is a pure read-only pass over source files.  The resulting JSON
    sidecar is *derived* and can be discarded and rebuilt at any time.
    Markdown files remain the sole source of truth.
    """
    initialize_memory_v2(paths)
    index_path = _semantic_index_path(paths)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect all entries
    authority_entries = _extract_authority_entries(paths)
    daily_entries = _extract_daily_note_entries(paths)
    all_entries = authority_entries + daily_entries

    # Build index records
    records: list[dict[str, Any]] = []
    for entry in all_entries:
        normalized = _normalize(entry.content)
        trigram_set = _trigrams(normalized)
        record = _build_entry_record(entry, trigram_set)
        record["trigrams"] = sorted(trigram_set)  # store sorted for deterministic load
        records.append(record)

    index_data: dict[str, Any] = {
        "version": _INDEX_VERSION,
        "indexed_at": datetime.now(UTC).isoformat(),
        "entry_count": len(records),
        "authority_count": len(authority_entries),
        "daily_count": len(daily_entries),
        "entries": records,
    }

    # Atomic write
    _atomic_json_save(index_path, index_data)

    return SemanticIndexSyncResult(
        indexed_count=len(records),
        authority_count=len(authority_entries),
        daily_count=len(daily_entries),
    )


def _atomic_json_save(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically using a temp file + rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)


# ---------------------------------------------------------------------------
# Query / retrieval
# ---------------------------------------------------------------------------


def _record_to_hit(score: float, record: dict[str, Any]) -> SemanticSearchHit:
    """Convert a scored index record into a SemanticSearchHit."""
    kind_str = record.get("kind", "authority")
    try:
        kind = MemoryDocumentKind(kind_str)
    except ValueError:
        kind = MemoryDocumentKind.AUTHORITY

    # Parse scope from record; default to None for non-authority entries
    scope: MemoryScope | None = None
    if kind == MemoryDocumentKind.AUTHORITY:
        scope_str = record.get("scope", "")
        if scope_str in ("local", "shared"):
            scope = MemoryScope(scope_str)

    return SemanticSearchHit(
        entry_id=record.get("entry_id", ""),
        kind=kind,
        source_path=record.get("source_path", ""),
        section=record.get("section"),
        content=record.get("content", ""),
        authority_entry_id=record.get("authority_entry_id"),
        line_number=record.get("line_number"),
        similarity=round(score, 4),
        scope=scope,
    )


def _load_index(paths: ControlMeshPaths) -> dict[str, Any] | None:
    """Load the semantic index sidecar, returning None if missing or unreadable."""
    index_path = _semantic_index_path(paths)
    if not index_path.exists():
        return None
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def search_semantic_index(
    paths: ControlMeshPaths,
    query: str,
    *,
    limit: int = _DEFAULT_LIMIT,
    rebuild: bool = False,
) -> SemanticSearchResult:
    """Perform trigram-Jaccard similarity search over the semantic index.

    If the index is missing or ``rebuild=True``, it is rebuilt from source files
    before searching.

    Returns ``SemanticSearchResult`` with hits sorted by similarity descending.
    Each hit carries a source reference so users can inspect the original
    markdown directly.
    """
    initialize_memory_v2(paths)

    if rebuild:
        sync_semantic_index(paths)

    index_data = _load_index(paths)
    if index_data is None:
        # Graceful degradation: rebuild and try again
        sync_semantic_index(paths)
        index_data = _load_index(paths)
        if index_data is None:
            return SemanticSearchResult(query=query, hits=[], index_available=False)

    query_trigram_set = set(_trigrams(_normalize(query)))
    if not query_trigram_set:
        return SemanticSearchResult(query=query, hits=[], index_available=True)

    scored: list[tuple[float, dict[str, Any]]] = []

    for record in index_data.get("entries", []):
        entry_trigram_set = set(record.get("trigrams", []))
        if not entry_trigram_set:
            continue

        score = _jaccard(query_trigram_set, entry_trigram_set)
        if score > 0.0:
            scored.append((score, record))

    # Sort: highest similarity first, then by kind priority (authority first)
    kind_priority = {"authority": 0, "daily-note": 1}
    scored.sort(key=lambda x: (-x[0], kind_priority.get(x[1].get("kind", ""), 9)))

    hits = [_record_to_hit(score, record) for score, record in scored[:limit]]

    return SemanticSearchResult(
        query=query,
        hits=hits,
        index_available=True,
        indexed_at=index_data.get("indexed_at"),
        total_indexed=index_data.get("entry_count", 0),
    )


# ---------------------------------------------------------------------------
# Result models (dataclass equivalents persisted alongside SemanticSearchHit)
# ---------------------------------------------------------------------------


@dataclass
class SemanticIndexSyncResult:
    """Counters from a semantic index sync pass."""

    indexed_count: int = 0
    authority_count: int = 0
    daily_count: int = 0
