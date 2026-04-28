"""Provider runtime/native command introspection models and helpers."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from shutil import which

from controlmesh.cli.auth import (
    AuthStatus,
    check_claw_auth,
    check_codex_auth,
    check_gemini_auth,
    check_openai_agents_auth,
    check_opencode_auth,
)


class ProbeStatus(StrEnum):
    """Availability state for a native command or probe result."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class NativeCommandSource(StrEnum):
    """Where a native command entry came from."""

    PROVIDER = "provider"
    CLI_HELP = "cli_help"
    STATIC_FALLBACK = "static_fallback"
    CONFIG = "config"


@dataclass(frozen=True, slots=True)
class NativeCommandSpec:
    """One provider-native slash command."""

    name: str
    description: str = ""
    provider: str = ""
    category: str = "native"
    aliases: tuple[str, ...] = ()
    visible: bool = True
    status: ProbeStatus = ProbeStatus.UNKNOWN
    source: NativeCommandSource = NativeCommandSource.STATIC_FALLBACK
    shadowed_by_controlmesh: bool = False
    requires_auth: bool = False
    raw: str = ""

    @property
    def slash(self) -> str:
        return self.name if self.name.startswith("/") else f"/{self.name}"


@dataclass(frozen=True, slots=True)
class ProviderIntrospection:
    """Runtime/native command snapshot for one provider."""

    provider: str
    model: str = ""
    installed: bool = False
    executable: str = ""
    version: str = ""
    auth_status: str = "unknown"
    permission_mode: str = ""
    native_commands: tuple[NativeCommandSpec, ...] = ()
    supports_live_command_registry: bool = False
    checked_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    errors: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return self.installed and self.auth_status in {
            AuthStatus.AUTHENTICATED.value,
            AuthStatus.INSTALLED.value,
            "authenticated",
            "installed",
        }

    @property
    def command_source(self) -> str:
        for command in self.native_commands:
            return command.source.value
        return "none"


def auth_status_for_provider(provider: str) -> str:
    """Return the current auth status string for one provider."""
    checker = _LIGHT_AUTH_CHECKERS.get(provider) or _AUTH_CHECKERS.get(provider)
    if checker is None:
        return "unknown"
    try:
        return checker().status.value
    except OSError:
        return "unknown"


async def probe_command_output(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: float = 5.0,
) -> tuple[str, tuple[str, ...]]:
    """Run a short command and return its combined version-like output."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=merged_env,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
        return "", (f"probe failed: {' '.join(command[:2])}: {exc}",)

    stdout_text = stdout.decode(errors="replace").strip()
    stderr_text = stderr.decode(errors="replace").strip()
    version = stdout_text or stderr_text
    errors: tuple[str, ...] = ()
    if process.returncode not in (0, None) and not version:
        errors = (f"probe exited with code {process.returncode}",)
    return version, errors


_AUTH_CHECKERS = {
    "codex": check_codex_auth,
    "gemini": check_gemini_auth,
    "claw": check_claw_auth,
    "opencode": check_opencode_auth,
    "openai_agents": check_openai_agents_auth,
}


def _check_claude_auth_light() -> object:
    credentials = Path.home() / ".claude" / ".credentials.json"
    if credentials.is_file():
        return _LightAuthResult(AuthStatus.AUTHENTICATED)
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return _LightAuthResult(AuthStatus.AUTHENTICATED)
    claude_home = Path.home() / ".claude"
    if claude_home.is_dir() or which("claude") is not None:
        return _LightAuthResult(AuthStatus.INSTALLED)
    return _LightAuthResult(AuthStatus.NOT_FOUND)


@dataclass(frozen=True, slots=True)
class _LightAuthResult:
    status: AuthStatus


_LIGHT_AUTH_CHECKERS = {
    "claude": _check_claude_auth_light,
}
