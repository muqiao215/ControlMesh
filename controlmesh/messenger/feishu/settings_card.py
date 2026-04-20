"""Feishu interactive card builder and action parsing for settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from controlmesh.config import AgentConfig
from controlmesh.infra.install import detect_install_mode
from controlmesh.infra.version import VersionInfo, get_current_version

SettingsTab = Literal["streaming", "feishu", "version"]
_TABS: tuple[SettingsTab, ...] = ("streaming", "feishu", "version")


@dataclass(frozen=True, slots=True)
class ParsedSettingsCardAction:
    """Normalized settings card action payload."""

    kind: Literal["tab", "apply", "version_refresh", "upgrade_hint", "upgrade"]
    tab: SettingsTab
    callback_data: str | None = None
    target_version: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    operator_open_id: str | None = None


def resolve_initial_settings_tab(text: str) -> SettingsTab | None:
    """Return the requested initial settings tab for a `/settings` message."""
    parts = text.strip().split()
    if not parts or parts[0] != "/settings":
        return None
    if len(parts) == 1 or parts[1].lower() == "status":
        return "streaming"
    head = parts[1].lower().replace("-", "_")
    if head in {"streaming", "output", "tools"} and len(parts) == 2:
        return "streaming"
    if head == "feishu" and len(parts) == 2:
        return "feishu"
    if head == "version" and len(parts) == 2:
        return "version"
    return None


def parse_settings_card_action(payload: dict[str, Any]) -> ParsedSettingsCardAction | None:
    """Parse a Feishu card action payload for settings interactions."""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action_obj = event.get("action") if isinstance(event, dict) else None
    value = action_obj.get("value") if isinstance(action_obj, dict) else None
    if not isinstance(event, dict) or not isinstance(value, dict):
        return None

    raw_kind = value.get("cm_action")
    raw_tab = value.get("tab")
    kind_map = {
        "settings_tab": "tab",
        "settings_apply": "apply",
        "settings_version_refresh": "version_refresh",
        "settings_upgrade_hint": "upgrade_hint",
        "settings_upgrade": "upgrade",
    }
    kind = kind_map.get(raw_kind) if raw_tab in _TABS else None
    if kind is None or raw_tab not in _TABS:
        return None

    callback_data = value.get("callback_data")
    if callback_data is not None and not isinstance(callback_data, str):
        return None
    target_version = value.get("target_version")
    if target_version is not None and not isinstance(target_version, str):
        return None

    operator = event.get("operator")
    operator_open_id = None
    if isinstance(operator, dict):
        operator_open_id = operator.get("open_id")
        if not operator_open_id and isinstance(operator.get("operator_id"), dict):
            operator_open_id = operator["operator_id"].get("open_id")

    chat_id = event.get("open_chat_id") or event.get("chat_id")
    message_id = event.get("open_message_id") or event.get("message_id")
    return ParsedSettingsCardAction(
        kind=kind,
        tab=raw_tab,
        callback_data=callback_data,
        target_version=target_version,
        chat_id=chat_id if isinstance(chat_id, str) else None,
        message_id=message_id if isinstance(message_id, str) else None,
        operator_open_id=operator_open_id if isinstance(operator_open_id, str) else None,
    )


def build_settings_card(
    config: AgentConfig,
    *,
    selected_tab: SettingsTab = "streaming",
    note: str | None = None,
    version_info: VersionInfo | None = None,
) -> dict[str, Any]:
    """Build the Feishu interactive settings card."""
    elements: list[dict[str, Any]] = [
        _tab_row(selected_tab),
    ]
    if note:
        elements.append({"tag": "markdown", "content": f"**Status**\n{note}"})
    elements.extend(_tab_body(config, selected_tab=selected_tab, version_info=version_info))
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "ControlMesh Advanced Settings",
            }
        },
        "elements": elements,
    }


def _tab_body(
    config: AgentConfig,
    *,
    selected_tab: SettingsTab,
    version_info: VersionInfo | None,
) -> list[dict[str, Any]]:
    if selected_tab == "streaming":
        return _streaming_tab(config)
    if selected_tab == "feishu":
        return _feishu_tab(config)
    return _version_tab(version_info)


def _tab_row(selected_tab: SettingsTab) -> dict[str, Any]:
    return {
        "tag": "action",
        "actions": [
            _action_button(
                "Streaming",
                selected=selected_tab == "streaming",
                value={"cm_action": "settings_tab", "tab": "streaming"},
            ),
            _action_button(
                "Feishu",
                selected=selected_tab == "feishu",
                value={"cm_action": "settings_tab", "tab": "feishu"},
            ),
            _action_button(
                "Version",
                selected=selected_tab == "version",
                value={"cm_action": "settings_tab", "tab": "version"},
            ),
        ],
    }


def _streaming_tab(config: AgentConfig) -> list[dict[str, Any]]:
    return [
        {
            "tag": "markdown",
            "content": (
                "**Streaming output**\n"
                f"Current: `{config.streaming.output_mode}`\n\n"
                "**Tool detail mode**\n"
                f"Current: `{config.streaming.tool_display}`"
            ),
        },
        {
            "tag": "action",
            "actions": [
                _settings_button(
                    "Full",
                    current=config.streaming.output_mode,
                    value="full",
                    callback_data="st:o:full",
                ),
                _settings_button(
                    "Tools",
                    current=config.streaming.output_mode,
                    value="tools",
                    callback_data="st:o:tools",
                ),
                _settings_button(
                    "Conversation",
                    current=config.streaming.output_mode,
                    value="conversation",
                    callback_data="st:o:conversation",
                ),
                _settings_button(
                    "Final only",
                    current=config.streaming.output_mode,
                    value="off",
                    callback_data="st:o:off",
                ),
            ],
        },
        {
            "tag": "action",
            "actions": [
                _settings_button(
                    "Tool names",
                    current=config.streaming.tool_display,
                    value="name",
                    callback_data="st:t:name",
                ),
                _settings_button(
                    "Command + output",
                    current=config.streaming.tool_display,
                    value="details",
                    callback_data="st:t:details",
                ),
            ],
        },
    ]


def _feishu_tab(config: AgentConfig) -> list[dict[str, Any]]:
    return [
        {
            "tag": "markdown",
            "content": (
                "**Feishu runtime**\n"
                f"Runtime: `{config.feishu.runtime_mode}`\n"
                f"Progress: `{config.feishu.progress_mode}`\n\n"
                "`native` enables full plugin/CardKit-oriented runtime.\n"
                "`bridge` keeps Feishu as the chat bridge only."
            ),
        },
        {
            "tag": "action",
            "actions": [
                _settings_button(
                    "Bridge only",
                    current=config.feishu.runtime_mode,
                    value="bridge",
                    callback_data="st:f:r:bridge",
                    tab="feishu",
                ),
                _settings_button(
                    "Native plugin",
                    current=config.feishu.runtime_mode,
                    value="native",
                    callback_data="st:f:r:native",
                    tab="feishu",
                ),
            ],
        },
        {
            "tag": "action",
            "actions": [
                _settings_button(
                    "Text",
                    current=config.feishu.progress_mode,
                    value="text",
                    callback_data="st:f:p:text",
                    tab="feishu",
                ),
                _settings_button(
                    "Card preview",
                    current=config.feishu.progress_mode,
                    value="card_preview",
                    callback_data="st:f:p:card_preview",
                    tab="feishu",
                ),
                _settings_button(
                    "Card stream",
                    current=config.feishu.progress_mode,
                    value="card_stream",
                    callback_data="st:f:p:card_stream",
                    tab="feishu",
                ),
            ],
        },
    ]


def _version_tab(version_info: VersionInfo | None) -> list[dict[str, Any]]:
    current = get_current_version()
    install_mode = detect_install_mode()
    if version_info is None:
        latest_line = "Latest: `not checked`"
        source_line = "Source: `not checked`"
    else:
        latest_line = f"Latest: `{version_info.latest}`"
        source_line = f"Source: `{version_info.source}`"
    actions = [
        _action_button(
            "Check latest",
            selected=False,
            value={"cm_action": "settings_version_refresh", "tab": "version"},
        ),
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "GitHub Releases"},
            "multi_url": {
                "url": "https://github.com/muqiao215/ControlMesh/releases",
                "pc_url": "https://github.com/muqiao215/ControlMesh/releases",
                "android_url": "https://github.com/muqiao215/ControlMesh/releases",
                "ios_url": "https://github.com/muqiao215/ControlMesh/releases",
            },
        },
    ]
    if version_info is not None and version_info.update_available:
        actions.append(
            _action_button(
                "Upgrade now",
                selected=False,
                value={
                    "cm_action": "settings_upgrade",
                    "tab": "version",
                    "target_version": version_info.latest,
                },
            )
        )
    else:
        actions.append(
            _action_button(
                "Upgrade help",
                selected=False,
                value={"cm_action": "settings_upgrade_hint", "tab": "version"},
            )
        )
    return [
        {
            "tag": "markdown",
            "content": (
                "**Version & upgrade**\n"
                f"Installed: `{current}`\n"
                f"Install mode: `{install_mode}`\n"
                f"{latest_line}\n"
                f"{source_line}\n\n"
                "Refresh checks GitHub Releases first, then falls back to PyPI.\n"
                "Use `/settings upgrade` to run the verified self-upgrade flow."
            ),
        },
        {
            "tag": "action",
            "actions": actions,
        },
    ]


def _settings_button(
    label: str,
    *,
    current: str,
    value: str,
    callback_data: str,
    tab: SettingsTab = "streaming",
) -> dict[str, Any]:
    selected = current == value
    return _action_button(
        label,
        selected=selected,
        value={
            "cm_action": "settings_apply",
            "callback_data": callback_data,
            "tab": tab,
        },
    )


def _action_button(
    label: str,
    *,
    selected: bool,
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tag": "button",
        "type": "primary" if selected else "default",
        "text": {
            "tag": "plain_text",
            "content": label,
        },
        "value": value,
    }
