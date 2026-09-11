"""Tests for cron/execution.py: CLI command building and output parsing."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from controlmesh.cli.param_resolver import TaskExecutionConfig
from controlmesh.cron.execution import (
    OneShotCommand,
    UnsupportedOneShotProviderError,
    observe_one_shot,
    build_cmd,
    enrich_instruction,
    execute_one_shot,
    indent,
    parse_claude_result,
    parse_codex_result,
    parse_gemini_result,
    parse_result,
)


class TestBuildCmd:
    def test_claude_provider_non_root(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="claude",
            model="opus",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            file_access="all",
        )
        with (
            patch("controlmesh.cron.execution.which", return_value="/usr/bin/claude"),
            patch("controlmesh.cron.execution.os.geteuid", return_value=1000),
        ):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert result.cmd[0] == "/usr/bin/claude"
        assert "--no-session-persistence" in result.cmd
        # Claude: prompt as CLI arg, no stdin
        assert result.stdin_input is None
        assert result.cmd[-1] == "hello"
        assert result.cmd[-2] == "--"
        assert "--dangerously-skip-permissions" not in result.cmd
        assert result.env_overrides == {}

    def test_claude_provider_root_force_bypass(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="claude",
            model="opus",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            file_access="all",
            claude_root_force_bypass_via_is_sandbox=True,
        )
        with (
            patch("controlmesh.cron.execution.which", return_value="/usr/bin/claude"),
            patch("controlmesh.cron.execution.os.geteuid", return_value=0),
        ):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert "--dangerously-skip-permissions" in result.cmd
        assert result.env_overrides == {"IS_SANDBOX": "1"}
        idx = result.cmd.index("--permission-mode")
        assert result.cmd[idx + 1] == "bypassPermissions"

    def test_claude_provider_root_defaults_to_force_bypass(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="claude",
            model="opus",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            file_access="all",
        )
        with (
            patch("controlmesh.cron.execution.which", return_value="/usr/bin/claude"),
            patch("controlmesh.cron.execution.os.geteuid", return_value=0),
        ):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert "--dangerously-skip-permissions" in result.cmd
        assert result.env_overrides == {"IS_SANDBOX": "1"}
        idx = result.cmd.index("--permission-mode")
        assert result.cmd[idx + 1] == "bypassPermissions"

    def test_claude_provider_root_falls_back_without_force_bypass(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="claude",
            model="opus",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            file_access="all",
            claude_root_permission_mode="dontAsk",
            claude_root_force_bypass_via_is_sandbox=False,
        )
        with (
            patch("controlmesh.cron.execution.which", return_value="/usr/bin/claude"),
            patch("controlmesh.cron.execution.os.geteuid", return_value=0),
        ):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert "--dangerously-skip-permissions" not in result.cmd
        assert result.env_overrides == {}
        idx = result.cmd.index("--permission-mode")
        assert result.cmd[idx + 1] == "dontAsk"

    def test_codex_provider(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="codex",
            model="gpt-4",
            reasoning_effort="medium",
            cli_parameters=[],
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            file_access="all",
        )
        with patch("controlmesh.cron.execution.which", return_value="/usr/bin/codex"):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert result.cmd[0] == "/usr/bin/codex"
        assert "--dangerously-bypass-approvals-and-sandbox" in result.cmd
        # Codex: prompt as CLI arg, no stdin
        assert result.stdin_input is None

    def test_codex_full_auto(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="codex",
            model="gpt-4",
            reasoning_effort="medium",
            cli_parameters=[],
            permission_mode="plan",
            working_dir="/tmp",
            file_access="all",
        )
        with patch("controlmesh.cron.execution.which", return_value="/usr/bin/codex"):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert "--full-auto" in result.cmd

    def test_returns_none_when_cli_missing(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="claude",
            model="opus",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="plan",
            working_dir="/tmp",
            file_access="all",
        )
        with patch("controlmesh.cron.execution.which", return_value=None):
            assert build_cmd(exec_config, "hello") is None

    def test_gemini_provider(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="gemini",
            model="gemini-2.5-pro",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="bypassPermissions",
            working_dir="/tmp",
            file_access="all",
        )
        with patch("controlmesh.cron.execution.find_gemini_cli", return_value="/usr/bin/gemini"):
            result = build_cmd(exec_config, "hello")
        assert result is not None
        assert result.cmd[0] == "/usr/bin/gemini"
        assert "--approval-mode" in result.cmd
        assert "yolo" in result.cmd
        # Hybrid mode: -p "" instead of -- prompt
        assert "-p" in result.cmd
        p_idx = result.cmd.index("-p")
        assert result.cmd[p_idx + 1] == ""
        assert "--" not in result.cmd
        assert "hello" not in result.cmd
        # Prompt via stdin
        assert result.stdin_input == b"hello"

    def test_gemini_returns_none_when_cli_missing(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="gemini",
            model="gemini-2.5-pro",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="plan",
            working_dir="/tmp",
            file_access="all",
        )
        with patch(
            "controlmesh.cron.execution.find_gemini_cli",
            side_effect=FileNotFoundError("not found"),
        ):
            assert build_cmd(exec_config, "hello") is None

    def test_unknown_provider_is_rejected_without_fallback(self) -> None:
        exec_config = TaskExecutionConfig(
            provider="unknown",
            model="model",
            reasoning_effort="",
            cli_parameters=[],
            permission_mode="plan",
            working_dir="/tmp",
            file_access="all",
        )
        with patch("controlmesh.cron.execution.which") as lookup, pytest.raises(UnsupportedOneShotProviderError):
            build_cmd(exec_config, "hello")
        lookup.assert_not_called()


class TestExecuteOneShotStdin:
    """Test execute_one_shot stdin_input parameter."""

    async def test_with_stdin_input_uses_pipe(self) -> None:
        """stdin_input is forwarded to subprocess via PIPE."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b'{"result":"ok"}', b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await execute_one_shot(
                OneShotCommand(cmd=["/usr/bin/gemini", "-p", ""], stdin_input=b"hello"),
                cwd=Path("/tmp"),
                provider="gemini",
                timeout_seconds=60,
                timeout_label="Test",
            )

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["stdin"] == asyncio.subprocess.PIPE
        proc.communicate.assert_called_once_with(input=b"hello")
        assert result.status == "success"

    async def test_without_stdin_input_uses_devnull(self) -> None:
        """Without stdin_input, DEVNULL is used (backward compat)."""
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b'{"result":"ok"}', b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            await execute_one_shot(
                OneShotCommand(
                    cmd=["/usr/bin/claude", "-p", "--", "hello"],
                    env_overrides={"IS_SANDBOX": "1"},
                ),
                cwd=Path("/tmp"),
                provider="claude",
                timeout_seconds=60,
                timeout_label="Test",
            )

        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert call_kwargs["env"] is not None
        assert call_kwargs["env"]["IS_SANDBOX"] == "1"
        proc.communicate.assert_called_once_with(input=None)


