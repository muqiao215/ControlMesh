"""Async wrapper around the OpenAI Codex CLI."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING

from controlmesh.cli.base import (
    _IS_WINDOWS,
    BaseCLI,
    CLIConfig,
    docker_wrap,
)
from controlmesh.cli.introspection import ProviderIntrospection, auth_status_for_provider, probe_command_output
from controlmesh.cli.codex_events import (
    CodexThinkingFilter,
    parse_codex_jsonl,
    parse_codex_stream_event,
)
from controlmesh.cli.executor import (
    SubprocessResult,
    SubprocessSpec,
    run_oneshot_subprocess,
    run_streaming_subprocess,
)
from controlmesh.cli.stream_events import (
    AssistantTextDelta,
    ResultEvent,
    StreamEvent,
    SystemInitEvent,
)
from controlmesh.cli.types import CLIResponse
from controlmesh.native_commands import fallback_native_commands

if TYPE_CHECKING:
    from controlmesh.cli.timeout_controller import TimeoutController

logger = logging.getLogger(__name__)


class _StreamState:
    """Mutable accumulator for streaming session data."""

    __slots__ = ("accumulated_text", "thread_id")

    def __init__(self) -> None:
        self.accumulated_text: list[str] = []
        self.thread_id: str | None = None

    def track(self, event: StreamEvent) -> None:
        """Update state from a single stream event."""
        if isinstance(event, SystemInitEvent) and event.session_id:
            self.thread_id = event.session_id
        elif isinstance(event, AssistantTextDelta) and event.text:
            self.accumulated_text.append(event.text)


class CodexCLI(BaseCLI):
    """Async wrapper around the OpenAI Codex CLI."""

    def __init__(self, config: CLIConfig) -> None:
        self._config = config
        self._working_dir = Path(config.working_dir).resolve()
        self._cli = "codex" if config.docker_container else self._find_cli()
        logger.info("Codex CLI wrapper: cwd=%s, model=%s", self._working_dir, config.model)

    @staticmethod
    def _find_cli() -> str:
        path = which("codex")
        if not path:
            msg = "codex CLI not found on PATH. Install via: npm install -g @openai/codex"
            raise FileNotFoundError(msg)
        return path

    def _compose_prompt(self, prompt: str) -> str:
        """Inject system context into user prompt (Codex has no --system-prompt)."""
        cfg = self._config
        parts: list[str] = []
        if cfg.system_prompt:
            parts.append(cfg.system_prompt)
        parts.append(prompt)
        if cfg.append_system_prompt:
            parts.append(cfg.append_system_prompt)
        return "\n\n".join(parts)

    def _sandbox_flags(self) -> list[str]:
        """Return sandbox/approval flags based on permission_mode."""
        cfg = self._config
        if cfg.permission_mode == "bypassPermissions":
            return ["--dangerously-bypass-approvals-and-sandbox"]
        if cfg.sandbox_mode == "full-access":
            return ["--sandbox", "danger-full-access"]
        if cfg.sandbox_mode == "workspace-write":
            return ["--full-auto"]
        return ["--sandbox", cfg.sandbox_mode]

    def _common_codex_flags(self, *, json_output: bool) -> list[str]:
        """Return Codex flags for new executions."""
        cfg = self._config
        flags: list[str] = []
        if json_output:
            flags.append("--json")
        flags += ["--color", "never"]
        flags += self._sandbox_flags()
        flags.append("--skip-git-repo-check")

        if cfg.model:
            flags += ["--model", cfg.model]
        if cfg.reasoning_effort and cfg.reasoning_effort != "default":
            flags += ["-c", f"model_reasoning_effort={cfg.reasoning_effort}"]
        if cfg.instructions:
            flags += ["--instructions", cfg.instructions]
        for img in cfg.images:
            flags += ["--image", img]
        if cfg.cli_parameters:
            flags.extend(cfg.cli_parameters)
        return flags

    def _resume_codex_flags(self, *, json_output: bool) -> list[str]:
        """Return only flags accepted by ``codex exec resume``."""
        cfg = self._config
        flags: list[str] = []
        if json_output:
            flags.append("--json")
        if cfg.permission_mode == "bypassPermissions":
            flags.append("--dangerously-bypass-approvals-and-sandbox")
        flags.append("--skip-git-repo-check")

        if cfg.model:
            flags += ["--model", cfg.model]
        if cfg.reasoning_effort and cfg.reasoning_effort != "default":
            flags += ["-c", f"model_reasoning_effort={cfg.reasoning_effort}"]
        for img in cfg.images:
            flags += ["--image", img]
        flags.extend(_resume_supported_cli_parameters(cfg.cli_parameters))
        return flags

    def _build_resume_command(
        self, final_prompt: str, session_id: str, *, json_output: bool
    ) -> list[str]:
        """Build command to resume an existing Codex session."""
        cmd = [self._cli, "exec", "resume", *self._resume_codex_flags(json_output=json_output)]
        cmd += ["--", session_id]
        if not _IS_WINDOWS:
            cmd.append(final_prompt)
        return cmd

    def _build_command(
        self,
        prompt: str,
        resume_session: str | None = None,
        *,
        json_output: bool = True,
    ) -> list[str]:
        final_prompt = self._compose_prompt(prompt)

        if resume_session:
            return self._build_resume_command(final_prompt, resume_session, json_output=json_output)

        cmd = [self._cli, "exec", *self._common_codex_flags(json_output=json_output)]

        # On Windows, .CMD wrappers mangle arguments with special characters.
        # The prompt is passed via stdin instead (see send / send_streaming).
        if not _IS_WINDOWS:
            cmd.append("--")
            cmd.append(final_prompt)
        return cmd

    def _docker_wrap(self, cmd: list[str]) -> tuple[list[str], str | None]:
        """Keep stdin open for Dockerized Codex on Windows so prompts reach the CLI."""
        return docker_wrap(
            cmd,
            self._config,
            interactive=_IS_WINDOWS,
        )

    async def send(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
        hard_timeout_seconds: float | None = None,
    ) -> CLIResponse:
        """Send a prompt and return the final result."""
        if continue_session:
            logger.debug("continue_session is not supported by Codex CLI, ignoring")
        cmd = self._build_command(prompt, resume_session, json_output=True)
        exec_cmd, use_cwd = self._docker_wrap(cmd)
        _log_cmd(exec_cmd)
        return await run_oneshot_subprocess(
            config=self._config,
            spec=SubprocessSpec(
                exec_cmd,
                use_cwd,
                prompt,
                timeout_seconds,
                timeout_controller,
                hard_timeout_seconds,
            ),
            parse_output=self._parse_output,
            provider_label="Codex",
        )

    async def send_streaming(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
        hard_timeout_seconds: float | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Send a prompt and yield stream events as they arrive."""
        cmd = self._build_command(prompt, resume_session, json_output=True)
        exec_cmd, use_cwd = self._docker_wrap(cmd)
        _log_cmd(exec_cmd, streaming=True)

        state = _StreamState()
        thinking_filter = CodexThinkingFilter()

        async def line_handler(line: str) -> AsyncGenerator[StreamEvent, None]:
            if not line:
                return
            for raw_event in parse_codex_stream_event(line):
                for event in thinking_filter.process(raw_event):
                    state.track(event)
                    yield event
            for event in thinking_filter.flush():
                state.track(event)
                yield event

        async def post_handler(result: SubprocessResult) -> AsyncGenerator[StreamEvent, None]:
            yield _codex_final_result(result, state.accumulated_text, state.thread_id)

        async for event in run_streaming_subprocess(
            config=self._config,
            spec=SubprocessSpec(
                exec_cmd,
                use_cwd,
                prompt,
                timeout_seconds,
                timeout_controller,
                hard_timeout_seconds,
            ),
            line_handler=line_handler,
            provider_label="Codex",
            post_handler=post_handler,
        ):
            yield event

    async def introspect(self) -> ProviderIntrospection:
        """Return runtime/native-command state for Codex CLI."""
        version, errors = await probe_command_output(
            [self._cli, "--version"],
            cwd=self._working_dir,
            timeout_seconds=1.0,
        )
        return ProviderIntrospection(
            provider="codex",
            model=self._config.model or "",
            installed=True,
            executable=self._cli,
            version=version,
            auth_status=auth_status_for_provider("codex"),
            permission_mode=self._config.permission_mode,
            native_commands=fallback_native_commands("codex"),
            supports_live_command_registry=False,
            errors=errors,
            expires_at=time.time() + 120.0,
        )

    @staticmethod
    def _parse_output(
        stdout: bytes,
        stderr: bytes,
        returncode: int | None,
    ) -> CLIResponse:
        """Parse Codex subprocess output into a CLIResponse."""
        stderr_text = stderr.decode(errors="replace")[:2000] if stderr else ""
        if stderr_text:
            logger.warning("Codex stderr (exit=%s): %s", returncode, stderr_text[:500])

        raw = stdout.decode(errors="replace").strip()
        if not raw:
            logger.error("Codex returned empty output (exit=%s)", returncode)
            return CLIResponse(result="", is_error=True, returncode=returncode, stderr=stderr_text)

        is_error = returncode != 0
        result_text, thread_id, usage = parse_codex_jsonl(raw)
        structured_event_only = _looks_like_codex_event_stream(raw) and not result_text
        response = CLIResponse(
            session_id=thread_id,
            result=(
                result_text
                or (
                    "Codex returned structured event output without a final assistant message."
                    if structured_event_only
                    else raw
                )
            ),
            is_error=is_error or not result_text,
            returncode=returncode,
            stderr=stderr_text,
            usage=usage or {},
        )

        if response.is_error:
            logger.error("Codex error exit=%s: %s", returncode, response.result[:300])
        else:
            logger.info(
                "Codex done session=%s tokens=%d",
                (response.session_id or "?")[:8],
                response.total_tokens,
            )

        return response


