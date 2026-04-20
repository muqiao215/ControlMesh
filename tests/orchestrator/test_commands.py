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
    cmd_cron,
    cmd_diagnose,
    cmd_history,
    cmd_memory,
    cmd_mode,
    cmd_model,
    cmd_settings,
    cmd_status,
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


# -- cmd_memory --


async def test_memory_shows_content(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("# My Memories\n- Learned X")
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "My Memories" in result.text


async def test_memory_empty(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("")
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "empty" in result.text.lower()


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
