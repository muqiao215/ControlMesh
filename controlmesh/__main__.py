"""Entry point: python -m controlmesh."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from rich.console import Console

# Re-exports from cli_commands — referenced by main() dispatch and by
# tests that patch controlmesh.__main__.<name>.
from controlmesh.cli_commands.agents import cmd_agents as _cmd_agents
from controlmesh.cli_commands.api_cmd import cmd_api as _cmd_api
from controlmesh.cli_commands.auth import cmd_auth as _cmd_auth
from controlmesh.cli_commands.docker import cmd_docker as _cmd_docker
from controlmesh.cli_commands.feishu import cmd_feishu as _cmd_feishu
from controlmesh.cli_commands.install import cmd_install as _cmd_install
from controlmesh.cli_commands.lifecycle import (
    cmd_restart as _cmd_restart,
)
from controlmesh.cli_commands.lifecycle import (
    start_bot as _start_bot,
)
from controlmesh.cli_commands.lifecycle import (
    stop_bot as _stop_bot,
)
from controlmesh.cli_commands.lifecycle import (
    uninstall as _uninstall,
)
from controlmesh.cli_commands.lifecycle import (
    upgrade as _upgrade,
)
from controlmesh.cli_commands.service import cmd_service as _cmd_service
from controlmesh.cli_commands.status import (
    print_status as _print_status,
)
from controlmesh.cli_commands.status import (
    print_usage as _print_usage,
)
from controlmesh.cli_commands.tasks import cmd_tasks as _cmd_tasks
from controlmesh.config import (
    DEFAULT_EMPTY_GEMINI_API_KEY,
    AgentConfig,
    deep_merge_config,
)
from controlmesh.i18n import t_rich
from controlmesh.infra.json_store import atomic_json_save
from controlmesh.infra.version import get_current_version
from controlmesh.workspace.init import init_workspace
from controlmesh.workspace.paths import resolve_paths

logger = logging.getLogger(__name__)

_console = Console()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _cmd_runtime(args: Sequence[str]) -> None:
    """Load the runtime ingress CLI only when the subcommand is invoked."""
    from controlmesh.cli_commands.runtime import cmd_runtime

    cmd_runtime(args)


def _is_configured() -> bool:
    """Check if bot has a valid configuration."""
    paths = resolve_paths()
    if not paths.config_path.exists():
        return False
    try:
        data = json.loads(paths.config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    transports = data.get("transports", [])
    if not transports:
        transports = [data.get("transport", "telegram")]
    for t in transports:
        checker = _IS_CONFIGURED_CHECKS.get(t, _is_configured_telegram)
        if not checker(data):
            return False
    return True


def _is_configured_telegram(data: dict[str, object]) -> bool:
    token = data.get("telegram_token", "")
    users = data.get("allowed_user_ids", [])
    return bool(token) and not str(token).startswith("YOUR_") and bool(users)


def _is_configured_matrix(data: dict[str, object]) -> bool:
    mx = data.get("matrix", {})
    if not isinstance(mx, dict):
        return False
    return bool(mx.get("homeserver")) and bool(mx.get("user_id"))


def _is_configured_feishu(data: dict[str, object]) -> bool:
    fs = data.get("feishu", {})
    if not isinstance(fs, dict):
        return False
    return (
        fs.get("mode", "bot_only") == "bot_only"
        and fs.get("brand", "feishu") == "feishu"
        and bool(fs.get("app_id"))
        and bool(fs.get("app_secret"))
    )


def _is_configured_weixin(data: dict[str, object]) -> bool:
    wx = data.get("weixin", {})
    if not isinstance(wx, dict):
        return False
    if wx.get("mode", "ilink") != "ilink":
        return False
    if not bool(wx.get("enabled", False)):
        return False

    raw_home = data.get("controlmesh_home") or os.environ.get(
        "CONTROLMESH_HOME",
        "~/.controlmesh",
    )
    controlmesh_home = Path(str(raw_home)).expanduser()
    relative_path = str(wx.get("credentials_path", "weixin_store/credentials.json"))
    from controlmesh.messenger.weixin.auth_store import WeixinCredentialStore

    return (
        WeixinCredentialStore(controlmesh_home, relative_path=relative_path).load_credentials()
        is not None
    )


def _qqbot_account_is_configured(raw: object) -> bool:
    if not isinstance(raw, dict):
        return False
    app_id = raw.get("app_id") or raw.get("appId") or ""
    client_secret = raw.get("client_secret") or raw.get("clientSecret") or ""
    client_secret_file = raw.get("client_secret_file") or raw.get("clientSecretFile") or ""
    return bool(app_id) and bool(client_secret or client_secret_file)


def _is_configured_qqbot(data: dict[str, object]) -> bool:
    qq = data.get("qqbot", {})
    if not isinstance(qq, dict):
        return False
    if _qqbot_account_is_configured(qq):
        return True
    accounts = qq.get("accounts", {})
    if not isinstance(accounts, dict):
        return False
    return any(_qqbot_account_is_configured(account) for account in accounts.values())


_IS_CONFIGURED_CHECKS: dict[str, Callable[[dict[str, object]], bool]] = {
    "telegram": _is_configured_telegram,
    "matrix": _is_configured_matrix,
    "feishu": _is_configured_feishu,
    "weixin": _is_configured_weixin,
    "qqbot": _is_configured_qqbot,
}


def load_config() -> AgentConfig:
    """Load, auto-create, and smart-merge the bot config.

    Resolution order:
    1. ``~/.controlmesh/config/config.json`` (canonical location)
    2. Copy from ``config.example.json`` in the framework root on first start
    3. Fall back to Pydantic defaults if example file is missing

    On every load the config is deep-merged with current Pydantic defaults
    so that new fields from framework updates are added without destroying
    user settings.
    """
    paths = resolve_paths()
    config_path = paths.config_path

    first_start = not config_path.exists()

    if first_start:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        example = paths.config_example_path
        if example.is_file():
            shutil.copy2(example, config_path)
            logger.info("Created config from config.example.json at %s", config_path)
        else:
            defaults = AgentConfig().model_dump(mode="json")
            defaults["gemini_api_key"] = DEFAULT_EMPTY_GEMINI_API_KEY
            defaults.pop("api", None)  # Beta: only written by `controlmesh api enable`
            atomic_json_save(config_path, defaults)
            logger.info("Created default config at %s", config_path)

    try:
        user_data: dict[str, object] = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to parse config at %s", config_path)
        sys.exit(1)

    normalized_existing = False
    if user_data.get("gemini_api_key") is None:
        user_data["gemini_api_key"] = DEFAULT_EMPTY_GEMINI_API_KEY
        normalized_existing = True

    defaults = AgentConfig().model_dump(mode="json")
    defaults["gemini_api_key"] = DEFAULT_EMPTY_GEMINI_API_KEY
    defaults.pop("api", None)  # Beta: only written by `controlmesh api enable`
    merged, changed = deep_merge_config(user_data, defaults)
    changed = changed or normalized_existing
    configured_home = user_data.get("controlmesh_home")
    default_home = defaults.get("controlmesh_home")
    env_selected_home = os.environ.get("CONTROLMESH_HOME")
    if not configured_home or (env_selected_home and configured_home == default_home):
        resolved_home = str(paths.controlmesh_home)
        if merged.get("controlmesh_home") != resolved_home:
            merged["controlmesh_home"] = resolved_home
            changed = True

    if changed:
        atomic_json_save(config_path, merged)
        logger.info("Extended config with new default fields")

    init_workspace(paths)
    return AgentConfig.model_validate(merged)


# ---------------------------------------------------------------------------
# Bot lifecycle
# ---------------------------------------------------------------------------


def _validate_transports(config: AgentConfig) -> None:
    """Run transport-specific config validators for all active transports."""
    for t in config.transports:
        validator = _TRANSPORT_VALIDATORS.get(t)
        if validator:
            validator(config)


async def run_bot(config: AgentConfig) -> int:
    """Validate config and run the bot via AgentSupervisor.

    The supervisor manages the main agent and dynamically created sub-agents
    from ``agents.json``.  If no sub-agents are defined, the supervisor runs
    only the main agent — behaviour is identical to the old single-bot path.

    Returns the exit code from the bot (``0`` = clean, ``42`` = restart requested).
    """
    paths = resolve_paths(controlmesh_home=config.controlmesh_home)
    _validate_transports(config)

    from controlmesh.infra.pidlock import acquire_lock, release_lock
    from controlmesh.multiagent.supervisor import AgentSupervisor

    acquire_lock(pid_file=paths.controlmesh_home / "bot.pid", kill_existing=True)

    supervisor = AgentSupervisor(config)
    exit_code = 0
    loop = asyncio.get_running_loop()
    current_task = asyncio.current_task()
    installed_signals: list[signal.Signals] = []

    def _request_shutdown() -> None:
        if current_task is not None and not current_task.done():
            current_task.cancel()

    if current_task is not None and sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except (NotImplementedError, RuntimeError, ValueError):
                continue
            installed_signals.append(sig)

    try:
        exit_code = await supervisor.start()
    except asyncio.CancelledError:
        logger.info("Termination signal received, shutting down gracefully...")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        for sig in installed_signals:
            loop.remove_signal_handler(sig)
        await supervisor.stop_all()
        release_lock(pid_file=paths.controlmesh_home / "bot.pid")
    return exit_code


# Backward-compat alias for external scripts that call run_telegram().
run_telegram = run_bot


def _validate_telegram_config(config: AgentConfig) -> None:
    """Validate Telegram transport requirements."""
    missing_token = not config.telegram_token or config.telegram_token.startswith("YOUR_")
    needs_users = not config.allowed_user_ids
    if missing_token or needs_users:
        _console.print(t_rich("config.incomplete"))
        sys.exit(1)


def _validate_matrix_config(config: AgentConfig) -> None:
    """Validate Matrix transport requirements."""
    m = config.matrix
    hint = t_rich("config.onboarding_hint")
    if not m.homeserver:
        _console.print(t_rich("config.matrix_no_homeserver", hint=hint))
        sys.exit(1)
    if not m.user_id:
        _console.print(t_rich("config.matrix_no_user", hint=hint))
        sys.exit(1)
    if not m.password and not m.access_token:
        _console.print(t_rich("config.matrix_no_auth", hint=hint))
        sys.exit(1)
    if not m.allowed_rooms and not m.allowed_users:
        _console.print(t_rich("config.matrix_no_target", hint=hint))
        sys.exit(1)


def _validate_feishu_config(config: AgentConfig) -> None:
    """Validate Feishu bot-only transport requirements."""
    fs = config.feishu
    if fs.mode != "bot_only":
        _console.print("Feishu cut 1 supports only feishu.mode='bot_only'.")
        sys.exit(1)
    if fs.brand != "feishu":
        _console.print("Feishu cut 1 supports only feishu.brand='feishu'.")
        sys.exit(1)
    if not fs.app_id:
        _console.print("Feishu transport requires an existing Feishu self-built app.")
        _console.print("Missing field: feishu.app_id.")
        _console.print("Run `controlmesh auth feishu setup` for zero-app onboarding guidance.")
        sys.exit(1)
    if not fs.app_secret:
        _console.print("Feishu transport requires an existing Feishu self-built app.")
        _console.print("Missing field: feishu.app_secret.")
        _console.print("Run `controlmesh auth feishu setup` for zero-app onboarding guidance.")
        sys.exit(1)


def _validate_weixin_config(config: AgentConfig) -> None:
    """Validate Weixin iLink transport requirements."""
    wx = config.weixin
    if wx.mode != "ilink":
        _console.print("Weixin cut 1 supports only weixin.mode='ilink'.")
        sys.exit(1)
    if not wx.enabled:
        _console.print("Weixin iLink transport is disabled by default; set weixin.enabled=true.")
        sys.exit(1)

    from controlmesh.messenger.weixin.auth_store import WeixinCredentialStore

    store = WeixinCredentialStore(config.controlmesh_home, relative_path=wx.credentials_path)
    if store.load_credentials() is None:
        _console.print(f"Weixin iLink transport requires stored QR credentials at {store.path}.")
        sys.exit(1)


def _validate_qqbot_config(config: AgentConfig) -> None:
    """Validate official QQ Bot transport requirements."""
    qq = config.qqbot
    selected = None
    selected_name = "default"
    if qq.default_account:
        selected = qq.accounts.get(qq.default_account)
        selected_name = qq.default_account
        if selected is None:
            _console.print(f"QQ Bot default_account {qq.default_account!r} was not found.")
            sys.exit(1)
    elif qq.app_id and (qq.client_secret or qq.client_secret_file):
        selected = qq
    else:
        for account_name, account in qq.accounts.items():
            if account.enabled and account.app_id and (account.client_secret or account.client_secret_file):
                selected = account
                selected_name = account_name
                break
    if selected is None:
        _console.print("QQ Bot transport requires at least one configured official bot account.")
        _console.print(
            "Set qqbot.app_id plus qqbot.client_secret/client_secret_file, or define a valid qqbot.accounts entry."
        )
        sys.exit(1)
    if not selected.app_id or not (selected.client_secret or selected.client_secret_file):
        _console.print(f"QQ Bot account {selected_name!r} is incomplete.")
        sys.exit(1)
    if selected.client_secret_file:
        secret_path = Path(selected.client_secret_file)
        if not secret_path.is_absolute():
            secret_path = Path(config.controlmesh_home).expanduser() / secret_path
        if not secret_path.exists():
            _console.print(
                f"QQ Bot account {selected_name!r} references missing client_secret_file: {secret_path}"
            )
            sys.exit(1)


_TRANSPORT_VALIDATORS: dict[str, Callable[[AgentConfig], None]] = {
    "telegram": _validate_telegram_config,
    "matrix": _validate_matrix_config,
    "feishu": _validate_feishu_config,
    "weixin": _validate_weixin_config,
    "qqbot": _validate_qqbot_config,
}


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------


def _cmd_status() -> None:
    """Show bot status or hint to configure."""
    from rich.panel import Panel

    _console.print()
    if _is_configured():
        _print_status()
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


def _cmd_setup(verbose: bool) -> None:
    """Run onboarding (with smart reset if already configured), then start."""
    from controlmesh.cli.init_wizard import run_onboarding, run_smart_reset

    _stop_bot()
    paths = resolve_paths()
    if _is_configured():
        run_smart_reset(paths.controlmesh_home)
    service_installed = run_onboarding()
    if service_installed:
        return
    _start_bot(verbose)


def _default_action(verbose: bool) -> None:
    """Auto-onboarding if unconfigured, then start bot."""
    if not _is_configured():
        from controlmesh.cli.init_wizard import run_onboarding

        service_installed = run_onboarding()
        if service_installed:
            return
    _start_bot(verbose)


def _print_version() -> None:
    """Print the installed ControlMesh version."""
    _console.print(get_current_version())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMANDS: dict[str, str] = {
    "help": "help",
    "status": "status",
    "stop": "stop",
    "restart": "restart",
    "upgrade": "upgrade",
    "uninstall": "uninstall",
    "onboarding": "setup",
    "reset": "setup",
    "service": "service",
    "docker": "docker",
    "api": "api",
    "agents": "agents",
    "install": "install",
    "auth": "auth",
    "runtime": "runtime",
    "tasks": "tasks",
    "feishu": "feishu",
    "qq": "qq",
}

_Action = Callable[[], None]


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]
    commands = [a for a in args if not a.startswith("-")]
    verbose = "--verbose" in args
    show_version = "--version" in args or ("-v" in args and not commands and not verbose)

    if "--help" in args or "-h" in args:
        commands.append("help")

    if show_version:
        _print_version()
        return

    # Resolve first matching command
    action = next((_COMMANDS[c] for c in commands if c in _COMMANDS), None)

    dispatch: dict[str, _Action] = {
        "help": _print_usage,
        "status": _cmd_status,
        "stop": _stop_bot,
        "restart": _cmd_restart,
        "upgrade": _upgrade,
        "uninstall": _uninstall,
        "setup": lambda: _cmd_setup(verbose),
        "service": lambda: _cmd_service(args),
        "docker": lambda: _cmd_docker(args),
        "api": lambda: _cmd_api(args),
        "agents": lambda: _cmd_agents(args),
        "install": lambda: _cmd_install(args),
        "auth": lambda: _cmd_auth(args),
        "runtime": lambda: _cmd_runtime(args),
        "tasks": lambda: _cmd_tasks(args),
        "feishu": lambda: _cmd_feishu(args),
    }

    handler = dispatch.get(action) if action else None
    if handler is not None:
        handler()
    else:
        _default_action(verbose)


if __name__ == "__main__":
    main()
