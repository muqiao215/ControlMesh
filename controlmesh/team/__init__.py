"""State-only team coordination package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from controlmesh.team.api import execute_team_api_operation
    from controlmesh.team.live import TeamLiveDispatcher
    from controlmesh.team.orchestrator import TeamOrchestrator, transition_phase
    from controlmesh.team.state import TeamStateStore

__all__ = [
    "TeamLiveDispatcher",
    "TeamOrchestrator",
    "TeamStateStore",
    "execute_team_api_operation",
    "transition_phase",
]


def __getattr__(name: str) -> Any:
    """Load team package exports lazily to avoid config/session import cycles."""
    if name == "execute_team_api_operation":
        from controlmesh.team.api import execute_team_api_operation

        return execute_team_api_operation
    if name == "TeamLiveDispatcher":
        from controlmesh.team.live import TeamLiveDispatcher

        return TeamLiveDispatcher
    if name == "TeamOrchestrator":
        from controlmesh.team.orchestrator import TeamOrchestrator

        return TeamOrchestrator
    if name == "transition_phase":
        from controlmesh.team.orchestrator import transition_phase

        return transition_phase
    if name == "TeamStateStore":
        from controlmesh.team.state import TeamStateStore

        return TeamStateStore
    msg = f"module 'controlmesh.team' has no attribute {name!r}"
    raise AttributeError(msg)
