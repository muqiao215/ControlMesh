"""Shared log rendering helpers for service backends."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh.i18n import t_rich

if TYPE_CHECKING:
    from rich.console import Console


def print_recent_logs(
    console: Console,
    logs_dir: Path,
    *,
    preferred_name: str = "agent.log",
    line_count: int = 50,
) -> None:
    """Print the last lines from a preferred or newest log file."""
    preferred_log = logs_dir / preferred_name
    if preferred_log.exists():
        latest_log = preferred_log
    else:
        log_files = sorted(
            logs_dir.glob("*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not log_files:
            console.print(t_rich("service.logs.no_logs"))
            return
        latest_log = log_files[0]

    console.print(t_rich("service.logs.showing", count=line_count, name=latest_log.name) + "\n")

    try:
        lines = latest_log.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-line_count:]:
            console.print(line)
    except OSError as exc:
        console.print(t_rich("service.logs.read_error", error=exc))
        return

    console.print(f"\n{t_rich('service.logs.full_path', path=latest_log)}")


def print_file_service_logs(
    console: Console,
    *,
    installed: bool,
    logs_dir: Path,
) -> None:
    """Print recent service logs from log files when service is installed."""
    if not installed:
        console.print(t_rich("service.logs.not_installed"))
        return
    print_recent_logs(console, logs_dir)


def print_journal_service_logs(
    console: Console,
    *,
    installed: bool,
    service_name: str,
    fallback_logs_dir: Path | None = None,
) -> None:
    """Follow journalctl service logs when service is installed."""
    if not installed:
        console.print(t_rich("service.logs.not_installed"))
        return

    console.print(t_rich("service.logs.streaming") + "\n")
    try:
        if fallback_logs_dir is not None:
            probe = subprocess.run(
                ["journalctl", "--user", "-u", service_name, "-n", "1", "--no-hostname"],
                capture_output=True,
                text=True,
                check=False,
            )
            combined = f"{probe.stdout}\n{probe.stderr}"
            if probe.returncode != 0 or "No journal files were found." in combined:
                console.print("[dim]No user journal available; showing recent file logs instead.[/dim]\n")
                print_recent_logs(console, fallback_logs_dir)
                return

        subprocess.run(
            ["journalctl", "--user", "-u", service_name, "-f", "--no-hostname"],
            check=False,
        )
    except FileNotFoundError:
        if fallback_logs_dir is not None:
            console.print("[dim]journalctl not found; showing recent file logs instead.[/dim]\n")
            print_recent_logs(console, fallback_logs_dir)
        else:
            console.print(t_rich("service.logs.no_journalctl"))
    except KeyboardInterrupt:
        pass
