# ControlMesh v0.32.1

This patch release fixes the regressions that blocked `v0.32.0` from clearing CI and PyPI publish.

## Fixes

- Fixed `release_task.py` repo-root probing to ignore inaccessible candidate paths instead of crashing with `PermissionError` on CI hosts.
- Updated task-tool regression tests so repo-root resolution is validated with self-contained local fixtures instead of depending on `/root/.controlmesh/dev/*`.
- Added `create_task.py --prompt-file` so shell-unsafe prompts containing quotes, backticks, or parentheses can be passed without controller-side quoting bugs.
- Kept the Telegram raw-event-stream hardening and type-checking import cleanup aligned with CI expectations.

## Release intent

`v0.32.1` supersedes the failed `v0.32.0` publish attempt and is the version intended for install/upgrade.
