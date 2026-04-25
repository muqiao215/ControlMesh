"""Tests for command handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from controlmesh.cli.auth import AuthResult, AuthStatus
from controlmesh.history import TranscriptAttachment, TranscriptTurn
from controlmesh.infra.version import VersionInfo
from controlmesh.orchestrator.commands import (
    HistoryRequestKind,
    cmd_claude_native,
    cmd_controlmesh,
    cmd_cron,
    cmd_diagnose,
    cmd_history,
    cmd_memory,
    cmd_mode,
    cmd_model,
    cmd_settings,
    cmd_status,
    cmd_tasks,
    parse_history_request,
)
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.runtime import RuntimeEvent
from controlmesh.session.key import SessionKey
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.models import TeamLeader, TeamManifest, TeamSessionRef, TeamTask
from controlmesh.team.state import TeamStateStore

# -- cmd_model (wizard + direct switch) --

_AUTHED = {
    "claude": AuthResult("claude", AuthStatus.AUTHENTICATED),
    "codex": AuthResult("codex", AuthStatus.AUTHENTICATED),
}


async def test_model_list_returns_keyboard(orch: Orchestrator) -> None:
    with patch(
        "controlmesh.orchestrator.selectors.model_selector.check_all_auth", return_value=_AUTHED
    ):
        result = await cmd_model(orch, SessionKey(chat_id=1), "/model")
    assert result.buttons is not None
    assert "Model Selector" in result.text


async def test_model_direct_switch(orch: Orchestrator) -> None:
    kill_mock = AsyncMock(return_value=0)
    object.__setattr__(orch._process_registry, "kill_all", kill_mock)
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model sonnet")
    assert "opus" in result.text
    assert "sonnet" in result.text
    assert orch._config.model == "sonnet"
    kill_mock.assert_called_once_with(1)


async def test_model_already_set(orch: Orchestrator) -> None:
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model opus")
    assert "Already running" in result.text


async def test_model_provider_change(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model o3")
    assert "Provider:" in result.text


async def test_model_switch_persists_to_config(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    await cmd_model(orch, SessionKey(chat_id=1), "/model sonnet")
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["model"] == "sonnet"
    assert saved["provider"] == "claude"


async def test_model_provider_change_persists_to_config(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    await cmd_model(orch, SessionKey(chat_id=1), "/model o3")
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["model"] == "o3"
    assert saved["provider"] == "codex"


async def test_model_same_provider_does_not_show_reset(orch: Orchestrator) -> None:
    kill_mock = AsyncMock(return_value=0)
    object.__setattr__(orch._process_registry, "kill_all", kill_mock)
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model sonnet")
    assert "Session reset" not in result.text
    assert "Provider:" not in result.text
    kill_mock.assert_called_once_with(1)


# -- cmd_status --


async def test_status_no_session(orch: Orchestrator) -> None:
    with patch("controlmesh.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")
    assert "No active session" in result.text
    assert "opus" in result.text


async def test_status_with_session(orch: Orchestrator) -> None:
    await orch._sessions.resolve_session(SessionKey(chat_id=1))
    with patch("controlmesh.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")
    assert "Session:" in result.text
    assert "Messages:" in result.text


async def test_status_prefers_session_model_over_config(orch: Orchestrator) -> None:
    await orch._sessions.resolve_session(
        SessionKey(chat_id=1), provider="codex", model="gpt-5.2-codex"
    )
    with patch("controlmesh.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")
    assert "Model: gpt-5.2-codex (configured: opus)" in result.text


async def test_mode_status_defaults_to_controlmesh(orch: Orchestrator) -> None:
    result = await cmd_mode(orch, SessionKey(chat_id=1), "/mode status")

    assert "Takeover mode: ControlMesh" in result.text


async def test_mode_without_args_returns_takeover_selector_buttons(orch: Orchestrator) -> None:
    result = await cmd_mode(orch, SessionKey(chat_id=1), "/mode")

    assert "Takeover mode: ControlMesh" in result.text
    assert result.buttons is not None
    rows = result.buttons.rows
    assert rows[0][0].callback_data == "/mode cm"
    assert rows[0][1].callback_data == "/mode claude"
    assert rows[0][2].callback_data == "/mode codex"
    assert rows[0][3].callback_data == "/mode gemini"


async def test_mode_without_args_appends_runtime_buttons_when_available(orch: Orchestrator) -> None:
    orch._providers._available_providers = frozenset({"claude", "codex", "gemini", "claw", "opencode"})

    result = await cmd_mode(orch, SessionKey(chat_id=1), "/mode")

    assert result.buttons is not None
    rows = result.buttons.rows
    assert rows[1][0].callback_data == "/mode claw-code"
    assert rows[1][1].callback_data == "/mode opencode"


async def test_mode_switch_sets_session_local_takeover_target(orch: Orchestrator) -> None:
    key = SessionKey(chat_id=1)

    with patch.object(orch._providers, "default_model_for_provider", return_value="gpt-5.2-codex"):
        result = await cmd_mode(orch, key, "/mode codex")

    assert "Takeover mode: Codex" in result.text
    assert "gpt-5.2-codex" in result.text

    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.provider == "claude"
    assert session.model == "opus"
    assert session.command_mode == "codex"
    assert session.command_mode_model == "gpt-5.2-codex"


async def test_mode_switch_supports_opencode_runtime_channel(orch: Orchestrator) -> None:
    key = SessionKey(chat_id=1)

    with patch.object(orch._providers, "default_model_for_provider", return_value="openai/gpt-4.1"):
        result = await cmd_mode(orch, key, "/mode opencode")

    assert "Takeover mode: OpenCode" in result.text
    assert "openai/gpt-4.1" in result.text

    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.command_mode == "opencode"
    assert session.command_mode_model == "openai/gpt-4.1"


async def test_mode_switch_supports_claw_code_runtime_channel(orch: Orchestrator) -> None:
    key = SessionKey(chat_id=1)

    with patch.object(orch._providers, "default_model_for_provider", return_value="sonnet"):
        result = await cmd_mode(orch, key, "/mode claw-code")

    assert "Takeover mode: Claw-Code" in result.text
    assert "sonnet" in result.text

    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.command_mode == "claw"
    assert session.command_mode_model == "sonnet"


async def test_claude_native_on_requires_claude_provider(orch: Orchestrator) -> None:
    await orch._sessions.resolve_session(
        SessionKey(chat_id=1), provider="codex", model="gpt-5.2-codex"
    )

    result = await cmd_claude_native(orch, SessionKey(chat_id=1), "/claude_native on")

    assert "only available when the active provider is Claude" in result.text


async def test_claude_native_on_off_updates_provider_local_mode(orch: Orchestrator) -> None:
    key = SessionKey(chat_id=1)

    enabled = await cmd_claude_native(orch, key, "/claude_native on")
    assert "Claude native command mode: on" in enabled.text

    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.provider == "claude"
    assert session.native_commands_enabled is True
    assert session.command_mode == "claude"
    assert session.command_mode_model == "opus"

    disabled = await cmd_claude_native(orch, key, "/claude_native off")
    assert "Claude native command mode: off" in disabled.text

    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.native_commands_enabled is False
    assert session.command_mode == "cm"
    assert session.command_mode_model is None


async def test_cm_without_nested_command_exits_takeover_mode(orch: Orchestrator) -> None:
    key = SessionKey(chat_id=1)
    session, _ = await orch._sessions.resolve_session(key, provider="claude", model="opus")
    await orch._sessions.sync_command_mode(session, mode="codex", model="gpt-5.2-codex")

    result = await cmd_controlmesh(orch, key, "/cm")

    assert "Takeover mode: ControlMesh" in result.text

    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.command_mode == "cm"
    assert session.command_mode_model is None


# -- cmd_settings --


async def test_settings_status_returns_keyboard(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings")

    assert result.buttons is not None
    assert "Advanced Settings" in result.text
    assert "Streaming output" in result.text
    assert "Tool event display" in result.text


async def test_settings_output_switch_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings output tools")

    assert "Streaming output updated" in result.text
    assert orch._config.streaming.output_mode == "tools"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["streaming"]["output_mode"] == "tools"


async def test_settings_tool_display_switch_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings tools details")

    assert "Tool event display updated" in result.text
    assert orch._config.streaming.tool_display == "details"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["streaming"]["tool_display"] == "details"


async def test_settings_feishu_runtime_switch_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings feishu runtime native")

    assert "Feishu runtime updated" in result.text
    assert orch._config.feishu.runtime_mode == "native"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["feishu"]["runtime_mode"] == "native"


async def test_settings_feishu_progress_switch_persists_to_config(orch: Orchestrator) -> None:
    orch._config.feishu.runtime_mode = "native"
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings feishu progress card_stream")

    assert "Feishu progress updated" in result.text
    assert orch._config.feishu.progress_mode == "card_stream"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["feishu"]["progress_mode"] == "card_stream"


async def test_settings_feishu_card_stream_requires_native_runtime(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings feishu progress card_stream")

    assert "requires `native` runtime mode" in result.text
    assert orch._config.feishu.progress_mode == "text"


async def test_settings_messaging_telegram_token_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(
        orch,
        SessionKey(chat_id=1),
        "/settings messaging telegram token 123456:ABCDEF_token",
    )

    assert "Telegram bot token saved" in result.text
    assert orch._config.telegram_token == "123456:ABCDEF_token"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["telegram_token"] == "123456:ABCDEF_token"


async def test_settings_messaging_feishu_app_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(
        orch,
        SessionKey(chat_id=1),
        "/settings messaging feishu app cli_app secret_value",
    )

    assert "Feishu app_id/app_secret saved" in result.text
    assert orch._config.feishu.app_id == "cli_app"
    assert orch._config.feishu.app_secret == "secret_value"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["feishu"]["app_id"] == "cli_app"
    assert saved["feishu"]["app_secret"] == "secret_value"


async def test_tasks_topology_status_reports_manual_default(orch: Orchestrator) -> None:
    result = await cmd_tasks(orch, SessionKey(chat_id=1), "/tasks topology status")

    assert "Background topology default: manual" in result.text
    assert "pipeline, fanout_merge, director_worker, debate_judge" in result.text
    assert "will not infer a topology automatically" in result.text


async def test_tasks_topology_update_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_tasks(orch, SessionKey(chat_id=1), "/tasks topology pipeline")

    assert "Background topology default updated: pipeline" in result.text
    assert orch._config.tasks.default_topology == "pipeline"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["tasks"]["default_topology"] == "pipeline"


async def test_tasks_topology_off_clears_default(orch: Orchestrator) -> None:
    orch._config.tasks.default_topology = "pipeline"
    result = await cmd_tasks(orch, SessionKey(chat_id=1), "/tasks topology off")

    assert "Background topology default updated: manual" in result.text
    assert orch._config.tasks.default_topology is None
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["tasks"]["default_topology"] is None


async def test_tasks_topology_update_accepts_director_worker(orch: Orchestrator) -> None:
    result = await cmd_tasks(orch, SessionKey(chat_id=1), "/tasks topology director_worker")

    assert "Background topology default updated: director_worker" in result.text
    assert orch._config.tasks.default_topology == "director_worker"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["tasks"]["default_topology"] == "director_worker"


async def test_tasks_topology_update_accepts_debate_judge(orch: Orchestrator) -> None:
    result = await cmd_tasks(orch, SessionKey(chat_id=1), "/tasks topology debate_judge")

    assert "Background topology default updated: debate_judge" in result.text
    assert orch._config.tasks.default_topology == "debate_judge"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["tasks"]["default_topology"] == "debate_judge"


async def test_tasks_topology_rejects_unknown_topology(orch: Orchestrator) -> None:
    result = await cmd_tasks(orch, SessionKey(chat_id=1), "/tasks topology swarm")

    assert "Usage: /tasks topology" in result.text
    assert "director_worker" in result.text
    assert "debate_judge" in result.text
    assert orch._config.tasks.default_topology is None


async def test_settings_version_refresh_shows_latest_release(orch: Orchestrator) -> None:
    info = VersionInfo(
        current="0.15.0",
        latest="0.16.0",
        update_available=True,
        summary="release",
        source="github",
    )
    with (
        patch("controlmesh.orchestrator.commands.detect_install_mode", return_value="pipx"),
        patch("controlmesh.orchestrator.commands.check_latest_version", new=AsyncMock(return_value=info)),
        patch("controlmesh.orchestrator.commands.get_current_version", return_value="0.15.0"),
    ):
        result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings version")

    assert "Version & upgrade" in result.text
    assert "0.16.0" in result.text
    assert "github" in result.text.lower()
    assert result.buttons is not None


async def test_settings_upgrade_delegates_to_upgrade_flow(orch: Orchestrator) -> None:
    info = VersionInfo(
        current="0.15.0",
        latest="0.16.0",
        update_available=True,
        summary="release",
        source="github",
    )
    with (
        patch("controlmesh.orchestrator.commands.detect_install_mode", return_value="pipx"),
        patch("controlmesh.orchestrator.commands.check_latest_version", new=AsyncMock(return_value=info)),
    ):
        result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings upgrade")

    assert "Update Available" in result.text
    assert result.buttons is not None


async def test_settings_rejects_unknown_values(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings output verbose")

    assert "Usage: /settings" in result.text


async def test_settings_language_en_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings language en")

    assert "Language updated" in result.text
    assert orch._config.language == "en"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["language"] == "en"


async def test_settings_language_zh_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings language zh")

    assert "Language updated" in result.text
    assert orch._config.language == "zh"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["language"] == "zh"


async def test_settings_language_lang_alias_persists_to_config(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings lang de")

    assert "Language updated" in result.text
    assert orch._config.language == "de"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["language"] == "de"


async def test_settings_language_without_value_shows_panel(orch: Orchestrator) -> None:
    result = await cmd_settings(orch, SessionKey(chat_id=1), "/settings language")

    assert "Advanced Settings" in result.text
    assert "Language" in result.text
    assert result.buttons is not None


async def test_settings_language_shows_in_usage_text() -> None:
    from controlmesh.orchestrator.selectors.settings_selector import settings_usage_text

    usage = settings_usage_text()
    assert "/settings language" in usage


# -- cmd_memory --


async def test_memory_shows_content(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("# My Memories\n- Learned X")
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "My Memories" in result.text


async def test_memory_shows_authority_memory_content(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("")
    orch.paths.authority_memory_path.write_text(
        "# ControlMesh Memory v2\n\n## Durable Memory\n\n### Decision\n- Keep memory local.\n",
        encoding="utf-8",
    )
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "Keep memory local." in result.text


async def test_memory_empty(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("")
    orch.paths.authority_memory_path.write_text("")
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "empty" in result.text.lower()


async def test_memory_today_shows_daily_note(orch: Orchestrator) -> None:
    """Test /memory today returns a compact summary of today's daily note."""
    from datetime import UTC, datetime

    from controlmesh.memory.store import ensure_daily_note

    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(orch.paths, today)
    note_path.write_text(
        f"# Daily Memory: {today.isoformat()}\n\n"
        "## Events\n\n- User asked about memory\n\n"
        "## Signals\n\n- User seems interested in review\n\n"
        "## Evidence\n\n## Open Candidates\n\n"
        "- [decision] Consider memory review workflow.\n",
        encoding="utf-8",
    )

    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory today")
    assert today.isoformat() in result.text
    assert "Events" in result.text
    assert "Open Candidates" in result.text
    assert "decision" in result.text


