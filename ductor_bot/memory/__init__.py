"""Additive memory-v2 primitives for Ductor."""

from ductor_bot.memory.commands import (
    apply_daily_note_promotions,
    preview_daily_note_promotions,
)
from ductor_bot.memory.dreaming import (
    acquire_dream_lock,
    load_checkpoints,
    load_sweep_state,
    release_dream_lock,
    save_checkpoints,
    save_sweep_state,
)
from ductor_bot.memory.models import (
    DreamingCheckpoint,
    DreamingLock,
    DreamingSweepState,
    PromotionApplyResult,
    PromotionCandidate,
    PromotionPreview,
)
from ductor_bot.memory.promotion import (
    apply_candidates,
    parse_promotion_candidates,
    preview_candidates,
)
from ductor_bot.memory.store import append_dream_entry, ensure_daily_note, initialize_memory_v2

__all__ = [
    "DreamingCheckpoint",
    "DreamingLock",
    "DreamingSweepState",
    "PromotionApplyResult",
    "PromotionCandidate",
    "PromotionPreview",
    "acquire_dream_lock",
    "append_dream_entry",
    "apply_candidates",
    "apply_daily_note_promotions",
    "ensure_daily_note",
    "initialize_memory_v2",
    "load_checkpoints",
    "load_sweep_state",
    "parse_promotion_candidates",
    "preview_candidates",
    "preview_daily_note_promotions",
    "release_dream_lock",
    "save_checkpoints",
    "save_sweep_state",
]
