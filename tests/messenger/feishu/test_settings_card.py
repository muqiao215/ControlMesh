"""Tests for Feishu interactive settings cards."""

from __future__ import annotations

from controlmesh.config import AgentConfig
from controlmesh.infra.version import VersionInfo
from controlmesh.messenger.feishu.settings_card import (
    build_settings_card,
    parse_settings_card_action,
    resolve_initial_settings_tab,
)


def _config() -> AgentConfig:
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        streaming={"output_mode": "tools", "tool_display": "details"},
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_123",
            "app_secret": "sec_456",
            "runtime_mode": "native",
            "progress_mode": "card_stream",
        },
    )


def test_resolve_initial_settings_tab_accepts_read_only_entries() -> None:
    assert resolve_initial_settings_tab("/settings") == "streaming"
    assert resolve_initial_settings_tab("/settings status") == "streaming"
    assert resolve_initial_settings_tab("/settings output") == "streaming"
    assert resolve_initial_settings_tab("/settings tools") == "streaming"
    assert resolve_initial_settings_tab("/settings feishu") == "feishu"
    assert resolve_initial_settings_tab("/settings version") == "version"


def test_resolve_initial_settings_tab_ignores_mutating_entries() -> None:
    assert resolve_initial_settings_tab("/settings output tools") is None
    assert resolve_initial_settings_tab("/settings tools details") is None
    assert resolve_initial_settings_tab("/settings feishu runtime native") is None
    assert resolve_initial_settings_tab("/settings upgrade") is None


def test_parse_settings_card_action_normalizes_payload() -> None:
    parsed = parse_settings_card_action(
        {
            "event": {
                "open_message_id": "om_card",
                "operator": {"operator_id": {"open_id": "ou_user"}},
                "action": {
                    "value": {
                        "cm_action": "settings_apply",
                        "tab": "feishu",
                        "callback_data": "st:f:r:native",
                    }
                },
            }
        }
    )

    assert parsed is not None
    assert parsed.kind == "apply"
    assert parsed.tab == "feishu"
    assert parsed.callback_data == "st:f:r:native"
    assert parsed.message_id == "om_card"
    assert parsed.operator_open_id == "ou_user"


def test_parse_settings_card_action_normalizes_upgrade_payload() -> None:
    parsed = parse_settings_card_action(
        {
            "event": {
                "open_chat_id": "oc_chat",
                "open_message_id": "om_card",
                "action": {
                    "value": {
                        "cm_action": "settings_upgrade",
                        "tab": "version",
                        "target_version": "0.16.0",
                    }
                },
            }
        }
    )

    assert parsed is not None
    assert parsed.kind == "upgrade"
    assert parsed.tab == "version"
    assert parsed.target_version == "0.16.0"
    assert parsed.chat_id == "oc_chat"
    assert parsed.message_id == "om_card"


def test_parse_settings_card_action_ignores_non_settings_payload() -> None:
    assert (
        parse_settings_card_action(
            {
                "event": {
                    "action": {
                        "value": {
                            "action": "permissions_granted_continue",
                            "operation_id": "op_123",
                        }
                    }
                }
            }
        )
        is None
    )


def test_build_settings_card_marks_selected_tab_and_contains_version_actions() -> None:
    info = VersionInfo(
        current="0.15.0",
        latest="0.16.0",
        update_available=True,
        summary="release",
        source="github",
    )

    card = build_settings_card(
        _config(),
        selected_tab="version",
        note="Version status refreshed.",
        version_info=info,
    )

    assert card["header"]["title"]["content"] == "ControlMesh Advanced Settings"
    tab_actions = card["elements"][0]["actions"]
    assert tab_actions[2]["text"]["content"] == "Version"
    assert tab_actions[2]["type"] == "primary"

    markdown_blocks = [
        element["content"]
        for element in card["elements"]
        if element.get("tag") == "markdown"
    ]
    assert any("Version status refreshed." in block for block in markdown_blocks)
    assert any("Latest: `0.16.0`" in block for block in markdown_blocks)
    assert any("Source: `github`" in block for block in markdown_blocks)

    action_labels = [
        action["text"]["content"]
        for element in card["elements"]
        if element.get("tag") == "action"
        for action in element["actions"]
    ]
    assert "Check latest" in action_labels
    assert "GitHub Releases" in action_labels
    assert "Upgrade now" in action_labels
