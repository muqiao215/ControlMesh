"""Router-only policy for optional orchestrator backend selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from controlmesh.config import AgentConfig
from controlmesh.orchestrator.directives import ParsedDirectives


class RouteDecisionKind(StrEnum):
    """Backend decision kinds produced by the router-only MVP."""

    LEGACY_CLI = "legacy_cli"
    OPENAI_AGENTS = "openai_agents"
    BACKGROUND_TASK_DEFER_LATER = "background_task_defer_later"
    CLARIFY = "clarify"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """A typed backend-routing decision for one orchestrator turn."""

    kind: RouteDecisionKind
    provider_override: str | None = None
    model_override: str | None = None
    message: str | None = None


def decide_backend_route(
    config: AgentConfig,
    directives: ParsedDirectives,
) -> RouteDecision:
    """Choose the narrow backend route for a non-command message."""
    if directives.model is not None:
        return RouteDecision(RouteDecisionKind.LEGACY_CLI)

    if not config.agent_graph.enabled:
        return RouteDecision(RouteDecisionKind.LEGACY_CLI)

    if "openai_agents" not in directives.raw_directives:
        return RouteDecision(RouteDecisionKind.LEGACY_CLI)

    return RouteDecision(
        RouteDecisionKind.OPENAI_AGENTS,
        provider_override="openai_agents",
        model_override=config.agent_graph.openai_agents_model or None,
    )
