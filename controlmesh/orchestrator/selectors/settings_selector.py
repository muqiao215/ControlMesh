"""Interactive advanced settings selector for streaming output controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from controlmesh.config import update_config_file_async
from controlmesh.i18n import LANGUAGES
from controlmesh.i18n import init as init_i18n
from controlmesh.infra.install import detect_install_info, detect_install_mode
from controlmesh.infra.version import VersionInfo, check_latest_version, get_current_version
from controlmesh.orchestrator.selectors.models import Button, ButtonGrid, SelectorResponse

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator

_OUTPUT_MODES: tuple[str, ...] = ("full", "tools", "conversation", "off")
_LANGUAGE_CODES: tuple[str, ...] = tuple(LANGUAGES.keys())
_TOOL_DISPLAYS: tuple[str, ...] = ("name", "details")
_FEISHU_RUNTIME_MODES: tuple[str, ...] = ("bridge", "native")
_FEISHU_PROGRESS_MODES: tuple[str, ...] = ("text", "card_preview", "card_stream")
_MESSAGING_TARGETS: tuple[str, ...] = ("telegram", "feishu", "weixin")
_PREFIX = "st:"

_OUTPUT_LABELS: dict[str, str] = {
    "full": "Full",
    "tools": "Tools only",
    "conversation": "Conversation only",
    "off": "Final only",
}
_TOOL_DISPLAY_LABELS: dict[str, str] = {
    "name": "Tool names",
    "details": "Command + output",
}
_FEISHU_RUNTIME_LABELS: dict[str, str] = {
    "bridge": "Bridge only",
    "native": "Native plugin",
}
_FEISHU_PROGRESS_LABELS: dict[str, str] = {
    "text": "Text",
    "card_preview": "Card preview",
    "card_stream": "Card stream",
}


def is_settings_selector_callback(data: str) -> bool:
    """Return True when *data* belongs to the settings selector."""
    return bool(data) and data.startswith(_PREFIX)


async def settings_selector_start(
    orch: Orchestrator,
    note: str | None = None,
    *,
    version_info: VersionInfo | None = None,
) -> SelectorResponse:
    """Build the advanced settings panel."""
    return _render_settings_panel(orch, note=note, version_info=version_info)


async def set_streaming_output_mode(
    orch: Orchestrator,
    mode: Literal["full", "tools", "conversation", "off"],
) -> SelectorResponse:
    """Persist one streaming output mode and return the updated panel."""
    orch._config.streaming.output_mode = mode
    await _persist_streaming_config(orch)
    return _render_settings_panel(orch, note=f"Streaming output updated: {mode}")


async def set_tool_display_mode(
    orch: Orchestrator,
    display: Literal["name", "details"],
) -> SelectorResponse:
    """Persist one tool event display mode and return the updated panel."""
    orch._config.streaming.tool_display = display
    await _persist_streaming_config(orch)
    return _render_settings_panel(orch, note=f"Tool event display updated: {display}")


async def set_feishu_runtime_mode(
    orch: Orchestrator,
    mode: Literal["bridge", "native"],
) -> SelectorResponse:
    """Persist the Feishu runtime mode and return the updated panel."""
    note = f"Feishu runtime updated: {mode}"
    if mode == "bridge" and orch._config.feishu.progress_mode == "card_stream":
        orch._config.feishu.progress_mode = "card_preview"
        note += " (progress auto-switched to card_preview)"
    orch._config.feishu.runtime_mode = mode
    await _persist_feishu_config(orch)
    return _render_settings_panel(orch, note=note)


async def set_feishu_progress_mode(
    orch: Orchestrator,
    mode: Literal["text", "card_preview", "card_stream"],
) -> SelectorResponse:
    """Persist the Feishu progress mode and return the updated panel."""
    if mode == "card_stream" and orch._config.feishu.runtime_mode != "native":
        return _render_settings_panel(
            orch,
            note="Feishu progress `card_stream` requires `native` runtime mode.",
        )
    orch._config.feishu.progress_mode = mode
    await _persist_feishu_config(orch)
    return _render_settings_panel(orch, note=f"Feishu progress updated: {mode}")


async def set_language(
    orch: Orchestrator,
    language: str,
) -> SelectorResponse:
    """Persist the language setting and return the updated panel."""
    if language not in LANGUAGES:
        return _render_settings_panel(orch, note=f"Unknown language: {language}")
    orch._config.language = language
    await update_config_file_async(orch.paths.config_path, language=language)
    init_i18n(language)
    return _render_settings_panel(orch, note=f"Language updated: {LANGUAGES[language]}")


async def refresh_version_info(orch: Orchestrator) -> SelectorResponse:
    """Refresh latest-version status and return the updated panel."""
    info = await check_latest_version(fresh=True)
    note = "Version status refreshed." if info is not None else "Version check failed."
    return _render_settings_panel(orch, note=note, version_info=info)


async def show_messaging_help(
    orch: Orchestrator,
    target: Literal["telegram", "feishu", "weixin"],
) -> SelectorResponse:
    """Render the settings panel with one transport-specific setup note."""
    return _render_settings_panel(orch, note=_messaging_help_note(orch, target))


async def set_telegram_bot_token(orch: Orchestrator, token: str) -> SelectorResponse:
    """Persist the Telegram bot token and advise restart."""
    cleaned = token.strip()
    if not cleaned:
        return _render_settings_panel(orch, note="Telegram bot token cannot be empty.")
    orch._config.telegram_token = cleaned
    await update_config_file_async(orch.paths.config_path, telegram_token=cleaned)
    return _render_settings_panel(
        orch,
        note=(
            "Telegram bot token saved. This is a transport-level change, so run `/restart` "
            "to apply it."
        ),
    )


async def set_feishu_app_credentials(
    orch: Orchestrator,
    app_id: str,
    app_secret: str,
) -> SelectorResponse:
    """Persist Feishu app credentials and advise restart."""
    cleaned_app_id = app_id.strip()
    cleaned_app_secret = app_secret.strip()
    if not cleaned_app_id or not cleaned_app_secret:
        return _render_settings_panel(
            orch,
            note="Feishu app_id and app_secret must both be provided.",
        )
    orch._config.feishu.app_id = cleaned_app_id
    orch._config.feishu.app_secret = cleaned_app_secret
    await _persist_feishu_config(orch)
    return _render_settings_panel(
        orch,
        note=(
            "Feishu app_id/app_secret saved. Restart ControlMesh to reload the Feishu transport."
        ),
    )


async def handle_settings_callback(orch: Orchestrator, data: str) -> SelectorResponse:
    """Handle one settings selector callback."""
    resp: SelectorResponse | None = None
    if data in {"st:r", "st:r:root"}:
        resp = _render_settings_panel(orch)
    elif data == "st:v:refresh":
        resp = await refresh_version_info(orch)
    else:
        parts = data.split(":")
        if len(parts) == 3 and parts[1] == "o" and parts[2] in _OUTPUT_MODES:
            resp = await set_streaming_output_mode(orch, parts[2])  # type: ignore[arg-type]
        elif len(parts) == 3 and parts[1] == "t" and parts[2] in _TOOL_DISPLAYS:
            resp = await set_tool_display_mode(orch, parts[2])  # type: ignore[arg-type]
        elif len(parts) == 3 and parts[1] == "m" and parts[2] in _MESSAGING_TARGETS:
            resp = await show_messaging_help(orch, parts[2])  # type: ignore[arg-type]
        elif (
            len(parts) == 4
            and parts[1] == "f"
            and parts[2] == "r"
            and parts[3] in _FEISHU_RUNTIME_MODES
        ):
            resp = await set_feishu_runtime_mode(orch, parts[3])  # type: ignore[arg-type]
        elif (
            len(parts) == 4
            and parts[1] == "f"
            and parts[2] == "p"
            and parts[3] in _FEISHU_PROGRESS_MODES
        ):
            resp = await set_feishu_progress_mode(orch, parts[3])  # type: ignore[arg-type]
        elif len(parts) == 3 and parts[1] == "l" and parts[2] in _LANGUAGE_CODES:
            resp = await set_language(orch, parts[2])  # type: ignore[arg-type]

    return resp or _render_settings_panel(orch, note="Unknown settings action.")


def settings_usage_text() -> str:
    """Render slash-command usage for transports without interactive callbacks."""
    return (
        "Usage: /settings\n"
        "       /settings output <full|tools|conversation|off>\n"
        "       /settings tools <name|details>\n"
        "       /settings language <en|de|nl|es|fr|pt|ru|zh>\n"
        "       /settings feishu runtime <bridge|native>\n"
        "       /settings feishu progress <text|card_preview|card_stream>\n"
        "       /settings messaging\n"
        "       /settings messaging telegram [token <BOT_TOKEN>]\n"
        "       /settings messaging feishu [app <APP_ID> <APP_SECRET>]\n"
        "       /settings messaging weixin\n"
        "       /settings version\n"
        "       /settings upgrade"
    )


async def _persist_streaming_config(orch: Orchestrator) -> None:
    await update_config_file_async(
        orch.paths.config_path,
        streaming=orch._config.streaming.model_dump(mode="json"),
    )


async def _persist_feishu_config(orch: Orchestrator) -> None:
    await update_config_file_async(
        orch.paths.config_path,
        feishu=orch._config.feishu.model_dump(mode="json"),
    )


def _render_settings_panel(
    orch: Orchestrator,
    *,
    note: str | None = None,
    version_info: VersionInfo | None = None,
) -> SelectorResponse:
    output_mode = orch._config.streaming.output_mode
    tool_display = orch._config.streaming.tool_display
    feishu_runtime = orch._config.feishu.runtime_mode
    feishu_progress = orch._config.feishu.progress_mode
    current_language = orch._config.language
    current_version = get_current_version()
    install_info = detect_install_info()
    install_mode = detect_install_mode()

    lines = ["**Advanced Settings**"]
    if note:
        lines.extend(["", note])
    lines.extend(
        [
            "",
            "**Streaming output**",
            f"Current: `{output_mode}`",
            "- `full`: conversation, tool activity, and system progress",
            "- `tools`: conversation plus tool activity only",
            "- `conversation`: assistant text only",
            "- `off`: no live stream, final reply only",
            "",
            "**Tool event display**",
            f"Current: `{tool_display}`",
            "- `name`: show only the tool name, e.g. `[TOOL: Bash]`",
            "- `details`: show Bash command text and output body in real time",
            "",
            "**Feishu runtime**",
            f"Runtime: `{feishu_runtime}`",
            f"Progress: `{feishu_progress}`",
            "- `native`: bundled plugin path with full native/runtime capabilities",
            "- `bridge`: reuse app credentials mainly as the chat bridge",
            "- `card_stream`: streaming cards, requires `native`",
            "",
            "**Messaging interfaces**",
            _messaging_status_line(
                "Telegram bot",
                "configured" if orch._config.telegram_token.strip() else "missing token",
            ),
            _messaging_status_line(
                "Feishu app",
                "configured"
                if orch._config.feishu.app_id.strip() and orch._config.feishu.app_secret.strip()
                else "missing app_id/app_secret",
            ),
            _messaging_status_line(
                "Weixin iLink",
                "enabled" if orch._config.weixin.enabled else "auth flow available",
            ),
            "- Telegram supports bot token config here.",
            "- Feishu supports app id/app secret and official console links.",
            "- Weixin uses QR/link-based auth flow rather than static secret fields.",
            "",
            "**Language**",
            f"Current: `{LANGUAGES.get(current_language, current_language)}`",
            "- Changes apply immediately and persist across restarts.",
            "",
            "**Version & upgrade**",
            f"Installed: `{current_version}`",
            f"Install mode: `{install_mode}`",
            f"Install source: `{_format_install_source(install_info)}`",
            _version_status_line(version_info),
            "- Refresh checks the newest version your current install source can actually upgrade to.",
            "- Upgrade follows the active install source; GitHub direct installs stay on their tracked ref.",
            "- GitHub branch installs verify commit changes as well as version changes after update.",
            "",
            settings_usage_text(),
        ]
    )

    rows = [
        [
            Button(text=_button_label(output_mode, "full", _OUTPUT_LABELS), callback_data="st:o:full"),
            Button(
                text=_button_label(output_mode, "tools", _OUTPUT_LABELS),
                callback_data="st:o:tools",
            ),
        ],
        [
            Button(
                text=_button_label(output_mode, "conversation", _OUTPUT_LABELS),
                callback_data="st:o:conversation",
            ),
            Button(text=_button_label(output_mode, "off", _OUTPUT_LABELS), callback_data="st:o:off"),
        ],
        [
            Button(
                text=_button_label(tool_display, "name", _TOOL_DISPLAY_LABELS),
                callback_data="st:t:name",
            ),
            Button(
                text=_button_label(tool_display, "details", _TOOL_DISPLAY_LABELS),
                callback_data="st:t:details",
            ),
        ],
        [
            Button(
                text=_button_label(feishu_runtime, "bridge", _FEISHU_RUNTIME_LABELS),
                callback_data="st:f:r:bridge",
            ),
            Button(
                text=_button_label(feishu_runtime, "native", _FEISHU_RUNTIME_LABELS),
                callback_data="st:f:r:native",
            ),
        ],
        [
            Button(
                text=_button_label(feishu_progress, "text", _FEISHU_PROGRESS_LABELS),
                callback_data="st:f:p:text",
            ),
            Button(
                text=_button_label(feishu_progress, "card_preview", _FEISHU_PROGRESS_LABELS),
                callback_data="st:f:p:card_preview",
            ),
        ],
        [
            Button(
                text=_button_label(feishu_progress, "card_stream", _FEISHU_PROGRESS_LABELS),
                callback_data="st:f:p:card_stream",
            ),
        ],
        [
            Button(text="Telegram bot", callback_data="st:m:telegram"),
            Button(text="Feishu app", callback_data="st:m:feishu"),
            Button(text="Weixin iLink", callback_data="st:m:weixin"),
        ],
        *_language_button_rows(current_language),
        [Button(text="Check latest", callback_data="st:v:refresh")],
        *_version_action_rows(version_info, install_mode, install_info),
        [Button(text="Refresh", callback_data="st:r:root")],
    ]
    return SelectorResponse(text="\n".join(lines), buttons=ButtonGrid(rows=rows))


def _button_label(current: str, value: str, labels: dict[str, str]) -> str:
    marker = "[x]" if current == value else "[ ]"
    return f"{marker} {labels[value]}"


def _version_status_line(version_info: VersionInfo | None) -> str:
    if version_info is None:
        return "Latest: `not available from current install source`"
    state = "update available" if version_info.update_available else "up to date"
    return f"Latest: `{version_info.latest}` ({version_info.source}, {state})"


def _messaging_status_line(label: str, state: str) -> str:
    return f"- {label}: `{state}`"


def _messaging_help_note(orch: Orchestrator, target: str) -> str:
    if target == "telegram":
        return (
            "Telegram setup:\n"
            "- Save token: `/settings messaging telegram token <BOT_TOKEN>`\n"
            "- This requires `/restart` to swap the live Telegram bot token."
        )
    if target == "feishu":
        return (
            "Feishu setup:\n"
            "- Save app credentials: `/settings messaging feishu app <APP_ID> <APP_SECRET>`\n"
            "- Official console: https://open.feishu.cn/app\n"
            "- Restart after saving credentials to reload the Feishu transport.\n"
            f"- Current runtime mode: `{orch._config.feishu.runtime_mode}`"
        )
    return (
        "Weixin setup:\n"
        "- Login flow: `controlmesh auth weixin login`\n"
        "- Reauth: `controlmesh auth weixin reauth`\n"
        f"- Service URL: `{orch._config.weixin.base_url}`\n"
        "- Weixin uses QR/link-based auth instead of a static bot token."
    )


def _language_button_rows(current: str) -> list[list[Button]]:
    """Build button rows for language selection."""
    rows: list[list[Button]] = []
    items = list(LANGUAGES.items())
    for i in range(0, len(items), 2):
        row: list[Button] = []
        for code, label in items[i : i + 2]:
            marker = "[x]" if current == code else "[ ]"
            row.append(Button(text=f"{marker} {label}", callback_data=f"st:l:{code}"))
        rows.append(row)
    return rows


def _format_install_source(install_info: object) -> str:
    source = getattr(install_info, "source", "unknown")
    requested_revision = getattr(install_info, "requested_revision", None)
    if source == "github" and isinstance(requested_revision, str) and requested_revision:
        return f"github@{requested_revision}"
    return str(source)


def _version_action_rows(
    version_info: VersionInfo | None,
    install_mode: str,
    install_info: object,
) -> list[list[Button]]:
    if version_info is None:
        return []

    rows: list[list[Button]] = [
        [
            Button(
                text=f"Changelog v{version_info.latest}",
                callback_data=f"upg:cl:{version_info.latest}",
            )
        ]
    ]
    if version_info.update_available and install_mode != "dev":
        source_label = _format_install_source(install_info)
        if str(getattr(install_info, "source", "")) == "github":
            action_label = f"Upgrade {source_label}"
        else:
            action_label = f"Upgrade to {version_info.latest}"
        rows.append(
            [
                Button(
                    text=action_label,
                    callback_data=f"upg:yes:{version_info.latest}",
                )
            ]
        )
    return rows
