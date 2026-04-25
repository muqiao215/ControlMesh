"""Tests for the advanced settings selector."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from controlmesh.infra.version import VersionInfo
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
    with (
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.detect_install_mode",
            return_value="pipx",
        ),
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.detect_install_info",
        ) as mock_install_info,
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.get_current_version",
            return_value="0.15.0",
        ),
    ):
        mock_install_info.return_value.source = "github"
        mock_install_info.return_value.requested_revision = "main"
        resp = await settings_selector_start(orch)

    assert "Advanced Settings" in resp.text
    assert "Streaming output" in resp.text
    assert "Feishu runtime" in resp.text
    assert "Messaging interfaces" in resp.text
    assert "Version & upgrade" in resp.text
    assert "Tool event display" in resp.text
    assert "Install source" in resp.text
    assert "github" in resp.text.lower()
    assert resp.buttons is not None
    labels = [button.text for row in resp.buttons.rows for button in row]
    assert any("Tools only" in label for label in labels)
    assert any("Command + output" in label for label in labels)
    assert any("Native plugin" in label for label in labels)
    assert "Telegram bot" in labels
    assert "Feishu app" in labels
    assert "Weixin iLink" in labels
    assert any("Check latest" in label for label in labels)


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


async def test_settings_feishu_runtime_callback_updates_config(orch: Orchestrator) -> None:
    resp = await handle_settings_callback(orch, "st:f:r:native")

    assert "Feishu runtime updated" in resp.text
    assert orch._config.feishu.runtime_mode == "native"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["feishu"]["runtime_mode"] == "native"


async def test_settings_feishu_progress_callback_updates_config(orch: Orchestrator) -> None:
    orch._config.feishu.runtime_mode = "native"

    resp = await handle_settings_callback(orch, "st:f:p:card_stream")

    assert "Feishu progress updated" in resp.text
    assert orch._config.feishu.progress_mode == "card_stream"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["feishu"]["progress_mode"] == "card_stream"


async def test_settings_messaging_callback_shows_telegram_help(orch: Orchestrator) -> None:
    resp = await handle_settings_callback(orch, "st:m:telegram")

    assert "Telegram setup" in resp.text
    assert "/settings messaging telegram token <BOT_TOKEN>" in resp.text


async def test_settings_version_refresh_callback_shows_upgrade_actions(orch: Orchestrator) -> None:
    info = VersionInfo(
        current="0.15.0",
        latest="0.16.0",
        update_available=True,
        summary="release",
        source="github",
    )
    with (
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.detect_install_mode",
            return_value="pipx",
        ),
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.detect_install_info",
        ) as mock_install_info,
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.get_current_version",
            return_value="0.15.0",
        ),
        patch(
            "controlmesh.orchestrator.selectors.settings_selector.check_latest_version",
            new=AsyncMock(return_value=info),
        ),
    ):
        mock_install_info.return_value.source = "github"
        mock_install_info.return_value.requested_revision = "main"
        resp = await handle_settings_callback(orch, "st:v:refresh")

    assert "0.16.0" in resp.text
    assert "github" in resp.text.lower()
    assert resp.buttons is not None
    callback_values = [button.callback_data for row in resp.buttons.rows for button in row]
    assert "upg:cl:0.16.0" in callback_values
    assert "upg:yes:0.16.0" in callback_values
    labels = [button.text for row in resp.buttons.rows for button in row]
    assert any("github@main" in label for label in labels)


async def test_settings_language_section_appears(orch: Orchestrator) -> None:
    resp = await settings_selector_start(orch)

    assert "**Language**" in resp.text
    assert "Current:" in resp.text
    assert resp.buttons is not None
    labels = [button.text for row in resp.buttons.rows for button in row]
    assert any("English" in label for label in labels)
    assert any("中文" in label for label in labels)


async def test_settings_language_callback_updates_config_english(orch: Orchestrator) -> None:
    resp = await handle_settings_callback(orch, "st:l:en")

    assert "Language updated" in resp.text
    assert orch._config.language == "en"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["language"] == "en"


async def test_settings_language_callback_updates_config_chinese(orch: Orchestrator) -> None:
    resp = await handle_settings_callback(orch, "st:l:zh")

    assert "Language updated" in resp.text
    assert orch._config.language == "zh"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["language"] == "zh"


async def test_settings_language_buttons_show_current_marker(orch: Orchestrator) -> None:
    orch._config.language = "zh"
    resp = await settings_selector_start(orch)

    assert resp.buttons is not None
    labels = [button.text for row in resp.buttons.rows for button in row]
    # Chinese should have [x] marker since it's the current language
    assert any("[x] 中文" in label for label in labels)
    # English should have [ ] marker
    assert any("[ ] English" in label for label in labels)
