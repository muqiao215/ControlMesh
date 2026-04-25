"""Tests for deterministic promotion candidate parsing and application."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from controlmesh.memory.commands import (
    _count_authority_entries,
    apply_daily_note_promotions,
    preview_daily_note_promotions,
    render_memory_review,
)
from controlmesh.memory.compat import (
    _COMPAT_END_MARKER,
    _COMPAT_START_MARKER,
    sync_authority_to_legacy_mainmemory,
)
from controlmesh.memory.models import LifecycleStatus, MemoryCategory, MemoryScope
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
    line = "- Keep local memory canonical. _(id: abc123; status: active; scope: local; source: memory/2026-04-08.md#L7; promoted: 2026-04-08)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "abc123"
    assert meta.status == LifecycleStatus.ACTIVE
    assert meta.scope == MemoryScope.LOCAL
    assert meta.source_ref == "memory/2026-04-08.md#L7"
    assert meta.promoted_at == "2026-04-08"
    assert meta.superseded_by is None


def test_parse_authority_entry_metadata_superseded() -> None:
    """Parse a superseded authority entry correctly."""
    line = "- Old decision. _(id: def456; status: superseded; scope: local; superseded_by: xyz789; source: memory/2026-04-10.md#L3; promoted: 2026-04-10)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "def456"
    assert meta.status == LifecycleStatus.SUPERSEDED
    assert meta.scope == MemoryScope.LOCAL
    assert meta.superseded_by == "xyz789"
    assert meta.source_ref == "memory/2026-04-10.md#L3"


def test_parse_authority_entry_metadata_deprecated() -> None:
    """Parse a deprecated authority entry correctly."""
    line = "- Deprecated preference. _(id: ghi101; status: deprecated; scope: local; source: memory/2026-03-15.md#L12; promoted: 2026-03-15)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "ghi101"
    assert meta.status == LifecycleStatus.DEPRECATED
    assert meta.scope == MemoryScope.LOCAL
    assert meta.promoted_at == "2026-03-15"


def test_parse_authority_entry_roundtrip() -> None:
    """Round-trip: parse content and metadata from rendered entry."""
    line = "- Keep local memory canonical. _(id: abc123; status: active; scope: local; source: memory/2026-04-08.md#L7; promoted: 2026-04-08)_"

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
    assert meta.scope == MemoryScope.LOCAL
    assert meta.source_ref == "memory/2026-04-08.md"
    assert meta.promoted_at == "2026-04-08"
    assert meta.superseded_by is None

    # parse_authority_entry also returns content and metadata
    assert result is not None
    content, parsed_meta = result
    assert content == "Legacy fact."
    assert parsed_meta.status == LifecycleStatus.ACTIVE
    assert parsed_meta.entry_id is None
    assert parsed_meta.scope == MemoryScope.LOCAL


def test_parse_authority_entry_returns_none_for_non_entry_lines() -> None:
    """Non-entry lines return None."""
    assert parse_authority_entry_metadata("## Decision") is None
    assert parse_authority_entry_metadata("- plain bullet without metadata") is None
    assert parse_authority_entry_metadata("") is None


def test_parse_authority_entry_metadata_disputed() -> None:
    """Parse a disputed authority entry correctly."""
    line = "- Disputed claim. _(id: jkl202; status: disputed; scope: local; source: memory/2026-04-12.md#L5; promoted: 2026-04-12)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.status == LifecycleStatus.DISPUTED
    assert meta.entry_id == "jkl202"
    assert meta.scope == MemoryScope.LOCAL


def test_promoted_entry_contains_id_and_status(tmp_path: Path) -> None:
    """Applied entries include id, status, and scope in metadata."""
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

    # Entry should contain id, status, and scope markers
    assert "id:" in memory_text
    assert "status: active" in memory_text
    assert "scope: local" in memory_text
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
            assert meta.scope == MemoryScope.LOCAL


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
            assert meta.scope == MemoryScope.LOCAL


def test_parse_authority_entry_with_shared_scope() -> None:
    """Parse an entry with shared scope correctly."""
    line = "- Shared team decision. _(id: shared123; status: active; scope: shared; source: memory/2026-04-15.md#L3; promoted: 2026-04-15)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "shared123"
    assert meta.status == LifecycleStatus.ACTIVE
    assert meta.scope == MemoryScope.SHARED
    assert meta.source_ref == "memory/2026-04-15.md#L3"
    assert meta.promoted_at == "2026-04-15"


def test_parse_authority_entry_with_local_scope() -> None:
    """Parse an entry with local scope correctly."""
    line = "- Local preference. _(id: local456; status: active; scope: local; source: memory/2026-04-16.md#L5; promoted: 2026-04-16)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.entry_id == "local456"
    assert meta.status == LifecycleStatus.ACTIVE
    assert meta.scope == MemoryScope.LOCAL
    assert meta.source_ref == "memory/2026-04-16.md#L5"
    assert meta.promoted_at == "2026-04-16"


def test_parse_authority_entry_unknown_scope_defaults_to_local() -> None:
    """Entries with unknown scope value default to LOCAL for safety."""
    line = "- Unknown scope entry. _(id: unk789; status: active; scope: unknown; source: memory/2026-04-17.md#L2; promoted: 2026-04-17)_"

    meta = parse_authority_entry_metadata(line)

    assert meta is not None
    assert meta.scope == MemoryScope.LOCAL


def test_count_authority_entries_filters_by_scope() -> None:
    """Authority entry counting respects scope filter."""
    authority_text = """# ControlMesh Memory v2

