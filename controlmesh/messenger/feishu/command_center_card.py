"""Feishu command-center card builder and parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.settings_card import SettingsTab

_COMMAND_CENTER_TABS: tuple[SettingsTab, ...] = ("streaming", "feishu", "version")


@dataclass(frozen=True, slots=True)
class ParsedCommandCenterAction:
    """Normalized command-center card action payload."""

    tab: SettingsTab
    chat_id: str | None = None
    receive_id_type: str = "chat_id"
    message_id: str | None = None
    operator_open_id: str | None = None


def build_command_center_card(
    config: AgentConfig,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Build a compact Feishu-visible command/help panel."""
    runtime_note = (
        f"Feishu runtime: `{config.feishu.runtime_mode}`\n"
        f"Progress mode: `{config.feishu.progress_mode}`"
    )
    commands = (
        "**Quick commands**\n"
        "- `/settings` interactive settings panel\n"
        "- `/status` current runtime status\n"
        "- `/model` switch or inspect active model\n"
        "- `/tasks topology status` inspect background task topology\n"
        "- `/feishu_auth_all` narrow native auth path\n"
        "- `/feishu_auth_useful` bulk auth excluding heavy enterprise domains\n\n"
        f"{runtime_note}"
    )

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": commands},
        {
            "tag": "action",
            "actions": [
                _button("Settings", tab="streaming", selected=True),
                _button("Feishu", tab="feishu"),
                _button("Version", tab="version"),
            ],
        },
    ]
    if note:
        elements.append({"tag": "markdown", "content": f"**Status**\n{note}"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "ControlMesh Command Center",
            }
        },
        "elements": elements,
    }


def parse_command_center_action(payload: dict[str, Any]) -> ParsedCommandCenterAction | None:
    """Parse a Feishu card action payload for command-center interactions."""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action_obj = event.get("action") if isinstance(event, dict) else None
    value = action_obj.get("value") if isinstance(action_obj, dict) else None
    if not isinstance(event, dict) or not isinstance(value, dict):
        return None
    if value.get("cm_action") != "command_center_settings":
        return None

    raw_tab = value.get("tab")
    if raw_tab not in _COMMAND_CENTER_TABS:
        return None

    operator = event.get("operator")
    operator_open_id = None
    if isinstance(operator, dict):
        operator_open_id = operator.get("open_id")
        if not operator_open_id and isinstance(operator.get("operator_id"), dict):
            operator_open_id = operator["operator_id"].get("open_id")

    receive_id_type = "chat_id"
    chat_id = event.get("open_chat_id")
    if isinstance(chat_id, str) and chat_id:
        receive_id_type = "open_chat_id"
    else:
        chat_id = event.get("chat_id")
    message_id = event.get("open_message_id") or event.get("message_id")
    return ParsedCommandCenterAction(
        tab=raw_tab,
        chat_id=chat_id if isinstance(chat_id, str) else None,
        receive_id_type=receive_id_type,
        message_id=message_id if isinstance(message_id, str) else None,
        operator_open_id=operator_open_id if isinstance(operator_open_id, str) else None,
    )


def _button(
    label: str,
    *,
    tab: Literal["streaming", "feishu", "version"],
    selected: bool = False,
) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": "primary" if selected else "default",
        "value": {
            "cm_action": "command_center_settings",
            "tab": tab,
        },
    }
