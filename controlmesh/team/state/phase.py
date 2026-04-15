"""Persisted phase state helpers."""

from __future__ import annotations

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.team.models import TeamPhaseState
from controlmesh.team.phases import initial_phase_state
from controlmesh.team.state.base import TeamStatePaths, utc_now


def write_phase(paths: TeamStatePaths, phase: TeamPhaseState) -> TeamPhaseState:
    """Persist the phase state."""
    now = utc_now()
    persisted = phase.model_copy(
        update={
            "created_at": phase.created_at or now,
            "updated_at": now,
        }
    )
    atomic_json_save(paths.phase_path, persisted.model_dump(mode="json"))
    return persisted


def read_phase(paths: TeamStatePaths) -> TeamPhaseState:
    """Read the phase state, defaulting to the initial state."""
    raw = load_json(paths.phase_path)
    if raw is None:
        return initial_phase_state()
    return TeamPhaseState.model_validate(raw)
