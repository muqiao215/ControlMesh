"""Thin operator helpers for memory-v2 promotion preview/apply."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime

from controlmesh.memory.dreaming import apply_dreaming_sweep, preview_dreaming_sweep
from controlmesh.memory.models import (
    AuthorityEntryMetadata,
    DreamingSweepResult,
    LifecycleStatus,
    MemoryCategory,
    MemoryIndexSyncResult,
    MemoryScope,
    MemorySearchResult,
    PromotionApplyResult,
    PromotionCandidate,
    PromotionPreview,
    PromotionSourceKind,
)
from controlmesh.memory.promotion import (
    apply_candidates,
    parse_authority_entry,
    parse_promotion_candidates,
    preview_candidates,
    update_authority_entry_status,
)
from controlmesh.memory.search import search_memory_index, sync_memory_index
from controlmesh.memory.store import daily_note_path, ensure_daily_note, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

_OPEN_CANDIDATES_RE = re.compile(
    r"^- \[(?P<category>[a-z-]+)(?: (?P<scope>local|shared))?(?:\s+score=(?P<score>[0-9]+(?:\.[0-9]+)?))?\]\s+(?P<content>.+)$"
)


def preview_daily_note_promotions(
    paths: ControlMeshPaths,
    note_date: date,
    *,
    min_score: float = 0.0,
) -> PromotionPreview:
    """Preview explicit promotion candidates from one daily note."""
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, note_date)
    note_text = note_path.read_text(encoding="utf-8")
    candidates = parse_promotion_candidates(
        note_text,
        source_path=note_path.relative_to(paths.workspace),
        source_date=note_date,
    )
    return preview_candidates(paths, candidates, min_score=min_score)


def apply_daily_note_promotions(
    paths: ControlMeshPaths,
    note_date: date,
    *,
    min_score: float = 0.0,
) -> PromotionApplyResult:
    """Apply explicit promotion candidates from one daily note into ``MEMORY.md``."""
    initialize_memory_v2(paths)
    note_path = ensure_daily_note(paths, note_date)
    note_text = note_path.read_text(encoding="utf-8")
    candidates = parse_promotion_candidates(
        note_text,
        source_path=note_path.relative_to(paths.workspace),
        source_date=note_date,
    )
    return apply_candidates(paths, candidates, min_score=min_score, applied_on=note_date)


def sync_memory_search(paths: ControlMeshPaths) -> MemoryIndexSyncResult:
    """Synchronize the local memory-v2 FTS5 index."""
    return sync_memory_index(paths)


def search_memory(
    paths: ControlMeshPaths,
    query: str,
    *,
    limit: int = 10,
    refresh: bool = True,
) -> MemorySearchResult:
    """Search the local memory-v2 FTS5 index."""
    return search_memory_index(paths, query, limit=limit, refresh=refresh)


def preview_memory_dreaming_sweep(
    paths: ControlMeshPaths,
    *,
    owner: str,
    min_score: float = 0.0,
) -> DreamingSweepResult:
    """Preview a local deterministic dreaming sweep."""
    return preview_dreaming_sweep(paths, owner=owner, min_score=min_score)


def apply_memory_dreaming_sweep(
    paths: ControlMeshPaths,
    *,
    owner: str,
    min_score: float = 0.0,
) -> DreamingSweepResult:
    """Apply a local deterministic dreaming sweep."""
    return apply_dreaming_sweep(paths, owner=owner, min_score=min_score)


def render_daily_note_summary(paths: ControlMeshPaths, note_date: date) -> str:
    """Render a compact summary of a daily note for inspection.

    Shows section headers with entry counts and a preview of non-empty content.
    Returns an empty string if the note does not exist.
    """
    initialize_memory_v2(paths)
    note_path = daily_note_path(paths, note_date)
    if not note_path.exists():
        return ""

    note_text = note_path.read_text(encoding="utf-8")
    lines = note_text.splitlines()

    sections: list[str] = []
    current_section = ""
    section_counts: dict[str, int] = {}
    section_previews: dict[str, list[str]] = {}

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if current_section:
                sections.append(
                    _format_note_section(
                        current_section,
                        section_counts.get(current_section, 0),
                        section_previews.get(current_section, []),
                    )
                )
            current_section = stripped[3:]
            section_counts[current_section] = 0
            section_previews[current_section] = []
        elif current_section and stripped.startswith("- "):
            section_counts[current_section] = section_counts.get(current_section, 0) + 1
            preview = stripped[2:]
            if len(section_previews[current_section]) < 2:
                section_previews[current_section].append(
                    preview[:80] + ("..." if len(preview) > 80 else "")
                )

    if current_section:
        sections.append(
            _format_note_section(
                current_section,
                section_counts.get(current_section, 0),
                section_previews.get(current_section, []),
            )
        )

    if not sections:
        return ""

    date_str = note_date.isoformat()
    header = f"## Daily Note: {date_str}"
    return header + "\n\n" + "\n\n".join(sections)


def _format_note_section(name: str, count: int, previews: list[str]) -> str:
    """Format a single section with count and previews."""
    lines = [f"### {name} ({count} entries)"]
    lines.extend(f"- {preview}" for preview in previews)
    if count > len(previews):
        lines.append(f"  ... and {count - len(previews)} more")
    return "\n".join(lines)


def explain_authority_entry(paths: ControlMeshPaths, entry_id: str) -> str | None:
    """Explain the provenance of an authority memory entry by its id.

    Returns a human-readable explanation string, or None if the entry
    is not found or the id does not match any authority entry.
    """
    initialize_memory_v2(paths)
    authority_path = paths.authority_memory_path
    if not authority_path.exists():
        return None

    authority_text = authority_path.read_text(encoding="utf-8")
    lines = authority_text.splitlines()

    for line in lines:
        parsed = parse_authority_entry(line)
        if parsed is None:
            continue
        content, meta = parsed
        if meta.entry_id == entry_id:
            return _format_provenance(content, meta)

    return None


def _format_provenance(content: str, meta: AuthorityEntryMetadata) -> str:
    """Format entry provenance as a readable explanation."""
    lines = [
        f"**Entry:** {content[:100]}",
        "",
        f"- **Status:** {meta.status.value if meta.status else 'unknown'}",
        f"- **Scope:** {meta.scope.value if meta.scope else 'local'}",
    ]

    if meta.source_ref:
        lines.append(f"- **Source:** {meta.source_ref}")

    if meta.promoted_at:
        lines.append(f"- **Promoted:** {meta.promoted_at}")

    if meta.superseded_by:
        lines.append(f"- **Superseded by:** `{meta.superseded_by}`")

    if meta.evidence_count is not None:
        lines.append(f"- **Evidence count:** {meta.evidence_count}")

    return "\n".join(lines)


def render_memory_review(paths: ControlMeshPaths, *, scope: MemoryScope | None = None) -> str:
    """Render a compact review surface combining authority memory and promotion state.

    Shows entry counts by category, recent promotions, and open promotion candidates.
    When scope is specified, only entries with that scope are counted.
    """
    initialize_memory_v2(paths)

    sections: list[str] = ["## Memory Review"]
    if scope is not None:
        sections[0] += f" (scope: {scope.value})"
    _append_authority_counts(paths, sections, scope=scope)
    _append_recent_promotions(paths, sections, scope=scope)
    _append_open_candidates(paths, sections, scope=scope)

    return "\n\n".join(sections)


def _append_authority_counts(
    paths: ControlMeshPaths,
    sections: list[str],
    *,
    scope: MemoryScope | None = None,
) -> None:
    """Append authority memory entry counts by category, optionally filtered by scope."""
    authority_path = paths.authority_memory_path
    if not authority_path.exists():
        return

    authority_text = authority_path.read_text(encoding="utf-8")
    category_counts = _count_authority_entries(authority_text, scope=scope)
    if scope is not None:
        category_counts = {
            cat: count for cat, count in category_counts.items() if count > 0
        }
    if not category_counts:
        return

    scope_label = f" (scope: {scope.value})" if scope else ""
    lines = [f"### Authority Memory{scope_label}"]
    for cat, count in sorted(category_counts.items()):
        lines.append(f"- **{cat}:** {count} entries")
    sections.append("\n".join(lines))


def _append_recent_promotions(
    paths: ControlMeshPaths,
    sections: list[str],
    *,
    scope: MemoryScope | None = None,
) -> None:
    """Append recent promotions from promotion log."""
    promotion_log_path = paths.memory_promotion_log_path
    if not promotion_log_path.exists():
        return

    try:
        log = json.loads(promotion_log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    if not log:
        return

    matching_entries = [
        (key, entry)
        for key, entry in log.items()
        if _scope_matches_filter(_coerce_memory_scope(entry.get("scope")), scope)
    ]
    if not matching_entries:
        return

    recent = matching_entries[-5:]
    lines = ["### Recent Promotions"]
    for _key, entry in reversed(recent):
        cat = entry.get("category", "unknown")
        content = entry.get("content", "")[:60]
        promoted = entry.get("promoted_on", "?")
        scope = _coerce_memory_scope(entry.get("scope"))
        lines.append(
            f"- [{cat}] {content}... ({scope.value}, promoted {promoted})"
        )
    sections.append("\n".join(lines))


def _append_open_candidates(
    paths: ControlMeshPaths,
    sections: list[str],
    *,
    scope: MemoryScope | None = None,
) -> None:
    """Append today's open candidates count."""
    today = datetime.now(UTC).date()
    note_path = daily_note_path(paths, today)
    if not note_path.exists():
        return

    note_text = note_path.read_text(encoding="utf-8")
    candidates = parse_promotion_candidates(
        note_text,
        source_path=note_path.relative_to(paths.workspace),
        source_date=today,
    )
    if not candidates:
        candidates = _parse_open_candidates_from_daily_note(note_text)
    candidates = [
        cand for cand in candidates if _scope_matches_filter(cand.scope, scope)
    ]
    if not candidates:
        return

    lines = [f"### Today's Open Candidates ({len(candidates)})"]
    lines.extend(
        _format_open_candidate_review_line(cand)
        for cand in candidates[:3]
    )
    if len(candidates) > 3:
        lines.append(f"- ... and {len(candidates) - 3} more")
    sections.append("\n".join(lines))