class TestEnrichInstruction:
    def test_appends_memory_instructions(self) -> None:
        result = enrich_instruction("Do the work", "daily-report")
        assert "daily-report_MEMORY.md" in result
        assert "Do the work" in result

    def test_preserves_original(self) -> None:
        original = "Original instruction"
        result = enrich_instruction(original, "weekly")
        assert result.startswith(original)


class TestParseClaude:
    def test_parses_json(self) -> None:
        import json

        stdout = json.dumps({"result": "Hello world"}).encode()
        assert parse_claude_result(stdout) == "Hello world"

    def test_empty_bytes(self) -> None:
        assert parse_claude_result(b"") == ""

    def test_non_json_returns_raw(self) -> None:
        raw = b"Some raw text output"
        assert parse_claude_result(raw) == "Some raw text output"


class TestParseCodex:
    def test_empty_bytes(self) -> None:
        assert parse_codex_result(b"") == ""

    def test_parsed_jsonl_with_no_text_returns_empty(self) -> None:
        """Silent-success: valid JSONL events but no assistant text -> empty."""
        raw = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '{"type":"turn.started"}\n'
            '{"type":"item.started","item":{"type":"command_execution"}}\n'
            '{"type":"item.completed","item":{"type":"command_execution"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10}}\n'
        )
        assert parse_codex_result(raw.encode()) == ""

    def test_parsed_jsonl_with_text_returns_text(self) -> None:
        raw = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"Hello"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10}}\n'
        )
        assert parse_codex_result(raw.encode()) == "Hello"

    def test_non_jsonl_returns_raw(self) -> None:
        raw = b"Plain text output from codex"
        assert parse_codex_result(raw) == "Plain text output from codex"


