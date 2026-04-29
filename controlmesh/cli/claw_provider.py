"""Async wrapper around the claw-code CLI."""

from __future__ import annotations

import asyncio
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


class ClawCLI(BaseCLI):
    """Async wrapper around the claw CLI."""

    def __init__(self, config: CLIConfig) -> None:
        self._config = config
        self._working_dir = Path(config.working_dir).resolve()
        self._cli = "claw" if config.docker_container else self._find_cli()
        logger.info("Claw CLI wrapper: cwd=%s model=%s", self._working_dir, config.model)

    @staticmethod
    def _find_cli() -> str:
        path = which("claw")
        if not path:
            msg = "claw CLI not found on PATH. Install/build ultraworkers/claw-code first."
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

    def _permission_mode(self) -> str:
        if self._config.permission_mode == "bypassPermissions":
            return "danger-full-access"
        if self._config.permission_mode in {"read-only", "workspace-write", "danger-full-access"}:
            return self._config.permission_mode
        return "workspace-write"

    def _build_command(
        self,
        prompt: str,
        resume_session: str | None = None,
        continue_session: bool = False,
    ) -> list[str]:
        cmd = [self._cli, "--output-format", "json"]
        if self._config.model:
            cmd += ["--model", self._config.model]
        cmd += ["--permission-mode", self._permission_mode()]
        if self._config.allowed_tools:
            cmd += ["--allowedTools", ",".join(self._config.allowed_tools)]
        if resume_session:
            cmd += ["--resume", resume_session]
        elif continue_session:
            cmd += ["--resume", "latest"]
        if self._config.cli_parameters:
            cmd.extend(self._config.cli_parameters)
        cmd += ["prompt", self._compose_prompt(prompt)]
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
        response = await run_oneshot_subprocess(
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
            provider_label="Claw",
        )
        if not response.session_id:
            response.session_id = await self._read_state_session_id(timeout_seconds)
        return response

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
        """Return runtime/native-command state for Claw."""
        version, errors = await probe_command_output(
            [self._cli, "--version"],
            cwd=self._working_dir,
            timeout_seconds=1.0,
        )
        return ProviderIntrospection(
            provider="claw",
            model=self._config.model or "",
            installed=True,
            executable=self._cli,
            version=version,
            auth_status=auth_status_for_provider("claw"),
            permission_mode=self._config.permission_mode,
            native_commands=fallback_native_commands("claw"),
            supports_live_command_registry=False,
            errors=errors,
            expires_at=time.time() + 120.0,
        )

    async def _read_state_session_id(self, timeout_seconds: float | None) -> str | None:
        cmd = [self._cli, "state", "--output-format", "json"]
        exec_cmd, use_cwd = docker_wrap(cmd, self._config)
        try:
            process = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=use_cwd,
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds or 15.0,
            )
        except (OSError, TimeoutError, asyncio.TimeoutError):
            return None
        if process.returncode != 0 or not stdout:
            return None
        try:
            data = json.loads(stdout.decode(errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return _extract_session_id(data)

    @staticmethod
    def _parse_output(stdout: bytes, stderr: bytes, returncode: int | None) -> CLIResponse:
        stderr_text = stderr.decode(errors="replace")[:2000] if stderr else ""
        raw = stdout.decode(errors="replace").strip()
        if not raw:
            return CLIResponse(result="", is_error=True, returncode=returncode, stderr=stderr_text)

        data: Any
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return CLIResponse(
                result=raw,
                is_error=returncode not in (0, None),
                returncode=returncode,
                stderr=stderr_text,
            )

        usage = data.get("usage") if isinstance(data, dict) and isinstance(data.get("usage"), dict) else {}
        return CLIResponse(
            session_id=_extract_session_id(data),
            result=_extract_text(data) or raw,
            is_error=(returncode not in (0, None)) or _has_error(data),
            returncode=returncode,
            stderr=stderr_text,
            usage=usage,
        )


def _has_error(data: Any) -> bool:
    return isinstance(data, dict) and bool(data.get("error") or data.get("is_error"))


def _extract_session_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("session_id", "sessionId", "session", "sessionRef", "session_ref"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _extract_session_id(value)
                if nested:
                    return nested
        worker = data.get("worker") or data.get("state")
        if isinstance(worker, dict):
            nested = _extract_session_id(worker)
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
        for key in ("result", "output", "text", "message", "response", "content"):
            value = data.get(key)
            text = _extract_text(value)
            if text:
                return text
        for value in data.values():
            if isinstance(value, (dict, list)):
                text = _extract_text(value)
                if text:
                    return text
    return ""
