"""Shared helpers for platform-specific service backends."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from rich.panel import Panel

from controlmesh.i18n import t_rich

if TYPE_CHECKING:
    from rich.console import Console

# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


def ensure_console(console: Console | None) -> Console:
    """Return an initialized Rich console instance."""
    if console is not None:
        return console

    from rich.console import Console as RichConsole

    return RichConsole()


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------


def find_controlmesh_binary() -> str | None:
    """Find the controlmesh binary in PATH. Shared across all backends."""
    return shutil.which("controlmesh")


# ---------------------------------------------------------------------------
# NVM
# ---------------------------------------------------------------------------


def collect_nvm_bin_dirs(home: Path) -> list[str]:
    """Return bin directories for all NVM-managed Node.js versions."""
    nvm_dir = home / ".nvm"
    if not nvm_dir.is_dir():
        return []
    return [str(node_dir) for node_dir in sorted(nvm_dir.glob("versions/node/*/bin"), reverse=True)]


# ---------------------------------------------------------------------------
# Standardised messages
# ---------------------------------------------------------------------------


def print_not_installed(console: Console) -> None:
    """Print the 'service not installed' hint."""
    console.print(t_rich("service.not_installed"))


def print_not_running(console: Console) -> None:
    """Print the 'service is not running' hint."""
    console.print(t_rich("service.not_running"))


def print_no_service(console: Console) -> None:
    """Print the 'no service installed' hint (for uninstall)."""
    console.print(t_rich("service.no_service"))


def print_binary_not_found(console: Console) -> None:
    """Print the 'controlmesh binary not found' error."""
    console.print(t_rich("service.no_binary"))


def print_removed(console: Console) -> None:
    """Print the 'service removed' confirmation."""
    console.print(t_rich("service.removed"))


def print_started(console: Console) -> None:
    """Print the 'service started' confirmation."""
    console.print(t_rich("service.started"))


def print_stopped(console: Console) -> None:
    """Print the 'service stopped' confirmation."""
    console.print(t_rich("service.stopped"))


def print_start_failed(console: Console, stderr: str) -> None:
    """Print a start-failure message with stderr detail."""
    console.print(t_rich("service.start_failed", error=stderr))


def print_stop_failed(console: Console, stderr: str) -> None:
    """Print a stop-failure message with stderr detail."""
    console.print(t_rich("service.stop_failed", error=stderr))


def print_install_success(
    console: Console,
    *,
    detail: str,
    logs_hint: str = "View recent logs",
) -> None:
    """Print the standard success panel after service installation.

    *detail* is the platform-specific restart/boot sentence (second line).
    *logs_hint* is the description next to ``controlmesh service logs``.
    """
    console.print(
        Panel(
            t_rich("service.install.body", detail=detail, logs_hint=logs_hint),
            title=t_rich("service.install.title"),
            border_style="green",
            padding=(1, 2),
        ),
    )