## Durable Memory

### Fact

- Local fact. _(id: f001; status: active; scope: local; source: memory/2026-04-01.md#L5; promoted: 2026-04-01)_
- Shared fact. _(id: f002; status: active; scope: shared; source: memory/2026-04-02.md#L5; promoted: 2026-04-02)_
- Another local. _(id: f003; status: active; scope: local; source: memory/2026-04-03.md#L5; promoted: 2026-04-03)_

### Decision

- Shared decision. _(id: d001; status: active; scope: shared; source: memory/2026-04-04.md#L5; promoted: 2026-04-04)_
"""
    # No filter - should count all
    counts_all = _count_authority_entries(authority_text)
    assert counts_all.get("Fact", 0) == 3
    assert counts_all.get("Decision", 0) == 1

    # Local scope filter
    counts_local = _count_authority_entries(authority_text, scope=MemoryScope.LOCAL)
    assert counts_local.get("Fact", 0) == 2
    assert counts_local.get("Decision", 0) == 0

    # Shared scope filter
    counts_shared = _count_authority_entries(authority_text, scope=MemoryScope.SHARED)
    assert counts_shared.get("Fact", 0) == 1
    assert counts_shared.get("Decision", 0) == 1


def test_count_authority_entries_legacy_entries_default_to_local() -> None:
    """Legacy entries without scope are counted as LOCAL."""
    authority_text = """# ControlMesh Memory v2

## Durable Memory

### Fact

- New local fact. _(id: f001; status: active; scope: local; source: memory/2026-04-01.md#L5; promoted: 2026-04-01)_
- Legacy fact. _(source: memory/2026-04-02.md; promoted: 2026-04-02)_
"""
    counts_all = _count_authority_entries(authority_text)
    assert counts_all.get("Fact", 0) == 2

    counts_local = _count_authority_entries(authority_text, scope=MemoryScope.LOCAL)
    assert counts_local.get("Fact", 0) == 2

    counts_shared = _count_authority_entries(authority_text, scope=MemoryScope.SHARED)
    assert counts_shared.get("Fact", 0) == 0


# --- Phase 10: Lifecycle mutation tests ---


def test_deprecate_authority_entry_by_id(tmp_path: Path) -> None:
    """Deprecating an active entry updates its status to deprecated."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Inject an active entry directly into MEMORY.md
    entry_line = "- Fact entry for deprecation. _(id: dep001; status: active; scope: local; source: memory/2026-04-20.md#L3; promoted: 2026-04-20)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "dep001")
    assert success is True
    assert scope == MemoryScope.LOCAL

    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "status: deprecated" in updated
    assert "id: dep001" in updated
    assert "Fact entry for deprecation" in updated


def test_deprecate_authority_entry_not_found(tmp_path: Path) -> None:
    """Deprecating a non-existent entry returns False with no scope."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "nonexistent")
    assert success is False
    assert scope is None


def test_deprecate_authority_entry_idempotent(tmp_path: Path) -> None:
    """Re-deprecating an already-deprecated entry succeeds (idempotent) and returns scope."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Fact entry. _(id: dep002; status: deprecated; scope: local; source: memory/2026-04-20.md#L3; promoted: 2026-04-20)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "dep002")
    assert success is True
    assert scope == MemoryScope.LOCAL

    # Content unchanged
    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "status: deprecated" in updated


def test_dispute_authority_entry_by_id(tmp_path: Path) -> None:
    """Disputing an active entry updates its status to disputed."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Fact entry for disputing. _(id: dis001; status: active; scope: local; source: memory/2026-04-21.md#L3; promoted: 2026-04-21)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "dis001")
    assert success is True
    assert scope == MemoryScope.LOCAL

    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "status: disputed" in updated
    assert "id: dis001" in updated
    assert "Fact entry for disputing" in updated


def test_dispute_authority_entry_not_found(tmp_path: Path) -> None:
    """Disputing a non-existent entry returns False with no scope."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "nonexistent")
    assert success is False
    assert scope is None


def test_dispute_authority_entry_idempotent(tmp_path: Path) -> None:
    """Re-disputing an already-disputed entry succeeds (idempotent) and returns scope."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Fact entry. _(id: dis002; status: disputed; scope: local; source: memory/2026-04-21.md#L3; promoted: 2026-04-21)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "dis002")
    assert success is True
    assert scope == MemoryScope.LOCAL

    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "status: disputed" in updated


def test_supersede_authority_entry(tmp_path: Path) -> None:
    """Superseding an entry sets status to superseded and records superseded_by."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Old fact being superseded. _(id: sup001; status: active; scope: local; source: memory/2026-04-22.md#L3; promoted: 2026-04-22)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "sup001", "new001")
    assert success is True
    assert scope == MemoryScope.LOCAL

    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "status: superseded" in updated
    assert "superseded_by: new001" in updated
    assert "id: sup001" in updated
    assert "Old fact being superseded" in updated


def test_supersede_authority_entry_not_found(tmp_path: Path) -> None:
    """Superseding a non-existent entry returns False with no scope."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "nonexistent", "new001")
    assert success is False
    assert scope is None


def test_supersede_authority_entry_idempotent(tmp_path: Path) -> None:
    """Re-superseding with the same new id succeeds (idempotent) and returns scope."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Old fact. _(id: sup002; status: superseded; scope: local; superseded_by: new002; source: memory/2026-04-22.md#L3; promoted: 2026-04-22)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "sup002", "new002")
    assert success is True
    assert scope == MemoryScope.LOCAL

    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "status: superseded" in updated
    assert "superseded_by: new002" in updated


def test_supersede_authority_entry_updates_superseded_by_field(tmp_path: Path) -> None:
    """Superseding with a different new id updates the superseded_by field."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Old fact. _(id: sup003; status: superseded; scope: local; superseded_by: old_new; source: memory/2026-04-22.md#L3; promoted: 2026-04-22)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "sup003", "updated_new")
    assert success is True
    assert scope == MemoryScope.LOCAL

    updated = paths.authority_memory_path.read_text(encoding="utf-8")
    assert "superseded_by: updated_new" in updated
    assert "superseded_by: old_new" not in updated


# --- Phase 11: Scope-aware promotion tests ---


def test_parse_promotion_candidates_with_explicit_shared_scope(tmp_path: Path) -> None:
    """Candidates with explicit [category shared] format parse scope correctly."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] Team uses shared memory for cross-agent context.
- [fact shared] Project deadline is end of Q2.
""",
        encoding="utf-8",
    )

    candidates = parse_promotion_candidates(
        note_path.read_text(encoding="utf-8"),
        source_path=note_path.relative_to(paths.workspace),
        source_date=date(2026, 4, 25),
    )

    assert len(candidates) == 2
    assert all(c.scope == MemoryScope.SHARED for c in candidates)
    assert candidates[0].category == MemoryCategory.DECISION
    assert candidates[1].category == MemoryCategory.FACT
    assert "cross-agent" in candidates[0].content


def test_parse_promotion_candidates_with_explicit_local_scope(tmp_path: Path) -> None:
    """Candidates with explicit [category local] format parse scope correctly."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [preference local] User prefers dark mode.
""",
        encoding="utf-8",
    )

    candidates = parse_promotion_candidates(
        note_path.read_text(encoding="utf-8"),
        source_path=note_path.relative_to(paths.workspace),
        source_date=date(2026, 4, 25),
    )

    assert len(candidates) == 1
    assert candidates[0].scope == MemoryScope.LOCAL
    assert candidates[0].category == MemoryCategory.PREFERENCE


def test_parse_promotion_candidates_defaults_to_local_when_no_scope(tmp_path: Path) -> None:
    """Legacy candidates without explicit scope default to LOCAL scope."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision] Keep authority memory file-backed.
- [fact] Simple fact without scope annotation.
""",
        encoding="utf-8",
    )

    candidates = parse_promotion_candidates(
        note_path.read_text(encoding="utf-8"),
        source_path=note_path.relative_to(paths.workspace),
        source_date=date(2026, 4, 25),
    )

    assert len(candidates) == 2
    assert all(c.scope == MemoryScope.LOCAL for c in candidates)


def test_parse_promotion_candidates_shared_with_score(tmp_path: Path) -> None:
    """Candidates with [category shared score=X] format parse correctly."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared score=0.95] Important team decision to share.
""",
        encoding="utf-8",
    )

    candidates = parse_promotion_candidates(
        note_path.read_text(encoding="utf-8"),
        source_path=note_path.relative_to(paths.workspace),
        source_date=date(2026, 4, 25),
    )

    assert len(candidates) == 1
    assert candidates[0].scope == MemoryScope.SHARED
    assert candidates[0].score == 0.95
    assert candidates[0].category == MemoryCategory.DECISION


def test_apply_promotes_entry_with_scope_preserved(tmp_path: Path) -> None:
    """Applied entries preserve explicit scope in rendered authority metadata."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] Shared decision should retain shared scope.
- [fact local] Local fact should retain local scope.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))
    assert result.applied_count == 2

    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")

    # Verify shared entry has scope: shared
    shared_found = False
    local_found = False
    for line in memory_text.splitlines():
        if "Shared decision should retain shared scope" in line:
            assert "scope: shared" in line
            shared_found = True
        if "Local fact should retain local scope" in line:
            assert "scope: local" in line
            local_found = True

    assert shared_found, "Shared decision entry not found in authority memory"
    assert local_found, "Local fact entry not found in authority memory"


def test_apply_shared_entry_round_trip(tmp_path: Path) -> None:
    """A promoted shared entry can be parsed back with correct scope."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [preference shared] Team preference for standup time.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))
    assert result.applied_count == 1

    # Read and parse the authority entry
    memory_text = paths.authority_memory_path.read_text(encoding="utf-8")
    for line in memory_text.splitlines():
        if "Team preference for standup time" in line:
            parsed = parse_authority_entry(line)
            assert parsed is not None
            content, meta = parsed
            assert meta.scope == MemoryScope.SHARED
            assert "Team preference for standup time" in content
            return

    raise AssertionError("Authority entry not found")


def test_preview_shows_scope_for_shared_candidates(tmp_path: Path) -> None:
    """Preview output includes scope indicator for shared candidates."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] This is a shared decision.
- [fact] This is a local fact (no scope shown).
""",
        encoding="utf-8",
    )

    from controlmesh.memory.commands import preview_daily_note_promotions

    preview = preview_daily_note_promotions(paths, date(2026, 4, 25))

    assert len(preview.selected) == 2
    shared_cand = next(c for c in preview.selected if "shared" in c.content.lower())
    local_cand = next(c for c in preview.selected if "local" in c.content.lower())

    assert shared_cand.scope == MemoryScope.SHARED
    assert local_cand.scope == MemoryScope.LOCAL


# --- Phase 12: Scope-aware promotion audit/review ---


def test_apply_writes_scope_into_promotion_log(tmp_path: Path) -> None:
    """Applied entries record scope in the promotion log."""
    import json

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] Shared team decision to promote.
- [fact local] Local fact to keep private.
- [preference] Default scope preference (should be local).
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))
    assert result.applied_count == 3

    log_text = paths.memory_promotion_log_path.read_text(encoding="utf-8")
    log = json.loads(log_text)

    scopes = {key: entry.get("scope") for key, entry in log.items()}
    assert "shared" in scopes.values(), f"Expected 'shared' in scopes: {scopes}"
    assert "local" in scopes.values(), f"Expected 'local' in scopes: {scopes}"
    # Default scope should be local
    local_count = sum(1 for s in scopes.values() if s == "local")
    assert local_count == 2, f"Expected 2 local entries, got {local_count}"


def test_render_memory_review_shows_shared_scope_for_shared_promotions(tmp_path: Path) -> None:
    """render_memory_review shows scope for shared promotions in recent section."""

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] Shared decision should show scope.
""",
        encoding="utf-8",
    )

    apply_daily_note_promotions(paths, date(2026, 4, 25))

    review = render_memory_review(paths)
    assert "shared" in review, f"Expected 'shared' in review output: {review}"
    assert "Shared decision should show scope" in review


def test_render_memory_review_shows_local_scope_for_local_promotions(tmp_path: Path) -> None:
    """render_memory_review shows local scope explicitly for local/default promotions."""

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [fact local] Local fact should not show scope label.
- [decision] Default scope decision also concise.
""",
        encoding="utf-8",
    )

    apply_daily_note_promotions(paths, date(2026, 4, 25))

    review = render_memory_review(paths)
    assert "Local fact should not show scope label" in review
    assert "Default scope decision also concise" in review
    assert "(local, promoted 2026-04-25)" in review


def test_render_memory_review_shows_shared_scope_for_open_candidates(tmp_path: Path) -> None:
    """Today's open candidates show shared scope when explicitly marked shared."""
    from datetime import UTC, datetime

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, today)
    note_path.write_text(
        f"""# Daily Memory: {today.isoformat()}

## Open Candidates
- [decision shared] Shared open candidate should show scope.
""",
        encoding="utf-8",
    )

    review = render_memory_review(paths)
    assert "Today's Open Candidates (1)" in review
    assert "Shared open candidate should show scope" in review
    assert "(shared)" in review


def test_render_memory_review_shows_local_scope_for_open_candidates(tmp_path: Path) -> None:
    """Today's open candidates show local scope for local/default candidate lines."""
    from datetime import UTC, datetime

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, today)
    note_path.write_text(
        f"""# Daily Memory: {today.isoformat()}

## Open Candidates
- [fact local] Local open candidate should show scope.
- [preference] Default local candidate should show scope too.
""",
        encoding="utf-8",
    )

    review = render_memory_review(paths)
    assert "Local open candidate should show scope" in review
    assert "Default local candidate should show scope too" in review
    assert review.count("(local)") >= 2


