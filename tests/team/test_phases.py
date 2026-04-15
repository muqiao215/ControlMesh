"""Tests for team phase orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh.team.models import TeamPhaseState
from controlmesh.team.orchestrator import TeamOrchestrator, transition_phase
from controlmesh.team.state import TeamStateStore


def test_transition_phase_allows_happy_path() -> None:
    state = TeamPhaseState()
    state = transition_phase(state, "approve", reason="plan ready")
    state = transition_phase(state, "execute", reason="approved")
    state = transition_phase(state, "verify", reason="implementation done")
    state = transition_phase(state, "complete", reason="verified")

    assert state.current_phase == "complete"
    assert state.active is False
    assert len(state.transitions) == 4


def test_transition_phase_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError, match="invalid team phase transition"):
        transition_phase(TeamPhaseState(), "verify")


def test_repair_loop_exhaustion_marks_phase_failed() -> None:
    state = TeamPhaseState(max_repair_attempts=1)
    state = transition_phase(state, "approve")
    state = transition_phase(state, "execute")
    state = transition_phase(state, "verify")
    state = transition_phase(state, "repair", reason="fix needed")
    state = transition_phase(state, "verify", reason="re-check")
    state = transition_phase(state, "repair", reason="still broken")

    assert state.current_phase == "failed"
    assert state.active is False
    assert state.terminal_reason is not None
    assert "repair loop limit" in state.terminal_reason


def test_orchestrator_persists_phase_state(tmp_path: Path) -> None:
    store = TeamStateStore(tmp_path / "team-state", "alpha-team")
    orchestrator = TeamOrchestrator(store)

    orchestrator.transition("approve", reason="plan ready")
    persisted = store.read_phase()

    assert persisted.current_phase == "approve"
    assert persisted.transitions[-1].to_phase == "approve"
