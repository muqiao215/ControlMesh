# ControlMesh v0.32.3

This patch release supersedes the failed `v0.32.2` attempt.

## Fixes

- Removed the remaining `TelegramMethod` type dependency from polling-heartbeat middleware annotations, fixing the last `ruff` blocker on `main`.
- Carries forward the `release_task.py` repo-root permission fix.
- Carries forward `create_task.py --prompt-file` for shell-unsafe prompts.

## Release intent

`v0.32.3` is the active patch release intended to replace `v0.32.0`, `v0.32.1`, and `v0.32.2`.