def test_render_memory_review_scope_local_filters_recent_promotions_and_open_candidates(
    tmp_path: Path,
) -> None:
    """Scoped local review keeps local/default items across recent and open sections."""
    import json
    from datetime import UTC, datetime

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.memory_promotion_log_path.write_text(
        json.dumps(
            {
                "legacy001": {
                    "category": "fact",
                    "content": "Legacy local promotion stays visible",
                    "promoted_on": "2026-04-24",
                },
                "shared001": {
                    "category": "decision",
                    "content": "Shared promotion is filtered out",
                    "promoted_on": "2026-04-25",
                    "scope": "shared",
                },
                "local001": {
                    "category": "preference",
                    "content": "Explicit local promotion stays visible",
                    "promoted_on": "2026-04-26",
                    "scope": "local",
                },
            }
        ),
        encoding="utf-8",
    )

    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, today)
    note_path.write_text(
        f"""# Daily Memory: {today.isoformat()}

## Open Candidates
- [preference] Default local candidate stays visible.
- [fact shared] Shared open candidate is filtered out.
- [decision local] Explicit local candidate stays visible.
""",
        encoding="utf-8",
    )

    review = render_memory_review(paths, scope=MemoryScope.LOCAL)
    assert "Legacy local promotion stays visible" in review
    assert "Explicit local promotion stays visible" in review
    assert "Shared promotion is filtered out" not in review
    assert "Today's Open Candidates (2)" in review
    assert "Default local candidate stays visible." in review
    assert "Explicit local candidate stays visible." in review
    assert "Shared open candidate is filtered out." not in review


