"""Tests for capability route decisions."""

from __future__ import annotations

from controlmesh.config import AgentConfig
from controlmesh.routing.router import resolve_route


def test_resolve_route_for_test_execution() -> None:
    decision = resolve_route(
        AgentConfig(),
        prompt="Run tests",
        route="auto",
        workunit_kind="test_execution",
        command="uv run pytest tests/test_x.py -q",
    )

    assert decision is not None
    assert decision.workunit.kind.value == "test_execution"
    assert "shell_execution" in decision.required_capabilities
    assert decision.topology == ""
    assert "test_execution" in decision.contract


def test_resolve_route_maps_code_review_to_fanout() -> None:
    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="auto",
        workunit_kind="code_review",
        target="git diff main",
    )

    assert decision is not None
    assert decision.topology == "fanout_merge"
    assert decision.evaluator == "foreground"


def test_resolve_route_keeps_explicit_topology_alias() -> None:
    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="auto",
        workunit_kind="code_review",
        target="git diff main",
        topology="review_fanout",
    )

    assert decision is not None
    assert decision.topology == "fanout_merge"
