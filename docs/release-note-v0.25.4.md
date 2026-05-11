# ControlMesh v0.25.4

This patch release fixes an issue where `controlmesh version` was not a recognized subcommand and could fall through to default runtime startup, accidentally launching the bot and stealing the PID lock.

## Highlights

- `controlmesh version` and `controlmesh --version` are now properly recognized CLI subcommands that print the version and exit immediately.
- `--help` and `-h` flags are now explicitly mapped to the help action in the command dispatch table.
- Help surface cleanup for both CLI (`controlmesh help`) and Telegram bot `/help` - commands are now grouped into logical categories (start-here, daily controls, advanced).

## Upgrade Notes

- Release this version with tag `v0.25.4`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.4`.
- Running `controlmesh version` will no longer accidentally start the bot process.
- Pushing tag `v0.25.4` should trigger the existing GitHub Actions `Publish to PyPI` workflow.

## Verification

- Focused dispatch regression coverage passes with `uv run pytest tests/test_main.py -q`.
- CLI smoke tests pass: `controlmesh version`, `controlmesh --version`, `controlmesh --help` all exit cleanly without starting the bot.