def _codex_final_result(
    result: SubprocessResult,
    accumulated_text: list[str],
    thread_id: str | None,
) -> ResultEvent:
    """Build the final ResultEvent after the stream loop completes."""
    if result.process.returncode != 0:
        error_detail = (
            result.diagnostic.render_user_error()
            if result.diagnostic is not None
            else (
                result.stderr_bytes.decode(errors="replace")[:2000]
                if result.stderr_bytes
                else ""
            )
            or (
                "\n".join(accumulated_text)
                or f"Codex exited with code {result.process.returncode} and produced no stdout/stderr."
            )
        )
        logger.error(
            "Codex stream exited with code %d: %s",
            result.process.returncode,
            error_detail[:300],
        )
        return ResultEvent(
            type="result",
            result=error_detail,
            is_error=True,
            returncode=result.process.returncode,
        )

    return ResultEvent(
        type="result",
        session_id=thread_id,
        result="\n".join(accumulated_text),
        is_error=False,
        returncode=result.process.returncode,
    )


def _log_cmd(cmd: list[str], *, streaming: bool = False) -> None:
    """Log the CLI command with truncated long values."""
    safe_cmd = [(c[:80] + "...") if len(c) > 80 else c for c in cmd]
    prefix = "Codex stream cmd" if streaming else "Codex cmd"
    logger.info("%s: %s", prefix, " ".join(safe_cmd))


