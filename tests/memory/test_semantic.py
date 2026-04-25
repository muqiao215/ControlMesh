"""Tests for the non-authoritative trigram-similarity semantic index."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from controlmesh.memory.models import MemoryDocumentKind, MemoryScope
from controlmesh.memory.semantic import (
    _extract_authority_entries,
    _extract_daily_note_entries,
    _jaccard,
    _normalize,
    _semantic_index_path,
    _trigrams,
    search_semantic_index,
    sync_semantic_index,
)
from controlmesh.memory.store import ensure_daily_note, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


# ---------------------------------------------------------------------------
# Normalization and n-gram helpers
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_lowercase(self) -> None:
        assert _normalize("Hello World") == "hello world"

    def test_collapse_whitespace(self) -> None:
        assert _normalize("hello  world\n\ttab") == "hello world tab"

    def test_strip(self) -> None:
        assert _normalize("  hello  ") == "hello"

    def test_punctuation_removed(self) -> None:
        assert _normalize("hello, world!") == "hello world"


class TestTrigrams:
    def test_basic(self) -> None:
        tg = _trigrams("hello")
        assert "hel" in tg
        assert "ell" in tg
        assert "llo" in tg
        assert len(tg) == 3

    def test_short_string_returns_empty(self) -> None:
        assert _trigrams("ab") == set()

    def test_unique(self) -> None:
        tg = _trigrams("aaaa")
        assert len(tg) == 1  # "aaa" is the only trigram, stored as a set

    def test_deterministic(self) -> None:
        t1 = _trigrams("hello world")
        t2 = _trigrams("hello world")
        assert t1 == t2


class TestJaccard:
    def test_identical(self) -> None:
        s = {"a", "b", "c"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint(self) -> None:
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial(self) -> None:
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        inter = 2
        union = 4
        assert _jaccard(a, b) == inter / union


# ---------------------------------------------------------------------------
# Entry extraction
# ---------------------------------------------------------------------------


def test_extract_authority_entries_parses_section_and_metadata(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- User prefers dark mode _(\id: abc123; status: active)_


### Preference
- User likes concise answers _(\id: def456; status: active; source: memory/2026-04-08.md#L5)_


### Project
- ControlMesh Phase 7 semantic search _(\id: proj001; status: active)_
""",
        encoding="utf-8",
    )

    entries = _extract_authority_entries(paths)

    assert len(entries) == 3
    assert {e.section for e in entries} == {"fact", "preference", "project"}
    assert {e.authority_entry_id for e in entries} == {"abc123", "def456", "proj001"}
    # Content is the raw entry text without the metadata suffix
    for e in entries:
        assert "id:" not in e.content
        assert "_(" not in e.content
    # Check content is the actual user-facing text
    contents = {e.content for e in entries}
    assert "User prefers dark mode" in contents
    assert "User likes concise answers" in contents
    assert "ControlMesh Phase 7 semantic search" in contents


def test_extract_daily_note_entries_parses_events_and_signals(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Events
- [deploy] Deployed Phase 7 semantic search [evt:evt001]

## Signals
- [preference] User asks about semantic memory retrieval [sig:sig001]

## Open Candidates
- [fact score=0.9] Trigram indexing works well for approximate matching [oc:oc001]
""",
        encoding="utf-8",
    )

    entries = _extract_daily_note_entries(paths)

    assert len(entries) == 3
    kinds = {e.kind for e in entries}
    assert kinds == {MemoryDocumentKind.DAILY_NOTE}
    contents = {e.content for e in entries}
    assert "Deployed Phase 7 semantic search" in contents
    assert "User asks about semantic memory retrieval" in contents
    assert "Trigram indexing works well for approximate matching" in contents


# ---------------------------------------------------------------------------
# Index building and sync
# ---------------------------------------------------------------------------


def test_sync_semantic_index_builds_json_sidecar(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Dark mode is preferred by the user _(\id: fact001; status: active)_
""",
        encoding="utf-8",
    )
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Signals
- [preference] User interested in semantic search [sig:sig001]
""",
        encoding="utf-8",
    )

    result = sync_semantic_index(paths)

    index_path = _semantic_index_path(paths)
    assert index_path.exists()
    assert result.indexed_count == 2
    assert result.authority_count == 1
    assert result.daily_count == 1

    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["entry_count"] == 2
    assert len(data["entries"]) == 2
    # Each entry should have a stable entry_id and trigrams
    for entry in data["entries"]:
        assert "entry_id" in entry
        assert "trigrams" in entry
        assert "content" in entry
        assert isinstance(entry["trigrams"], list)


def test_sync_semantic_index_is_rebuildable_and_deterministic(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Deterministic indexing matters _(\id: det001; status: active)_
""",
        encoding="utf-8",
    )

    first = sync_semantic_index(paths)
    second = sync_semantic_index(paths)

    assert first.indexed_count == second.indexed_count
    assert first.authority_count == second.authority_count
    assert first.daily_count == second.daily_count

    # entry_ids should be stable across rebuilds
    data1 = json.loads(_semantic_index_path(paths).read_text(encoding="utf-8"))
    ids1 = sorted(e["entry_id"] for e in data1["entries"])
    sync_semantic_index(paths)
    data2 = json.loads(_semantic_index_path(paths).read_text(encoding="utf-8"))
    ids2 = sorted(e["entry_id"] for e in data2["entries"])
    assert ids1 == ids2


