"""Provider command resolution for native terminal mode."""

from __future__ import annotations

from shutil import which

from controlmesh.config import AgentConfig
from controlmesh.terminal.errors import TerminalProviderError

_NATIVE_PROVIDER_BINARIES: dict[str, str] = {
    "codex": "codex",
    "claude": "claude",
    "opencode": "opencode",
    "gemini": "gemini",
    "claw": "claw",
}


def resolve_native_provider_argv(provider: str, config: AgentConfig) -> list[str]:
    """Return argv for the real provider CLI used by native mode."""
    normalized = provider.strip().lower()
    binary = _NATIVE_PROVIDER_BINARIES.get(normalized)
    if binary is None:
        msg = f"Unsupported native provider: {provider}"
        raise TerminalProviderError(msg)

    executable = which(binary) or binary
    return [executable, *config.terminal.native_provider_args.get(normalized, [])]
