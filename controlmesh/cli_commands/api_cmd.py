"""API server management CLI subcommands (``controlmesh api ...``)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
from collections.abc import Callable
from contextlib import suppress

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from controlmesh.config import _BIND_ALL_INTERFACES
from controlmesh.i18n import t_rich
from controlmesh.workspace.paths import resolve_paths

_console = Console()

_API_SUBCOMMANDS = frozenset({"enable", "disable", "serve"})


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
    table.add_row(
        "controlmesh api serve",
        "Serve the local read-only API and bundled dashboard",
    )

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


def _parse_serve_options(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="controlmesh api serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--token", default=os.environ.get("CONTROLMESH_API_TOKEN", ""))
    return parser.parse_args(args[args.index("serve") + 1 :])


async def _serve_read_only(options: argparse.Namespace) -> None:
    from controlmesh.api.admin_read import AdminHistoryCatalogReader
    from controlmesh.api.server import ApiServer
    from controlmesh.config import ApiConfig

    if options.host != "127.0.0.1":
        raise SystemExit("read-only alpha server must bind to 127.0.0.1")
    if not 0 <= options.port <= 65535:
        raise SystemExit("port must be between 0 and 65535")

    token = options.token or secrets.token_urlsafe(32)
    server = ApiServer(
        ApiConfig(
            enabled=True,
            host=options.host,
            port=options.port,
            token=token,
            allow_public=False,
        ),
        read_only=True,
    )
    server.set_admin_catalog_reader(AdminHistoryCatalogReader(resolve_paths()))
    await server.start()
    port = server.bound_port
    _console.print(f"Read-only API: http://127.0.0.1:{port}/api/v1")
    _console.print(f"Dashboard: http://127.0.0.1:{port}/dashboard/")
    _console.print(f"Bearer token: {token}")
    _console.print("Press Ctrl+C to stop.")

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for watched_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(watched_signal, stopped.set)
        except NotImplementedError:
            break
    try:
        await stopped.wait()
    finally:
        await server.stop()


def api_serve(args: list[str]) -> None:
    """Run the local-only read-only facade without starting a transport runtime."""
    with suppress(KeyboardInterrupt):
        asyncio.run(_serve_read_only(_parse_serve_options(args)))


def cmd_api(args: list[str]) -> None:
    """Handle 'controlmesh api <subcommand>'."""
    sub = _parse_api_subcommand(args)
    if sub is None:
        print_api_help()
        return

    dispatch: dict[str, Callable[[], None]] = {
        "enable": api_enable,
        "disable": api_disable,
        "serve": lambda: api_serve(args),
    }
    _console.print()
    dispatch[sub]()
    _console.print()
