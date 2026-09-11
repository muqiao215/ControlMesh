"""Cron job CLI command building and output parsing."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

from controlmesh.cli.codex_events import parse_codex_jsonl
from controlmesh.cli.gemini_events import parse_gemini_json
from controlmesh.cli.gemini_utils import find_gemini_cli
from controlmesh.cli.param_resolver import TaskExecutionConfig
from controlmesh.cron.policy import CronTaskPolicy
from controlmesh.infra.platform import CREATION_FLAGS as _CREATION_FLAGS
from controlmesh.infra.process_tree import force_kill_process_tree

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Hard ceiling for draining a killed subprocess's pipes. Provider CLIs such as
# ``claude`` spawn worker subprocesses that inherit stdout/stderr; if any of
# those survivors keep a pipe write-end open, ``communicate()`` would otherwise
# block the event loop forever. This bound guarantees the loop stays live.
_POST_KILL_DRAIN_SECONDS = 10.0


@dataclass(slots=True)
class OneShotCommand:
    """Command + optional stdin payload for one-shot execution."""

    cmd: list[str] = field(default_factory=list)
    stdin_input: bytes | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)


class UnsupportedOneShotProviderError(ValueError):
    """A registered runtime engine may still require a non-CLI execution owner."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"unsupported_oneshot_provider:{provider}")


def build_cmd(exec_config: TaskExecutionConfig, prompt: str) -> OneShotCommand | None:
    """Build a CLI command for one-shot cron execution."""
    builder = _CMD_BUILDERS.get(exec_config.provider)
    if builder is None:
        raise UnsupportedOneShotProviderError(exec_config.provider)
    from controlmesh.execution_grants import ToolGrantDenied, map_tool_grant

    grant = exec_config.tool_grant
    if grant and grant.confirmation_policy == "controller_required":
        raise ToolGrantDenied(exec_config.provider, "controller_approval_unavailable")
    mapping = map_tool_grant(
        exec_config.provider, grant,
        config_permission_mode=exec_config.permission_mode,
        config_sandbox_mode="workspace-write" if exec_config.provider == "codex" and exec_config.permission_mode != "bypassPermissions" else "",
        config_cli_parameters=exec_config.cli_parameters,
    )
    command = builder(exec_config, prompt)
    if command is not None and mapping.flags:
        offset = 2 if exec_config.provider in {"codex", "opencode"} else 1
        command.cmd[offset:offset] = mapping.flags
    return command


def enrich_instruction(
    instruction: str,
    task_folder: str,
    *,
    policy: CronTaskPolicy | None = None,
) -> str:
    """Append memory file instructions to the agent instruction."""
    policy = policy or CronTaskPolicy()
    memory_file = f"{task_folder}_MEMORY.md"
    policy_block = _render_policy_instruction(policy)
    return (
        f"{instruction}\n\n"
        f"IMPORTANT:\n"
        f"- Read the {memory_file} file (it contains important information!)\n"
        f"- When finished, update {memory_file} with DATE + TIME and what you have done.\n"
        f"{policy_block}\n"
        "- The final answer is delivered to Telegram automatically by controlmesh.\n"
        "- Return only the user-facing result text.\n"
        "- Do not include transport/debug/tool confirmations "
        '(for example: "Message sent successfully").'
    )


def _render_policy_instruction(policy: CronTaskPolicy) -> str:
    """Describe artifact/notify/publish boundaries inside the task prompt."""
    lines = [
        "- Cron delivery policy:",
        f"  - notify primary: {policy.delivery.primary}",
        f"  - notify format: {policy.delivery.format}",
        f"  - local artifact path: {policy.artifact.path}",
        f"  - artifact mode: {policy.artifact.mode}",
    ]
    if policy.publish.enabled:
        lines.extend(
            [
                "  - publish.enabled=true",
                f"  - publish target: {policy.publish.target}",
                f"  - publish mode: {policy.publish.mode}",
            ],
        )
        if policy.publish.require_review:
            lines.append("  - external publish still requires review before finalizing")
    else:
        lines.extend(
            [
                "  - publish.enabled=false",
                "  - Do not write to external publishing targets, docs, tables, wikis, or APIs.",
            ],
        )
    return "\n".join(lines)


def parse_claude_result(stdout: bytes) -> str:
    """Extract result text from Claude CLI JSON output."""
    if not stdout:
        return ""
    raw = stdout.decode(errors="replace").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        return str(data.get("result", ""))
    except json.JSONDecodeError:
        return raw[:2000]


