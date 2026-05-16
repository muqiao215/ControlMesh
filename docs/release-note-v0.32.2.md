# ControlMesh v0.32.2

This patch release supersedes the failed `v0.32.1` attempt.

## Fixes

- Removed the unused `TelegramMethod` import that kept `main` red under Ruff.
- Carries forward the `v0.32.1` repo-root permission fix for `release_task.py`.
- Keeps the `create_task.py --prompt-file` addition for shell-unsafe prompts.

## Release intent

`v0.32.2` is the patch version intended to replace both failed publish attempts: `v0.32.0` and `v0.32.1`.
