"""Guard tests proving capability metadata does not change routing by default."""

from __future__ import annotations

from controlmesh.config import AgentConfig
from controlmesh.orchestrator.directives import ParsedDirectives
from controlmesh.orchestrator.selectors.agent_router import (
    RouteDecisionKind,
    decide_backend_route,
)


def test_enabled_router_still_defaults_to_legacy_without_explicit_directive() -> None:
    config = AgentConfig()
    config.agent_graph.enabled = True

    decision = decide_backend_route(
        config,
        ParsedDirectives(cleaned="please review this repo diff"),
    )

    assert decision.kind is RouteDecisionKind.LEGACY_CLI
