# ControlMesh v0.23.5

This hotfix turns `/cm` into a provider-neutral Native Commands entry and
restores ControlMesh command boundaries inside native menus.

## Fixes

- `/cm` now opens Native Commands for the current CLI provider instead of
  forcing Claude.
- ControlMesh registered commands win even while a native command menu is active,
  so `/model`, `/status`, and `/help` no longer get swallowed by Codex/Gemini/etc.
- Unknown `/xxx` commands still pass through to the active native CLI.
- Telegram and Feishu labels now say `Native Commands` instead of `Claude native`.

## Verification

- `uv run --extra lint ruff check .`
- Focused command routing regression tests
- `python -m compileall controlmesh tests`