def _looks_like_codex_event_stream(raw: str) -> bool:
    """Return True when *raw* looks like Codex JSONL event output."""
    saw_event = False
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        event_type = str(data.get("type") or "")
        if event_type.startswith(("thread.", "turn.", "item.", "message")):
            saw_event = True
            continue
        if isinstance(data.get("item"), dict):
            saw_event = True
            continue
        return False
    return saw_event


def _resume_supported_cli_parameters(parameters: list[str]) -> list[str]:
    """Filter custom flags down to the subset supported by ``codex exec resume``."""
    supported_standalone = {
        "--all",
        "--dangerously-bypass-hook-trust",
        "--ephemeral",
        "--ignore-rules",
        "--ignore-user-config",
        "--strict-config",
    }
    supported_with_value = {
        "-c",
        "--config",
        "--disable",
        "--enable",
        "-i",
        "--image",
        "-m",
        "--model",
        "-o",
        "--output-last-message",
        "--output-schema",
    }
    filtered: list[str] = []
    index = 0
    while index < len(parameters):
        param = parameters[index]
        if param in supported_standalone:
            filtered.append(param)
            index += 1
            continue
        if param in supported_with_value:
            if index + 1 < len(parameters):
                filtered.extend((param, parameters[index + 1]))
                index += 2
                continue
            logger.warning("Dropping Codex resume CLI flag without value: %s", param)
            index += 1
            continue
        logger.warning("Dropping unsupported Codex resume CLI parameter: %s", param)
        index += 1
    return filtered
