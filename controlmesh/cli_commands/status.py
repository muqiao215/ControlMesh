"""Status display CLI commands (``controlmesh status``, ``controlmesh help``, `doctor`)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from controlmesh.cli.auth import check_all_auth
from controlmesh.i18n import t_rich
from controlmesh.infra.platform import is_windows
from controlmesh.provider_health import (
    FleetDoctorHostResult,
    apply_config_migrations,
    assess_bootstrap_health,
    load_bootstrap_health_snapshot,
    render_doctor_providers_text,
)
from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths

_console = Console()


@dataclass(slots=True)
class StatusSummary:
    """Runtime status inputs needed by the status panel renderer."""

    bot_running: bool
    bot_pid: int | None
    bot_uptime: str
    provider: str
    model: str
    docker_enabled: bool
    docker_name: str | None
    error_count: int


@dataclass(slots=True)
class FleetInventoryHost:
    """One host entry from fleet inventory."""

    id: str
    ssh_host: str
    enabled: bool = True
    role: tuple[str, ...] = ()
    environment: str = ""
    default_provider_profile: str = ""


def build_status_lines(status: StatusSummary, *, paths: ControlMeshPaths) -> list[str]:
    """Assemble the status panel content lines."""
    lines: list[str] = []
    if status.bot_running:
        lines.append(t_rich("status.running", pid=status.bot_pid, uptime=status.bot_uptime))
    else:
        lines.append(t_rich("status.not_running"))
    lines.append(t_rich("status.provider", provider=status.provider, model=status.model))
    if status.docker_enabled:
        lines.append(t_rich("status.docker_enabled", name=status.docker_name))
    else:
        lines.append(t_rich("status.docker_disabled"))
    if status.error_count > 0:
        lines.append(t_rich("status.errors_found", count=status.error_count))
    else:
        lines.append(t_rich("status.errors_none"))
    lines.append("")
    lines.append(t_rich("status.paths_header"))
    lines.append(f"  Home:       [cyan]{paths.controlmesh_home}[/cyan]")
    lines.append(f"  Config:     [cyan]{paths.config_path}[/cyan]")
    lines.append(f"  Workspace:  [cyan]{paths.workspace}[/cyan]")
    lines.append(f"  Logs:       [cyan]{paths.logs_dir}[/cyan]")
    lines.append(f"  Sessions:   [cyan]{paths.sessions_path}[/cyan]")
    snapshot = load_bootstrap_health_snapshot(paths.runtime_health_path)
    if snapshot:
        lines.append("")
        lines.append("Bootstrap health:")
        lines.append(f"  Status:     [cyan]{snapshot.get('status', 'unknown')}[/cyan]")
        lines.append(
            "  Runtime:    [cyan]"
            f"{snapshot.get('default_provider', '')} / {snapshot.get('default_model', '')}"
            "[/cyan]"
        )
        fallback_provider = snapshot.get("fallback_provider", "")
        fallback_model = snapshot.get("fallback_model", "")
        if fallback_provider and fallback_model:
            lines.append(f"  Fallback:   [cyan]{fallback_provider} / {fallback_model}[/cyan]")
        policy = snapshot.get("fallback_policy_summary", "")
        if isinstance(policy, str) and policy:
            lines.append(f"  Policy:     [cyan]{policy}[/cyan]")
    return lines


def count_log_errors(log_dir: Path) -> int:
    """Count ERROR entries in the most recent log file."""
    if not log_dir.is_dir():
        return 0
    log_files = sorted(
        log_dir.glob("controlmesh*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not log_files:
        return 0
    try:
        return log_files[0].read_text(encoding="utf-8", errors="replace").count(" ERROR ")
    except OSError:
        return 0


def print_status() -> None:
    """Print bot status, paths, and runtime info including sub-agents."""
    from controlmesh.cli_commands.agents import load_agents_registry, print_agents_status

    paths = resolve_paths()
    try:
        data: dict[str, object] = json.loads(
            paths.config_path.read_text(encoding="utf-8"),
        )
    except (json.JSONDecodeError, OSError):
        return

    provider = data.get("provider", "claude")
    model = data.get("model", "opus")
    docker_cfg = data.get("docker", {})
    docker_enabled = isinstance(docker_cfg, dict) and bool(docker_cfg.get("enabled"))
    docker_name: str | None = None
    if docker_enabled and isinstance(docker_cfg, dict):
        docker_name = str(docker_cfg.get("container_name", "controlmesh-sandbox"))

    # Running state
    pid_file = paths.controlmesh_home / "bot.pid"
    bot_running = False
    bot_pid: int | None = None
    bot_uptime = ""
    if pid_file.exists():
        try:
            bot_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            bot_pid = None
        if bot_pid is not None:
            from controlmesh.infra.pidlock import _is_process_alive

            bot_running = _is_process_alive(bot_pid)
            if bot_running:
                mtime = datetime.fromtimestamp(pid_file.stat().st_mtime, tz=UTC)
                delta = datetime.now(UTC) - mtime
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                bot_uptime = f"{hours}h {minutes}m"

    # Error count from latest log
    error_count = count_log_errors(paths.logs_dir)

    # Build status lines
    summary = StatusSummary(
        bot_running=bot_running,
        bot_pid=bot_pid,
        bot_uptime=bot_uptime,
        provider=str(provider),
        model=str(model),
        docker_enabled=docker_enabled,
        docker_name=str(docker_name) if docker_name else None,
        error_count=error_count,
    )
    lines = build_status_lines(summary, paths=paths)

    _console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Status — main[/bold]",
            border_style="green",
            padding=(1, 2),
        ),
    )

    # Show sub-agents
    agents = load_agents_registry(paths)
    if agents:
        print_agents_status(agents, bot_running=bot_running)


def cmd_doctor(args: Sequence[str]) -> None:
    """Handle `controlmesh doctor ...` surfaces."""
    command = next((arg for arg in args[1:] if not arg.startswith("-")), "")
    if command == "providers":
        tail = _command_tail(args, "providers")
        if tail and tail[0] == "fleet":
            print_fleet_provider_doctor(tail[1:])
            return
        print_provider_doctor()
        return
    _console.print("Usage:\n  controlmesh doctor providers\n  controlmesh doctor providers fleet\n  controlmesh doctor providers fleet --host HOST [--host HOST...]\n  controlmesh doctor providers fleet --hosts-file PATH")


def print_provider_doctor() -> None:
    """Print single-host provider/model/auth/bootstrap health."""
    from controlmesh.config import AgentConfig, ModelRegistry

    paths = resolve_paths()
    try:
        raw: dict[str, object] = json.loads(paths.config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _console.print("[red]Failed to read config for provider doctor.[/red]")
        return

    migrated, migration_events, _changed = apply_config_migrations(raw)
    config = AgentConfig.model_validate(migrated)
    registry = ModelRegistry()
    auth_results = check_all_auth()
    default_model = config.model
    default_provider = config.provider
    try:
        from controlmesh.orchestrator.providers import ProviderManager

        default_model, default_provider = ProviderManager(config).resolve_runtime_target(config.model)
    except ValueError:
        pass
    health = assess_bootstrap_health(
        configured_provider=config.provider,
        configured_model=config.model,
        default_provider=default_provider,
        default_model=default_model,
        auth_results=auth_results,
        model_provider_resolver=registry.provider_for,
        migration_events=migration_events,
    )
    _console.print(render_doctor_providers_text(health, auth_results))


def print_fleet_provider_doctor(args: Sequence[str]) -> None:
    """Run provider doctor across explicit hosts via SSH."""
    hosts = _parse_fleet_hosts(args)
    if not hosts:
        hosts = [item.ssh_host for item in _load_inventory_hosts(resolve_paths().fleet_hosts_path)]
    if not hosts:
        raise SystemExit("Provide at least one host via --host or --hosts-file.")

    results = [_run_fleet_provider_probe(host) for host in hosts]
    _console.print("Fleet provider doctor")
    for result in results:
        status = "ok" if result.ok else "failed"
        _console.print(f"\n[{result.host}] {status}")
        if result.output:
            _console.print(result.output.strip())
        if result.error:
            _console.print(result.error.strip())


def print_usage() -> None:
    """Print commands and smart status information."""
    from controlmesh.__main__ import _is_configured

    _console.print()
    banner_path = Path(__file__).resolve().parent.parent / "_banner.txt"
    try:
        banner_text = banner_path.read_text(encoding="utf-8").rstrip()
    except OSError:
        banner_text = "ControlMesh"
    _console.print(
        Panel(
            Text(banner_text, style="bold cyan"),
            subtitle=f"[dim]{t_rich('wizard.common.subtitle')}[/dim]",
            border_style="cyan",
            padding=(0, 2),
        ),
    )

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold green", min_width=24)
    table.add_column()
    table.add_row("controlmesh", t_rich("help.controlmesh"))
    table.add_row("controlmesh help", t_rich("help.help"))
    table.add_row("controlmesh status", t_rich("help.status"))
    table.add_row("controlmesh doctor providers", "Check provider/model compatibility, auth, and startup readiness.")
    table.add_row(
        "controlmesh doctor providers fleet",
        "Run the same provider doctor over explicit SSH hosts.",
    )
    table.add_row("controlmesh version", t_rich("help.version"))
    table.add_row("controlmesh onboarding", t_rich("help.onboarding"))
    table.add_row("controlmesh upgrade [version]", t_rich("help.upgrade"))
    table.add_row("controlmesh restart", t_rich("help.restart"))
    table.add_row("controlmesh stop", t_rich("help.stop"))
    table.add_row("controlmesh uninstall", t_rich("help.uninstall"))
    is_macos = sys.platform == "darwin"
    svc_hint = "Task Scheduler" if is_windows() else ("launchd" if is_macos else "systemd")
    table.add_row("controlmesh service install", t_rich("help.service_install", hint=svc_hint))
    table.add_row("controlmesh service", t_rich("help.service"))
    table.add_row("controlmesh tasks list", "List background tasks from the local task runtime.")
    table.add_row("controlmesh tasks doctor", "Show task runtime health, policy, and primitive endpoints.")
    table.add_row("controlmesh agents", t_rich("help.agents"))
    table.add_row("controlmesh docker", t_rich("help.docker"))
    table.add_row("controlmesh api", t_rich("help.api"))
    table.add_row(
        "controlmesh feishu native bootstrap",
        "Feishu-native product entrypoint for setup/bootstrap guidance.",
    )
    table.add_row("controlmesh install <extra>", t_rich("help.install"))
    table.add_row("--help / -h", t_rich("help.help_flag"))
    table.add_row("--version", t_rich("help.version_flag"))
    table.add_row("--verbose / -v", t_rich("help.verbose"))

    _console.print(
        Panel(table, title="[bold]Commands[/bold]", border_style="blue", padding=(1, 0)),
    )

    if _is_configured():
        print_status()
    else:
        _console.print(
            Panel(
                t_rich("status.not_configured"),
                title="[bold]Status[/bold]",
                border_style="yellow",
                padding=(1, 2),
            ),
        )
    _console.print()


def _command_tail(args: Sequence[str], token: str) -> list[str]:
    for idx, arg in enumerate(args):
        if arg == token:
            return list(args[idx + 1 :])
    return []


def _parse_fleet_hosts(args: Sequence[str]) -> list[str]:
    hosts: list[str] = []
    hosts_file = ""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--host" and index + 1 < len(args):
            hosts.append(args[index + 1].strip())
            index += 2
            continue
        if arg == "--hosts-file" and index + 1 < len(args):
            hosts_file = args[index + 1].strip()
            index += 2
            continue
        index += 1
    if hosts_file:
        file_hosts = [
            line.strip()
            for line in Path(hosts_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        hosts.extend(file_hosts)
    deduped: list[str] = []
    for host in hosts:
        if host and host not in deduped:
            deduped.append(host)
    return deduped


def _load_inventory_hosts(path: Path) -> list[FleetInventoryHost]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [
            FleetInventoryHost(id=str(item).strip(), ssh_host=str(item).strip())
            for item in data
            if str(item).strip()
        ]
    if isinstance(data, dict):
        raw_hosts = data.get("hosts", [])
        if isinstance(raw_hosts, list):
            parsed: list[FleetInventoryHost] = []
            for item in raw_hosts:
                if isinstance(item, str):
                    host = item.strip()
                    if host:
                        parsed.append(FleetInventoryHost(id=host, ssh_host=host))
                    continue
                if not isinstance(item, dict):
                    continue
                host_id = str(item.get("id", "")).strip()
                ssh_host = str(item.get("ssh_host") or item.get("host") or host_id).strip()
                if not ssh_host:
                    continue
                enabled = bool(item.get("enabled", True))
                if not enabled:
                    continue
                role = item.get("role", ())
                parsed.append(
                    FleetInventoryHost(
                        id=host_id or ssh_host,
                        ssh_host=ssh_host,
                        enabled=enabled,
                        role=tuple(str(value).strip() for value in role) if isinstance(role, list) else (),
                        environment=str(item.get("environment", "")).strip(),
                        default_provider_profile=str(item.get("default_provider_profile", "")).strip(),
                    )
                )
            return parsed
    return []


def _run_fleet_provider_probe(host: str) -> FleetDoctorHostResult:
    try:
        proc = subprocess.run(
            ["ssh", host, "controlmesh", "doctor", "providers"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FleetDoctorHostResult(host=host, ok=False, output="", error=str(exc))
    return FleetDoctorHostResult(
        host=host,
        ok=proc.returncode == 0,
        output=proc.stdout,
        error=proc.stderr,
    )