def _parse_open_candidates_from_daily_note(note_text: str) -> list[PromotionCandidate]:
    """Parse promotion candidate lines from the '## Open Candidates' section.

    Daily notes use '## Open Candidates' instead of '## Promotion Candidates'.
    This parses the same line format with optional scope/score markers from that section.
    """
    candidates: list[PromotionCandidate] = []
    in_section = False

    for raw_line in note_text.splitlines():
        line = raw_line.strip()
        if raw_line.startswith("## "):
            in_section = line == "## Open Candidates"
            continue
        if not in_section or not line:
            continue

        match = _OPEN_CANDIDATES_RE.match(line)
        if match is None:
            continue

        try:
            category = MemoryCategory(match.group("category"))
        except ValueError:
            continue
        content = match.group("content").strip()
        key_seed = f"{category.value}:{' '.join(content.split())}".encode()
        key = hashlib.sha256(key_seed).hexdigest()[:12]
        scope_text = match.group("scope")
        scope = MemoryScope(scope_text) if scope_text else MemoryScope.LOCAL
        candidates.append(
            PromotionCandidate(
                key=key,
                category=category,
                content=content,
                source_kind=PromotionSourceKind.DAILY_NOTE,
                source_path="memory",
                source_date=None,
                score=1.0,
                scope=scope,
            )
        )
    return candidates


