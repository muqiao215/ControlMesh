"""Async wrapper around the opencode CLI."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Any

from controlmesh.cli.base import BaseCLI, CLIConfig, docker_wrap
from controlmesh.cli.executor import SubprocessSpec, run_oneshot_subprocess
from controlmesh.cli.introspection import ProviderIntrospection, auth_status_for_provider, probe_command_output
from controlmesh.cli.stream_events import ResultEvent, StreamEvent, SystemInitEvent
from controlmesh.cli.types import CLIResponse
from controlmesh.native_commands import fallback_native_commands

if TYPE_CHECKING:
    from controlmesh.cli.timeout_controller import TimeoutController

logger = logging.getLogger(__name__)


class OpenCodeCLI(BaseCLI):
    """Async wrapper around the opencode CLI."""

    def __init__(self, config: CLIConfig) -> None:
        self._config = config
        self._working_dir = Path(config.working_dir).resolve()
        self._cli = "opencode" if config.docker_container else self._find_cli()
        logger.info("OpenCode CLI wrapper: cwd=%s model=%s", self._working_dir, config.model)

    @staticmethod
    def _find_cli() -> str:
        path = which("opencode")
        if not path:
            msg = "opencode CLI not found on PATH. Install opencode first."
            raise FileNotFoundError(msg)
        return path

    def _compose_prompt(self, prompt: str) -> str:
        parts: list[str] = []
        if self._config.system_prompt:
            parts.append(self._config.system_prompt)
        parts.append(prompt)
        if self._config.append_system_prompt:
            parts.append(self._config.append_system_prompt)
        return "\n\n".join(parts)

    def _permission_flags(self) -> list[str]:
        """Map ControlMesh permission_mode onto OpenCode's CLI surface."""
        if self._config.permission_mode == "bypassPermissions":
            return ["--dangerously-skip-permissions"]
        return []

    def _build_command(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
    ) -> list[str]:
        # OpenCode 1.14.x dropped `--quiet`; `--format json` is the stable
        # machine-readable surface we rely on across hosts.
        cmd = [self._cli, "run", "--format", "json"]
        cmd.extend(self._permission_flags())
        if self._config.model:
            cmd += ["--model", self._config.model]
        if resume_session:
            cmd += ["--session", resume_session]
        elif continue_session:
            cmd.append("--continue")
        if self._config.cli_parameters:
            cmd.extend(self._config.cli_parameters)
        cmd += [self._compose_prompt(prompt)]
        return cmd

    async def send(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
        timeout_seconds: float | None = None,
        timeout_controller: TimeoutController | None = None,
        hard_timeout_seconds: float | None = None,
    ) -> CLIResponse:
        cmd = self._build_command(prompt, resume_session, continue_session)
        exec_cmd, use_cwd = docker_wrap(cmd, self._config)
        return await run_oneshot_subprocess(
            config=self._config,
            spec=SubprocessSpec(
                exec_cmd,
                use_cwd,
                "",
                timeout_seconds,
                timeout_controller,
                hard_timeout_seconds,
            ),
            parse_output=self._parse_output,
            provider_label="OpenCode",
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
        response = await self.send(
            prompt,
            resume_session=resume_session,
            continue_session=continue_session,
            timeout_seconds=timeout_seconds,
            timeout_controller=timeout_controller,
            hard_timeout_seconds=hard_timeout_seconds,
        )
        if response.session_id:
            yield SystemInitEvent(type="system", subtype="init", session_id=response.session_id)
        yield ResultEvent(
            type="result",
            session_id=response.session_id,
            result=response.result,
            is_error=response.is_error,
            returncode=response.returncode,
        )

    async def introspect(self) -> ProviderIntrospection:
        """Return runtime/native-command state for OpenCode."""
        version, errors = await probe_command_output(
            [self._cli, "--version"],
            cwd=self._working_dir,
            timeout_seconds=1.0,
        )
        return ProviderIntrospection(
            provider="opencode",
            model=self._config.model or "",
            installed=True,
            executable=self._cli,
            version=version,
            auth_status=auth_status_for_provider("opencode"),
            permission_mode=self._config.permission_mode,
            native_commands=fallback_native_commands("opencode"),
            supports_live_command_registry=False,
            errors=errors,
            expires_at=time.time() + 120.0,
        )

    @staticmethod
    def _parse_output(stdout: bytes, stderr: bytes, returncode: int | None) -> CLIResponse:
        stderr_text = stderr.decode(errors="replace")[:2000] if stderr else ""
        raw = stdout.decode(errors="replace").strip()
        if not raw:
            return CLIResponse(result="", is_error=True, returncode=returncode, stderr=stderr_text)

        events: list[Any] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append(line)

        if len(events) == 1 and isinstance(events[0], dict):
            data = events[0]
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            result_text = _extract_text(data)
            is_error = (returncode not in (0, None)) or _has_error(data) or not result_text
            return CLIResponse(
                session_id=_extract_session_id(data),
                result=_finalize_result_text(
                    result_text,
                    raw=raw,
                    stderr_text=stderr_text,
                    is_error=is_error,
                ),
                is_error=is_error or not result_text,
                returncode=returncode,
                stderr=stderr_text,
                usage=usage,
            )

        usage: dict[str, Any] = {}
        session_id: str | None = None
        texts: list[str] = []
        saw_error = False
        for event in events:
            if isinstance(event, dict):
                session_id = session_id or _extract_session_id(event)
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                saw_error = saw_error or _has_error(event)
                text = _extract_text(event)
                if text:
                    texts.append(text)
            elif isinstance(event, str):
                texts.append(event)
        is_error = (returncode not in (0, None)) or saw_error or not texts
        return CLIResponse(
            session_id=session_id,
            result=_finalize_result_text(
                "\n".join(part for part in texts if part).strip(),
                raw=raw,
                stderr_text=stderr_text,
                is_error=is_error,
            ),
            is_error=is_error,
            returncode=returncode,
            stderr=stderr_text,
            usage=usage,
        )


def _has_error(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("error") or data.get("is_error"))


def _finalize_result_text(
    text: str,
    *,
    raw: str,
    stderr_text: str,
    is_error: bool,
) -> str:
    if text:
        return text
    if is_error:
        return stderr_text or "OpenCode returned no assistant text."
    return raw


def _extract_session_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("session_id", "sessionId", "sessionID", "session"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _extract_session_id(value)
                if nested:
                    return nested
        if isinstance(data.get("id"), str) and data.get("type") in {"session", "session.created"}:
            return data["id"].strip()
        for value in data.values():
            nested = _extract_session_id(value)
            if nested:
                return nested
    return None


def _extract_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        parts = [_extract_text(item) for item in data]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(data, dict):
        part = data.get("part")
        if isinstance(part, dict) and part.get("type") == "text":
            text = _extract_text(part.get("text"))
            if text:
                return text
        for key in ("result", "output", "text", "message", "response", "content"):
            value = data.get(key)
            text = _extract_text(value)
            if text:
                return text
        delta = data.get("delta")
        if isinstance(delta, dict):
            text = _extract_text(delta)
            if text:
                return text
        for value in data.values():
            if isinstance(value, (dict, list)):
                text = _extract_text(value)
                if text:
                    return text
    return ""
