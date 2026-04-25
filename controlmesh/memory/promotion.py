"""Deterministic promotion parsing and apply helpers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.memory.compat import sync_authority_to_legacy_mainmemory
from controlmesh.memory.models import (
    AuthorityEntryMetadata,
    LifecycleStatus,
    MemoryCategory,
    MemoryScope,
    PromotionAppliedEntry,
    PromotionApplyResult,
    PromotionCandidate,
    PromotionPreview,
    PromotionSourceKind,
)
from controlmesh.memory.store import initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

_PROMOTION_SECTION_HEADING = "## Promotion Candidates"
_PROMOTION_LINE_RE = re.compile(
    r"^- \[(?P<category>[a-z-]+)(?: (?P<scope>local|shared))?(?:\s+score=(?P<score>[0-9]+(?:\.[0-9]+)?))?\]\s+(?P<content>.+)$"
)

# Pattern for parsing authority entry metadata from rendered entries
# The meta string captured by _AUTHORITY_ENTRY_RE has format:
# id: abc123; status: active; scope: local; source: path#LN; promoted: YYYY-MM-DD
# (without the surrounding parentheses since those are matched by the outer regex)
# Note: scope is optional for backward compatibility with entries created before Phase 8
_AUTHORITY_METADATA_RE = re.compile(
    r"^id:\s*(?P<id>[^;]+);\s*"
    r"status:\s*(?P<status>\w+);"
    r"(?:\s*scope:\s*(?P<scope>\w+);)?"
    r"(?:\s*superseded_by:\s*(?P<superseded_by>[^;]+);)?"
    r"\s*source:\s*(?P<source>[^;]+);\s*"
    r"promoted:\s*(?P<promoted>.+)$"
)

# Pattern to match entry with metadata block at end
_AUTHORITY_ENTRY_RE = re.compile(
    r"^(?P<content>.+?)\s*_\((?P<meta>.+)\)_$"
)

# Legacy metadata format: only source and promoted, no id or status
_LEGACY_AUTHORITY_METADATA_RE = re.compile(
    r"source:\s*(?P<source>[^;]+);\s*"
    r"promoted:\s*(?P<promoted>.+)$"
)


def parse_promotion_candidates(
    note_text: str,
    *,
    source_path: Path,
    source_date: date | None = None,
    source_kind: PromotionSourceKind = PromotionSourceKind.DAILY_NOTE,
) -> list[PromotionCandidate]:
    """Parse explicit markdown promotion lines from a daily note."""
    in_section = False
    candidates: list[PromotionCandidate] = []
    for line_number, raw_line in enumerate(note_text.splitlines(), start=1):
        line = raw_line.strip()
        if raw_line.startswith("## "):
            in_section = raw_line.strip() == _PROMOTION_SECTION_HEADING
            continue
        if not in_section or not line:
            continue

        match = _PROMOTION_LINE_RE.match(line)
        if match is None:
            continue

        try:
            category = MemoryCategory(match.group("category"))
        except ValueError:
            continue
        content = match.group("content").strip()
        key_seed = f"{category.value}:{' '.join(content.split())}".encode()
        key = hashlib.sha256(key_seed).hexdigest()[:12]
        score_text = match.group("score")
        scope_text = match.group("scope")
        scope = MemoryScope(scope_text) if scope_text else MemoryScope.LOCAL
        candidates.append(
            PromotionCandidate(
                key=key,
                category=category,
                content=content,
                source_kind=source_kind,
                source_path=source_path.as_posix(),
                source_date=source_date.isoformat() if source_date else None,
                line_start=line_number,
                line_end=line_number,
                score=float(score_text) if score_text else 1.0,
                scope=scope,
            )
        )
    return candidates


def preview_candidates(
    paths: ControlMeshPaths,
    candidates: Iterable[PromotionCandidate],
    *,
    min_score: float = 0.0,
) -> PromotionPreview:
    """Filter candidates into selected vs skipped buckets."""
    initialize_memory_v2(paths)
    log = _load_promotion_log(paths)
    selected: list[PromotionCandidate] = []
    skipped_existing = 0
    skipped_low_score = 0
    for candidate in candidates:
        if candidate.score < min_score:
            skipped_low_score += 1
            continue
        if candidate.key in log:
            skipped_existing += 1
            continue
        selected.append(candidate)
    return PromotionPreview(
        selected=selected,
        skipped_existing=skipped_existing,
        skipped_low_score=skipped_low_score,
    )


def apply_candidates(
    paths: ControlMeshPaths,
    candidates: Iterable[PromotionCandidate],
    *,
    min_score: float = 0.0,
    applied_on: date | None = None,
) -> PromotionApplyResult:
    """Apply selected candidates into ``MEMORY.md`` and record them in the log."""
    preview = preview_candidates(paths, candidates, min_score=min_score)
    if not preview.selected:
        return PromotionApplyResult(
            applied_count=0,
            skipped_existing=preview.skipped_existing,
            skipped_low_score=preview.skipped_low_score,
            applied_keys=[],
            applied_entries=[],
        )

    authority_text = paths.authority_memory_path.read_text(encoding="utf-8")
    updated = authority_text
    for candidate in preview.selected:
        updated = _insert_candidate(updated, candidate, applied_on=applied_on)
    atomic_text_save(paths.authority_memory_path, updated)
    sync_authority_to_legacy_mainmemory(paths, authority_text=updated)

    promotion_log = _load_promotion_log(paths)
    promoted_on = (applied_on or datetime.now(UTC).date()).isoformat()
    for candidate in preview.selected:
        promotion_log[candidate.key] = {
            "category": candidate.category.value,
            "content": candidate.content,
            "source_path": candidate.source_path,
            "source_date": candidate.source_date,
            "promoted_on": promoted_on,
            "scope": candidate.scope.value,
        }
    atomic_json_save(paths.memory_promotion_log_path, promotion_log)

    return PromotionApplyResult(
        applied_count=len(preview.selected),
        skipped_existing=preview.skipped_existing,
        skipped_low_score=preview.skipped_low_score,
        applied_keys=[candidate.key for candidate in preview.selected],
        applied_entries=[
            PromotionAppliedEntry(key=candidate.key, scope=candidate.scope)
            for candidate in preview.selected
        ],
    )


def _load_promotion_log(paths: ControlMeshPaths) -> dict[str, dict[str, str | None]]:
    raw = load_json(paths.memory_promotion_log_path)
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, str | None]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            cleaned[key] = {
                str(inner_key): _coerce_string(inner_value)
                for inner_key, inner_value in value.items()
            }
    return cleaned


def _coerce_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def parse_authority_entry_metadata(line: str) -> AuthorityEntryMetadata | None:
    """Parse lifecycle metadata from a rendered authority entry line.

    Handles both new-format entries with full metadata and legacy entries
    with only source/promoted annotations.
    Returns None only for lines that cannot be parsed as authority entries.
    """
    content_match = _AUTHORITY_ENTRY_RE.match(line.strip())
    if content_match is None:
        return None

    meta_str = content_match.group("meta")

    # Try new format first (has id, status, and scope)
    meta_match = _AUTHORITY_METADATA_RE.search(meta_str)
    if meta_match is not None:
        try:
            status_str = meta_match.group("status")
            status = LifecycleStatus(status_str)
        except ValueError:
            status = LifecycleStatus.ACTIVE

        try:
            scope_str = meta_match.group("scope")
            scope = MemoryScope(scope_str)
        except ValueError:
            scope = MemoryScope.LOCAL

        return AuthorityEntryMetadata(
            entry_id=meta_match.group("id"),
            status=status,
            scope=scope,
            source_ref=meta_match.group("source"),
            promoted_at=meta_match.group("promoted"),
            superseded_by=meta_match.group("superseded_by"),
        )

    # Fall back to legacy format (source and promoted only, no id/status/scope)
    legacy_match = _LEGACY_AUTHORITY_METADATA_RE.search(meta_str)
    if legacy_match is not None:
        return AuthorityEntryMetadata(
            entry_id=None,
            status=LifecycleStatus.ACTIVE,
            scope=MemoryScope.LOCAL,
            source_ref=legacy_match.group("source"),
            promoted_at=legacy_match.group("promoted"),
            superseded_by=None,
        )

    return None


def parse_authority_entry(line: str) -> tuple[str, AuthorityEntryMetadata] | None:
    """Parse a full authority entry line into content and metadata.

    Returns (content, metadata) if the line is a valid authority entry,
    or None if it cannot be parsed as an authority entry.
    """
    content_match = _AUTHORITY_ENTRY_RE.match(line.strip())
    if content_match is None:
        return None

    meta = parse_authority_entry_metadata(line)
    if meta is None:
        return None

    # Strip leading "- " from content since that's the markdown list marker
    raw_content = content_match.group("content")
    if raw_content.startswith("- "):
        raw_content = raw_content.removeprefix("- ")
    return (raw_content, meta)


def _insert_candidate(
    authority_text: str, candidate: PromotionCandidate, *, applied_on: date | None
) -> str:
    heading = f"### {candidate.category.value.title()}"
    marker = _render_entry(candidate, applied_on=applied_on)
    lines = authority_text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        lines.extend(["", heading, ""])
        start = lines.index(heading)

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("### ") or lines[index].startswith("## "):
            end = index
            break

    if marker in lines[start:end]:
        return authority_text

    insert_at = end
    while insert_at > start + 1 and lines[insert_at - 1] == "":
        insert_at -= 1
    lines[insert_at:insert_at] = [marker, ""]
    return "\n".join(lines).rstrip() + "\n"


def update_authority_entry_status(
    paths: ControlMeshPaths,
    entry_id: str,
    new_status: LifecycleStatus,
    *,
    superseded_by: str | None = None,
) -> bool:
    """Update the lifecycle status of an authority entry by its id.

    Returns True if the entry was found and updated, False otherwise.
    Updates are idempotent: re-setting the same status is a no-op (returns True).
    When superseded_by is provided, it sets/updates the superseded_by field.
    """
    authority_path = paths.authority_memory_path
    if not authority_path.exists():
        return False

    authority_text = authority_path.read_text(encoding="utf-8")
    lines = authority_text.splitlines()
    updated_lines: list[str] = []
    found = False

    for line in lines:
        parsed = parse_authority_entry(line)
        if parsed is not None:
            content, meta = parsed
            if meta.entry_id == entry_id:
                found = True
                # Idempotent: no change needed if status already matches
                if meta.status == new_status and meta.superseded_by == superseded_by:
                    updated_lines.append(line)
                    continue
                # Build replacement line with updated metadata
                new_meta = AuthorityEntryMetadata(
                    entry_id=meta.entry_id,
                    status=new_status,
                    scope=meta.scope,
                    promoted_at=meta.promoted_at,
                    source_ref=meta.source_ref,
                    superseded_by=superseded_by if superseded_by is not None else meta.superseded_by,
                    evidence_count=meta.evidence_count,
                )
                updated_line = _render_entry_from_metadata(content, new_meta)
                updated_lines.append(updated_line)
                continue
        updated_lines.append(line)

    if not found:
        return False

    updated_text = "\n".join(updated_lines) + "\n"
    atomic_text_save(authority_path, updated_text)
    sync_authority_to_legacy_mainmemory(paths, authority_text=updated_text)
    return True


def _render_entry_from_metadata(content: str, meta: AuthorityEntryMetadata) -> str:
    """Render an authority entry line from content and metadata."""
    parts = [
        f"id: {meta.entry_id}",
        f"status: {meta.status.value}",
        f"scope: {meta.scope.value}",
    ]
    if meta.superseded_by:
        parts.append(f"superseded_by: {meta.superseded_by}")
    parts.extend([
        f"source: {meta.source_ref}",
        f"promoted: {meta.promoted_at}",
    ])
    meta_str = "; ".join(parts)
    return f"- {content} _({meta_str})_"


def _render_entry(candidate: PromotionCandidate, *, applied_on: date | None) -> str:
    promoted_on = (applied_on or datetime.now(UTC).date()).isoformat()
    source_ref = candidate.source_path
    if candidate.line_start is not None:
        source_ref = f"{source_ref}#L{candidate.line_start}"

    # Build metadata block with entry_id, status, and scope
    entry_id = candidate.key[:12]
    meta_str = "; ".join([
        f"id: {entry_id}",
        f"status: {LifecycleStatus.ACTIVE.value}",
        f"scope: {candidate.scope.value}",
        f"source: {source_ref}",
        f"promoted: {promoted_on}",
    ])
    return f"- {candidate.content} _({meta_str})_"