# ---------------------------------------------------------------------------
# Query / retrieval
# ---------------------------------------------------------------------------


def test_search_semantic_index_returns_similar_entries(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- User prefers dark mode theme _(\id: dark001; status: active)_
- User works with Python projects _(\id: py001; status: active)_
- User likes fast build times _(\id: fast001; status: active)_
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "dark theme preference", limit=5)

    assert result.index_available is True
    assert len(result.hits) >= 1
    # The "dark mode theme" entry should score highest for "dark theme preference"
    hit_contents = [h.content for h in result.hits]
    assert "User prefers dark mode theme" in hit_contents
    # The top hit should be the dark mode entry
    top = result.hits[0]
    assert top.similarity > 0.0
    assert top.kind == MemoryDocumentKind.AUTHORITY
    assert top.source_path == "MEMORY.md"


def test_search_semantic_index_covers_daily_note_entries(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- User has a dog _(\id: dog001; status: active)_
""",
        encoding="utf-8",
    )
    note_path = ensure_daily_note(paths, date(2026, 4, 10))
    note_path.write_text(
        """# Daily Memory: 2026-04-10

## Signals
- [pet] User talked about their golden retriever puppy [sig:sig002]
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "dog pet puppy", limit=5)

    assert result.index_available is True
    # Should find both the authority entry about dogs and the daily note about the puppy
    hit_kinds = {h.kind for h in result.hits}
    assert MemoryDocumentKind.DAILY_NOTE in hit_kinds
    hit_contents = [h.content for h in result.hits]
    # Both entries should appear since they share semantic similarity
    assert any("dog" in c.lower() for c in hit_contents)


def test_search_semantic_index_returns_authority_entry_ids(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- User prefers dark mode _(\id: pref001; status: active)_
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "dark mode", limit=5)

    assert len(result.hits) >= 1
    top = result.hits[0]
    assert top.authority_entry_id == "pref001"
    assert top.entry_id != ""


def test_search_semantic_index_graceful_when_index_missing(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Test entry _(\id: t001; status: active)_
""",
        encoding="utf-8",
    )

    index_path = _semantic_index_path(paths)
    assert not index_path.exists()

    # Should rebuild automatically when missing
    result = search_semantic_index(paths, "test", limit=5)

    assert result.index_available is True
    assert index_path.exists()
    assert len(result.hits) >= 1


def test_search_semantic_index_rebuild_flag(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Original entry _(\id: orig001; status: active)_
""",
        encoding="utf-8",
    )
    sync_semantic_index(paths)

    # Add new entry
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Original entry _(\id: orig001; status: active)_
- New entry added after first sync _(\id: new001; status: active)_
""",
        encoding="utf-8",
    )

    # Without rebuild flag, should not find new entry
    result_old = search_semantic_index(paths, "new entry", limit=5, rebuild=False)
    # With rebuild flag, should find new entry
    result_new = search_semantic_index(paths, "new entry", limit=5, rebuild=True)

    contents_old = [h.content for h in result_old.hits]
    contents_new = [h.content for h in result_new.hits]
    assert "New entry added after first sync" not in contents_old
    assert "New entry added after first sync" in contents_new


def test_search_semantic_index_respects_limit(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- First fact entry _(\id: f001; status: active)_
- Second fact entry _(\id: f002; status: active)_
- Third fact entry _(\id: f003; status: active)_
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "fact entry", limit=2)

    assert len(result.hits) <= 2


def test_search_semantic_index_short_query_returns_empty(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Test _(\id: t001; status: active)_
""",
        encoding="utf-8",
    )
    sync_semantic_index(paths)

    result = search_semantic_index(paths, "a", limit=5)

    # Single character normalizes to empty ngram set, should return gracefully
    assert result.index_available is True


