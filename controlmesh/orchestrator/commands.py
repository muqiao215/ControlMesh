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
    apply_daily_note_promotions,
    deprecate_authority_entry,
    dispute_authority_entry,
    explain_authority_entry,
    preview_daily_note_promotions,
    render_daily_note_summary,
    render_memory_review,
    search_memory,
    supersede_authority_entry,
)
from controlmesh.memory.frequency import find_repeated_patterns, render_patterns_summary
from controlmesh.memory.promotion import parse_authority_entry
from controlmesh.memory.semantic import search_semantic_index
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
    from controlmesh.memory.models import MemoryScope
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.session.key import SessionKey

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_LIMIT = 6
_MAX_HISTORY_LIMIT = 20
_CONTROL_MODE = "cm"
_CLAUDE_NATIVE_REGISTRY = (
    "**Claude 原生命令**\n\n"
    "- `/add-dir` 添加工作目录\n"
    "- `/agents` 管理 Claude agents\n"
    "- `/bug` 上报 Claude Code 问题\n"
    "- `/clear` 清空当前上下文\n"
    "- `/compact` 压缩上下文\n"
    "- `/config` Claude Code 配置\n"
    "- `/cost` 查看用量成本\n"
    "- `/doctor` 诊断 Claude Code 环境\n"
    "- `/help` Claude 原生帮助\n"
    "- `/ide` IDE 集成\n"
    "- `/init` 初始化项目上下文\n"
    "- `/install-github-app` 安装 GitHub App\n"
    "- `/login` 登录 Claude\n"
    "- `/logout` 退出 Claude\n"
    "- `/mcp` 管理 MCP server\n"
    "- `/memory` Claude 记忆\n"
    "- `/model` Claude 模型选择\n"
    "- `/permissions` Claude 工具权限\n"
    "- `/pr_comments` 拉取 PR 评论\n"
    "- `/review` 代码审查\n"
    "- `/status` Claude 会话状态\n"
    "- `/terminal-setup` 终端集成\n"
    "- `/vim` Vim 模式\n"
    "- `/remote-control` Claude Remote Control\n"
    "- `/rc` Remote Control 简写\n"
    "- `/back` 返回 ControlMesh 命令\n\n"
    "当前菜单：Claude 原生命令。上面的 `/xxx` 会直接发给 Claude。"
)
_CONTROL_MESH_REGISTRY = (
    "**ControlMesh 命令**\n\n"
    "- `/new` 新会话\n"
    "- `/cm` 打开 Claude 原生命令\n"
    "- `/back` 返回 ControlMesh 命令\n"
    "- `/model` 模型/通道\n"
    "- `/tasks` 后台任务\n"
    "- `/session` 会话入口\n"
    "- `/agents` Agent 队列\n"
    "- `/cron` 定时任务\n"
    "- `/status` 当前状态\n"
    "- `/memory` 主记忆\n"
    "- `/settings` 设置\n"
    "- `/help` 完整帮助\n\n"
    "当前菜单：ControlMesh 命令。"
)
_TASKS_TOPOLOGY_OFF_TOKENS = frozenset({"off", "none", "manual", "unset"})
_COMMAND_MENU_LABELS = {
    "cm": "ControlMesh",
    "claude": "Claude 原生命令",
    "codex": "Codex",
    "gemini": "Gemini",
    "claw": "Claw-Code",
    "opencode": "OpenCode",
}
_CLAUDE_NATIVE_BUTTONS = ButtonGrid(rows=[[Button(text="返回 ControlMesh", callback_data="/back")]])
_CONTROL_MESH_BUTTONS = ButtonGrid(rows=[[Button(text="Claude 原生命令", callback_data="/cm")]])


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


def _command_menu_label(mode: str) -> str:
    """Return the user-facing command-menu label."""
    return _COMMAND_MENU_LABELS.get(mode, mode)


async def _resolve_command_mode_model(
    orch: Orchestrator,
    key: SessionKey,
    provider: str,
) -> str | None:
    """Resolve the model to pin for a provider-native command menu."""
    active = await orch._sessions.get_active(key)
    if active is not None and active.provider == provider and active.model.strip():
        return active.model

    configured_model, configured_provider = orch.resolve_runtime_target(orch._config.model)
    if configured_provider == provider and configured_model.strip():
        return configured_model

    default_model = orch._providers.default_model_for_provider(provider).strip()
    return default_model or None


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