def test_render_memory_review_scope_shared_filters_recent_promotions_and_open_candidates(
    tmp_path: Path,
) -> None:
    """Scoped shared review keeps only shared items across recent and open sections."""
    import json
    from datetime import UTC, datetime

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.memory_promotion_log_path.write_text(
        json.dumps(
            {
                "legacy001": {
                    "category": "fact",
                    "content": "Legacy local promotion is filtered out",
                    "promoted_on": "2026-04-24",
                },
                "local001": {
                    "category": "preference",
                    "content": "Explicit local promotion is filtered out",
                    "promoted_on": "2026-04-25",
                    "scope": "local",
                },
                "shared001": {
                    "category": "decision",
                    "content": "Shared promotion stays visible",
                    "promoted_on": "2026-04-26",
                    "scope": "shared",
                },
            }
        ),
        encoding="utf-8",
    )

    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, today)
    note_path.write_text(
        f"""# Daily Memory: {today.isoformat()}

## Open Candidates
- [preference] Default local candidate is filtered out.
- [decision local] Explicit local candidate is filtered out.
- [fact shared] Shared open candidate stays visible.
""",
        encoding="utf-8",
    )

    review = render_memory_review(paths, scope=MemoryScope.SHARED)
    assert "Shared promotion stays visible" in review
    assert "Legacy local promotion is filtered out" not in review
    assert "Explicit local promotion is filtered out" not in review
    assert "Today's Open Candidates (1)" in review
    assert "Shared open candidate stays visible." in review
    assert "Default local candidate is filtered out." not in review
    assert "Explicit local candidate is filtered out." not in review


