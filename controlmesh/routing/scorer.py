"""Scoring for capability-based route decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

from controlmesh.routing.capabilities import AgentSlot
from controlmesh.routing.score_events import RouteScoreStats
from controlmesh.routing.workunit import WorkUnit


@dataclass(frozen=True, slots=True)
class SlotScore:
    """Scored slot with explanatory factors."""

    slot: AgentSlot
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class SlotRuntimeState:
    """Runtime health and recent quality signals for one slot."""

    healthy: bool | None = None
    authenticated: bool | None = None
    recent_success_rate: float = 0.5
    evidence_quality: float = 0.5
    cost_penalty: float = 0.0
    latency_penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RouteScoringContext:
    """Optional runtime context used to adjust static capability scores."""

    slot_state: dict[str, SlotRuntimeState] = field(default_factory=dict)

    def state_for(self, slot: AgentSlot) -> SlotRuntimeState:
        return self.slot_state.get(slot.name, SlotRuntimeState())


def state_from_score_stats(stats: RouteScoreStats) -> SlotRuntimeState:
    """Convert historical score stats into a scorer runtime state."""
    return SlotRuntimeState(
        recent_success_rate=stats.success_rate,
        evidence_quality=stats.evidence_quality,
        cost_penalty=min(0.12, stats.needed_human_fix_rate * 0.12),
        reason=f"history count={stats.count}",
    )


def score_slot(
    slot: AgentSlot,
    unit: WorkUnit,
    context: RouteScoringContext | None = None,
) -> SlotScore:
    """Score one slot against a WorkUnit."""
    context = context or RouteScoringContext()
    state = context.state_for(slot)
    if state.healthy is False or state.authenticated is False:
        return SlotScore(
            slot=slot,
            score=-1.0,
            reason=(
                f"{slot.name}: unavailable "
                f"healthy={state.healthy} authenticated={state.authenticated}"
            ),
        )

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
    cost = {"cheap": 0.03, "standard": 0.0, "premium": -0.04}.get(slot.cost_class, 0.0)
    reliability = 0.12 * state.recent_success_rate
    evidence = 0.08 * state.evidence_quality
    penalties = state.cost_penalty + state.latency_penalty
    health = 0.04 if state.healthy is True else 0.0
    auth = 0.03 if state.authenticated is True else 0.0
    score = (
        capability_match
        + permission
        + topology
        + role
        + cost
        + reliability
        + evidence
        + health
        + auth
        - penalties
    )
    reason = (
        f"{slot.name}: capability={capability_match:.2f} "
        f"permission={permission:+.2f} topology={topology:+.2f} "
        f"cost={cost:+.2f} "
        f"reliability={reliability:+.2f} evidence={evidence:+.2f} "
        f"health={health:+.2f} auth={auth:+.2f} penalties={penalties:+.2f}"
    )
    if state.reason:
        reason = f"{reason}; {state.reason}"
    return SlotScore(slot=slot, score=score, reason=reason)


def rank_slots(
    slots: tuple[AgentSlot, ...],
    unit: WorkUnit,
    context: RouteScoringContext | None = None,
) -> list[SlotScore]:
    """Rank slots by suitability."""
    scores = (score_slot(slot, unit, context) for slot in slots)
    return sorted(scores, key=lambda item: item.score, reverse=True)
