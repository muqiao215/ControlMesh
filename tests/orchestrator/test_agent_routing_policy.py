"""Tests for the orchestrator-level agents backend routing policy."""

from __future__ import annotations

from controlmesh.config import AgentConfig
from controlmesh.orchestrator.directives import ParsedDirectives
from controlmesh.orchestrator.selectors.agent_router import (
    RouteDecisionKind,
    decide_backend_route,
)


def test_disabled_policy_is_noop_even_with_openai_agents_directive() -> None:
    decision = decide_backend_route(
        AgentConfig(),
        ParsedDirectives(cleaned="hello", raw_directives={"openai_agents": None}),
    )

    assert decision.kind is RouteDecisionKind.LEGACY_CLI
    assert decision.provider_override is None


def test_enabled_policy_routes_explicit_openai_agents_directive() -> None:
    config = AgentConfig()
    config.agent_graph.enabled = True
    config.agent_graph.openai_agents_model = "gpt-5.4"

    decision = decide_backend_route(
        config,
        ParsedDirectives(cleaned="hello", raw_directives={"openai_agents": None}),
    )

    assert decision.kind is RouteDecisionKind.OPENAI_AGENTS
    assert decision.provider_override == "openai_agents"
    assert decision.model_override == "gpt-5.4"


def test_model_directive_keeps_existing_routing_precedence() -> None:
    config = AgentConfig()
    config.agent_graph.enabled = True

    decision = decide_backend_route(
        config,
        ParsedDirectives(
            cleaned="hello",
            model="sonnet",
            raw_directives={"openai_agents": None},
        ),
    )

    assert decision.kind is RouteDecisionKind.LEGACY_CLI
    assert decision.provider_override is None