def test_render_memory_review_scope_shared_omits_empty_recent_and_open_sections(
    tmp_path: Path,
) -> None:
    """Scoped review omits empty recent/open sections after filtering."""
    import json
    from datetime import UTC, datetime

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.memory_promotion_log_path.write_text(
        json.dumps(
            {
                "legacy001": {
                    "category": "fact",
                    "content": "Legacy local promotion only",
                    "promoted_on": "2026-04-24",
                }
            }
        ),
        encoding="utf-8",
    )

    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(paths, today)
    note_path.write_text(
        f"""# Daily Memory: {today.isoformat()}

## Open Candidates
- [preference] Default local candidate only.
""",
        encoding="utf-8",
    )

    review = render_memory_review(paths, scope=MemoryScope.SHARED)
    assert review.strip() == "## Memory Review (scope: shared)"
    assert "### Recent Promotions" not in review
    assert "### Today's Open Candidates" not in review


def test_legacy_promotion_log_without_scope_still_loads(tmp_path: Path) -> None:
    """Promotion log entries without scope field are handled gracefully."""
    import json

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Write a pre-Phase-12 style promotion log entry without scope
    legacy_log = {
        "abc123": {
            "category": "fact",
            "content": "Legacy fact before Phase 12",
            "source_path": "memory/2026-04-01.md",
            "source_date": "2026-04-01",
            "promoted_on": "2026-04-01",
        },
        "def456": {
            "category": "decision",
            "content": "Another legacy decision",
            "source_path": "memory/2026-04-02.md",
            "source_date": "2026-04-02",
            "promoted_on": "2026-04-02",
            # No scope field
        },
    }
    paths.memory_promotion_log_path.write_text(json.dumps(legacy_log), encoding="utf-8")

    # Load log via apply_candidates path - should not raise
    from controlmesh.memory.models import PromotionCandidate
    from controlmesh.memory.promotion import preview_candidates

    # Verify the log can be read (used by preview_candidates)
    candidates = [
        PromotionCandidate(
            key="abc123",
            category=MemoryCategory.FACT,
            content="Test content",
            source_path="memory/2026-04-01.md",
            source_date="2026-04-01",
        )
    ]
    preview = preview_candidates(paths, candidates)
    # The existing entry should be skipped (not re-applied)
    assert preview.skipped_existing == 1


def test_render_memory_review_handles_legacy_log_without_scope(tmp_path: Path) -> None:
    """Review surface renders legacy log entries without scope gracefully."""
    import json

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Write legacy log entries without scope
    legacy_log = {
        "legacy001": {
            "category": "fact",
            "content": "Legacy fact without scope",
            "source_path": "memory/2026-04-01.md",
            "source_date": "2026-04-01",
            "promoted_on": "2026-04-01",
        },
    }
    paths.memory_promotion_log_path.write_text(json.dumps(legacy_log), encoding="utf-8")

    # render_memory_review should not raise and should show the entry
    review = render_memory_review(paths)
    assert "Legacy fact without scope" in review
    assert "fact" in review
    assert "(local, promoted 2026-04-01)" in review


