from __future__ import annotations

from controlmesh.config import AgentConfig
from controlmesh.terminal.providers import resolve_native_provider_argv


def test_native_provider_argv_uses_configured_extra_args() -> None:
    config = AgentConfig()
    config.terminal.native_provider_args["codex"] = ["--some-flag"]

    argv = resolve_native_provider_argv("codex", config)

    assert argv[-1] == "--some-flag"
