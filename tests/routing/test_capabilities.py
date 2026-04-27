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


def test_missing_registry_falls_back_to_defaults(tmp_path: Path) -> None:
    registry = load_capability_registry(tmp_path / "missing.yaml", AgentConfig())

    assert registry.slots
    assert any(slot.name == "background_worker" for slot in registry.slots)
