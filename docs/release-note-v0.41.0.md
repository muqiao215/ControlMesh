# ControlMesh v0.41.0

## Highlights

- `controlmesh` now defaults to ControlMesh Enhanced Terminal in interactive TTYs.
- Added `controlmesh terminal` / `controlmesh term` explicit terminal commands.
- Added `controlmesh bot` for the legacy chat transport runtime.
- Added `/cm` native provider mode and `/back` return flow for the terminal.
- Added terminal inbox and explicit `/memory inject <hit-id>` handling.
- Added headless sub-agent stack support for terminal-managed agent orchestration.

## Compatibility

Existing subcommands keep their behavior:

- `controlmesh service ...`
- `controlmesh tasks ...`
- `controlmesh cron ...`
- `controlmesh agents ...`
- `controlmesh api ...`
- `controlmesh feishu ...`

Non-interactive `controlmesh` still follows the previous default action.