async def _switch_to_claude_native_registry(
    orch: Orchestrator,
    key: SessionKey,
) -> OrchestratorResult:
    active = await orch._sessions.get_active(key)
    if active is not None and active.provider == "claude":
        model = active.model
    else:
        model, provider = orch.resolve_runtime_target(orch._config.model)
        if provider != "claude":
            model = await _resolve_command_mode_model(orch, key, "claude") or ""

    if not model:
        return OrchestratorResult(
            text="Claude 原生命令不可用：当前没有可用的 Claude provider/model。"
        )

    session, _is_new = await orch._sessions.resolve_session(
        key,
        provider="claude",
        model=model,
        preserve_existing_target=True,
    )
    await orch._sessions.sync_command_mode(session, mode="claude", model=model)
    return OrchestratorResult(text=_CLAUDE_NATIVE_REGISTRY, buttons=_CLAUDE_NATIVE_BUTTONS)


async def cmd_controlmesh(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /cm as the Claude native registry or /cm <command> as a CM escape hatch."""
    parts = text.strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        return await _switch_to_claude_native_registry(orch, key)
    nested = parts[1].strip()
    if not nested.startswith("/"):
        nested = f"/{nested}"
    return await orch.dispatch_controlmesh_command(key, nested)


async def cmd_back(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Return from provider-native slash command mode to the ControlMesh registry."""
    session = await orch._sessions.get_active(key)
    if session is not None:
        await orch._sessions.sync_command_mode(session, mode=_CONTROL_MODE, model=None)
    return OrchestratorResult(text=_CONTROL_MESH_REGISTRY, buttons=_CONTROL_MESH_BUTTONS)


_MEMORY_USAGE = "Usage: /memory [today|search <query>|semantic <query>|why <id>|review [--scope local|shared]|patterns|deprecate <id>|dispute <id>|supersede <old-id> <new-id>|promote [apply]]"


async def cmd_memory(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /memory [today|search <query>|semantic <query>|why <id>|review [--scope local|shared]|patterns]."""
    from datetime import UTC, datetime

    logger.info("Memory requested")
    parts = _text.strip().split(None, 3)

    # /memory with no subcommand - show full authority + legacy
    if len(parts) == 1:
        return await _cmd_memory_full(orch)

    subcommand = parts[1].lower()

    if subcommand == "today":
        today = datetime.now(UTC).date()
        return await _cmd_memory_today(orch, today)

    if subcommand == "review":
        scope = None
        if len(parts) >= 3 and parts[2].lower() == "--scope":
            if len(parts) < 4 or parts[3].lower() not in ("local", "shared"):
                return OrchestratorResult(text="Usage: /memory review [--scope local|shared]")
            from controlmesh.memory.models import MemoryScope
            scope = MemoryScope(parts[3].lower())
        return await _cmd_memory_review(orch, scope=scope)

    _handlers = {
        "search": lambda: _cmd_memory_search(orch, parts),
        "semantic": lambda: _cmd_memory_semantic(orch, parts),
        "why": lambda: _cmd_memory_why(orch, parts),
        "patterns": lambda: _cmd_memory_patterns(orch),
        "promote": lambda: _cmd_memory_promote(orch, parts),
        "deprecate": lambda: _cmd_memory_deprecate(orch, parts),
        "dispute": lambda: _cmd_memory_dispute(orch, parts),
        "supersede": lambda: _cmd_memory_supersede(orch, parts),
    }
    handler = _handlers.get(subcommand)
    if handler is not None:
        return await handler()
    return OrchestratorResult(text=_MEMORY_USAGE)


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
        scope_str = f" [{hit.scope.value}]" if hit.scope else ""
        lines.append(f"**[{hit.kind.value}]{scope_str}** {hit.source_path}")
        lines.append(f"_{hit.snippet}_")
        lines.append("")
    return OrchestratorResult(text="\n".join(lines))


async def _cmd_memory_semantic(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory semantic <query>."""
    if len(parts) < 3:
        return OrchestratorResult(text="Usage: /memory semantic <query>")
    query = parts[2]
    result = await asyncio.to_thread(search_semantic_index, orch.paths, query)
    if not result.hits:
        lines = [
            "## Semantic Search",
            f"__{result.query}__",
            "",
            "(no similar entries found — semantic index may be empty or query is too short)",
        ]
        return OrchestratorResult(text="\n".join(lines))

    lines = [
        f"## Semantic Search: {result.query}",
        f"_(non-authoritative trigram similarity; {len(result.hits)} of {result.total_indexed} entries shown)_",
        "",
    ]
    for hit in result.hits:
        ref = hit.source_path
        if hit.section:
            ref += f" > {hit.section}"
        if hit.line_number:
            ref += f" (line {hit.line_number})"
        extra = f" [id:{hit.authority_entry_id}]" if hit.authority_entry_id else ""
        scope_str = f"[{hit.scope.value}]" if hit.scope else ""
        lines.append(f"**[{hit.kind.value}]{scope_str}** {ref}  _similarity={hit.similarity:.2f}{extra}_")
        lines.append(f"- {hit.content}")
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


async def _cmd_memory_review(orch: Orchestrator, scope: MemoryScope | None = None) -> OrchestratorResult:
    """Handle /memory review [--scope local|shared]."""
    review = await asyncio.to_thread(render_memory_review, orch.paths, scope=scope)
    if not review:
        return OrchestratorResult(text="No memory to review.")
    return OrchestratorResult(text=review)


async def _cmd_memory_patterns(orch: Orchestrator) -> OrchestratorResult:
    """Handle /memory patterns."""
    result = await asyncio.to_thread(find_repeated_patterns, orch.paths)
    summary = render_patterns_summary(result)
    return OrchestratorResult(text=summary)


async def _cmd_memory_promote(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory promote [apply]."""
    if len(parts) >= 3 and parts[2].lower() == "apply":
        return await _cmd_memory_promote_apply(orch)
    return await _cmd_memory_promote_preview(orch)


def _format_memory_scope_badge(scope: MemoryScope) -> str:
    """Render an explicit local/shared scope badge for command surfaces."""
    return f"[{scope.value}]"


async def _cmd_memory_promote_preview(orch: Orchestrator) -> OrchestratorResult:
    """Handle /memory promote (preview only)."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    preview = await asyncio.to_thread(preview_daily_note_promotions, orch.paths, today)

    lines = [f"## Promotion Preview ({today.isoformat()})"]
    if not preview.selected:
        lines.append("_No new candidates to promote._")
        if preview.skipped_existing:
            lines.append(f"_(already promoted: {preview.skipped_existing})_")
        if preview.skipped_low_score:
            lines.append(f"_(low score filtered: {preview.skipped_low_score})_")
        return OrchestratorResult(text="\n".join(lines))

    lines.append(f"__{len(preview.selected)} candidates ready to promote__")
    for cand in preview.selected:
        score_str = f" (score={cand.score})" if cand.score < 1.0 else ""
        scope_str = _format_memory_scope_badge(cand.scope)
        lines.append(f"- [{cand.category.value}] {scope_str}{score_str} {cand.content}")

    if preview.skipped_existing:
        lines.append(f"\n_skipped (already promoted): {preview.skipped_existing}_")
    if preview.skipped_low_score:
        lines.append(f"_skipped (low score): {preview.skipped_low_score}_")

    lines.append("\n_Run `/memory promote apply` to promote these entries._")
    return OrchestratorResult(text="\n".join(lines))


async def _cmd_memory_promote_apply(orch: Orchestrator) -> OrchestratorResult:
    """Handle /memory promote apply."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    result = await asyncio.to_thread(apply_daily_note_promotions, orch.paths, today)

    if result.applied_count == 0:
        lines = [f"## Promotion Apply ({today.isoformat()})"]
        lines.append("_No new candidates to promote._")
        if result.skipped_existing:
            lines.append(f"_(already promoted: {result.skipped_existing})_")
        if result.skipped_low_score:
            lines.append(f"_(low score filtered: {result.skipped_low_score})_")
        return OrchestratorResult(text="\n".join(lines))

    lines = [f"## Promotion Apply ({today.isoformat()})"]
    lines.append(f"__{result.applied_count} entry(s) promoted to authority memory.__")
    for entry in result.applied_entries:
        scope_str = _format_memory_scope_badge(entry.scope)
        lines.append(f"- _(id: {entry.key[:12]}, {scope_str})_")
    if result.skipped_existing:
        lines.append(f"\n_skipped (already promoted): {result.skipped_existing}_")
    if result.skipped_low_score:
        lines.append(f"_skipped (low score): {result.skipped_low_score}_")
    return OrchestratorResult(text="\n".join(lines))


def _build_authority_scope_summary(authority_text: str) -> str:
    """Build a scope summary annotation for authority memory entries.

    Returns a string like "(N local, M shared)" when entries with explicit scope exist,
    or an empty string if there are no entries or all are legacy (no explicit scope).
    """
    local_count = 0
    shared_count = 0
    has_entries = False

    for line in authority_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parsed = parse_authority_entry(stripped)
        if parsed is not None:
            has_entries = True
            _content, meta = parsed
            if meta.scope.value == "shared":
                shared_count += 1
            else:
                local_count += 1

    if not has_entries:
        return ""
    if shared_count > 0:
        return f"_({local_count} local, {shared_count} shared)_"
    return f"_({local_count} local)_"


async def _cmd_memory_full(orch: Orchestrator) -> OrchestratorResult:
    """Render the full /memory output (authority + legacy)."""
    legacy = await asyncio.to_thread(read_mainmemory, orch.paths)
    authority = await asyncio.to_thread(read_file, orch.paths.authority_memory_path) or ""
    sections: list[str] = []
    if authority.strip():
        scope_summary = _build_authority_scope_summary(authority)
        if scope_summary:
            sections.extend([f"## Authority Memory (v2) {scope_summary}", authority.strip()])
        else:
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


async def _cmd_memory_deprecate(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory deprecate <entry-id>."""
    if len(parts) < 3:
        return OrchestratorResult(text="Usage: /memory deprecate <entry-id>")
    entry_id = parts[2]
    updated, scope = await asyncio.to_thread(deprecate_authority_entry, orch.paths, entry_id)
    if not updated:
        return OrchestratorResult(text=f"No authority entry found with id: {entry_id}")
    scope_str = f" [{scope.value}]" if scope else ""
    return OrchestratorResult(
        text=f"Entry `{entry_id}`{scope_str} marked as deprecated.\n\n_Entry content is preserved; lifecycle status is now deprecated._"
    )


async def _cmd_memory_dispute(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory dispute <entry-id>."""
    if len(parts) < 3:
        return OrchestratorResult(text="Usage: /memory dispute <entry-id>")
    entry_id = parts[2]
    updated, scope = await asyncio.to_thread(dispute_authority_entry, orch.paths, entry_id)
    if not updated:
        return OrchestratorResult(text=f"No authority entry found with id: {entry_id}")
    scope_str = f" [{scope.value}]" if scope else ""
    return OrchestratorResult(
        text=f"Entry `{entry_id}`{scope_str} marked as disputed.\n\n_Entry content is preserved; lifecycle status is now disputed._"
    )


async def _cmd_memory_supersede(orch: Orchestrator, parts: list[str]) -> OrchestratorResult:
    """Handle /memory supersede <old-entry-id> <new-entry-id>."""
    if len(parts) < 4:
        return OrchestratorResult(text="Usage: /memory supersede <old-entry-id> <new-entry-id>")
    old_entry_id = parts[2]
    new_entry_id = parts[3]
    updated, scope = await asyncio.to_thread(
        supersede_authority_entry, orch.paths, old_entry_id, new_entry_id
    )
    if not updated:
        return OrchestratorResult(text=f"No authority entry found with id: {old_entry_id}")
    scope_str = f" [{scope.value}]" if scope else ""
    return OrchestratorResult(
        text=f"Entry `{old_entry_id}`{scope_str} marked as superseded by `{new_entry_id}`.\n\n"
        f"_Entry content is preserved; lifecycle status is now superseded._"
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
            f"Current menu: {_command_menu_label(session.command_mode)}\n"
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
