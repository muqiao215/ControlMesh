"""Command handlers for all slash commands."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh.cli.auth import check_all_auth
from controlmesh.config import update_config_file_async
from controlmesh.history.catalog import (
    HistoryCatalog,
    render_search_result,
    render_session_result,
    render_task_result,
)
from controlmesh.i18n import t
from controlmesh.infra.install import detect_install_mode
from controlmesh.infra.updater import check_source_upgrade_status
from controlmesh.infra.version import check_latest_version, get_current_version
from controlmesh.memory.commands import (
    explain_authority_entry,
    render_daily_note_summary,
    render_memory_review,
    search_memory,
)
from controlmesh.orchestrator.providers import (
    normalize_provider_name,
    provider_display_name,
    provider_public_token,
)
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.orchestrator.selectors.cron_selector import cron_selector_start
from controlmesh.orchestrator.selectors.model_selector import model_selector_start, switch_model
from controlmesh.orchestrator.selectors.models import Button, ButtonGrid, SelectorResponse
from controlmesh.orchestrator.selectors.session_selector import session_selector_start
from controlmesh.orchestrator.selectors.settings_selector import (
    set_feishu_app_credentials,
    set_feishu_progress_mode,
    set_feishu_runtime_mode,
    set_language,
    set_streaming_output_mode,
    set_telegram_bot_token,
    set_tool_display_mode,
    settings_selector_start,
    settings_usage_text,
    show_messaging_help,
)
from controlmesh.orchestrator.selectors.task_selector import task_selector_start
from controlmesh.team.contracts import TEAM_TOPOLOGIES, ensure_team_topology
from controlmesh.text.response_format import SEP, fmt, new_session_text
from controlmesh.workspace.loader import read_file, read_mainmemory

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.session.key import SessionKey

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_LIMIT = 6
_MAX_HISTORY_LIMIT = 20
_CONTROL_MODE = "cm"
_PROVIDER_MODES = frozenset({"claude", "codex", "gemini", "claw", "claw-code", "opencode"})
_INTERNAL_PROVIDER_MODES = frozenset({"claude", "codex", "gemini", "claw", "opencode"})
_MODE_USAGE = "Usage: /mode [status|cm|claude|codex|gemini|claw-code|opencode]"
_TASKS_TOPOLOGY_OFF_TOKENS = frozenset({"off", "none", "manual", "unset"})
_MODE_LABELS = {
    "cm": "ControlMesh",
    "claude": "Claude-compatible channel",
    "codex": "Codex",
    "gemini": "Gemini",
    "claw": "Claw-Code",
    "claw-code": "Claw-Code",
    "opencode": "OpenCode",
}
_CORE_MODE_BUTTONS: tuple[tuple[str, str], ...] = (
    ("cm", "CM"),
    ("claude", "CLAUDE"),
    ("codex", "CODEX"),
    ("gemini", "GEMINI"),
)
_OPTIONAL_MODE_BUTTONS: tuple[tuple[str, str, str], ...] = (
    ("claw-code", "claw", "CLAW-CODE"),
    ("opencode", "opencode", "OPENCODE"),
)


class HistoryRequestKind(StrEnum):
    """Explicit /history request variants."""

    TAIL = "tail"
    SEARCH = "search"
    TASK = "task"
    SESSION = "session"


@dataclass(frozen=True)
class HistoryRequest:
    """Parsed /history command request."""

    kind: HistoryRequestKind
    limit: int | None = None
    value: str = ""


# -- Command wrappers (registered by Orchestrator._register_commands) --


async def cmd_reset(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /new: kill processes and reset only active provider session."""
    logger.info("Reset requested")
    await orch._process_registry.kill_all(key.chat_id)
    provider = await orch.reset_active_provider_session(key)
    return OrchestratorResult(text=new_session_text(provider))


