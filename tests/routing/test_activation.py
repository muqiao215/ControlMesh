"""Tests for activation policy loading, matching, and routing integration."""

from __future__ import annotations

import tempfile
from pathlib import Path

from controlmesh.config import AgentConfig
from controlmesh.routing.activation import (
    ActivationIntent,
    ActivationPolicy,
    load_activation_policies,
    resolve_activation_intent,
)
from controlmesh.routing.router import resolve_route


# ---------------------------------------------------------------------------
# Policy loading tests
# ---------------------------------------------------------------------------


def test_load_activation_policies_parses_valid_yaml() -> None:
    yaml_content = """
activation_policies:
  test_policy:
    execution: background_required
    match:
      workunit_kinds:
        - github_release
    preferred_slots:
      - release_runner
    deny_slots:
      - codex_cli
    deny_providers:
      - codex
    max_cost_class: cheap
    topology: pipeline
    requires_foreground_approval: true
    allow_explicit_override: false
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write(yaml_content)
        path = f.name

    policies = load_activation_policies(path)
    Path(path).unlink()

    assert len(policies) == 1
    policy = policies[0]
    assert policy.name == "test_policy"
    assert policy.execution == "background_required"
    assert policy.match["workunit_kinds"] == ["github_release"]
    assert policy.preferred_slots == ("release_runner",)
    assert policy.deny_slots == ("codex_cli",)
    assert policy.deny_providers == ("codex",)
    assert policy.max_cost_class == "cheap"
    assert policy.topology == "pipeline"
    assert policy.requires_foreground_approval is True
    assert policy.allow_explicit_override is False


def test_load_activation_policies_returns_empty_for_missing_file() -> None:
    policies = load_activation_policies("/nonexistent/path/activation_policies.yaml")
    assert policies == ()


def test_load_activation_policies_handles_malformed_yaml() -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write("not: [valid: yaml: content")
        path = f.name

    policies = load_activation_policies(path)
    Path(path).unlink()
    assert policies == ()


# ---------------------------------------------------------------------------
# Policy matching tests
# ---------------------------------------------------------------------------


def test_resolve_activation_intent_matches_workunit_kind() -> None:
    policies = (
        ActivationPolicy(
            name="github_bg",
            execution="background_required",
            match={"workunit_kinds": ["github_release"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="github_release",
        prompt="Prepare release",
    )
    assert intent.matched_policy == "github_bg"
    assert intent.execution_mode == "background_required"


def test_resolve_activation_intent_no_match_on_kind() -> None:
    policies = (
        ActivationPolicy(
            name="github_bg",
            execution="background_required",
            match={"workunit_kinds": ["github_release"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="code_review",
        prompt="Review code",
    )
    assert intent.matched_policy == ""


def test_resolve_activation_intent_matches_command_pattern() -> None:
    policies = (
        ActivationPolicy(
            name="long_task_bg",
            execution="background_preferred",
            match={"command_patterns": [r"pytest.*full"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="test_execution",
        command="uv run pytest tests/ -q --full",
    )
    assert intent.matched_policy == "long_task_bg"


def test_resolve_activation_intent_matches_prompt_contains() -> None:
    policies = (
        ActivationPolicy(
            name="release_keyword",
            execution="background_required",
            match={"prompt_contains": ["release", "github"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="github_release",
        prompt="Prepare GitHub release for v1.0",
    )
    assert intent.matched_policy == "release_keyword"


def test_resolve_activation_intent_matches_name_starts_with() -> None:
    policies = (
        ActivationPolicy(
            name="codex_explicit",
            execution="foreground_required",
            match={"name_starts_with": "codex:"},
            allow_explicit_override=False,
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="code_review",
        name="codex:fix-bug-123",
    )
    assert intent.matched_policy == "codex_explicit"
    assert intent.execution_mode == "foreground_required"
    assert intent.allow_explicit_override is False


def test_resolve_activation_intent_matches_phase_ids() -> None:
    policies = (
        ActivationPolicy(
            name="phase_bg",
            execution="background_required",
            match={"phase_ids": ["phase-3"]},
            topology="pipeline",
            requires_foreground_approval=True,
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="phase_execution",
        phase_id="phase-3",
    )
    assert intent.matched_policy == "phase_bg"
    assert intent.execution_mode == "background_required"
    assert intent.topology == "pipeline"
    assert intent.requires_foreground_approval is True


def test_resolve_activation_intent_matches_phase_titles() -> None:
    policies = (
        ActivationPolicy(
            name="phase_impl_bg",
            execution="background_required",
            match={"phase_titles": ["execute", "implementation"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="phase_execution",
        phase_title="Implementation Phase",
    )
    assert intent.matched_policy == "phase_impl_bg"


def test_resolve_activation_intent_disallow_explicit_override_keeps_policy_match() -> None:
    """When allow_explicit_override=False, explicit routes do not bypass the policy."""
    policies = (
        ActivationPolicy(
            name="strict_bg",
            execution="background_required",
            match={"workunit_kinds": ["github_release"]},
            allow_explicit_override=False,
        ),
    )

    # With explicit route, policy should still match because override is disallowed.
    intent = resolve_activation_intent(
        policies,
        workunit_kind="github_release",
        explicit_route="foreground",
    )
    assert intent.matched_policy == "strict_bg"
    assert intent.execution_mode == "background_required"


def test_resolve_activation_intent_allow_explicit_override_bypasses_policy() -> None:
    """When allow_explicit_override=True, explicit routes bypass policy activation."""
    policies = (
        ActivationPolicy(
            name="release_bg",
            execution="background_required",
            match={"workunit_kinds": ["github_release"]},
            allow_explicit_override=True,
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="github_release",
        explicit_route="foreground",
    )
    assert intent.matched_policy == ""


def test_resolve_activation_intent_first_match_wins() -> None:
    """Multiple policies: first matching policy wins."""
    policies = (
        ActivationPolicy(
            name="first",
            execution="background_required",
            match={"workunit_kinds": ["github_release"]},
        ),
        ActivationPolicy(
            name="second",
            execution="foreground_required",
            match={"workunit_kinds": ["github_release"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        workunit_kind="github_release",
    )
    assert intent.matched_policy == "first"


def test_resolve_activation_intent_empty_policies_returns_empty() -> None:
    intent = resolve_activation_intent(
        (),
        workunit_kind="github_release",
    )
    assert intent.matched_policy == ""


def test_activation_intent_defaults() -> None:
    intent = ActivationIntent()
    assert intent.matched_policy == ""
    assert intent.execution_mode == "background_preferred"
    assert intent.preferred_slots == ()
    assert intent.deny_slots == ()
    assert intent.deny_providers == ()
    assert intent.max_cost_class == ""
    assert intent.topology == ""
    assert intent.requires_foreground_approval is False
    assert intent.allow_explicit_override is True
    assert intent.explicit_route == ""


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------


def test_resolve_route_with_activation_intent_preferred_slots() -> None:
    """Activation intent preferred_slots biases initial ordering before scoring."""
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="test_prefer",
        execution_mode="background_preferred",
        preferred_slots=("release_runner",),
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Run tests",
        route="auto",
        workunit_kind="test_execution",
        command="uv run pytest tests/test_x.py -q",
        activation_intent=intent,
    )

    # preferred_slots biases initial ordering; scoring may still override.
    # The key is that release_runner is NOT denied and IS available.
    assert decision is not None
    # opencode.explore has higher test_log_analysis (0.78) than release_runner (not set),
    # so scoring may still pick opencode.explore unless capability scores are close.
    assert decision.slot_name in ("release_runner", "opencode.explore", "background_worker")


def test_resolve_route_with_activation_intent_deny_slots() -> None:
    """Activation intent deny_slots filters out those slots."""
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="no_worker",
        execution_mode="background_preferred",
        deny_slots=("background_worker",),
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Run tests",
        route="auto",
        workunit_kind="test_execution",
        command="uv run pytest tests/test_x.py -q",
        activation_intent=intent,
    )

    # background_worker should be filtered out
    assert decision is not None
    assert decision.slot_name != "background_worker"


def test_resolve_route_with_activation_intent_topology() -> None:
    """Activation intent topology overrides the scored topology."""
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="release_pipeline",
        execution_mode="background_required",
        topology="pipeline",
        requires_foreground_approval=True,
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Prepare GitHub release",
        route="auto",
        workunit_kind="github_release",
        activation_intent=intent,
    )

    assert decision is not None
    assert decision.topology == "pipeline"
    assert decision.evaluator == "foreground"


def test_resolve_route_with_activation_intent_max_cost_class() -> None:
    """Activation intent max_cost_class filters out more expensive slots."""
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="cheap_only",
        execution_mode="background_preferred",
        max_cost_class="cheap",
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Run tests",
        route="auto",
        workunit_kind="test_execution",
        command="uv run pytest tests/test_x.py -q",
        activation_intent=intent,
    )

    # Only cheap slots should be considered (cheap: release_runner, opencode.explore)
    assert decision is not None
    # Both release_runner and opencode.explore are cheap, so either can be selected
    assert decision.slot_name in ("release_runner", "opencode.explore")
    # premium slots (codex_cli) and standard slots (background_worker) should be filtered
    assert decision.slot_name != "background_worker"
    assert decision.slot_name != "codex_cli"


def test_resolve_route_with_activation_intent_deny_providers() -> None:
    """Activation intent deny_providers filters out those providers."""
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="no_codex",
        execution_mode="background_preferred",
        deny_providers=("codex",),
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="auto",
        workunit_kind="code_review",
        activation_intent=intent,
    )

    assert decision is not None
    assert decision.provider != "codex"


# ---------------------------------------------------------------------------
# Execution-mode enforcement tests
# ---------------------------------------------------------------------------


def test_resolve_route_blocks_foreground_required_policy() -> None:
    """foreground_required + auto route = no-route outcome (hard block).

    When a matched policy says foreground_required, the auto-routing path cannot
    satisfy it (it would need a foreground slot). The correct outcome is None,
    not a scored background slot.
    """
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="codex_explicit_only",
        execution_mode="foreground_required",
        deny_slots=("codex_cli",),
        allow_explicit_override=False,
    )

    # Even though code_review has background-capable slots, the foreground_required
    # intent blocks auto-routing entirely.
    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff for fix-bug-123",
        route="auto",
        workunit_kind="code_review",
        activation_intent=intent,
    )

    # Foreground-required in auto mode is a hard block — auto cannot route a
    # foreground-only task to any slot, so None is the correct result.
    assert decision is None


def test_resolve_route_foreground_required_does_not_block_explicit_route() -> None:
    """When route != 'auto', activation intent is not consulted at all.

    Explicit foreground routing bypasses the routing engine entirely, so
    foreground_required policy is irrelevant there.
    """
    from controlmesh.routing.activation import ActivationIntent

    intent = ActivationIntent(
        matched_policy="codex_explicit_only",
        execution_mode="foreground_required",
        allow_explicit_override=False,
    )

    # route=foreground is handled before resolve_route is even called — the
    # routing engine is not entered.
    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="foreground",  # explicit, not "auto"
        workunit_kind="code_review",
        activation_intent=intent,
    )

    # With route=foreground, resolve_route returns None by design (not entered).
    assert decision is None


def test_resolve_route_with_deny_slots_excludes_slots_from_selection() -> None:
    """deny_slots in activation intent filters those slots from candidate set.

    This is the stable mechanism for codex_explicit_only — deny the codex_cli
    slot so it can never be auto-selected, while routing continues to other
    eligible slots (background_required does not hard-block).
    """
    from controlmesh.routing.activation import ActivationIntent

    # background_required + deny_slots: codex_cli is excluded but routing continues
    # to other eligible background slots for code_review.
    intent = ActivationIntent(
        matched_policy="codex_explicit_only",
        execution_mode="background_required",
        deny_slots=("codex_cli",),
        allow_explicit_override=False,
    )

    decision = resolve_route(
        AgentConfig(),
        prompt="Review the diff",
        route="auto",
        workunit_kind="code_review",
        activation_intent=intent,
    )

    # Routing should succeed — codex_cli is denied but other slots are eligible.
    # The key property is that codex_cli specifically cannot be selected.
    assert decision is not None
    assert decision.slot_name != "codex_cli"


def test_phase_execution_matches_policy_by_kind_not_title() -> None:
    """phase_execution workunits match planfiles_background_phase without any title match.

    The policy matches by workunit_kinds alone. A phase_execution with any phase_title
    (or no phase_title at all) must still be matched.
    """
    policies = (
        ActivationPolicy(
            name="planfiles_background_phase",
            execution="background_required",
            match={"workunit_kinds": ["phase_execution"]},
            topology="pipeline",
            requires_foreground_approval=True,
            allow_explicit_override=True,
        ),
    )

    # With a generic or empty phase_title, the policy still matches
    intent_no_title = resolve_activation_intent(
        policies,
        workunit_kind="phase_execution",
        phase_title="",  # no title
    )
    assert intent_no_title.matched_policy == "planfiles_background_phase"
    assert intent_no_title.execution_mode == "background_required"
    assert intent_no_title.topology == "pipeline"

    # With an arbitrary phase_title, the policy still matches
    intent_arbitrary = resolve_activation_intent(
        policies,
        workunit_kind="phase_execution",
        phase_title="Kickoff",  # not "execute/implementation/build/run"
    )
    assert intent_arbitrary.matched_policy == "planfiles_background_phase"
    assert intent_arbitrary.execution_mode == "background_required"


def test_resolve_activation_intent_does_not_match_missing_required_kind() -> None:
    policies = (
        ActivationPolicy(
            name="release_bg",
            execution="background_required",
            match={"workunit_kinds": ["github_release"]},
        ),
    )

    intent = resolve_activation_intent(
        policies,
        prompt="Prepare release",
    )
    assert intent.matched_policy == ""


def test_resolve_activation_intent_does_not_match_missing_phase_or_plan_context() -> None:
    policies = (
        ActivationPolicy(
            name="phase_policy",
            execution="background_required",
            match={"phase_ids": ["phase-1"], "plan_ids": ["plan-1"]},
        ),
    )

    assert resolve_activation_intent(policies).matched_policy == ""
    assert resolve_activation_intent(policies, phase_id="phase-1").matched_policy == ""
    assert resolve_activation_intent(policies, plan_id="plan-1").matched_policy == ""


def test_resolve_activation_intent_no_explicit_override_in_auto_path() -> None:
    """Passing explicit_route='' (auto path) lets allow_explicit_override=False
    policies still match — there is no override to honor in the auto path.
    """
    policies = (
        ActivationPolicy(
            name="strict_foreground",
            execution="foreground_required",
            match={"workunit_kinds": ["code_review"]},
            allow_explicit_override=False,
        ),
    )

    # Empty string = no explicit directive, so allow_explicit_override=False
    # should NOT block the match (there is nothing to override).
    intent = resolve_activation_intent(
        policies,
        workunit_kind="code_review",
        explicit_route="",  # auto path — no explicit directive
    )
    assert intent.matched_policy == "strict_foreground"
    assert intent.execution_mode == "foreground_required"


def test_seeded_codex_explicit_only_uses_deny_slots() -> None:
    """The seeded codex_explicit_only policy uses deny_slots, not name matching.

    execution=background_required ensures routing continues to other eligible slots
    while deny_slots=[codex_cli] prevents auto-selection of that specific slot.
    """
    from controlmesh.routing.activation import load_activation_policies

    policies = load_activation_policies(
        "controlmesh/_home_defaults/workspace/routing/activation_policies.yaml"
    )
    codex_policy = next(
        (p for p in policies if p.name == "codex_explicit_only"), None
    )
    assert codex_policy is not None
    # execution=background_required — does NOT hard-block routing;
    # it allows other eligible background slots to be selected.
    assert codex_policy.execution == "background_required"
    # deny_slots is the stable blocking mechanism
    assert "codex_cli" in codex_policy.deny_slots
    # No fragile name_starts_with
    assert codex_policy.match.get("name_starts_with", "") == ""
    # Still matches by workunit kind
    assert "code_review" in codex_policy.match.get("workunit_kinds", [])


def test_seeded_planfiles_background_phase_no_title_dependency() -> None:
    """The seeded planfiles_background_phase does not require phase_title matching."""
    from controlmesh.routing.activation import load_activation_policies

    policies = load_activation_policies(
        "controlmesh/_home_defaults/workspace/routing/activation_policies.yaml"
    )
    phase_policy = next(
        (p for p in policies if p.name == "planfiles_background_phase"), None
    )
    assert phase_policy is not None
    # Should match by kind only — no phase_titles criteria
    assert "phase_execution" in phase_policy.match.get("workunit_kinds", [])
    phase_titles = phase_policy.match.get("phase_titles", [])
    # The list should be absent or empty (not relying on title strings)
    assert phase_titles == [] or phase_titles is None or phase_titles == ""
