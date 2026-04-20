"""Interactive advanced settings selector for streaming output controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from controlmesh.config import update_config_file_async
from controlmesh.orchestrator.selectors.models import Button, ButtonGrid, SelectorResponse

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator

_OUTPUT_MODES: tuple[str, ...] = ("full", "tools", "conversation", "off")
_TOOL_DISPLAYS: tuple[str, ...] = ("name", "details")
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


def is_settings_selector_callback(data: str) -> bool:
    """Return True when *data* belongs to the settings selector."""
    return bool(data) and data.startswith(_PREFIX)


async def settings_selector_start(orch: Orchestrator, note: str | None = None) -> SelectorResponse:
    """Build the advanced settings panel."""
    return _render_settings_panel(orch, note=note)


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


async def handle_settings_callback(orch: Orchestrator, data: str) -> SelectorResponse:
    """Handle one settings selector callback."""
    if data in {"st:r", "st:r:root"}:
        return _render_settings_panel(orch)

    parts = data.split(":")
    if len(parts) == 3 and parts[1] == "o" and parts[2] in _OUTPUT_MODES:
        return await set_streaming_output_mode(orch, parts[2])  # type: ignore[arg-type]
    if len(parts) == 3 and parts[1] == "t" and parts[2] in _TOOL_DISPLAYS:
        return await set_tool_display_mode(orch, parts[2])  # type: ignore[arg-type]
    return _render_settings_panel(orch, note="Unknown settings action.")


def settings_usage_text() -> str:
    """Render slash-command usage for transports without interactive callbacks."""
    return (
        "Usage: /settings\n"
        "       /settings output <full|tools|conversation|off>\n"
        "       /settings tools <name|details>"
    )


async def _persist_streaming_config(orch: Orchestrator) -> None:
    await update_config_file_async(
        orch.paths.config_path,
        streaming=orch._config.streaming.model_dump(mode="json"),
    )


def _render_settings_panel(orch: Orchestrator, *, note: str | None = None) -> SelectorResponse:
    output_mode = orch._config.streaming.output_mode
    tool_display = orch._config.streaming.tool_display

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
        [Button(text="Refresh", callback_data="st:r:root")],
    ]
    return SelectorResponse(text="\n".join(lines), buttons=ButtonGrid(rows=rows))


def _button_label(current: str, value: str, labels: dict[str, str]) -> str:
    marker = "[x]" if current == value else "[ ]"
    return f"{marker} {labels[value]}"
