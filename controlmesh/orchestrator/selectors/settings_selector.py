"""Interactive advanced settings selector for streaming output controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from controlmesh.config import update_config_file_async
from controlmesh.infra.install import detect_install_info, detect_install_mode
from controlmesh.infra.version import VersionInfo, check_latest_version, get_current_version
from controlmesh.orchestrator.selectors.models import Button, ButtonGrid, SelectorResponse

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator

_OUTPUT_MODES: tuple[str, ...] = ("full", "tools", "conversation", "off")
_TOOL_DISPLAYS: tuple[str, ...] = ("name", "details")
_FEISHU_RUNTIME_MODES: tuple[str, ...] = ("bridge", "native")
_FEISHU_PROGRESS_MODES: tuple[str, ...] = ("text", "card_preview", "card_stream")
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


async def refresh_version_info(orch: Orchestrator) -> SelectorResponse:
    """Refresh latest-version status and return the updated panel."""
    info = await check_latest_version(fresh=True)
    note = "Version status refreshed." if info is not None else "Version check failed."
    return _render_settings_panel(orch, note=note, version_info=info)


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

    return resp or _render_settings_panel(orch, note="Unknown settings action.")


def settings_usage_text() -> str:
    """Render slash-command usage for transports without interactive callbacks."""
    return (
        "Usage: /settings\n"
        "       /settings output <full|tools|conversation|off>\n"
        "       /settings tools <name|details>\n"
        "       /settings feishu runtime <bridge|native>\n"
        "       /settings feishu progress <text|card_preview|card_stream>\n"
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
            "**Version & upgrade**",
            f"Installed: `{current_version}`",
            f"Install mode: `{install_mode}`",
            f"Install source: `{_format_install_source(install_info)}`",
            _version_status_line(version_info),
            "- Refresh checks public release metadata (GitHub Releases first, then PyPI).",
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
        return "Latest: `not checked`"
    state = "update available" if version_info.update_available else "up to date"
    return f"Latest: `{version_info.latest}` ({version_info.source}, {state})"


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
