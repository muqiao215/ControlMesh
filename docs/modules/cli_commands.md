# cli_commands/

CLI command implementation package extracted from `__main__.py`.

## Files

- `cli_commands/lifecycle.py`: `start_bot`, `stop_bot`, `cmd_restart`, `upgrade`, `uninstall`, `_re_exec_bot`
- `cli_commands/status.py`: `print_status`, `print_usage`
- `cli_commands/service.py`: `controlmesh service ...`
- `cli_commands/docker.py`: `controlmesh docker ...`
- `cli_commands/api_cmd.py`: `controlmesh api ...`
- `cli_commands/agents.py`: `controlmesh agents ...`
- `cli_commands/install.py`: `controlmesh install <extra>`

## Role in runtime

`controlmesh/__main__.py` is now a thin entrypoint:

- argument parsing + command dispatch
- config helpers (`_is_configured`, `load_config`, `run_bot`)
- imports/re-exports command handlers from `cli_commands/*`

This keeps lifecycle logic testable and prevents command monolith growth.

## Command groups

- lifecycle: `controlmesh`, `stop`, `restart`, `upgrade`, `uninstall`, onboarding/reset flow
- status/help: `controlmesh status`, `controlmesh help`
- service: install/status/start/stop/logs/uninstall wrapper for platform backends
- docker: enable/disable/rebuild/mount/unmount/mounts/extras/extras-add/extras-remove
- api: enable/disable direct WebSocket API block in config
- agents: list/add/remove sub-agent entries in `agents.json`
- install extras: `controlmesh install <extra>` for optional Python extras (`matrix`, `api`)

## Notable behavior details

- `stop_bot()` stops service first, then PID instance, then remaining controlmesh processes, then Docker container (if enabled).
- `start_bot()` calls `load_config()` and starts `AgentSupervisor` via `run_bot()`.
- `controlmesh agents add <name>` is an interactive Telegram-focused scaffold; Matrix sub-agents are configured via `agents.json` or the bundled agent tool scripts.
- `controlmesh restart` always runs `stop_bot()` and then re-execs the current process.
- exit code `42` is the in-app runtime/supervisor restart signal (`/restart`, service-managed restarts), not the behavior of the CLI `controlmesh restart` command.
- `status.py` currently counts errors from latest `controlmesh*.log`; runtime primary log file is `~/.controlmesh/logs/agent.log`.

## Why this matters for docs

When documenting CLI behavior, reference `cli_commands/*` for command internals.
Use `__main__.py` as the dispatch map, not as the implementation source.
