"""Thin operator helpers for memory-v2 promotion preview/apply."""

from __future__ import annotations

from datetime import date

from ductor_bot.memory.models import PromotionApplyResult, PromotionPreview
from ductor_bot.memory.promotion import (
    apply_candidates,
    parse_promotion_candidates,
    preview_candidates,
)
from ductor_bot.memory.store import ensure_daily_note, initialize_memory_v2
from ductor_bot.workspace.paths import DuctorPaths


def preview_daily_note_promotions(
    paths: DuctorPaths,
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
    paths: DuctorPaths,
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
