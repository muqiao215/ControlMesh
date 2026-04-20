"""Tests for the advanced settings selector."""

from __future__ import annotations

import json

from controlmesh.orchestrator.core import Orchestrator
from controlmesh.orchestrator.selectors.settings_selector import (
    handle_settings_callback,
    is_settings_selector_callback,
    settings_selector_start,
)


def test_settings_callback_prefix_detection() -> None:
    assert is_settings_selector_callback("st:o:tools") is True
    assert is_settings_selector_callback("st:t:details") is True
    assert is_settings_selector_callback("ms:p:claude") is False


async def test_settings_selector_start_groups_streaming_controls(orch: Orchestrator) -> None:
    resp = await settings_selector_start(orch)

    assert "Advanced Settings" in resp.text
    assert "Streaming output" in resp.text
    assert "Tool event display" in resp.text
    assert resp.buttons is not None
    labels = [button.text for row in resp.buttons.rows for button in row]
    assert any("Tools only" in label for label in labels)
    assert any("Command + output" in label for label in labels)


async def test_settings_output_callback_updates_config(orch: Orchestrator) -> None:
    resp = await handle_settings_callback(orch, "st:o:conversation")

    assert "Streaming output updated" in resp.text
    assert orch._config.streaming.output_mode == "conversation"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["streaming"]["output_mode"] == "conversation"
    assert resp.buttons is not None


async def test_settings_tool_display_callback_updates_config(orch: Orchestrator) -> None:
    resp = await handle_settings_callback(orch, "st:t:details")

    assert "Tool event display updated" in resp.text
    assert orch._config.streaming.tool_display == "details"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["streaming"]["tool_display"] == "details"
    assert resp.buttons is not None