def test_render_memory_review_unscoped_authority_summary_shows_local_only_count(
    tmp_path: Path,
) -> None:
    """Unscoped authority summary shows a concise local-only scope count."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        "# ControlMesh Memory v2\n\n"
        "## Durable Memory\n\n"
        "### Decision\n"
        "- Keep memory local. _(id: d1; status: active; scope: local; source: memory/2026-04-24.md#L2; promoted: 2026-04-24)_\n\n"
        "### Fact\n"
        "- Memory uses markdown files. _(id: f1; status: active; source: memory/2026-04-23.md#L5; promoted: 2026-04-23)_\n",
        encoding="utf-8",
    )

    review = render_memory_review(paths)

    assert "### Authority Memory _(2 local)_" in review
    assert "- **Decision:** 1 entries" in review
    assert "- **Fact:** 1 entries" in review


def test_render_memory_review_unscoped_authority_summary_shows_local_shared_split(
    tmp_path: Path,
) -> None:
    """Unscoped authority summary surfaces the local/shared split when mixed."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        "# ControlMesh Memory v2\n\n"
        "## Durable Memory\n\n"
        "### Decision\n"
        "- Local decision. _(id: d1; status: active; scope: local; source: memory/2026-04-24.md#L2; promoted: 2026-04-24)_\n"
        "- Shared decision. _(id: d2; status: active; scope: shared; source: memory/2026-04-24.md#L3; promoted: 2026-04-24)_\n\n"
        "### Fact\n"
        "- Local fact. _(id: f1; status: active; source: memory/2026-04-23.md#L5; promoted: 2026-04-23)_\n",
        encoding="utf-8",
    )

    review = render_memory_review(paths)

    assert "### Authority Memory _(2 local, 1 shared)_" in review
    assert "- **Decision:** 2 entries" in review
    assert "- **Fact:** 1 entries" in review


def test_render_memory_review_unscoped_authority_summary_counts_legacy_entries_as_local(
    tmp_path: Path,
) -> None:
    """Legacy authority entries without explicit scope still count as local."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text(
        "# ControlMesh Memory v2\n\n"
        "## Durable Memory\n\n"
        "### Fact\n"
        "- Legacy fact. _(source: memory/2026-04-22.md#L5; promoted: 2026-04-22)_\n"
        "- Shared fact. _(id: f2; status: active; scope: shared; source: memory/2026-04-23.md#L5; promoted: 2026-04-23)_\n",
        encoding="utf-8",
    )

    review = render_memory_review(paths)

    assert "### Authority Memory _(1 local, 1 shared)_" in review
    assert "- **Fact:** 2 entries" in review


def test_promotion_log_scope_field_added_to_existing_log_on_reapply(tmp_path: Path) -> None:
    """New promotions append scope; existing entries without scope remain readable."""
    import json

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Start with a legacy entry (no scope)
    legacy_log = {
        "old001": {
            "category": "fact",
            "content": "Pre-existing legacy fact",
            "source_path": "memory/2026-04-01.md",
            "source_date": "2026-04-01",
            "promoted_on": "2026-04-01",
        },
    }
    paths.memory_promotion_log_path.write_text(json.dumps(legacy_log), encoding="utf-8")

    # Apply a new entry with scope
    note_path = ensure_daily_note(paths, date(2026, 4, 26))
    note_path.write_text(
        """# Daily Memory: 2026-04-26

## Promotion Candidates
- [decision shared] New shared decision.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 26))
    assert result.applied_count == 1

    # Verify log has both old entry and new entry with scope
    log = json.loads(paths.memory_promotion_log_path.read_text(encoding="utf-8"))
    assert "old001" in log
    assert "scope" not in log["old001"], "Legacy entry should not have scope field added"

    # Find the new entry by content
    new_entry = next(
        (v for k, v in log.items() if "New shared decision" in v.get("content", "")),
        None,
    )
    assert new_entry is not None, "New entry not found in log"
    assert new_entry.get("scope") == "shared", f"New entry should have scope=shared: {new_entry}"


# --- Phase 13: Scope-aware apply result surface ---


def test_apply_result_contains_applied_entries_with_scope(tmp_path: Path) -> None:
    """Apply result includes per-entry scope metadata for command-surface rendering."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] Shared team decision.
- [fact local] Local fact entry.
- [preference] Default scope (local).
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))

    assert result.applied_count == 3
    assert len(result.applied_entries) == 3
    assert len(result.applied_keys) == 3

    scopes = {entry.key: entry.scope for entry in result.applied_entries}
    assert MemoryScope.SHARED in scopes.values()
    local_count = sum(1 for s in scopes.values() if s == MemoryScope.LOCAL)
    assert local_count == 2


def test_apply_result_applied_entries_keys_match_applied_keys(tmp_path: Path) -> None:
    """applied_entries keys match applied_keys for each entry."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] First shared decision.
- [fact] Second local fact.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))

    assert result.applied_count == 2
    assert set(result.applied_keys) == {entry.key for entry in result.applied_entries}