class TestParseGemini:
    def test_empty_bytes(self) -> None:
        assert parse_gemini_result(b"") == ""

    def test_json_response(self) -> None:
        import json

        data = json.dumps([{"type": "message", "role": "model", "content": "Result text"}])
        result = parse_gemini_result(data.encode())
        assert "Result text" in result

    def test_non_json_returns_raw(self) -> None:
        raw = b"Raw gemini output"
        assert parse_gemini_result(raw) == "Raw gemini output"


class TestParseResult:
    def test_dispatches_to_gemini_parser(self) -> None:
        assert parse_result("gemini", b'{"result":"ok"}') == "ok"

    def test_unknown_provider_cannot_use_another_parser(self) -> None:
        with pytest.raises(UnsupportedOneShotProviderError):
            parse_result("unknown", b'{"result":"fallback"}')


class TestIndent:
    def test_indents_lines(self) -> None:
        result = indent("a\nb\nc", "  ")
        assert result == "  a\n  b\n  c"

    def test_single_line(self) -> None:
        assert indent("hello", ">> ") == ">> hello"


class TestExecuteOneShotTimeoutKill:
    """The timeout path must reap the whole process group and never block the loop.

    Regression: provider CLIs (e.g. ``claude``) spawn worker subprocesses that
    inherit stdout/stderr.  Killing only the lead PID left those pipe holders
    alive, so the post-timeout ``communicate()`` blocked forever and froze the
    main asyncio loop (no Telegram poller, no cron, no model-cache refresh).
    """

    def test_starts_subprocess_in_own_session_on_posix(self) -> None:
        if sys.platform == "win32":
            pytest.skip("POSIX-only: start_new_session enables process-group kill")

        async def run() -> None:
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
                proc = AsyncMock()
                proc.communicate.return_value = (b'{"result":"ok"}', b"")
                proc.returncode = 0
                mock_exec.return_value = proc
                await execute_one_shot(
                    OneShotCommand(cmd=["/usr/bin/claude", "-p", "--", "hi"]),
                    cwd=Path("/tmp"),
                    provider="claude",
                    timeout_seconds=60,
                    timeout_label="Test",
                )
            assert mock_exec.call_args[1].get("start_new_session") is True

        asyncio.run(run())

    async def test_post_kill_drain_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A pipe held open by an orphaned grandchild must not block the loop."""
        monkeypatch.setattr("controlmesh.cron.execution._POST_KILL_DRAIN_SECONDS", 0.05)

        async def hang_forever(**_kwargs: object) -> tuple[bytes, bytes]:
            await asyncio.sleep(3600)
            return (b"", b"")

        proc = AsyncMock()
        proc.pid = 424242
        proc.returncode = None
        proc.communicate = hang_forever

        async def fake_create(*_args: object, **_kwargs: object) -> AsyncMock:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

        kill_calls: list[int] = []
        monkeypatch.setattr(
            "controlmesh.cron.execution.force_kill_process_tree",
            kill_calls.append,
        )
        monkeypatch.setattr("os.getpgid", lambda _pid: 424242)
        monkeypatch.setattr("os.killpg", lambda *_a, **_k: None)

        result = await execute_one_shot(
            OneShotCommand(cmd=["/usr/bin/claude", "-p", "--", "hi"]),
            cwd=Path("/tmp"),
            provider="claude",
            timeout_seconds=0.01,
            timeout_label="Test",
        )

        # The bounded drain returned instead of hanging on the dead pipe.
        assert result.timed_out is True
        assert result.status == "error:timeout"
        assert result.stdout == b""
        assert 424242 in kill_calls

    async def test_timeout_kills_process_group(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On timeout the whole session/group is signalled, not just the lead PID."""
        monkeypatch.setattr("controlmesh.cron.execution._POST_KILL_DRAIN_SECONDS", 0.05)

        async def hang_forever(**_kwargs: object) -> tuple[bytes, bytes]:
            await asyncio.sleep(3600)
            return (b"", b"")

        proc = AsyncMock()
        proc.pid = 777
        proc.returncode = None
        proc.communicate = hang_forever

        async def fake_create(*_args: object, **_kwargs: object) -> AsyncMock:
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)

        group_signalled: list[int] = []
        monkeypatch.setattr("controlmesh.cron.execution.force_kill_process_tree", lambda _pid: None)
        monkeypatch.setattr("os.getpgid", lambda pid: pid)
        monkeypatch.setattr(
            "os.killpg",
            lambda pgid, _sig: group_signalled.append(pgid),
        )

        await execute_one_shot(
            OneShotCommand(cmd=["/usr/bin/claude", "-p", "--", "hi"]),
            cwd=Path("/tmp"),
            provider="claude",
            timeout_seconds=0.01,
            timeout_label="Test",
        )

        assert 777 in group_signalled


