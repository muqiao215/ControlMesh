"""Tests for capability registry loading."""

from __future__ import annotations

from pathlib import Path

from controlmesh.config import AgentConfig
from controlmesh.routing.capabilities import load_capability_registry


def test_loads_capability_registry_yaml(tmp_path: Path) -> None:
    path = tmp_path / "capabilities.yaml"
    path.write_text(
        """
agent_slots:
  opencode.explore:
    runtime: opencode
    provider: opencode
    model: ""
    mode: background
    role: worker
    sandbox: opencode
    approval_policy: never
    cwd: /repo
    visible_paths:
      - /repo
    tools:
      - shell
    output_policy: summarized_only
    can_edit: false
    capabilities:
      code_review:
        score: 0.8
""",
        encoding="utf-8",
    )

    registry = load_capability_registry(path, AgentConfig())

    assert len(registry.slots) == 1
    assert registry.slots[0].name == "opencode.explore"
    assert registry.slots[0].capability_score("code_review") == 0.8
    assert registry.slots[0].allow_subagent is True
    assert registry.slots[0].sandbox == "opencode"
    assert registry.slots[0].approval_policy == "never"
    assert registry.slots[0].cwd == "/repo"
    assert registry.slots[0].visible_paths == ("/repo",)
    assert registry.slots[0].tools == ("shell",)
    assert registry.slots[0].output_policy == "summarized_only"
    assert registry.slots[0].runtime_writeback is True
    assert registry.slots[0].declares_worker_contract()


def test_loads_slot_policy_metadata(tmp_path: Path) -> None:
    path = tmp_path / "capabilities.yaml"
    path.write_text(
        """
agent_slots:
  codex_cli:
    runtime: codex_cli
    provider: codex
    mode: background
    role: worker
    cost_class: premium
    allow_subagent: false
    capabilities:
      code_review:
        score: 0.9
""",
        encoding="utf-8",
    )

    registry = load_capability_registry(path, AgentConfig())

    assert registry.slots[0].cost_class == "premium"
    assert registry.slots[0].allow_subagent is False
    assert not registry.slots[0].declares_worker_contract()


def test_missing_registry_falls_back_to_defaults(tmp_path: Path) -> None:
    registry = load_capability_registry(tmp_path / "missing.yaml", AgentConfig())

    assert registry.slots
    assert any(slot.name == "background_worker" for slot in registry.slots)
    assert all(slot.runtime_writeback for slot in registry.slots if slot.mode == "background")