async def test_memory_today_no_note(orch: Orchestrator) -> None:
    """Test /memory today shows message when no daily note exists."""
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory today")
    assert "No daily note found" in result.text or "No daily note" in result.text


async def test_memory_search_returns_results(orch: Orchestrator) -> None:
    """Test /memory search delegates to FTS5 search and renders results."""
    from datetime import UTC, datetime

    from controlmesh.memory.store import ensure_daily_note

    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(orch.paths, today)
    note_path.write_text(
        f"# Daily Memory: {today.isoformat()}\n\n"
        "## Events\n\n- The user wants to find memory about Paris.\n\n"
        "## Open Candidates\n\n",
        encoding="utf-8",
    )

    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory search Paris")
    assert "Search" in result.text
    assert "Paris" in result.text


async def test_memory_search_no_results(orch: Orchestrator) -> None:
    """Test /memory search shows no results message."""
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory search xyzzy_nonexistent")
    assert "No results found" in result.text


async def test_memory_why_returns_provenance(orch: Orchestrator) -> None:
    """Test /memory why explains an authority entry's provenance."""
    # Write authority memory with a Phase-4 style entry containing metadata
    orch.paths.authority_memory_path.write_text(
        "# ControlMesh Memory v2\n\n"
        "## Durable Memory\n\n"
        "### Decision\n"
        "- Keep memory local. _(id: abc12345; status: active; source: memory/2026-04-25.md#L3; promoted: 2026-04-25)_\n",
        encoding="utf-8",
    )

    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory why abc12345")
    assert "Provenance" in result.text
    assert "Keep memory local" in result.text
    assert "active" in result.text
    assert "source:" in result.text or "memory/" in result.text
    assert "promoted:" in result.text or "2026-04-25" in result.text


