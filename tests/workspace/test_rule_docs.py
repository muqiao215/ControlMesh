"""Tests for agent-facing rule docs that are consumed by Gemini memory imports."""

from __future__ import annotations

from pathlib import Path


def test_agent_tools_rules_contains_transport_info() -> None:
    rules_path = (
        Path(__file__).resolve().parents[2]
        / "controlmesh"
        / "_home_defaults"
        / "workspace"
        / "tools"
        / "agent_tools"
        / "RULES.md"
    )

    content = rules_path.read_text(encoding="utf-8")

    # Transport-neutral: covers both Telegram and Matrix agent creation.
    assert "Telegram" in content
    assert "Matrix" in content
    assert "create_agent.py" in content
