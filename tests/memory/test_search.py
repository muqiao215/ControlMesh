"""Tests for the local SQLite FTS5 memory index."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.memory.search import search_memory_index, sync_memory_index
from controlmesh.memory.store import append_dream_entry, ensure_daily_note, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def test_sync_memory_index_indexes_authority_dreams_and_daily_notes(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        """# ControlMesh Memory v2

## Durable Memory

### Fact
- File-backed memory remains canonical.
""",
        encoding="utf-8",
    )
    append_dream_entry(
        paths,
        title="Cross-day synthesis",
        body="Dreaming sweep should stay deterministic and local.",
        dreamed_at=datetime(2026, 4, 8, 4, 0, 0, tzinfo=UTC),
    )
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Signals
- Preserve local file-backed authority.

## Promotion Candidates
- [decision] File-backed memory remains canonical.
""",
        encoding="utf-8",
    )

    stats = sync_memory_index(paths)
    result = search_memory_index(paths, "canonical", limit=5, refresh=False)

    assert paths.memory_search_index_path.exists()
    assert stats.inserted_count == 3
    assert stats.updated_count == 0
    assert stats.deleted_count == 0
    assert {hit.kind for hit in result.hits} == {"authority", "daily-note"}
    assert result.hits[0].source_path == "MEMORY.md"
    assert "canonical" in result.hits[0].snippet.lower()


def test_sync_memory_index_updates_by_content_hash_and_prunes_deleted_files(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    first_note = ensure_daily_note(paths, date(2026, 4, 7))
    second_note = ensure_daily_note(paths, date(2026, 4, 8))
    first_note.write_text(
        """# Daily Memory: 2026-04-07

## Signals
- Old local retrieval note.
""",
        encoding="utf-8",
    )
    second_note.write_text(
        """# Daily Memory: 2026-04-08

## Signals
- First local search draft.
""",
        encoding="utf-8",
    )

    initial = sync_memory_index(paths)
    second_note.write_text(
        """# Daily Memory: 2026-04-08

## Signals
- Updated deterministic search draft.
""",
        encoding="utf-8",
    )
    first_note.unlink()

    updated = sync_memory_index(paths)
    result = search_memory_index(paths, "deterministic", limit=5, refresh=False)

    assert initial.inserted_count == 4
    assert updated.updated_count == 1
    assert updated.deleted_count == 1
    assert updated.unchanged_count == 2
    assert [hit.source_path for hit in result.hits] == ["memory/2026-04-08.md"]


def test_search_memory_index_returns_empty_hits_for_invalid_fts_query(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    for query in ['"', "(", "foo OR"]:
        result = search_memory_index(paths, query, refresh=False)
        assert result.query == query
        assert result.hits == []