async def test_memory_why_unknown_id(orch: Orchestrator) -> None:
    """Test /memory why shows not found for unknown entry id."""
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory why nonexistent_id")
    assert "No authority entry found" in result.text


async def test_memory_review_shows_summary(orch: Orchestrator) -> None:
    """Test /memory review shows a compact review surface."""
    from datetime import UTC, datetime

    from controlmesh.memory.store import ensure_daily_note

    # Create authority memory with entries
    orch.paths.authority_memory_path.write_text(
        "# ControlMesh Memory v2\n\n"
        "## Durable Memory\n\n"
        "### Decision\n"
        "- Keep memory local. _(id: d1; status: active; source: memory/2026-04-24.md#L2; promoted: 2026-04-24)_\n\n"
        "### Fact\n"
        "- Memory system uses markdown files. _(id: f1; status: active; source: memory/2026-04-23.md#L5; promoted: 2026-04-23)_\n",
        encoding="utf-8",
    )

    # Create daily note with open candidates
    today = datetime.now(UTC).date()
    note_path = ensure_daily_note(orch.paths, today)
    note_path.write_text(
        f"# Daily Memory: {today.isoformat()}\n\n"
        "## Open Candidates\n\n"
        "- [preference] User prefers short responses.\n"
        "- [fact] User works in engineering.\n",
        encoding="utf-8",
    )

    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory review")
    assert "Memory Review" in result.text
    assert "Decision" in result.text or "Fact" in result.text
    assert "Open Candidates" in result.text