def test_apply_result_mixed_scope_shows_shared_scope_label(tmp_path: Path) -> None:
    """Shared entries in applied_entries carry SHARED scope; local carry LOCAL."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] Team uses shared memory.
- [fact local] User prefers dark mode.
- [preference] Default preference (local).
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))

    shared_entries = [e for e in result.applied_entries if e.scope == MemoryScope.SHARED]
    local_entries = [e for e in result.applied_entries if e.scope == MemoryScope.LOCAL]

    assert len(shared_entries) == 1
    assert shared_entries[0].scope == MemoryScope.SHARED

    assert len(local_entries) == 2
    assert all(e.scope == MemoryScope.LOCAL for e in local_entries)


def test_apply_result_zero_entries_has_empty_applied_entries(tmp_path: Path) -> None:
    """When no entries are applied, applied_entries is empty (not absent)."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision] Decision already promoted earlier.
""",
        encoding="utf-8",
    )

    # First apply
    first = apply_daily_note_promotions(paths, date(2026, 4, 25))
    assert first.applied_count == 1

    # Second apply should skip
    second = apply_daily_note_promotions(paths, date(2026, 4, 25))
    assert second.applied_count == 0
    assert second.skipped_existing == 1
    assert second.applied_keys == []
    assert second.applied_entries == []


def test_apply_result_applied_entries_order_deterministic(tmp_path: Path) -> None:
    """applied_entries order matches the order of applied_keys (deterministic)."""
    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] First decision.
- [fact local] First fact.
- [preference shared] Second shared preference.
- [person local] A person note.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))

    assert result.applied_count == 4
    assert len(result.applied_entries) == 4
    # Order must match applied_keys
    for i, entry in enumerate(result.applied_entries):
        assert entry.key == result.applied_keys[i]


def test_apply_result_promotion_log_scope_written_from_candidates(tmp_path: Path) -> None:
    """Promotion log records scope correctly for each applied entry."""
    import json

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, date(2026, 4, 25))
    note_path.write_text(
        """# Daily Memory: 2026-04-25

## Promotion Candidates
- [decision shared] A shared decision.
- [fact local] A local fact.
""",
        encoding="utf-8",
    )

    result = apply_daily_note_promotions(paths, date(2026, 4, 25))
    assert result.applied_count == 2

    log = json.loads(paths.memory_promotion_log_path.read_text(encoding="utf-8"))
    scopes_in_log = [entry.get("scope") for entry in log.values()]
    assert "shared" in scopes_in_log
    assert "local" in scopes_in_log


# --- Phase 14: Scope-aware provenance surface ---


def test_explain_authority_entry_shows_scope_for_shared_entry(tmp_path: Path) -> None:
    """Provenance for a shared entry shows shared scope."""
    from controlmesh.memory.commands import explain_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Team uses shared memory for cross-agent context. _(id: why001; status: active; scope: shared; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    result = explain_authority_entry(paths, "why001")

    assert result is not None
    assert "**Scope:** shared" in result
    assert "**Status:** active" in result
    assert "Team uses shared memory" in result


def test_explain_authority_entry_shows_scope_for_local_entry(tmp_path: Path) -> None:
    """Provenance for a local/default entry shows local scope."""
    from controlmesh.memory.commands import explain_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- User prefers dark mode. _(id: why002; status: active; scope: local; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    result = explain_authority_entry(paths, "why002")

    assert result is not None
    assert "**Scope:** local" in result
    assert "**Status:** active" in result
    assert "User prefers dark mode" in result


def test_explain_authority_entry_not_found_returns_none(tmp_path: Path) -> None:
    """Provenance for non-existent entry returns None (not-found behavior)."""
    from controlmesh.memory.commands import explain_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    result = explain_authority_entry(paths, "nonexistent")

    assert result is None


def test_explain_authority_entry_missing_scope_defaults_to_local(tmp_path: Path) -> None:
    """Provenance for legacy entries without explicit scope defaults to local."""
    from controlmesh.memory.commands import explain_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Legacy entry format: no scope field in metadata
    entry_line = "- Legacy fact without scope. _(id: why003; status: active; source: memory/2026-04-01.md#L3; promoted: 2026-04-01)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    result = explain_authority_entry(paths, "why003")

    assert result is not None
    # Should default to local since legacy entries have no explicit scope
    assert "**Scope:** local" in result


def test_explain_authority_entry_command_output_includes_scope(tmp_path: Path) -> None:
    """/memory why <entry-id> command output includes scope in provenance."""
    from controlmesh.memory.commands import explain_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Shared entry
    shared_line = "- Shared team decision. _(id: cmd001; status: active; scope: shared; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    # Local entry
    local_line = "- Local user preference. _(id: cmd002; status: active; scope: local; source: memory/2026-04-25.md#L4; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Decision\n\n{shared_line}\n\n### Preference\n\n{local_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    shared_result = explain_authority_entry(paths, "cmd001")
    local_result = explain_authority_entry(paths, "cmd002")

    assert shared_result is not None
    assert "**Scope:** shared" in shared_result
    assert "Shared team decision" in shared_result

    assert local_result is not None
    assert "**Scope:** local" in local_result
    assert "Local user preference" in local_result


# --- Phase 18: Scope-aware lifecycle mutation responses ---


def test_deprecate_authority_entry_returns_scope_for_local_entry(tmp_path: Path) -> None:
    """Deprecating a local entry returns LOCAL scope."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Local fact being deprecated. _(id: ph18dl001; status: active; scope: local; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "ph18dl001")
    assert success is True
    assert scope == MemoryScope.LOCAL


