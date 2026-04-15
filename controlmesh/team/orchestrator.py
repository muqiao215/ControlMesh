"""State-only orchestration wrapper for team phases."""

from __future__ import annotations

from controlmesh.team.models import TeamPhaseState
from controlmesh.team.phases import initial_phase_state, transition_phase


class TeamOrchestrator:
    """Thin persistence wrapper around the pure phase state machine."""

    def __init__(self, store: object) -> None:
        self._store = store

    def read_state(self) -> TeamPhaseState:
        """Read phase state, initializing the store lazily if empty."""
        state = self._store.read_phase()
        if state.created_at is None:
            state = initial_phase_state(max_repair_attempts=state.max_repair_attempts)
            self._store.write_phase(state)
        return state

    def transition(self, to_phase: str, *, reason: str | None = None) -> TeamPhaseState:
        """Persist a validated phase transition."""
        state = self.read_state()
        next_state = transition_phase(state, to_phase, reason=reason)
        self._store.write_phase(next_state)
        return next_state


__all__ = ["TeamOrchestrator", "transition_phase"]