def parse_gemini_result(stdout: bytes) -> str:
    """Extract result text from Gemini CLI JSON output."""
    if not stdout:
        return ""
    raw = stdout.decode(errors="replace").strip()
    if not raw:
        return ""
    return parse_gemini_json(raw) or raw[:2000]


def parse_codex_result(stdout: bytes) -> str:
    """Extract result text from Codex CLI JSONL output."""
    if not stdout:
        return ""
    raw = stdout.decode(errors="replace").strip()
    if not raw:
        return ""
    result_text, thread_id, usage = parse_codex_jsonl(raw)
    # If the JSONL was successfully parsed (thread_id or usage present),
    # an empty result genuinely means no output — don't leak raw events.
    if result_text:
        return result_text
    if thread_id is not None or usage is not None:
        return ""
    return raw[:2000]


def parse_result(provider: str, stdout: bytes) -> str:
    """Extract result text from provider-specific CLI output."""
    parser = _RESULT_PARSERS.get(provider)
    if parser is None:
        raise UnsupportedOneShotProviderError(provider)
    return parser(stdout)


def indent(text: str, prefix: str) -> str:
    """Indent every line of *text* with *prefix*."""
    return "\n".join(prefix + line for line in text.splitlines())


# -- Private builders --


def _build_claude_cmd(exec_config: TaskExecutionConfig, prompt: str) -> OneShotCommand | None:
    """Build a Claude CLI command for one-shot cron execution."""
    cli = "claude" if exec_config.docker_container else which("claude")
    if not cli:
        return None
    cmd = [
        cli,
        "-p",
        "--output-format",
        "json",
        "--model",
        exec_config.model,
        "--no-session-persistence",
    ]
    permission_mode = _claude_permission_mode(exec_config)
    env_overrides: dict[str, str] = {}
    if _should_force_claude_root_bypass(exec_config):
        cmd.append("--dangerously-skip-permissions")
        env_overrides["IS_SANDBOX"] = "1"
    cmd += ["--permission-mode", permission_mode]
    # Add extra CLI parameters
    cmd.extend(exec_config.cli_parameters)
    cmd += ["--", prompt]
    return OneShotCommand(cmd=cmd, env_overrides=env_overrides)


def _should_force_claude_root_bypass(exec_config: TaskExecutionConfig) -> bool:
    """Return whether Claude root bypass escape hatch should be enabled."""
    geteuid = getattr(os, "geteuid", None)
    return bool(
        exec_config.permission_mode == "bypassPermissions"
        and exec_config.claude_root_force_bypass_via_is_sandbox
        and callable(geteuid)
        and geteuid() == 0
    )


def _claude_permission_mode(exec_config: TaskExecutionConfig) -> str:
    """Return the effective Claude permission mode for one-shot cron runs."""
    mode = exec_config.permission_mode
    if _should_force_claude_root_bypass(exec_config):
        return mode
    geteuid = getattr(os, "geteuid", None)
    if mode == "bypassPermissions" and callable(geteuid) and geteuid() == 0:
        return exec_config.claude_root_permission_mode or "dontAsk"
    return mode


def _build_gemini_cmd(exec_config: TaskExecutionConfig, prompt: str) -> OneShotCommand | None:
    """Build a Gemini CLI command for one-shot cron execution.

    Uses hybrid mode: ``-p ""`` forces headless mode (bypassing the TTY check
    that causes exit-42 on Windows), while the actual prompt is fed via stdin.
    """
    try:
        cli = "gemini" if exec_config.docker_container else find_gemini_cli()
    except FileNotFoundError:
        return None
    cmd = [cli, "-p", "", "--output-format", "json", "--include-directories", "."]

    if exec_config.model:
        cmd += ["--model", exec_config.model]
    if exec_config.permission_mode == "bypassPermissions":
        cmd += ["--approval-mode", "yolo"]

    cmd.extend(exec_config.cli_parameters)
    return OneShotCommand(cmd=cmd, stdin_input=prompt.encode())


