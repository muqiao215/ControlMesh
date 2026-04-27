# ControlMesh v0.23.4

This UX hotfix removes `/mode` from the user-facing command surface.

## Fixes

- Removed `/mode` from Telegram command registration, help text, Feishu command
  cards, and the ControlMesh slash command registry.
- Removed `/claude_native` as a public command path.
- Made `/cm` the only entry point for Claude native commands.
- Made `/back` the return path to the ControlMesh command menu.
- Kept `/model` focused on model/provider selection only.
- Replaced user-facing `takeover mode` wording with `Current menu`.

## Verification

- `uv run --extra lint ruff check .`
- Focused command-menu regression suite
- `python -m compileall controlmesh tests`