class TestKillSubprocessGroupSafety:
    @pytest.mark.parametrize("pid", [None, True, -1, 0, 1, AsyncMock()])
    def test_invalid_pid_never_reaches_signal_api(self, pid: object) -> None:
        from controlmesh.cron.execution import _kill_subprocess_group

        proc = AsyncMock()
        proc.pid = pid
        with (
            patch("controlmesh.cron.execution.os.getpgid", create=True) as getpgid,
            patch("controlmesh.cron.execution.os.killpg", create=True) as killpg,
            patch("controlmesh.cron.execution.force_kill_process_tree") as tree,
        ):
            _kill_subprocess_group(proc)
        getpgid.assert_not_called()
        killpg.assert_not_called()
        tree.assert_not_called()

    def test_shared_group_is_not_signalled(self) -> None:
        from controlmesh.cron.execution import _kill_subprocess_group

        proc = AsyncMock()
        proc.pid = 424242
        with (
            patch("controlmesh.cron.execution._IS_WINDOWS", False),
            patch("controlmesh.cron.execution.os.getpgid", return_value=1, create=True),
            patch("controlmesh.cron.execution.os.killpg", create=True) as killpg,
            patch("controlmesh.cron.execution.force_kill_process_tree") as tree,
        ):
            _kill_subprocess_group(proc)
        killpg.assert_not_called()
        tree.assert_called_once_with(424242)


@pytest.mark.parametrize("provider", ["opencode", "claw"])
def test_explicit_provider_uses_its_own_binary_and_preserves_prompt(provider: str) -> None:
    config = TaskExecutionConfig(provider=provider, model="fixture/model", reasoning_effort="", cli_parameters=[], permission_mode="dontAsk", working_dir="/tmp", file_access="all")
    prompt = '中文 "quotes"\n$(literal)'
    with patch("controlmesh.cron.execution.which", return_value=f"/fixture/{provider}") as lookup:
        command = build_cmd(config, prompt)
    lookup.assert_called_once_with(provider)
    assert command is not None
    assert command.cmd[0] == f"/fixture/{provider}"
    if provider == "opencode":
        assert command.stdin_input == prompt.encode()
        assert prompt not in command.cmd
        assert "--format" in command.cmd
    else:
        assert command.cmd[-2:] == ["prompt", prompt]


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini", "opencode", "claw"])
def test_container_provider_does_not_require_a_host_binary(provider: str) -> None:
    config = TaskExecutionConfig(provider=provider, model="fixture/model", reasoning_effort="", cli_parameters=[], permission_mode="dontAsk", working_dir="/tmp", file_access="all", docker_container="configured")
    with patch("controlmesh.cron.execution.which") as lookup, patch("controlmesh.cron.execution.find_gemini_cli") as gemini:
        command = build_cmd(config, "fixture")
    assert command is not None
    assert command.cmd[0] == provider
    lookup.assert_not_called()
    gemini.assert_not_called()