def _build_codex_cmd(exec_config: TaskExecutionConfig, prompt: str) -> OneShotCommand | None:
    """Build a Codex CLI command for one-shot cron execution."""
    cli = "codex" if exec_config.docker_container else which("codex")
    if not cli:
        return None
    cmd = [cli, "exec", "--json", "--color", "never", "--skip-git-repo-check"]

    # Sandbox flags based on permission_mode
    if exec_config.permission_mode == "bypassPermissions":
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd.append("--full-auto")

    cmd += ["--model", exec_config.model]

    # Add reasoning effort (if not default)
    if exec_config.reasoning_effort and exec_config.reasoning_effort != "medium":
        cmd += ["-c", f"model_reasoning_effort={exec_config.reasoning_effort}"]

    # Add extra CLI parameters
    cmd.extend(exec_config.cli_parameters)

    cmd += ["--", prompt]
    return OneShotCommand(cmd=cmd)


def _build_opencode_cmd(exec_config: TaskExecutionConfig, prompt: str) -> OneShotCommand | None:
    cli = "opencode" if exec_config.docker_container else which("opencode")
    if not cli:
        return None
    cmd = [cli, "run", "--format", "json"]
    if exec_config.model:
        cmd += ["--model", exec_config.model]
    if exec_config.permission_mode == "bypassPermissions":
        cmd.append("--auto")
    cmd += [*exec_config.cli_parameters, "--print-logs", "--log-level", "ERROR"]
    # Native run re-quotes positional arguments. Stdin preserves the exact task prompt.
    return OneShotCommand(cmd=cmd, stdin_input=prompt.encode())


def _build_claw_cmd(exec_config: TaskExecutionConfig, prompt: str) -> OneShotCommand | None:
    cli = "claw" if exec_config.docker_container else which("claw")
    if not cli:
        return None
    mode = exec_config.permission_mode
    mode = "danger-full-access" if mode == "bypassPermissions" else mode
    if mode not in {"read-only", "workspace-write", "danger-full-access"}:
        mode = "workspace-write"
    cmd = [cli, "--output-format", "json"]
    if exec_config.model:
        cmd += ["--model", exec_config.model]
    cmd += ["--permission-mode", mode, *exec_config.cli_parameters, "prompt", prompt]
    return OneShotCommand(cmd=cmd)