def test_deprecate_authority_entry_returns_scope_for_shared_entry(tmp_path: Path) -> None:
    """Deprecating a shared entry returns SHARED scope."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Shared decision being deprecated. _(id: ph18ds001; status: active; scope: shared; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Decision\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "ph18ds001")
    assert success is True
    assert scope == MemoryScope.SHARED


def test_dispute_authority_entry_returns_scope_for_local_entry(tmp_path: Path) -> None:
    """Disputing a local entry returns LOCAL scope."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Local fact being disputed. _(id: ph18dpl001; status: active; scope: local; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "ph18dpl001")
    assert success is True
    assert scope == MemoryScope.LOCAL


def test_dispute_authority_entry_returns_scope_for_shared_entry(tmp_path: Path) -> None:
    """Disputing a shared entry returns SHARED scope."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Shared decision being disputed. _(id: ph18dps001; status: active; scope: shared; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Decision\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "ph18dps001")
    assert success is True
    assert scope == MemoryScope.SHARED


def test_supersede_authority_entry_returns_scope_for_local_entry(tmp_path: Path) -> None:
    """Superseding a local entry returns LOCAL scope."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Local fact being superseded. _(id: ph18supl001; status: active; scope: local; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "ph18supl001", "new_entry_id")
    assert success is True
    assert scope == MemoryScope.LOCAL


def test_supersede_authority_entry_returns_scope_for_shared_entry(tmp_path: Path) -> None:
    """Superseding a shared entry returns SHARED scope."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    entry_line = "- Shared decision being superseded. _(id: ph18sups001; status: active; scope: shared; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Decision\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "ph18sups001", "new_entry_id")
    assert success is True
    assert scope == MemoryScope.SHARED


def test_deprecate_authority_entry_not_found_returns_none_scope(tmp_path: Path) -> None:
    """Deprecating a non-existent entry returns None scope (not-found behavior unchanged)."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "nonexistent")
    assert success is False
    assert scope is None


def test_dispute_authority_entry_not_found_returns_none_scope(tmp_path: Path) -> None:
    """Disputing a non-existent entry returns None scope (not-found behavior unchanged)."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "nonexistent")
    assert success is False
    assert scope is None


def test_supersede_authority_entry_not_found_returns_none_scope(tmp_path: Path) -> None:
    """Superseding a non-existent entry returns None scope (not-found behavior unchanged)."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)
    paths.authority_memory_path.write_text("# ControlMesh Memory v2\n", encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "nonexistent", "new_id")
    assert success is False
    assert scope is None


def test_deprecate_authority_entry_legacy_entry_defaults_to_local_scope(tmp_path: Path) -> None:
    """Deprecating a legacy entry (no explicit scope) returns LOCAL scope."""
    from controlmesh.memory.commands import deprecate_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Legacy entry format: no scope field in metadata
    entry_line = "- Legacy fact without scope. _(id: ph18leg001; status: active; source: memory/2026-04-01.md#L3; promoted: 2026-04-01)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Fact\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = deprecate_authority_entry(paths, "ph18leg001")
    assert success is True
    # Legacy entries default to LOCAL scope
    assert scope == MemoryScope.LOCAL


def test_dispute_authority_entry_legacy_entry_defaults_to_local_scope(tmp_path: Path) -> None:
    """Disputing a legacy entry (no explicit scope) returns LOCAL scope."""
    from controlmesh.memory.commands import dispute_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Legacy entry format: no scope field in metadata
    entry_line = "- Legacy preference without scope. _(id: ph18leg002; status: active; source: memory/2026-04-01.md#L3; promoted: 2026-04-01)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Preference\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = dispute_authority_entry(paths, "ph18leg002")
    assert success is True
    # Legacy entries default to LOCAL scope
    assert scope == MemoryScope.LOCAL


def test_supersede_authority_entry_legacy_entry_defaults_to_local_scope(tmp_path: Path) -> None:
    """Superseding a legacy entry (no explicit scope) returns LOCAL scope."""
    from controlmesh.memory.commands import supersede_authority_entry

    paths = _make_paths(tmp_path)
    initialize_memory_v2(paths)

    # Legacy entry format: no scope field in metadata
    entry_line = "- Legacy decision without scope. _(id: ph18leg003; status: active; source: memory/2026-04-01.md#L3; promoted: 2026-04-01)_"
    authority_text = f"# ControlMesh Memory v2\n\n### Decision\n\n{entry_line}\n"
    paths.authority_memory_path.write_text(authority_text, encoding="utf-8")

    success, scope = supersede_authority_entry(paths, "ph18leg003", "new_entry")
    assert success is True
    # Legacy entries default to LOCAL scope
    assert scope == MemoryScope.LOCAL
