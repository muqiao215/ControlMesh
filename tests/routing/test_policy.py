"""Tests for WorkUnit detection policy."""

from __future__ import annotations

from controlmesh.routing.policy import detect_workunit_kind, normalize_topology
from controlmesh.routing.policy import default_topology_for_kind
from controlmesh.routing.workunit import (
    RoutingIntent,
    RoutingRisk,
    WorkUnitKind,
    force_foreground,
    intent_for_kind,
    may_background,
)
from controlmesh.routing.capabilities import AgentSlot


def test_detects_pytest_command_as_test_execution() -> None:
    assert (
        detect_workunit_kind(command="uv run pytest tests/test_x.py -q")
        is WorkUnitKind.TEST_EXECUTION
    )


def test_detects_review_prompt_as_code_review() -> None:
    assert detect_workunit_kind(prompt="Please 审查 this diff") is WorkUnitKind.CODE_REVIEW


def test_detects_patch_prompt_as_patch_candidate() -> None:
    assert detect_workunit_kind(prompt="修复 failing test") is WorkUnitKind.PATCH_CANDIDATE


def test_normalizes_review_fanout_alias() -> None:
    assert normalize_topology("review_fanout") == "fanout_merge"


def test_detects_github_release_prompt() -> None:
    assert detect_workunit_kind(prompt="prepare GitHub release notes") is WorkUnitKind.GITHUB_RELEASE


def test_detects_github_release_from_chinese_new_version_prompt() -> None:
    assert detect_workunit_kind(prompt="请帮我发布新版本") is WorkUnitKind.GITHUB_RELEASE


def test_does_not_false_positive_on_non_release_version_control_phrase() -> None:
    assert detect_workunit_kind(prompt="请解释发布版本控制策略") is None


def test_release_defaults_to_pipeline() -> None:
    assert default_topology_for_kind(WorkUnitKind.GITHUB_RELEASE) == "pipeline"


def test_force_foreground_blocks_high_risk_release_intent() -> None:
    intent = intent_for_kind(WorkUnitKind.GITHUB_RELEASE)

    assert intent.risk == RoutingRisk.HIGH
    assert "publish" in intent.side_effects
    assert force_foreground(intent)


def test_force_foreground_blocks_repo_write_capability() -> None:
    intent = RoutingIntent(
        risk=RoutingRisk.MEDIUM,
        required_caps=frozenset({"repo_write", "code_patch"}),
        side_effects=frozenset({"repo_write"}),
        output_policy="summarized_only",
    )

    assert force_foreground(intent)


def test_may_background_requires_summary_only_background_worker() -> None:
    intent = RoutingIntent(
        risk=RoutingRisk.LOW,
        required_caps=frozenset({"code_review"}),
        output_policy="summarized_only",
    )
    good = AgentSlot(
        name="reviewer",
        mode="background",
        capabilities={"code_review": 0.8},
        output_policy="summarized_only",
    )
    leaky = AgentSlot(
        name="leaky",
        mode="background",
        capabilities={"code_review": 0.8},
        output_policy="raw_events",
    )

    assert may_background(intent, good)
    assert not may_background(intent, leaky)
