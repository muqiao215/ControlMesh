"""Feishu command-center card builder and parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.card_action_payload import extract_card_action_target
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
        "**ControlMesh**\n"
        "- `/new` new session\n"
        "- `/model` switch or inspect active model\n"
        "- `/cm` open Claude native commands\n"
        "- `/tasks` inspect background tasks\n"
        "- `/session` session entry\n"
        "- `/agents` agent queue\n"
        "- `/cron` scheduled automation\n"
        "- `/status` current runtime status\n"
        "- `/memory` main memory\n"
        "- `/settings` interactive settings panel\n\n"
        "**Feishu**\n"
        "- `/feishu_auth_all` narrow native auth path\n"
        "- `/feishu_auth_useful` bulk auth excluding heavy enterprise domains\n\n"
        "Use `/cm` to open Claude native commands.\n\n"
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


def build_claude_native_command_card(
    config: AgentConfig,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    """Build the Feishu-visible Claude native slash command registry."""
    runtime_note = (
        f"Feishu runtime: `{config.feishu.runtime_mode}`\n"
        f"Progress mode: `{config.feishu.progress_mode}`"
    )
    commands = (
        "**Claude native**\n"
        "- `/add-dir` add working directory\n"
        "- `/agents` manage Claude agents\n"
        "- `/bug` report Claude Code issue\n"
        "- `/clear` clear context\n"
        "- `/compact` compact context\n"
        "- `/config` Claude Code config\n"
        "- `/cost` usage cost\n"
        "- `/doctor` diagnose Claude Code\n"
        "- `/help` Claude native help\n"
        "- `/ide` IDE integration\n"
        "- `/init` initialize project context\n"
        "- `/install-github-app` install GitHub App\n"
        "- `/login` log in to Claude\n"
        "- `/logout` log out of Claude\n"
        "- `/mcp` manage MCP servers\n"
        "- `/memory` Claude memory\n"
        "- `/model` Claude model selector\n"
        "- `/permissions` Claude tool permissions\n"
        "- `/pr_comments` pull PR comments\n"
        "- `/review` review code\n"
        "- `/status` Claude session status\n"
        "- `/terminal-setup` terminal integration\n"
        "- `/vim` Vim mode\n"
        "- `/remote-control` Claude Remote Control\n"
        "- `/rc` Remote Control shortcut\n"
        "- `/back` return to ControlMesh commands\n\n"
        "Current menu: Claude native commands.\n\n"
        f"{runtime_note}"
    )

    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": commands}]
    if note:
        elements.append({"tag": "markdown", "content": f"**Status**\n{note}"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "Claude Native Commands",
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

    chat_id, receive_id_type, message_id = extract_card_action_target(event)
    return ParsedCommandCenterAction(
        tab=raw_tab,
        chat_id=chat_id,
        receive_id_type=receive_id_type,
        message_id=message_id,
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
