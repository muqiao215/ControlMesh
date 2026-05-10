"""Tests for capability route decisions."""

from __future__ import annotations

from controlmesh.config import AgentConfig
from controlmesh.routing.capabilities import AgentSlot, CapabilityRegistry
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
    assert decision.runtime_writeback is True
    assert isinstance(decision.business_permissions, tuple)
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
    assert decision.runtime_writeback is True
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


def test_auto_route_skips_slots_disallowed_for_subagents() -> None:
    decision = resolve_route(
        AgentConfig(),
        prompt="Review the failing diff",
        route="auto",
        workunit_kind="code_review",
    )

    assert decision is not None
    assert decision.slot_name != "codex_cli"
    assert decision.provider != "codex"


def test_github_release_forces_foreground_even_with_preferred_release_runner() -> None:
    config = AgentConfig()
    config.agent_routing.workunit_overrides = {
        "github_release": {
            "preferred_slots": ["release_runner"],
            "topology": "pipeline",
            "requires_foreground_approval": True,
        }
    }

    decision = resolve_route(
        config,
        prompt="Prepare GitHub release notes for v1.2.3",
        route="auto",
        workunit_kind="github_release",
    )

    assert decision is None


def test_patch_candidate_repo_write_forces_foreground() -> None:
    decision = resolve_route(
        AgentConfig(),
        prompt="Fix the failing test",
        route="auto",
        workunit_kind="patch_candidate",
    )

    assert decision is None


def test_worker_slot_without_p0_contract_is_ineligible() -> None:
    registry = CapabilityRegistry(
        slots=(
            AgentSlot(
                name="legacy_worker",
                provider="claude",
                model="sonnet",
                mode="background",
                allow_subagent=True,
                capabilities={
                    "code_review": 0.9,
                    "diff_understanding": 0.9,
                    "evidence_writer": 0.9,
                },
            ),
        )
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="auto",
        workunit_kind="code_review",
        registry=registry,
    )

    assert decision is None


def test_worker_slot_with_raw_output_policy_is_ineligible() -> None:
    registry = CapabilityRegistry(
        slots=(
            AgentSlot(
                name="raw_worker",
                provider="claude",
                model="sonnet",
                mode="background",
                allow_subagent=True,
                sandbox="host",
                approval_policy="never",
                cwd="/repo",
                visible_paths=("/repo",),
                tools=("shell",),
                output_policy="raw_events",
                capabilities={
                    "code_review": 0.9,
                    "diff_understanding": 0.9,
                    "evidence_writer": 0.9,
                },
            ),
        )
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="auto",
        workunit_kind="code_review",
        registry=registry,
    )

    assert decision is None


def test_min_confidence_gate_rejects_weak_route() -> None:
    config = AgentConfig()
    config.agent_routing.min_confidence = 1.01
    config.agent_routing.subagent_policy = {"deny_cost_classes": ["premium"]}

    decision = resolve_route(
        config,
        prompt="Run tests",
        route="auto",
        workunit_kind="test_execution",
        command="uv run pytest tests/test_x.py -q",
    )

    assert decision is None
