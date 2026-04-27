"""Scoring for capability-based route decisions."""

from __future__ import annotations

from dataclasses import dataclass

from controlmesh.routing.capabilities import AgentSlot
from controlmesh.routing.workunit import WorkUnit


@dataclass(frozen=True, slots=True)
class SlotScore:
    """Scored slot with explanatory factors."""

    slot: AgentSlot
    score: float
    reason: str


def score_slot(slot: AgentSlot, unit: WorkUnit) -> SlotScore:
    """Score one slot against a WorkUnit."""
    caps = unit.requirements.capabilities
    capability_match = (
        sum(slot.capability_score(cap) for cap in caps) / len(caps) if caps else 0.5
    )

    permission = 0.0
    if (
        (unit.requirements.can_edit is False and not slot.can_edit)
        or (unit.requirements.can_edit is True and slot.can_edit)
    ):
        permission = 0.08
    elif unit.requirements.can_edit is False and slot.can_edit:
        permission = -0.05

    topology = 0.03 if unit.kind.value in slot.topology_preferences else 0.0
    role = 0.04 if slot.role == "worker" else 0.0
    score = capability_match + permission + topology + role
    reason = (
        f"{slot.name}: capability={capability_match:.2f} "
        f"permission={permission:+.2f} topology={topology:+.2f}"
    )
    return SlotScore(slot=slot, score=score, reason=reason)


def rank_slots(slots: tuple[AgentSlot, ...], unit: WorkUnit) -> list[SlotScore]:
    """Rank slots by suitability."""
    scores = (score_slot(slot, unit) for slot in slots)
    return sorted(scores, key=lambda item: item.score, reverse=True)