def test_daily_note_entry_line_numbers_are_real_file_positions(tmp_path: Path) -> None:
    """Verify that daily-note entry line numbers are real file positions, not section-local."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    # Layout:
    # Line 1: # Daily Memory: 2026-04-08
    # Line 2: (blank)
    # Line 3: ## Events
    # Line 4: (blank)
    # Line 5: - [test] First event [evt:ev1]
    # Line 6: (blank)
    # Line 7: ## Signals
    # Line 8: (blank)
    # Line 9: - [pref] Second signal [sig:sg1]
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Events

- [test] First event [evt:ev1]

## Signals

- [pref] Second signal [sig:sg1]
""",
        encoding="utf-8",
    )

    entries = _extract_daily_note_entries(paths)
    assert len(entries) == 2

    # First event is on line 5.
    # section_start=3, first non-blank body index=1 (line 4 blank, line 5 entry)
    # real_lineno = 3 + 1 + 1 = 5
    first_entry = next(e for e in entries if "First event" in e.content)
    assert first_entry.line_number == 5, f"Expected 5, got {first_entry.line_number}"

    # Second signal is on line 9.
    # section_start=7, first non-blank body index=1 (line 8 blank, line 9 entry)
    # real_lineno = 7 + 1 + 1 = 9
    second_entry = next(e for e in entries if "Second signal" in e.content)
    assert second_entry.line_number == 9, f"Expected 9, got {second_entry.line_number}"


# ---------------------------------------------------------------------------
# Scope-aware semantic search (Phase 16)
# ---------------------------------------------------------------------------


def test_search_semantic_index_returns_shared_scope_for_shared_authority_hit(tmp_path: Path) -> None:
    """Authority hits with scope:shared return MemoryScope.SHARED."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Team uses shared memory for cross-agent context _(\id: shared001; status: active; scope: shared)_
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "shared memory cross-agent", limit=5)

    assert len(result.hits) >= 1
    top = result.hits[0]
    assert top.kind == MemoryDocumentKind.AUTHORITY
    assert top.scope == MemoryScope.SHARED
    assert top.authority_entry_id == "shared001"


def test_search_semantic_index_returns_local_scope_for_local_authority_hit(tmp_path: Path) -> None:
    """Authority hits with scope:local return MemoryScope.LOCAL."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- User prefers dark mode theme _(\id: local001; status: active; scope: local)_
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "dark mode theme", limit=5)

    assert len(result.hits) >= 1
    top = result.hits[0]
    assert top.kind == MemoryDocumentKind.AUTHORITY
    assert top.scope == MemoryScope.LOCAL
    assert top.authority_entry_id == "local001"


def test_search_semantic_index_defaults_to_local_for_legacy_entries(tmp_path: Path) -> None:
    """Legacy authority entries without explicit scope default to MemoryScope.LOCAL."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    # Legacy format without scope field
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Legacy entry without scope field _(\id: legacy001; status: active)_
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "legacy entry", limit=5)

    assert len(result.hits) >= 1
    top = result.hits[0]
    assert top.kind == MemoryDocumentKind.AUTHORITY
    # Legacy entries without scope metadata default to local
    assert top.scope == MemoryScope.LOCAL


def test_search_semantic_index_daily_notes_have_no_scope(tmp_path: Path) -> None:
    """Daily note entries are not authority entries and have no scope."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Authority fact _(\id: fact001; status: active)_
""",
        encoding="utf-8",
    )
    note_path = ensure_daily_note(paths, date(2026, 4, 10))
    note_path.write_text(
        """# Daily Memory: 2026-04-10

## Signals
- [preference] User mentioned python projects [sig:sig001]
""",
        encoding="utf-8",
    )

    result = search_semantic_index(paths, "python projects", limit=5)

    # Find the daily note hit
    daily_hits = [h for h in result.hits if h.kind == MemoryDocumentKind.DAILY_NOTE]
    assert len(daily_hits) >= 1
    daily_top = daily_hits[0]
    # Daily notes are not authority entries, scope should be None
    assert daily_top.scope is None


def test_search_semantic_index_scope_in_index_record(tmp_path: Path) -> None:
    """Scope is persisted in the semantic index JSON records."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        r"""# ControlMesh Memory v2

## Durable Memory

### Fact
- Shared entry _(\id: shr001; status: active; scope: shared)_
- Local entry _(\id: loc001; status: active; scope: local)_
""",
        encoding="utf-8",
    )
    sync_semantic_index(paths)

    index_path = _semantic_index_path(paths)
    data = json.loads(index_path.read_text(encoding="utf-8"))

    entries_by_id = {e["authority_entry_id"]: e for e in data["entries"] if e.get("authority_entry_id")}

    assert entries_by_id["shr001"]["scope"] == "shared"
    assert entries_by_id["loc001"]["scope"] == "local"