def _coerce_memory_scope(scope_value: object) -> MemoryScope:
    """Normalize string-ish scope values, defaulting legacy/missing values to local."""
    if isinstance(scope_value, MemoryScope):
        return scope_value
    if isinstance(scope_value, str):
        try:
            return MemoryScope(scope_value.lower())
        except ValueError:
            pass
    return MemoryScope.LOCAL


def _scope_matches_filter(
    entry_scope: MemoryScope,
    scope_filter: MemoryScope | None,
) -> bool:
    """Return whether an entry should be included for the requested scope."""
    return scope_filter is None or entry_scope == scope_filter


def _format_open_candidate_review_line(candidate: PromotionCandidate) -> str:
    """Render one open-candidate review line with an explicit scope label."""
    return (
        f"- [{candidate.category.value}] {candidate.content[:60]}..."
        f" ({candidate.scope.value})"
    )


def _count_authority_entries(
    authority_text: str,
    *,
    scope: MemoryScope | None = None,
) -> dict[str, int]:
    """Count authority entries by category from rendered text, optionally filtered by scope."""
    lines = authority_text.splitlines()
    category_counts: dict[str, int] = {}
    current_category = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            current_category = stripped[4:].strip()
            if current_category and current_category not in category_counts:
                category_counts[current_category] = 0
        elif current_category and stripped.startswith("- "):
            parsed = parse_authority_entry(stripped)
            if parsed is not None:
                _content, meta = parsed
                if scope is None or meta.scope == scope:
                    category_counts[current_category] = category_counts.get(current_category, 0) + 1

    return category_counts


def deprecate_authority_entry(paths: ControlMeshPaths, entry_id: str) -> tuple[bool, MemoryScope | None]:
    """Mark an authority entry as deprecated by its id.

    Returns (True, scope) if the entry was found and updated (or already had that status).
    Returns (False, None) if not found.
    Idempotent: re-deprecating an already-deprecated entry returns (True, scope) with no change.
    """
    return update_authority_entry_status(
        paths, entry_id, LifecycleStatus.DEPRECATED
    )


def dispute_authority_entry(paths: ControlMeshPaths, entry_id: str) -> tuple[bool, MemoryScope | None]:
    """Mark an authority entry as disputed by its id.

    Returns (True, scope) if the entry was found and updated (or already had that status).
    Returns (False, None) if not found.
    Idempotent: re-disputing an already-disputed entry returns (True, scope) with no change.
    """
    return update_authority_entry_status(
        paths, entry_id, LifecycleStatus.DISPUTED
    )


def supersede_authority_entry(paths: ControlMeshPaths, old_entry_id: str, new_entry_id: str) -> tuple[bool, MemoryScope | None]:
    """Mark an authority entry as superseded by another entry.

    Returns (True, scope) if the old entry was found and updated (or already superseded).
    Returns (False, None) if not found.
    Idempotent: re-superseding with the same new_entry_id returns (True, scope) with no change.
    """
    return update_authority_entry_status(
        paths,
        old_entry_id,
        LifecycleStatus.SUPERSEDED,
        superseded_by=new_entry_id,
    )
