"""Tests for deterministic promotion candidate parsing and application."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from controlmesh.memory.commands import (
    apply_daily_note_promotions,
    preview_daily_note_promotions,
)
from controlmesh.memory.compat import (
    _COMPAT_END_MARKER,
    _COMPAT_START_MARKER,
    sync_authority_to_legacy_mainmemory,
)
from controlmesh.memory.models import LifecycleStatus
from controlmesh.memory.promotion import (
    parse_authority_entry,
    parse_authority_entry_metadata,
    parse_promotion_candidates,
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


def test_parse_promotion_candidates_from_explicit_section() -> None:
    note = """# Daily Memory: 2026-04-08

## Signals
- Routine observation

## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
- [preference score=0.90] Prefer OpenClaw-style split memory, but adapted for ControlMesh.
"""

    candidates = parse_promotion_candidates(
        note,
        source_path=Path("memory/2026-04-08.md"),
        source_date=date(2026, 4, 8),
    )

    assert [candidate.category for candidate in candidates] == ["decision", "preference"]
    assert candidates[0].content == "Keep canonical authority file-backed and human-readable."
    assert candidates[1].score == 0.9
    assert candidates[0].line_start == 7


def test_preview_and_apply_daily_note_promotions(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
- [preference score=0.70] Prefer OpenClaw-style split memory, but adapted for ControlMesh.
""",
        encoding="utf-8",
    )

    preview = preview_daily_note_promotions(paths, date(2026, 4, 8), min_score=0.8)

    assert len(preview.selected) == 1
    assert preview.selected[0].category == "decision"
    assert preview.skipped_low_score == 1

    result = apply_daily_note_promotions(paths, date(2026, 4, 8), min_score=0.8)
    assert result.applied_count == 1
    assert result.skipped_existing == 0

    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "Keep canonical authority file-backed and human-readable." in memory_text
    assert "memory/2026-04-08.md" in memory_text

    second = apply_daily_note_promotions(paths, date(2026, 4, 8), min_score=0.8)
    assert second.applied_count == 0
    assert second.skipped_existing == 1

    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert _COMPAT_START_MARKER in legacy_text
    assert _COMPAT_END_MARKER in legacy_text
    assert "Keep canonical authority file-backed and human-readable." in legacy_text


