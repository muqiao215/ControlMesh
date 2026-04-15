"""Pure phase transition logic for additive team orchestration."""

from __future__ import annotations

from datetime import UTC, datetime

from controlmesh.team.contracts import TEAM_PHASES, TEAM_TERMINAL_PHASES
from controlmesh.team.models import TeamPhaseState, TeamPhaseTransition

_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "plan": ("approve", "cancelled"),
    "approve": ("execute", "failed", "cancelled"),
    "execute": ("verify", "failed", "cancelled"),
    "verify": ("repair", "complete", "failed", "cancelled"),
    "repair": ("execute", "verify", "complete", "failed", "cancelled"),
}
_FIX_LOOP_EXCEEDED = "repair loop limit reached"


def is_terminal_phase(phase: str) -> bool:
    """Return True when the phase is terminal."""
    return phase in TEAM_TERMINAL_PHASES


def transition_phase(
    state: TeamPhaseState,
    to_phase: str,
    *,
    reason: str | None = None,
    at: datetime | None = None,
) -> TeamPhaseState:
    """Transition a phase state while enforcing the allowed graph."""
    from_phase = state.current_phase
    if from_phase in TEAM_TERMINAL_PHASES:
        msg = f"cannot transition from terminal team phase: {from_phase}"
        raise ValueError(msg)

    allowed = _TRANSITIONS.get(from_phase, ())
    if to_phase not in allowed:
        msg = f"invalid team phase transition: {from_phase} -> {to_phase}"
        raise ValueError(msg)

    now = (at or datetime.now(UTC)).astimezone(UTC).isoformat()
    next_repair_attempt = state.current_repair_attempt + 1 if to_phase == "repair" else state.current_repair_attempt

    if to_phase == "repair" and next_repair_attempt > state.max_repair_attempts:
        terminal = TeamPhaseTransition(
            from_phase=from_phase,
            to_phase="failed",
            at=now,
            reason=f"{_FIX_LOOP_EXCEEDED} ({state.max_repair_attempts})",
        )
        return TeamPhaseState(
            current_phase="failed",
            active=False,
            created_at=state.created_at,
            updated_at=now,
            transitions=[*state.transitions, terminal],
            max_repair_attempts=state.max_repair_attempts,
            current_repair_attempt=state.current_repair_attempt,
            terminal_reason=terminal.reason,
        )

    return TeamPhaseState(
        current_phase=to_phase,
        active=not is_terminal_phase(to_phase),
        created_at=state.created_at,
        updated_at=now,
        transitions=[
            *state.transitions,
            TeamPhaseTransition(from_phase=from_phase, to_phase=to_phase, at=now, reason=reason),
        ],
        max_repair_attempts=state.max_repair_attempts,
        current_repair_attempt=next_repair_attempt,
        terminal_reason=state.terminal_reason if to_phase not in TEAM_TERMINAL_PHASES else reason,
    )


def initial_phase_state(*, at: datetime | None = None, max_repair_attempts: int = 3) -> TeamPhaseState:
    """Create the default initial phase state."""
    now = (at or datetime.now(UTC)).astimezone(UTC).isoformat()
    return TeamPhaseState(
        current_phase=TEAM_PHASES[0],
        active=True,
        created_at=now,
        updated_at=now,
        max_repair_attempts=max_repair_attempts,
    )