# -- cmd_history --


async def test_history_shows_recent_visible_turns(orch: Orchestrator) -> None:
    key = SessionKey.telegram(1)
    orch._transcripts.append_turn(
        TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="user",
            visible_content="first question",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    orch._transcripts.append_turn(
        TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="first answer",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    orch._transcripts.append_turn(
        TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="user",
            visible_content="second question",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )

    result = await cmd_history(orch, key, "/history 2")

    assert "Recent Visible History" in result.text
    assert "1. [assistant] first answer" in result.text
    assert "2. [user] second question" in result.text
    assert "first question" not in result.text


async def test_history_rejects_invalid_limit(orch: Orchestrator) -> None:
    result = await cmd_history(orch, SessionKey.telegram(1), "/history nope")
    assert "Usage: /history [n]" in result.text


async def test_history_reports_empty_session(orch: Orchestrator) -> None:
    result = await cmd_history(orch, SessionKey.telegram(1), "/history")
    assert "No visible history yet." in result.text


async def test_history_shows_attachment_labels(orch: Orchestrator) -> None:
    key = SessionKey.telegram(1)
    orch._transcripts.append_turn(
        TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="Generated report",
            attachments=[
                TranscriptAttachment(
                    kind="document",
                    label="report.txt",
                    path="/tmp/report.txt",
                )
            ],
            source="foreground_task_result",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )

    result = await cmd_history(orch, key, "/history")

    assert "Generated report" in result.text
    assert "report.txt" in result.text


def test_history_parses_indexed_forms() -> None:
    assert parse_history_request("/history search outage").kind == HistoryRequestKind.SEARCH
    assert parse_history_request("/history task abc123").kind == HistoryRequestKind.TASK
    assert parse_history_request("/history session tg:42:root").kind == HistoryRequestKind.SESSION
    assert parse_history_request("/history 3").kind == HistoryRequestKind.TAIL


async def test_history_search_formats_bounded_separated_index_results(orch: Orchestrator) -> None:
    key = SessionKey.telegram(42)
    orch._transcripts.append_turn(
        TranscriptTurn(
            turn_id="turn-needle",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="needle visible answer",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    runtime_path = orch.paths.runtime_events_dir / key.transport / str(key.chat_id) / "root.jsonl"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        RuntimeEvent(
            event_id="runtime-needle",
            session_key=key.storage_key,
            event_type="worker.note",
            payload={"note": "needle runtime payload"},
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    registry = TaskRegistry(orch.paths.tasks_registry_path, orch.paths.tasks_dir)
    task = registry.create(
        TaskSubmit(
            chat_id=42,
            prompt="needle task prompt",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Needle Task",
        ),
        "codex",
        "gpt-5.2",
    )
    registry.update_status(task.task_id, "done", result_preview="needle task result")
    team_store = TeamStateStore(orch.paths.team_state_dir, "alpha-team")
    team_store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="needle team run",
            leader=TeamLeader(agent_name="main", session=TeamSessionRef(transport="tg", chat_id=7)),
        )
    )
    team_store.upsert_task(TeamTask(task_id="team-needle", subject="needle team task"))

    result = await cmd_history(orch, key, "/history search needle")

    assert "Indexed History Search" in result.text
    assert "Frontstage Transcript" in result.text
    assert "Runtime Events" in result.text
    assert "Task Catalog" in result.text
    assert "Team State" in result.text
    assert "needle visible answer" in result.text
    assert "worker.note" in result.text
    assert "Needle Task" in result.text
    assert "team-needle" in result.text


async def test_history_search_bounds_results(orch: Orchestrator) -> None:
    key = SessionKey.telegram(43)
    for idx in range(8):
        orch._transcripts.append_turn(
            TranscriptTurn(
                turn_id=f"turn-{idx}",
                session_key=key.storage_key,
                surface_session_id=key.storage_key,
                role="assistant",
                visible_content=f"needle visible answer {idx}",
                source="normal_chat",
                transport=key.transport,
                chat_id=key.chat_id,
                topic_id=key.topic_id,
            )
        )

    result = await cmd_history(orch, key, "/history search needle")

    assert "showing 5 of 8" in result.text
    assert "needle visible answer 0" in result.text
    assert "needle visible answer 4" in result.text
    assert "needle visible answer 5" not in result.text


async def test_history_task_formats_task_and_team_sections(orch: Orchestrator) -> None:
    registry = TaskRegistry(orch.paths.tasks_registry_path, orch.paths.tasks_dir)
    entry = registry.create(
        TaskSubmit(
            chat_id=42,
            prompt="investigate task",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Indexed Task",
        ),
        "codex",
        "gpt-5.2",
    )
    registry.update_status(entry.task_id, "done", result_preview="task result")
    team_store = TeamStateStore(orch.paths.team_state_dir, "alpha-team")
    team_store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate implementation",
            leader=TeamLeader(agent_name="main", session=TeamSessionRef(transport="tg", chat_id=7)),
        )
    )
    team_store.upsert_task(TeamTask(task_id=entry.task_id, subject="Team copy", owner="worker-1"))

    result = await cmd_history(orch, SessionKey.telegram(42), f"/history task {entry.task_id}")

    assert "Indexed Task History" in result.text
    assert "Task Catalog" in result.text
    assert "Team State" in result.text
    assert "Frontstage Transcript" in result.text
    assert entry.task_id in result.text
    assert "Indexed Task" in result.text
    assert "Team copy" in result.text


async def test_history_session_formats_transcript_and_runtime_sections(orch: Orchestrator) -> None:
    key = SessionKey.telegram(44, 9)
    orch._transcripts.append_turn(
        TranscriptTurn(
            turn_id="session-turn",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="user",
            visible_content="session visible question",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    runtime_path = orch.paths.runtime_events_dir / key.transport / str(key.chat_id) / "9.jsonl"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        RuntimeEvent(
            event_id="session-runtime",
            session_key=key.storage_key,
            event_type="worker.started",
            payload={"task": "session runtime"},
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    result = await cmd_history(orch, key, f"/history session {key.storage_key}")

    assert "Indexed Session History" in result.text
    assert "Frontstage Transcript" in result.text
    assert "Runtime Events" in result.text
    assert "Task Catalog" in result.text
    assert "Team State" in result.text
    assert "session visible question" in result.text
    assert "worker.started" in result.text


# -- cmd_cron --


async def test_cron_no_jobs(orch: Orchestrator) -> None:
    result = await cmd_cron(orch, SessionKey(chat_id=0), "/cron")
    assert "No cron jobs" in result.text


async def test_cron_lists_jobs(orch: Orchestrator) -> None:
    from controlmesh.cron.manager import CronJob

    orch._cron_manager.add_job(
        CronJob(
            id="test-job",
            title="Test Job",
            description="A test job",
            schedule="0 9 * * *",
            agent_instruction="do stuff",
            task_folder="test-task",
        ),
    )
    result = await cmd_cron(orch, SessionKey(chat_id=0), "/cron")
    assert result.buttons is not None
    assert "0 9 * * *" in result.text
    assert "Test Job" in result.text
    assert "active" in result.text


# -- cmd_diagnose --


async def test_diagnose_no_logs(orch: Orchestrator) -> None:
    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")
    assert "Diagnostics" in result.text
    assert "No log file" in result.text


async def test_diagnose_with_logs(orch: Orchestrator) -> None:
    log_path = orch.paths.logs_dir / "agent.log"
    log_path.write_text("2024-01-01 INFO Started\n2024-01-01 ERROR Something broke\n")
    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")
    assert "Something broke" in result.text


async def test_diagnose_shows_cache_status(orch: Orchestrator) -> None:
    """Should display Codex cache status in /diagnose output."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from controlmesh.cli.codex_cache import CodexModelCache
    from controlmesh.cli.codex_discovery import CodexModelInfo

    # Create mock cache with test data
    mock_cache = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="gpt-4o",
                display_name="GPT-4o",
                description="Test model",
                supported_efforts=("low", "medium", "high"),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )

    # Mock the cache observer
    mock_observer = MagicMock()
    mock_observer.get_cache = MagicMock(return_value=mock_cache)
    orch._observers.codex_cache_obs = mock_observer

    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")

    # Verify cache info is in output
    assert "Codex Model Cache" in result.text
    assert "Models cached: 1" in result.text
    assert "Default model: gpt-4o" in result.text


async def test_diagnose_shows_effective_runtime_target(orch: Orchestrator) -> None:
    orch._providers._available_providers = frozenset({"codex"})

    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")

    assert "Configured: claude / opus" in result.text
    assert "Effective runtime: claude / opus" in result.text


# -- cmd_model (unknown model) --


async def test_model_unknown_name(orch: Orchestrator) -> None:
    """Unknown model names are treated as codex models and the switch succeeds."""
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model totally_fake_model")
    assert "Model switched" in result.text
    assert "totally_fake_model" in result.text
    assert orch._config.model == "totally_fake_model"
    assert orch._config.provider == "codex"