def test_sync_authority_to_legacy_mainmemory_replaces_existing_compat_block(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.memory_system_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.mainmemory_path.write_text(
        "# Main Memory\n\n"
        "--- MEMORY V2 COMPAT START ---\nold mirror\n--- MEMORY V2 COMPAT END ---\n\n"
        "--- SHARED KNOWLEDGE START ---\nshared\n--- SHARED KNOWLEDGE END ---\n",
        encoding="utf-8",
    )

    written = sync_authority_to_legacy_mainmemory(
        paths,
        authority_text="# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n- New mirror.\n",
    )

    assert written is True
    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert "old mirror" not in legacy_text
    assert "New mirror." in legacy_text
    assert "shared" in legacy_text
    assert legacy_text.count(_COMPAT_START_MARKER) == 1
    assert legacy_text.count(_COMPAT_END_MARKER) == 1


def test_sync_authority_to_legacy_mainmemory_creates_file_on_first_compat_sync(
    tmp_path: Path,
) -> None:
    paths = _make_paths(tmp_path)
    assert not paths.mainmemory_path.exists()

    written = sync_authority_to_legacy_mainmemory(
        paths,
        authority_text="# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n- First compat sync.\n",
    )

    assert written is True
    assert paths.mainmemory_path.exists()
    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert _COMPAT_START_MARKER in legacy_text
    assert "First compat sync." in legacy_text


def test_sync_authority_to_legacy_mainmemory_removes_empty_compat_block(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.memory_system_dir.mkdir(parents=True, exist_ok=True)
    paths.mainmemory_path.write_text(
        "# Main Memory\n\n"
        "--- MEMORY V2 COMPAT START ---\nold mirror\n--- MEMORY V2 COMPAT END ---\n",
        encoding="utf-8",
    )

    written = sync_authority_to_legacy_mainmemory(
        paths,
        authority_text="# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n",
    )

    assert written is True
    legacy_text = paths.mainmemory_path.read_text(encoding="utf-8")
    assert _COMPAT_START_MARKER not in legacy_text
    assert "old mirror" not in legacy_text


def test_parse_authority_entry_metadata_with_full_metadata() -> None:
    """Parse a metadata-bearing authority entry correctly."""
    line = "- Keep local memory canonical. _(id: abc123; status: active; source: memory/2026-04-08.md#L7; promoted: 2026-04-08)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "abc123"
    assert meta.status == LifecycleStatus.ACTIVE
    assert meta.source_ref == "memory/2026-04-08.md#L7"
    assert meta.promoted_at == "2026-04-08"
    assert meta.superseded_by is None


def test_parse_authority_entry_metadata_superseded() -> None:
    """Parse a superseded authority entry correctly."""
    line = "- Old decision. _(id: def456; status: superseded; superseded_by: xyz789; source: memory/2026-04-10.md#L3; promoted: 2026-04-10)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "def456"
    assert meta.status == LifecycleStatus.SUPERSEDED
    assert meta.superseded_by == "xyz789"
    assert meta.source_ref == "memory/2026-04-10.md#L3"


def test_parse_authority_entry_metadata_deprecated() -> None:
    """Parse a deprecated authority entry correctly."""
    line = "- Deprecated preference. _(id: ghi101; status: deprecated; source: memory/2026-03-15.md#L12; promoted: 2026-03-15)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "ghi101"
    assert meta.status == LifecycleStatus.DEPRECATED
    assert meta.promoted_at == "2026-03-15"


def test_parse_authority_entry_roundtrip() -> None:
    """Round-trip: parse content and metadata from rendered entry."""
    line = "- Keep local memory canonical. _(id: abc123; status: active; source: memory/2026-04-08.md#L7; promoted: 2026-04-08)_"

    result = parse_authority_entry(line)

    assert result is not None
    content, meta = result
    assert content == "Keep local memory canonical."
    assert meta.entry_id == "abc123"
    assert meta.status == LifecycleStatus.ACTIVE


def test_parse_authority_entry_returns_none_for_legacy_format() -> None:
    """Legacy entries without new metadata format parse with sensible defaults."""
    # Legacy format had source and promoted but no id or status
    legacy_line = "- Legacy fact. _(source: memory/2026-04-08.md; promoted: 2026-04-08)_"

    meta = parse_authority_entry_metadata(legacy_line)
    result = parse_authority_entry(legacy_line)

    # Legacy entries parse successfully with sensible defaults
    assert meta is not None
    assert meta.entry_id is None
    assert meta.status == LifecycleStatus.ACTIVE
    assert meta.source_ref == "memory/2026-04-08.md"
    assert meta.promoted_at == "2026-04-08"
    assert meta.superseded_by is None

    # parse_authority_entry also returns content and metadata
    assert result is not None
    content, parsed_meta = result
    assert content == "Legacy fact."
    assert parsed_meta.status == LifecycleStatus.ACTIVE
    assert parsed_meta.entry_id is None


def test_parse_authority_entry_returns_none_for_non_entry_lines() -> None:
    """Non-entry lines return None."""
    assert parse_authority_entry_metadata("## Decision") is None
    assert parse_authority_entry_metadata("- plain bullet without metadata") is None
    assert parse_authority_entry_metadata("") is None


def test_parse_authority_entry_metadata_disputed() -> None:
    """Parse a disputed authority entry correctly."""
    line = "- Disputed claim. _(id: jkl202; status: disputed; source: memory/2026-04-12.md#L5; promoted: 2026-04-12)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.status == LifecycleStatus.DISPUTED
    assert meta.entry_id == "jkl202"


def test_promoted_entry_contains_id_and_status(tmp_path: Path) -> None:
    """Applied entries include id and status in metadata."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 8))

    assert result.applied_count == 1
    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")

    # Entry should contain id and status markers
    assert "id:" in memory_text
    assert "status: active" in memory_text
    assert "source: memory/2026-04-08.md" in memory_text
    assert "promoted: 2026-04-08" in memory_text

    # Should be parseable back
    for line in memory_text.splitlines():
        if line.startswith("- ") and "_(" in line:
            parsed = parse_authority_entry(line)
            assert parsed is not None
            content, meta = parsed
            assert "Keep canonical authority file-backed and human-readable." in content
            assert meta.entry_id is not None
            assert meta.status == LifecycleStatus.ACTIVE


def test_existing_promotion_flow_still_works(tmp_path: Path) -> None:
    """Existing promotion/dreaming flows still work with simple entries."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 8))
    note_path.write_text(
        """# Daily Memory: 2026-04-08

## Promotion Candidates
- [fact] Simple fact without score.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 8))

    assert result.applied_count == 1
    assert result.skipped_existing == 0

    # Verify round-trip works
    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")
    for line in memory_text.splitlines():
        if "Simple fact" in line:
            parsed = parse_authority_entry(line)
            assert parsed is not None
            content, meta = parsed
            assert "Simple fact" in content
            assert meta.status == LifecycleStatus.ACTIVE
