"""Deterministic promotion parsing and apply helpers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.memory.models import (
    MemoryCategory,
    PromotionApplyResult,
    PromotionCandidate,
    PromotionPreview,
    PromotionSourceKind,
)
from controlmesh.memory.store import initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths

_PROMOTION_SECTION_HEADING = "## Promotion Candidates"
_PROMOTION_LINE_RE = re.compile(
    r"^- \[(?P<category>[a-z-]+)(?:\s+score=(?P<score>[0-9]+(?:\.[0-9]+)?))?\]\s+(?P<content>.+)$"
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
        )

    authority_text = paths.authority_memory_path.read_text(encoding="utf-8")
    updated = authority_text
    for candidate in preview.selected:
        updated = _insert_candidate(updated, candidate, applied_on=applied_on)
    atomic_text_save(paths.authority_memory_path, updated)

    promotion_log = _load_promotion_log(paths)
    promoted_on = (applied_on or datetime.now(UTC).date()).isoformat()
    for candidate in preview.selected:
        promotion_log[candidate.key] = {
            "category": candidate.category.value,
            "content": candidate.content,
            "source_path": candidate.source_path,
            "source_date": candidate.source_date,
            "promoted_on": promoted_on,
        }
    atomic_json_save(paths.memory_promotion_log_path, promotion_log)

    return PromotionApplyResult(
        applied_count=len(preview.selected),
        skipped_existing=preview.skipped_existing,
        skipped_low_score=preview.skipped_low_score,
        applied_keys=[candidate.key for candidate in preview.selected],
    )


def _load_promotion_log(paths: ControlMeshPaths) -> dict[str, dict[str, str | None]]:
    raw = load_json(paths.memory_promotion_log_path)
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, str | None]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            cleaned[key] = {
                str(inner_key): _coerce_string(inner_value) for inner_key, inner_value in value.items()
            }
    return cleaned


def _coerce_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _insert_candidate(authority_text: str, candidate: PromotionCandidate, *, applied_on: date | None) -> str:
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


def _render_entry(candidate: PromotionCandidate, *, applied_on: date | None) -> str:
    promoted_on = (applied_on or datetime.now(UTC).date()).isoformat()
    source_ref = candidate.source_path
    if candidate.line_start is not None:
        source_ref = f"{source_ref}#L{candidate.line_start}"
    return f"- {candidate.content} _(source: {source_ref}; promoted: {promoted_on})_"
