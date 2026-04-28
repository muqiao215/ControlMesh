"""Feishu command-center card builder and parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from controlmesh.commands import get_bot_commands
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
    agent_name: str = "main",
    note: str | None = None,
) -> dict[str, Any]:
    """Build a compact Feishu-visible command/help panel."""
    runtime_note = (
        f"Feishu runtime: `{config.feishu.runtime_mode}`\n"
        f"Progress mode: `{config.feishu.progress_mode}`"
    )
    commands = _command_center_markdown(
        config,
        agent_name=agent_name,
        runtime_note=runtime_note,
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


def build_native_command_card(
    config: AgentConfig,
    *,
    agent_name: str = "main",
    note: str | None = None,
) -> dict[str, Any]:
    """Build the Feishu-visible native slash command registry."""
    runtime_note = (
        f"Feishu runtime: `{config.feishu.runtime_mode}`\n"
        f"Progress mode: `{config.feishu.progress_mode}`"
    )
    commands = _native_command_markdown(
        config,
        agent_name=agent_name,
        runtime_note=runtime_note,
    )

    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": commands}]
    if note:
        elements.append({"tag": "markdown", "content": f"**Status**\n{note}"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "Native Commands",
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


def build_command_guide_text(
    config: AgentConfig,
    *,
    agent_name: str = "main",
) -> str:
    """Build the one-time plain-text command guide for Feishu native runtime chats."""
    runtime_note = (
        f"Feishu runtime: {config.feishu.runtime_mode}\n"
        f"Progress mode: {config.feishu.progress_mode}"
    )
    controlmesh_lines = [
        f"/{cmd} — {desc}"
        for cmd, desc in get_bot_commands(agent_name=agent_name)
        if cmd in {"cm", "back", "status", "model", "tasks", "settings", "help"}
    ]
    guide_lines = [
        "ControlMesh 已接入。",
        "",
        "常用命令:",
        *controlmesh_lines,
        "/feishu_auth_all — 批量补齐飞书原生权限",
        "/feishu_auth_useful — 除黑名单外批量补齐应用已开放权限",
        "",
        "Native Commands 提示:",
        "/compact — native compact context",
        "/review — native code review",
        "/back — 返回 ControlMesh 命令",
        "",
        runtime_note,
        "",
        "不知道发什么时, 直接说需求也可以。",
    ]
    return "\n".join(guide_lines)


def _command_center_markdown(
    config: AgentConfig,
    *,
    agent_name: str,
    runtime_note: str,
) -> str:
    command_lines = [f"- `/{cmd}` {desc}" for cmd, desc in get_bot_commands(agent_name=agent_name)]
    return (
        "**ControlMesh**\n"
        + "\n".join(command_lines)
        + "\n\n**Feishu**\n"
        + "- `/feishu_auth_all` narrow native auth path\n"
        + "- `/feishu_auth_useful` bulk auth excluding heavy enterprise domains\n\n"
        + "Use `/cm` to open Native Commands for the current CLI.\n\n"
        + runtime_note
    )


def _native_command_markdown(
    config: AgentConfig,
    *,
    agent_name: str,
    runtime_note: str,
) -> str:
    back_line = next(
        (desc for cmd, desc in get_bot_commands(agent_name=agent_name) if cmd == "cm"),
        "open Native Commands",
    )
    return (
        "**Native Commands**\n"
        "- Send slash commands supported by the current CLI\n"
        "- ControlMesh owned commands still stay in ControlMesh\n"
        "- Unknown `/xxx` commands pass through to the current CLI\n"
        "- `/back` return to ControlMesh commands\n\n"
        "**Common native examples**\n"
        "- `/compact` compact context\n"
        "- `/review` review code\n"
        "- `/permissions` native tool permissions\n"
        "- `/mcp` manage MCP servers\n"
        f"- `/cm` {back_line}\n"
        "Current menu: Native Commands.\n\n"
        f"{runtime_note}"
    )