def parse_opencode_result(stdout: bytes) -> str:
    """Only native text events are assistant output; tool data is never a result."""
    parts: list[str] = []
    for line in stdout.decode(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "text":
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "".join(parts)


def parse_claw_result(stdout: bytes) -> str:
    from controlmesh.cli.claw_provider import ClawCLI

    return ClawCLI._parse_output(stdout, b"", 0).result


_CmdBuilder = Callable[[TaskExecutionConfig, str], OneShotCommand | None]
_ResultParser = Callable[[bytes], str]

_CMD_BUILDERS: dict[str, _CmdBuilder] = {
    "claude": _build_claude_cmd,
    "gemini": _build_gemini_cmd,
    "codex": _build_codex_cmd,
    "opencode": _build_opencode_cmd,
    "claw": _build_claw_cmd,
}

_RESULT_PARSERS: dict[str, _ResultParser] = {
    "claude": parse_claude_result,
    "gemini": parse_gemini_result,
    "codex": parse_codex_result,
    "opencode": parse_opencode_result,
    "claw": parse_claw_result,
}


@dataclass(slots=True)
class OneShotExecutionResult:
    """Normalized outcome for a one-shot provider subprocess run."""

    status: str
    result_text: str
    stdout: bytes
    stderr: bytes
    returncode: int | None
    timed_out: bool
    error_code: str | None = None
    quota_reset_at: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class OneShotObservation:
    text: str
    terminal: bool
    error_code: str | None
    session_id: str | None = None
    quota_reset_at: str | None = None


def observe_one_shot(provider: str, stdout: bytes, stderr: bytes) -> OneShotObservation:
    """Classify native output independently of process exit; tool/assistant prose is not error evidence."""
    if provider not in _RESULT_PARSERS:
        raise UnsupportedOneShotProviderError(provider)
    from controlmesh.cli.opencode_quota import quota_from_stderr, quota_response

    raw = stdout.decode(errors="replace").strip()
    events: list[object] = []
    invalid = False
    if raw:
        try:
            data = json.loads(raw)
            events = data if isinstance(data, list) else [data]
        except ValueError:
            for line in raw.splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    invalid = True
    text_parts: list[str] = []
    error: str | None = None
    session: str | None = None
    reset: str | None = None
    terminal = False
    for value in events:
        if not isinstance(value, dict):
            invalid = True
            continue
        kind = value.get("type")
        if provider == "opencode" and kind == "text" and isinstance(value.get("part"), dict):
            part_text = value["part"].get("text")
            if isinstance(part_text, str):
                text_parts.append(part_text)
        elif provider == "codex":
            item = value.get("item")
            if isinstance(item, dict):
                if kind == "item.started" and item.get("type") in {"command_execution", "file_change", "web_search", "mcp_tool_call"}:
                    text_parts.clear()
                if kind == "item.completed" and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
            if kind == "message" and value.get("role") == "assistant" and isinstance(value.get("content"), list):
                text_parts.extend(block["text"] for block in value["content"] if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str))
        elif provider in {"claude", "gemini", "claw"}:
            keys = ("result",) if provider == "claude" else ("result", "response", "output") if provider == "gemini" else ("result", "output", "text", "message", "response", "content")
            if kind in {None, "result"}:
                for key in keys:
                    if isinstance(value.get(key), str):
                        text_parts.append(value[key])
                        break
            elif provider == "gemini" and kind == "message" and value.get("role") in {"assistant", "model"} and isinstance(value.get("content"), str):
                text_parts.append(value["content"])
        native_error = value.get("error")
        if native_error or value.get("is_error") or kind in {"error", "turn.failed"}:
            if error != "quota_exhausted":
                error = "provider_error"
            if provider == "opencode" and kind == "error" and isinstance(native_error, dict):
                data = native_error.get("data")
                message = native_error.get("message") or (data.get("message") if isinstance(data, dict) else "")
                quota = quota_response(message) if isinstance(message, str) else None
                if quota:
                    error, reset = quota.error_code, quota.quota_reset_at
        candidate = value.get("sessionID") if provider == "opencode" else value.get("thread_id") if provider == "codex" else value.get("session_id")
        if candidate is not None:
            if not isinstance(candidate, str) or not candidate or (session and session != candidate):
                invalid = True
            else:
                session = candidate
        if provider == "opencode":
            if kind in {"step_start", "text", "step_finish"} and not isinstance(candidate, str):
                invalid = True
            if kind in {"step_start", "text", "tool_use"}:
                terminal = False
            if kind == "step_finish":
                part = value.get("part")
                terminal = isinstance(part, dict) and part.get("reason") == "stop"
        elif provider == "codex":
            if kind in {"turn.started", "item.started", "item.updated", "item.completed"}:
                terminal = False
            if kind == "turn.completed":
                terminal = True
        else:
            terminal = True  # Batch JSON response; native error fields still veto acceptance.
    if provider == "opencode":
        for line in stderr.decode(errors="replace").splitlines():
            quota = quota_from_stderr(line)
            if quota:
                error, reset = quota.error_code, quota.quota_reset_at
    text = ("" if provider == "opencode" else "\n\n" if provider == "gemini" else "\n").join(text_parts)
    error = error or ("invalid_native_output" if invalid else None)
    error = error or ("native_completion_unproven" if not terminal else None)
    error = error or ("empty_native_output" if not text.strip() else None)
    return OneShotObservation(text, error is None, error, session, reset)


class _OneShotStreamAbortError(Exception):
    def __init__(self, reason: str, stdout: bytes, stderr: bytes) -> None:
        self.reason, self.stdout, self.stderr = reason, stdout, stderr
        super().__init__(reason)


