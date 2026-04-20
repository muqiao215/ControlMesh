"""Tests for the conservative channel capability registry."""

from __future__ import annotations

from controlmesh.orchestrator.selectors.capability_registry import (
    Capability,
    CapabilityConfidence,
    CapabilityRegistry,
    default_capability_registry,
)


def test_claude_channel_is_treated_as_basic_by_default() -> None:
    registry = default_capability_registry()

    summary = registry.summary_for("claude")

    assert summary.channel == "claude"
    assert summary.profile_id == "claude_channel"
    assert summary.display_name == "Claude-compatible channel"
    assert (
        registry.confidence_for("claude", Capability.BASIC_SUMMARIZE)
        >= CapabilityConfidence.MEDIUM
    )
    assert (
        registry.confidence_for("claude", Capability.POLISH)
        >= CapabilityConfidence.MEDIUM
    )
    assert registry.confidence_for("claude", Capability.CODE_EDIT) <= CapabilityConfidence.LOW
    assert registry.confidence_for("claude", Capability.REPO_REVIEW) <= CapabilityConfidence.LOW


def test_provider_labels_are_not_hard_capability_guarantees() -> None:
    registry = default_capability_registry()

    claude_code = registry.confidence_for("claude", Capability.CODE_EDIT)
    codex_code = registry.confidence_for("codex", Capability.CODE_EDIT)
    claude_repo = registry.confidence_for("claude", Capability.REPO_REVIEW)
    codex_repo = registry.confidence_for("codex", Capability.REPO_REVIEW)

    assert claude_code < codex_code
    assert claude_repo < codex_repo


def test_codex_is_preferred_for_code_and_repo_capabilities() -> None:
    registry = default_capability_registry()

    assert registry.preferred_channels_for(Capability.CODE_EDIT)[0] == "codex"
    assert registry.preferred_channels_for(Capability.REPO_REVIEW)[0] == "codex"


def test_taskhub_and_feishu_native_only_claim_their_narrow_roles() -> None:
    registry = default_capability_registry()

    assert registry.confidence_for("taskhub", Capability.LONG_TASK) is CapabilityConfidence.HIGH
    assert registry.confidence_for("taskhub", Capability.CODE_EDIT) is CapabilityConfidence.NONE
    assert (
        registry.confidence_for("feishu_native", Capability.FEISHU_NATIVE)
        is CapabilityConfidence.HIGH
    )
    assert (
        registry.confidence_for("feishu_native", Capability.BASIC_SUMMARIZE)
        is CapabilityConfidence.NONE
    )


def test_unknown_channels_fall_back_to_empty_profile() -> None:
    registry = CapabilityRegistry()

    assert registry.summary_for("unknown").profile_id == "unknown"
    assert registry.confidence_for("unknown", Capability.BROWSER) is CapabilityConfidence.NONE