def test_native_error_and_tool_data_cannot_become_a_successful_assistant_result() -> None:
    assert observe_one_shot("claude", b'{"result":"partial","is_error":true}', b"").error_code == "provider_error"
    assert observe_one_shot("gemini", b'{"type":"tool_result","content":"secret tool output"}', b"").text == ""
    assert observe_one_shot("opencode", b'{"type":"text","sessionID":"ses_Test","part":{"text":"partial"}}', b"").terminal is False
    assert observe_one_shot("codex", b'{"type":"turn.completed"}', b"").error_code == "empty_native_output"
    assert observe_one_shot("claude", b"null", b"").error_code == "invalid_native_output"
    assert observe_one_shot("claude", b'{"result":"insufficient_quota is quoted prose"}', b"").terminal is True


async def test_native_stderr_quota_kills_real_process_before_retry(tmp_path: Path) -> None:
    import time

    retry = tmp_path / "retried"
    line = 'timestamp=2026-09-11 level=ERROR message="stream error" error.error="insufficient_quota; resets at 2026-09-12 01:00:00+08:00" session.id=ses_Test'
    script = f"import sys,time,pathlib; print({line!r},file=sys.stderr,flush=True); time.sleep(30); pathlib.Path({str(retry)!r}).write_text('bad retry')"
    spawn = asyncio.create_subprocess_exec
    owned: list[asyncio.subprocess.Process] = []

    async def create_owned(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        proc = await spawn(*args, **kwargs)
        owned.append(proc)
        return proc

    def kill_owned(proc: asyncio.subprocess.Process) -> None:
        # Global fixtures disable group signals. This fixture has no descendants;
        # terminate only the exact child created above, retaining that protection.
        assert len(owned) == 1
        assert proc is owned[0]
        proc.kill()

    started = time.monotonic()
    try:
        with patch("asyncio.create_subprocess_exec", side_effect=create_owned), patch("controlmesh.cron.execution._kill_subprocess_group", side_effect=kill_owned):
            result = await execute_one_shot(OneShotCommand(cmd=[sys.executable, "-c", script], stdin_input=b"fixture"), cwd=tmp_path, provider="opencode", timeout_seconds=10, timeout_label="fixture")
    finally:
        for proc in owned:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
    assert result.status == "error:quota_exhausted"
    assert result.error_code == "quota_exhausted"
    assert result.quota_reset_at == "2026-09-12 01:00:00+08:00"
    assert time.monotonic() - started < 5
    assert not retry.exists()


async def test_opencode_native_events_and_exact_stdin_are_collected_from_a_real_process(tmp_path: Path) -> None:
    prompt = 'exact "quoted"\n中文 prompt'
    script = "import sys,json; print(json.dumps({'type':'text','sessionID':'ses_Test','part':{'text':sys.stdin.read()}})); print(json.dumps({'type':'step_finish','sessionID':'ses_Test','part':{'reason':'stop'}}))"
    result = await execute_one_shot(OneShotCommand(cmd=[sys.executable, "-c", script], stdin_input=prompt.encode()), cwd=tmp_path, provider="opencode", timeout_seconds=5, timeout_label="fixture")
    assert result.status == "success"
    assert result.session_id == "ses_Test"
    assert result.result_text == prompt


async def test_native_error_with_zero_exit_code_is_not_success(tmp_path: Path) -> None:
    script = "print('" + '{"result":"partial","is_error":true}' + "')"
    result = await execute_one_shot(OneShotCommand(cmd=[sys.executable, "-c", script]), cwd=tmp_path, provider="claude", timeout_seconds=5, timeout_label="fixture")
    assert result.returncode == 0
    assert result.status == "error:provider_error"