async def _communicate_opencode(proc: asyncio.subprocess.Process, stdin_input: bytes | None) -> tuple[bytes, bytes]:
    """Bound native output and stop quota retries as soon as the trusted stderr record arrives."""
    from controlmesh.cli.opencode_quota import quota_from_stderr

    stdout: list[bytes] = []
    stderr: list[bytes] = []
    total = 0

    async def drain(stream: asyncio.StreamReader | None, chunks: list[bytes], watch: bool) -> bytes:
        nonlocal total
        assert stream is not None
        pending = b""
        while chunk := await stream.read(4096):
            total += len(chunk)
            if total > 4 * 1024 * 1024:
                raise _OneShotStreamAbortError("output_limit", b"".join(stdout), b"".join(stderr))
            chunks.append(chunk)
            if watch:
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if quota_from_stderr(line.decode(errors="replace")):
                        raise _OneShotStreamAbortError("quota_exhausted", b"".join(stdout), b"".join(stderr))
                if len(pending) > 65536:
                    pending = b""
        return b"".join(chunks)

    async def feed() -> None:
        if proc.stdin:
            try:
                if stdin_input:
                    proc.stdin.write(stdin_input)
                    await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.stdin.close()

    stdout_task = asyncio.create_task(drain(proc.stdout, stdout, watch=False))
    stderr_task = asyncio.create_task(drain(proc.stderr, stderr, watch=True))
    feed_task = asyncio.create_task(feed())
    tasks = [stdout_task, stderr_task, feed_task]
    try:
        out, err = await asyncio.gather(stdout_task, stderr_task)
        await feed_task
        await proc.wait()
        return out, err
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _kill_subprocess_group(proc: asyncio.subprocess.Process) -> None:
    """Force-kill a task subprocess together with every descendant it spawned.

    Cron/webhook provider CLIs (e.g. ``claude``) routinely launch worker
    subprocesses that inherit the parent's stdout/stderr pipes.  Killing only
    the lead PID leaves those pipe write-ends held open by orphaned
    grandchildren, so a following ``communicate()`` never observes EOF and the
    asyncio loop deadlocks.

    Each task is started in its own session (``start_new_session=True``), so
    signalling the whole process group reliably reaps every pipe-holder even
    when grandchildren were reparented to init between kill and reap.  The
    PID-tree kill remains as a best-effort fallback for children that escaped
    their session.
    """
    pid = proc.pid
    # Mock/invalid PIDs can coerce to 1. killpg(1) maps to kill(-1), which
    # broadcasts to processes owned by this user instead of one child group.
    if type(pid) is not int or pid <= 1 or pid == os.getpid():
        return
    if _IS_WINDOWS:
        force_kill_process_tree(pid)
        return
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        pgid = os.getpgid(pid)
        # Only signal the isolated group created for this subprocess.
        if pgid == pid and pgid != os.getpgrp():
            os.killpg(pgid, signal.SIGKILL)
    force_kill_process_tree(pid)


async def _drain_or_abandon(proc: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    """Best-effort pipe drain after killing the subprocess group.

    Returns whatever output was flushed within ``_POST_KILL_DRAIN_SECONDS``.
    If grandchildren still hold the pipes despite the group kill, the drain is
    abandoned (returning empty buffers) instead of blocking the event loop.
    """
    try:
        async with asyncio.timeout(_POST_KILL_DRAIN_SECONDS):
            return await proc.communicate()
    except TimeoutError:
        return (b"", b"")
    except asyncio.CancelledError:
        return (b"", b"")


async def execute_one_shot(
    one_shot: OneShotCommand,
    *,
    cwd: Path | None,
    provider: str,
    timeout_seconds: float,
    timeout_label: str,
) -> OneShotExecutionResult:
    """Run one provider CLI command with timeout and normalized status/result."""
    if provider not in _CMD_BUILDERS:
        raise UnsupportedOneShotProviderError(provider)
    stdin_input = one_shot.stdin_input
    env = os.environ.copy()
    if one_shot.env_overrides:
        env.update(one_shot.env_overrides)
    proc = await asyncio.create_subprocess_exec(
        *one_shot.cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdin=asyncio.subprocess.PIPE if stdin_input is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=not _IS_WINDOWS,
        creationflags=_CREATION_FLAGS,
    )

    timed_out = False
    aborted: str | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            if provider == "opencode":
                stdout, stderr = await _communicate_opencode(proc, stdin_input)
            else:
                stdout, stderr = await proc.communicate(input=stdin_input)
    except _OneShotStreamAbortError as exc:
        aborted = exc.reason
        _kill_subprocess_group(proc)
        await _drain_or_abandon(proc)
        stdout, stderr = exc.stdout, exc.stderr
    except TimeoutError:
        timed_out = True
        _kill_subprocess_group(proc)
        stdout, stderr = await _drain_or_abandon(proc)
    except asyncio.CancelledError:
        _kill_subprocess_group(proc)
        await _drain_or_abandon(proc)
        raise

    if timed_out:
        return OneShotExecutionResult(
            status="error:timeout",
            result_text=f"[{timeout_label} timed out after {timeout_seconds:.0f}s]",
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode,
            timed_out=True,
        )

    returncode = proc.returncode
    observed = observe_one_shot(provider, stdout, stderr)
    error_code = aborted or observed.error_code
    if not aborted and returncode != 0 and error_code not in {"provider_error", "quota_exhausted"}:
        error_code = f"exit_{returncode}"
    status = f"error:{error_code}" if error_code else "success"
    return OneShotExecutionResult(
        status=status,
        result_text=observed.text or f"[{provider}: {error_code or status}]",
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        timed_out=False,
        error_code=error_code,
        quota_reset_at=observed.quota_reset_at,
        session_id=observed.session_id,
    )
