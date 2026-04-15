"""API server management CLI subcommands (``controlmesh api ...``)."""

from __future__ import annotations

import json
from collections.abc import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from controlmesh.config import _BIND_ALL_INTERFACES
from controlmesh.i18n import t_rich
from controlmesh.workspace.paths import resolve_paths

_console = Console()

_API_SUBCOMMANDS = frozenset({"enable", "disable"})


def _parse_api_subcommand(args: list[str]) -> str | None:
    """Extract the subcommand after 'api' from CLI args."""
    found = False
    for a in args:
        if a.startswith("-"):
            continue
        if not found and a == "api":
            found = True
            continue
        if found:
            return a if a in _API_SUBCOMMANDS else None
    return None


def print_api_help() -> None:
    """Print the API subcommand help table with current status."""
    _console.print()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold green", min_width=30)
    table.add_column()
    table.add_row("controlmesh api enable", "Enable the WebSocket API server")
    table.add_row("controlmesh api disable", "Disable the WebSocket API server")

    # Show current status
    paths = resolve_paths()
    status = t_rich("api.status_not_configured")
    if paths.config_path.exists():
        try:
            data = json.loads(paths.config_path.read_text(encoding="utf-8"))
            api_cfg = data.get("api", {})
            if isinstance(api_cfg, dict) and api_cfg.get("enabled"):
                port = api_cfg.get("port", 8741)
                status = t_rich("api.status_enabled", port=port)
            elif isinstance(api_cfg, dict):
                status = t_rich("api.status_disabled")
        except (json.JSONDecodeError, OSError):
            pass

    _console.print(
        Panel(
            table,
            title=t_rich("api.title"),
            border_style="blue",
            padding=(1, 0),
        ),
    )
    _console.print(f"  Status: {status}")
    _console.print()


def nacl_available() -> bool:
    """Check if PyNaCl is importable."""
    from importlib.util import find_spec

    return find_spec("nacl.public") is not None


def api_install_hint() -> str:
    """Return the install command for PyNaCl based on install mode."""
    from controlmesh.infra.install import detect_install_mode

    mode = detect_install_mode()
    if mode == "pipx":
        return "pipx inject controlmesh PyNaCl"
    return "pip install controlmesh[api]"


def api_enable() -> None:
    """Enable the API server: check deps, write config, generate token."""
    from controlmesh.cli_commands.docker import docker_read_config

    if not nacl_available():
        hint = api_install_hint()
        _console.print(
            Panel(
                t_rich("api.missing_dep.body", hint=hint),
                title=t_rich("api.missing_dep.title"),
                border_style="yellow",
                padding=(1, 2),
            ),
        )
        return

    result = docker_read_config()
    if result is None:
        return
    config_path, data = result

    import secrets as _secrets

    api = data.get("api", {})
    if not isinstance(api, dict):
        api = {}
    api["enabled"] = True
    if not api.get("token"):
        api["token"] = _secrets.token_urlsafe(32)
    api.setdefault("host", _BIND_ALL_INTERFACES)
    api.setdefault("port", 8741)
    api.setdefault("chat_id", 0)
    api.setdefault("allow_public", False)
    from controlmesh.infra.json_store import atomic_json_save

    data["api"] = api
    atomic_json_save(config_path, data)

    _console.print(
        Panel(
            t_rich("api.enabled.body", host=api["host"], port=api["port"], token=api["token"]),
            title=t_rich("api.enabled.title"),
            border_style="green",
            padding=(1, 2),
        ),
    )


def api_disable() -> None:
    """Disable the API server in config."""
    from controlmesh.cli_commands.docker import docker_read_config

    result = docker_read_config()
    if result is None:
        return
    config_path, data = result

    api = data.get("api", {})
    if not isinstance(api, dict):
        api = {}
    from controlmesh.infra.json_store import atomic_json_save

    api["enabled"] = False
    data["api"] = api
    atomic_json_save(config_path, data)
    _console.print(t_rich("api.disabled.status"))
    _console.print(t_rich("docker.restart_hint"))


def cmd_api(args: list[str]) -> None:
    """Handle 'controlmesh api <subcommand>'."""
    sub = _parse_api_subcommand(args)
    if sub is None:
        print_api_help()
        return

    dispatch: dict[str, Callable[[], None]] = {
        "enable": api_enable,
        "disable": api_disable,
    }
    _console.print()
    dispatch[sub]()
    _console.print()