async def cmd_status(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /status."""
    logger.info("Status requested")
    return OrchestratorResult(text=await _build_status(orch, key))


async def cmd_model(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /model [name]."""
    logger.info("Model requested")
    parts = text.split(None, 1)
    if len(parts) < 2:
        resp = await model_selector_start(orch, key)
        return OrchestratorResult(text=resp.text, buttons=resp.buttons)
    name = parts[1].strip()
    result_text = await switch_model(orch, key, name)
    return OrchestratorResult(text=result_text)


def _mode_label(mode: str) -> str:
    """Return an accurate user-facing label for a command mode."""
    normalized = normalize_provider_name(mode)
    return _MODE_LABELS.get(mode, _MODE_LABELS.get(normalized, provider_display_name(normalized)))


def _mode_status_text(mode: str, model: str | None = None) -> str:
    """Render the session-local takeover mode status."""
    if mode == _CONTROL_MODE:
        return "Takeover mode: ControlMesh\nControlMesh handles slash commands normally."

    model_line = f"\nTarget model: {model}" if model else ""
    display_channel = provider_public_token(mode)
    return (
        f"Takeover mode: {_mode_label(mode)}\n"
        f"Target channel: {display_channel}{model_line}\n"
        "Subsequent /xxx messages route to this CLI channel first.\n"
        "Use /cm to exit takeover mode, or /cm /status for ControlMesh commands."
    )


def _mode_selector_buttons(
    current_mode: str,
    available_providers: frozenset[str],
) -> ButtonGrid:
    """Return the Telegram-friendly takeover selector keyboard."""
    rows: list[list[Button]] = [
        [
            Button(
                text=f"• {label}" if mode == current_mode else label,
                callback_data=f"/mode {mode}",
            )
            for mode, label in _CORE_MODE_BUTTONS
        ]
    ]
    optional_modes = [
        (public_mode, internal_mode, label)
        for public_mode, internal_mode, label in _OPTIONAL_MODE_BUTTONS
        if internal_mode in available_providers or current_mode == internal_mode
    ]
    if optional_modes:
        rows.append(
            [
                Button(
                    text=f"• {label}" if internal_mode == current_mode else label,
                    callback_data=f"/mode {public_mode}",
                )
                for public_mode, internal_mode, label in optional_modes
            ]
        )
    return ButtonGrid(rows=rows)


async def _resolve_command_mode_model(
    orch: Orchestrator,
    key: SessionKey,
    provider: str,
) -> str | None:
    """Resolve the model to pin for a provider takeover mode."""
    active = await orch._sessions.get_active(key)
    if active is not None and active.provider == provider and active.model.strip():
        return active.model

    configured_model, configured_provider = orch.resolve_runtime_target(orch._config.model)
    if configured_provider == provider and configured_model.strip():
        return configured_model

    default_model = orch._providers.default_model_for_provider(provider).strip()
    return default_model or None


async def cmd_mode(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /mode [status|cm|claude|codex|gemini]."""
    parts = text.strip().split(None, 1)
    action = parts[1].strip().lower() if len(parts) > 1 else "status"
    show_selector = len(parts) == 1
    if action == "status":
        session = await orch._sessions.get_active(key)
        current_mode = session.command_mode if session is not None else _CONTROL_MODE
        if session is None:
            return OrchestratorResult(
                text=_mode_status_text(_CONTROL_MODE),
                buttons=(
                    _mode_selector_buttons(_CONTROL_MODE, orch.available_providers)
                    if show_selector
                    else None
                ),
            )
        return OrchestratorResult(
            text=_mode_status_text(session.command_mode, session.command_mode_model),
            buttons=(
                _mode_selector_buttons(current_mode, orch.available_providers)
                if show_selector
                else None
            ),
        )

    if action == _CONTROL_MODE:
        session = await orch._sessions.get_active(key)
        if session is not None:
            await orch._sessions.sync_command_mode(session, mode=_CONTROL_MODE, model=None)
        return OrchestratorResult(text=_mode_status_text(_CONTROL_MODE))

    if action not in _PROVIDER_MODES:
        return OrchestratorResult(text=_MODE_USAGE)
    provider = normalize_provider_name(action)
    if provider not in _INTERNAL_PROVIDER_MODES:
        return OrchestratorResult(text=_MODE_USAGE)

    model = await _resolve_command_mode_model(orch, key, provider)
    if model is None:
        return OrchestratorResult(
            text=(
                f"Cannot enable {_mode_label(provider)} takeover mode yet: no default model "
                f"is known for channel '{provider_public_token(provider)}'.\n"
                "Make that runtime the active provider first, then retry."
            )
        )

    session = await orch._sessions.get_active(key)
    if session is None:
        configured_model, configured_provider = orch.resolve_runtime_target(orch._config.model)
        session, _is_new = await orch._sessions.resolve_session(
            key,
            provider=configured_provider,
            model=configured_model,
        )

    await orch._sessions.sync_command_mode(session, mode=provider, model=model)
    return OrchestratorResult(text=_mode_status_text(provider, model))


async def cmd_claude_native(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /claude_native [on|off|status]."""
    parts = text.strip().split(None, 1)
    action = parts[1].strip().lower() if len(parts) > 1 else "status"
    if action not in {"on", "off", "status"}:
        return OrchestratorResult(text="Usage: /claude_native [on|off|status]")

    active = await orch._sessions.get_active(key)
    if active is not None:
        provider = active.provider
        model = active.model
    else:
        model, provider = orch.resolve_runtime_target(orch._config.model)

    if provider != "claude":
        return OrchestratorResult(
            text=(
                "Claude native command mode is only available when the active provider is Claude.\n"
                "Switch to a Claude model first, then retry."
            )
        )

    session, _is_new = await orch._sessions.resolve_session(
        key,
        provider=provider,
        model=model,
        preserve_existing_target=False,
    )

    if action == "status":
        mode = "on" if session.command_mode == "claude" else "off"
        return OrchestratorResult(
            text=(
                f"Claude native command mode: {mode}\n"
                "When on, subsequent /xxx messages go to the claude channel first.\n"
                "Provider labels are channels; the configured backend may vary.\n"
                "Use /cm /status or /cm /model ... to force ControlMesh commands."
            )
        )

    enabled = action == "on"
    await orch._sessions.sync_command_mode(
        session,
        mode="claude" if enabled else _CONTROL_MODE,
        model=model if enabled else None,
    )
    mode = "on" if enabled else "off"
    return OrchestratorResult(
        text=(
            f"Claude native command mode: {mode}\n"
            "This uses the claude channel; the configured backend may vary.\n"
            "Use /cm /status or /cm /model ... to force ControlMesh commands."
        )
    )


async def cmd_settings(orch: Orchestrator, _key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /settings: advanced runtime output settings."""
    parts = text.strip().split()
    result: OrchestratorResult | None = None
    if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() == "status"):
        resp = await settings_selector_start(orch)
        result = OrchestratorResult(text=resp.text, buttons=resp.buttons)
    elif parts[1].lower().replace("-", "_") == "version":
        resp = await settings_selector_start(
            orch,
            note="Version status refreshed.",
            version_info=await check_latest_version(fresh=True),
        )
        result = OrchestratorResult(text=resp.text, buttons=resp.buttons)
    elif parts[1].lower().replace("-", "_") == "messaging":
        if len(parts) == 2:
            resp = await settings_selector_start(orch)
            result = OrchestratorResult(text=resp.text, buttons=resp.buttons)
        else:
            result = await _cmd_settings_update(orch, parts)
    elif parts[1].lower().replace("-", "_") == "upgrade":
        result = await cmd_upgrade(orch, _key, "/upgrade")
    elif parts[1].lower().replace("-", "_") in {"language", "lang"}:
        if len(parts) >= 3:
            result = await _cmd_settings_update(orch, parts)
        else:
            resp = await settings_selector_start(orch)
            result = OrchestratorResult(text=resp.text, buttons=resp.buttons)
    elif len(parts) >= 3:
        result = await _cmd_settings_update(orch, parts)

    return result or OrchestratorResult(text=settings_usage_text())


async def _cmd_settings_update(
    orch: Orchestrator,
    parts: list[str],
) -> OrchestratorResult | None:
    section = parts[1].lower().replace("-", "_")
    value = parts[2].lower()
    if section in {"output", "streaming"} and value in {"full", "tools", "conversation", "off"}:
        resp = await set_streaming_output_mode(orch, value)  # type: ignore[arg-type]
    elif section in {"tools", "tool_display", "tool_output"} and value in {"name", "details"}:
        resp = await set_tool_display_mode(orch, value)  # type: ignore[arg-type]
    elif section == "feishu":
        resp = await _cmd_settings_feishu_update(orch, parts)
    elif section == "messaging":
        resp = await _cmd_settings_messaging_update(orch, parts)
    elif section in {"language", "lang"}:
        resp = await set_language(orch, value)
    else:
        resp = None

    if resp is None:
        return None
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def _cmd_settings_feishu_update(
    orch: Orchestrator,
    parts: list[str],
) -> SelectorResponse | None:
    if len(parts) < 4:
        return None

    feishu_section = parts[2].lower()
    feishu_value = parts[3].lower()
    if feishu_section in {"runtime", "mode"} and feishu_value in {"bridge", "native"}:
        return await set_feishu_runtime_mode(orch, feishu_value)  # type: ignore[arg-type]
    if feishu_section in {"progress", "stream"} and feishu_value in {
        "text",
        "card_preview",
        "card_stream",
    }:
        return await set_feishu_progress_mode(orch, feishu_value)  # type: ignore[arg-type]
    return None


async def _cmd_settings_messaging_update(
    orch: Orchestrator,
    parts: list[str],
) -> SelectorResponse | None:
    target = parts[2].lower()
    if target not in {"telegram", "feishu", "weixin"}:
        return None
    if len(parts) == 3:
        return await show_messaging_help(orch, target)  # type: ignore[arg-type]

    action = parts[3].lower()
    if target == "telegram" and action == "token" and len(parts) >= 5:
        token = " ".join(parts[4:]).strip()
        return await set_telegram_bot_token(orch, token)
    if target == "feishu" and action == "app" and len(parts) >= 6:
        return await set_feishu_app_credentials(orch, parts[4], parts[5])
    if target == "weixin":
        return await show_messaging_help(orch, "weixin")
    return None


async def cmd_controlmesh(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /cm <controlmesh-command> as an escape hatch from native mode."""
    parts = text.strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        session = await orch._sessions.get_active(key)
        if session is not None:
            await orch._sessions.sync_command_mode(session, mode=_CONTROL_MODE, model=None)
        return OrchestratorResult(text=_mode_status_text(_CONTROL_MODE))
    nested = parts[1].strip()
    if not nested.startswith("/"):
        return OrchestratorResult(text="Usage: /cm /status")
    return await orch.dispatch_controlmesh_command(key, nested)


async def cmd_memory(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /memory [today|search <query>|why <id>|review]."""
    from datetime import UTC, datetime

    logger.info("Memory requested")
    parts = _text.strip().split(None, 2)

    # /memory with no subcommand - show full authority + legacy
    if len(parts) == 1:
        return await _cmd_memory_full(orch)

    subcommand = parts[1].lower()

    if subcommand == "today":
        today = datetime.now(UTC).date()
        return await _cmd_memory_today(orch, today)

    if subcommand == "search":
        return await _cmd_memory_search(orch, parts)

    if subcommand == "why":
        return await _cmd_memory_why(orch, parts)

    if subcommand == "review":
        return await _cmd_memory_review(orch)

    # Unknown subcommand - show usage
    return OrchestratorResult(text="Usage: /memory [today|search <query>|why <id>|review]")


async def _cmd_memory_today(orch: Orchestrator, today: date) -> OrchestratorResult:
    """Handle /memory today."""
    summary = await asyncio.to_thread(render_daily_note_summary, orch.paths, today)
    if not summary:
        return OrchestratorResult(text=f"No daily note found for {today.isoformat()}.")
    return OrchestratorResult(text=summary)


async def _cmd_memory_search(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory search <query>."""
    if len(parts) < 3:
        return OrchestratorResult(text="Usage: /memory search <query>")
    query = parts[2]
    result = await asyncio.to_thread(search_memory, orch.paths, query)
    if not result.hits:
        return OrchestratorResult(text=f"No results found for: {query}")
    lines = [f"## Search: {query}\n"]
    for hit in result.hits:
        lines.append(f"**[{hit.kind.value}]** {hit.source_path}")
        lines.append(f"_{hit.snippet}_")
        lines.append("")
    return OrchestratorResult(text="\n".join(lines))


async def _cmd_memory_why(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory why <entry-id>."""
    if len(parts) < 3:
        return OrchestratorResult(text="Usage: /memory why <entry-id>")
    entry_id = parts[2]
    explanation = await asyncio.to_thread(explain_authority_entry, orch.paths, entry_id)
    if explanation is None:
        return OrchestratorResult(text=f"No authority entry found with id: {entry_id}")
    return OrchestratorResult(text=f"## Provenance\n\n{explanation}")


async def _cmd_memory_review(orch: Orchestrator) -> OrchestratorResult:
    """Handle /memory review."""
    review = await asyncio.to_thread(render_memory_review, orch.paths)
    if not review:
        return OrchestratorResult(text="No memory to review.")
    return OrchestratorResult(text=review)


async def _cmd_memory_full(orch: Orchestrator) -> OrchestratorResult:
    """Render the full /memory output (authority + legacy)."""
    legacy = await asyncio.to_thread(read_mainmemory, orch.paths)
    authority = await asyncio.to_thread(read_file, orch.paths.authority_memory_path) or ""
    sections: list[str] = []
    if authority.strip():
        sections.extend(["## Authority Memory (v2)", authority.strip()])
    if legacy.strip():
        sections.extend(["## Legacy Compatibility Memory", legacy.strip()])

    if not sections:
        return OrchestratorResult(
            text=fmt(
                t("memory.header"),
                SEP,
                t("memory.empty"),
                SEP,
                t("memory.empty_tip"),
            ),
        )
    return OrchestratorResult(
        text=fmt(
            t("memory.header"),
            SEP,
            *sections,
            SEP,
            t("memory.filled_tip"),
        ),
    )


async def cmd_history(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /history [n|search <query>|task <task_id>|session <session_key>]."""
    logger.info("History requested")
    request = parse_history_request(text)
    if request is None:
        return OrchestratorResult(text=_history_usage_text())

    if request.kind == HistoryRequestKind.TAIL:
        rendered = await _render_history_tail(orch, key, request.limit or _DEFAULT_HISTORY_LIMIT)
        return OrchestratorResult(text=rendered)

    rendered = await _render_indexed_history(orch, request)
    return OrchestratorResult(text=rendered)


async def cmd_sessions(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /sessions."""
    logger.info("Sessions requested")
    resp = await session_selector_start(orch, key.chat_id)
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def cmd_tasks(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /tasks."""
    logger.info("Tasks requested")
    parts = _text.strip().split()
    if len(parts) >= 2 and parts[1].lower() == "topology":
        return await _cmd_tasks_topology(orch, parts[2:])

    hub = orch.task_hub
    if hub is None:
        return OrchestratorResult(
            text=fmt(t("tasks.header"), SEP, t("tasks.disabled")),
        )
    resp = task_selector_start(hub, key.chat_id)
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def _cmd_tasks_topology(
    orch: Orchestrator,
    args: list[str],
) -> OrchestratorResult:
    if not args or args[0].lower() == "status":
        return OrchestratorResult(
            text=_tasks_topology_status_text(orch._config.tasks.default_topology)
        )

    if len(args) > 1:
        return OrchestratorResult(text=_tasks_topology_usage_text())

    requested = args[0].lower()
    if requested in _TASKS_TOPOLOGY_OFF_TOKENS:
        topology: str | None = None
    else:
        try:
            topology = ensure_team_topology(requested, "topology")
        except ValueError:
            return OrchestratorResult(text=_tasks_topology_usage_text())

    orch._config.tasks.default_topology = topology
    await update_config_file_async(
        orch.paths.config_path,
        tasks=orch._config.tasks.model_dump(mode="json"),
    )
    return OrchestratorResult(text=_tasks_topology_status_text(topology, updated=True))


def _tasks_topology_usage_text() -> str:
    options = "|".join(("status", *TEAM_TOPOLOGIES, "off"))
    supported = ", ".join(TEAM_TOPOLOGIES)
    return f"Usage: /tasks topology [{options}]\nApproved topologies: {supported}"


def _tasks_topology_status_text(topology: str | None, *, updated: bool = False) -> str:
    selected = topology or "manual"
    action_line = (
        f"Background topology default updated: {selected}"
        if updated
        else f"Background topology default: {selected}"
    )
    supported = ", ".join(TEAM_TOPOLOGIES)
    return (
        f"{action_line}\n"
        f"Approved topologies: {supported}\n"
        "Selection stays explicit. ControlMesh will not infer a topology automatically."
    )


async def cmd_cron(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /cron."""
    logger.info("Cron requested")
    resp = await cron_selector_start(orch)
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def cmd_upgrade(_orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /upgrade: check for updates and offer upgrade."""
    logger.info("Upgrade check requested")
    current = get_current_version()

    if detect_install_mode() == "dev":
        status = await check_source_upgrade_status(current_version=current)
        current_label = f"{current} ({status.current_commit[:7]})" if status.current_commit else current
        if status.actionable:
            keyboard = ButtonGrid(
                rows=[
                    [
                        Button(
                            text=t("upgrade.btn_yes"),
                            callback_data="upg:yes:source",
                        ),
                        Button(text=t("upgrade.btn_not_now"), callback_data="upg:no"),
                    ],
                ]
            )
            target_label = status.upstream or "upstream"
            behind_label = f"{status.behind} commit{'s' if status.behind != 1 else ''}"
            return OrchestratorResult(
                text=fmt(
                    t("upgrade.available_header"),
                    SEP,
                    (
                        f"Installed: `{current_label}`\n"
                        f"New:       `{target_label}` ({behind_label})\n\n"
                        "Source checkout can fast-forward safely. Upgrade now?"
                    ),
                ),
                buttons=keyboard,
            )

        if status.message.startswith("Source checkout already matches upstream"):
            latest_label = status.upstream or current_label
            return OrchestratorResult(
                text=fmt(
                    t("upgrade.up_to_date_header"),
                    SEP,
                    (
                        f"Installed: `{current_label}`\n"
                        f"Latest:    `{latest_label}`\n\n"
                        "Your source checkout already matches upstream."
                    ),
                ),
            )

        return OrchestratorResult(
            text=fmt(
                "**Source Upgrade Blocked**",
                SEP,
                status.message or "Source upgrade is not currently actionable.",
            ),
        )

    info = await check_latest_version(fresh=True)

    if info is None:
        return OrchestratorResult(
            text=t("upgrade.pypi_unreachable"),
        )

    if not info.update_available:
        keyboard = ButtonGrid(
            rows=[
                [
                    Button(
                        text=t("upgrade.btn_changelog", version=info.current),
                        callback_data=f"upg:cl:{info.current}",
                    )
                ],
            ]
        )
        return OrchestratorResult(
            text=fmt(
                t("upgrade.up_to_date_header"),
                SEP,
                t("upgrade.up_to_date_body", current=info.current, latest=info.latest),
            ),
            buttons=keyboard,
        )

    keyboard = ButtonGrid(
        rows=[
            [
                Button(
                    text=t("upgrade.btn_changelog", version=info.latest),
                    callback_data=f"upg:cl:{info.latest}",
                )
            ],
            [
                Button(
                    text=t("upgrade.btn_yes"),
                    callback_data=f"upg:yes:{info.latest}",
                ),
                Button(text=t("upgrade.btn_not_now"), callback_data="upg:no"),
            ],
        ]
    )

    return OrchestratorResult(
        text=fmt(
            t("upgrade.available_header"),
            SEP,
            t("upgrade.available_body", current=info.current, latest=info.latest),
        ),
        buttons=keyboard,
    )


def _build_codex_cache_block(orch: Orchestrator) -> str:
    """Build the Codex model cache section for /diagnose."""
    if not orch._observers.codex_cache_obs:
        return "\n🔄 " + t("diagnose.codex_cache_not_init")
    cache = orch._observers.codex_cache_obs.get_cache()
    if not cache or not cache.models:
        return "\n🔄 " + t("diagnose.codex_cache_not_loaded")
    default_model = next((m.id for m in cache.models if m.is_default), "N/A")
    return "\n🔄 " + t(
        "diagnose.codex_cache_info",
        updated=cache.last_updated,
        count=len(cache.models),
        default=default_model,
    )


def _build_diagnose_health_block(orch: Orchestrator) -> str:
    """Build the multi-agent health section for /diagnose."""
    supervisor = orch._supervisor
    if supervisor is None:
        return ""
    status_icon = {"running": "●", "starting": "◐", "crashed": "✖", "stopped": "○"}
    agent_lines = ["\n" + t("diagnose.health_header")]
    for name in sorted(supervisor.health.keys()):
        h = supervisor.health[name]
        icon = status_icon.get(h.status, "?")
        role = "main" if name == "main" else "sub"
        line = f"  {icon} `{name}` [{role}] — {h.status}"
        if h.status == "running" and h.uptime_human:
            line += f" ({h.uptime_human})"
        if h.restart_count > 0:
            line += f" | restarts: {h.restart_count}"
        if h.status == "crashed" and h.last_crash_error:
            line += f"\n      `{h.last_crash_error[:100]}`"
        agent_lines.append(line)
    return "\n".join(agent_lines)


def _resolve_log_path(orch: Orchestrator) -> Path:
    """Return the best available log file path.

    Sub-agents don't have their own log files — fall back to the central
    log in the main controlmesh home (parent of ``agents/<name>``).
    """
    log_path = orch.paths.logs_dir / "agent.log"
    if not log_path.exists():
        main_logs = orch.paths.controlmesh_home.parent.parent / "logs" / "agent.log"
        if main_logs.exists():
            return main_logs
    return log_path


async def cmd_diagnose(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /diagnose."""
    logger.info("Diagnose requested")
    version = get_current_version()
    effective_model, effective_provider = orch.resolve_runtime_target(orch._config.model)
    info_block = (
        f"{t('diagnose.version_line', version=version)}\n"
        f"{t('diagnose.configured_line', provider=orch._config.provider, model=orch._config.model)}\n"
        f"{t('diagnose.effective_line', provider=effective_provider, model=effective_model)}"
    )

    cache_block = _build_codex_cache_block(orch)
    agent_block = _build_diagnose_health_block(orch)

    log_tail = await _read_log_tail(_resolve_log_path(orch))
    log_block = (
        f"{t('diagnose.log_header')}\n```\n{log_tail}\n```" if log_tail else t("diagnose.no_log")
    )

    return OrchestratorResult(
        text=fmt(t("diagnose.header"), SEP, info_block, cache_block, agent_block, SEP, log_block),
    )


# -- Helpers ------------------------------------------------------------------


def _parse_history_limit(text: str) -> int | None:
    """Parse the optional /history limit."""
    request = parse_history_request(text)
    if request is None or request.kind != HistoryRequestKind.TAIL:
        return None
    return request.limit or _DEFAULT_HISTORY_LIMIT


def parse_history_request(text: str) -> HistoryRequest | None:
    """Parse explicit /history read variants."""
    parts = text.strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return HistoryRequest(kind=HistoryRequestKind.TAIL, limit=_DEFAULT_HISTORY_LIMIT)

    arg = parts[1].strip()
    head, _, tail = arg.partition(" ")
    subcommand = head.lower()
    indexed_request = _parse_indexed_history_request(subcommand, tail.strip())
    if indexed_request is not None:
        return indexed_request
    if subcommand in {
        HistoryRequestKind.SEARCH,
        HistoryRequestKind.TASK,
        HistoryRequestKind.SESSION,
    }:
        return None

    try:
        limit = int(arg)
    except ValueError:
        return None
    if limit < 1 or limit > _MAX_HISTORY_LIMIT:
        return None
    return HistoryRequest(kind=HistoryRequestKind.TAIL, limit=limit)


def _history_usage_text() -> str:
    return (
        "Usage: /history [n]\n"
        "       /history search <query>\n"
        "       /history task <task_id>\n"
        "       /history session <session_key>\n"
        "Choose a number from 1 to 20."
    )


async def _render_history_tail(orch: Orchestrator, key: SessionKey, limit: int) -> str:
    turns = await orch.read_frontstage_history(key, limit=limit)
    if not turns:
        return "No visible history yet."

    body = "\n".join(
        f"{idx}. [{turn.role}] {_history_preview(turn.visible_content) or '(attachment only)'}"
        f"{_history_attachment_suffix(turn)}"
        for idx, turn in enumerate(turns, start=1)
    )
    header = f"**Recent Visible History** ({len(turns)} turns)"
    return fmt(header, SEP, body)


async def _render_indexed_history(orch: Orchestrator, request: HistoryRequest) -> str:
    catalog = HistoryCatalog(orch.history_index)
    try:
        if request.kind == HistoryRequestKind.SEARCH:
            return await asyncio.to_thread(render_search_result, catalog.search(request.value))
        if request.kind == HistoryRequestKind.TASK:
            return await asyncio.to_thread(render_task_result, catalog.task(request.value))
        return await asyncio.to_thread(render_session_result, catalog.session(request.value))
    except ValueError:
        return _history_usage_text()


def _parse_indexed_history_request(subcommand: str, value: str) -> HistoryRequest | None:
    if not value:
        return None
    if subcommand == HistoryRequestKind.SEARCH:
        return HistoryRequest(kind=HistoryRequestKind.SEARCH, value=value)
    if subcommand == HistoryRequestKind.TASK:
        return HistoryRequest(kind=HistoryRequestKind.TASK, value=value)
    if subcommand == HistoryRequestKind.SESSION:
        return HistoryRequest(kind=HistoryRequestKind.SESSION, value=value)
    return None


def _history_preview(text: str, *, limit: int = 160) -> str:
    """Collapse one visible turn into a bounded single-line preview."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _history_attachment_suffix(turn: object) -> str:
    """Return a compact attachment suffix for one transcript turn."""
    attachments = getattr(turn, "attachments", [])
    if not attachments:
        return ""
    labels = [attachment.label or attachment.path or attachment.kind for attachment in attachments]
    return f" [attachments: {', '.join(labels)}]"


def _build_agent_health_block(orch: Orchestrator) -> str:
    """Build the multi-agent health section for /status (main agent only)."""
    supervisor = orch._supervisor
    if supervisor is None or len(supervisor.health) <= 1:
        return ""

    status_icon = {
        "running": "●",
        "starting": "◐",
        "crashed": "✖",
        "stopped": "○",
    }
    agent_lines = [t("status.agents_header")]
    for name in sorted(supervisor.health.keys()):
        if name == "main":
            continue
        h = supervisor.health[name]
        icon = status_icon.get(h.status, "?")
        line = f"  {icon} {name} — {h.status}"
        if h.status == "running" and h.uptime_human:
            line += f" ({h.uptime_human})"
        if h.restart_count > 0:
            line += f" ⟳{h.restart_count}"
        if h.status == "crashed" and h.last_crash_error:
            line += f"\n      {h.last_crash_error[:80]}"
        agent_lines.append(line)
    return "\n".join(agent_lines)


async def _build_status(orch: Orchestrator, key: SessionKey) -> str:
    """Build the /status response text."""
    runtime_model, _runtime_provider = orch.resolve_runtime_target(orch._config.model)
    configured_model = orch._config.model

    def _model_line(model_name: str) -> str:
        if model_name == configured_model:
            return t("status.model_line", model=model_name)
        return t("status.model_line_configured", model=model_name, configured=configured_model)

    session = await orch._sessions.get_active(key)
    if session:
        topic_line = (
            f"{t('status.topic_line', topic=session.topic_name)}\n" if session.topic_name else ""
        )
        session_block = (
            f"{topic_line}"
            f"{t('status.session_line', sid=session.session_id[:8] + '...')}\n"
            f"{t('status.messages_line', count=session.message_count)}\n"
            f"{t('status.tokens_line', tokens=f'{session.total_tokens:,}')}\n"
            f"{t('status.cost_line', cost=f'{session.total_cost_usd:.4f}')}\n"
            f"Takeover mode: {_mode_label(session.command_mode)}\n"
            f"{_model_line(session.model)}"
        )
    else:
        session_block = f"{t('status.no_session')}\n{_model_line(runtime_model)}"

    bg_tasks = orch.active_background_tasks(key.chat_id)
    bg_block = ""
    if bg_tasks:
        import time

        bg_lines = [t("status.bg_header", count=len(bg_tasks))]
        for bg_t in bg_tasks:
            age = time.monotonic() - bg_t.submitted_at
            bg_lines.append(f"  `{bg_t.task_id}` {bg_t.prompt[:40]}... ({age:.0f}s)")
        bg_block = "\n".join(bg_lines)

    auth = await asyncio.to_thread(check_all_auth)
    auth_lines: list[str] = []
    for provider, result in auth.items():
        age_label = f" ({result.age_human})" if result.age_human else ""
        auth_lines.append(f"  [{provider}] {result.status.value}{age_label}")
    auth_block = t("status.auth_header") + "\n" + "\n".join(auth_lines)

    agent_block = _build_agent_health_block(orch)

    blocks = [t("status.header"), SEP, session_block]
    if bg_block:
        blocks += [SEP, bg_block]
    blocks += [SEP, auth_block]
    if agent_block:
        blocks += [SEP, agent_block]
    return fmt(*blocks)


async def _read_log_tail(log_path: Path, lines: int = 50) -> str:
    """Read the last *lines* of a log file without blocking the event loop."""

    def _read() -> str:
        if not log_path.is_file():
            return ""
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.strip().splitlines()[-lines:])
        except OSError:
            return "(could not read log file)"

    return await asyncio.to_thread(_read)
