# ControlMesh v0.24.5

Compared to `v0.24.4`, this patch release fixes an OpenCode permission-mode
regression in headless chat runs and updates the public README so the homepage
matches the current product/runtime shape.

## Highlights

- The OpenCode adapter now maps ControlMesh `permission_mode=bypassPermissions`
  onto OpenCode's `--dangerously-skip-permissions` flag.
- Headless Telegram /model sessions using `opencode + zhipuai/glm-5.1` no
  longer auto-reject `external_directory` permission requests for common paths
  like `/root/.cache/{pip,uv,whisper}` and `/usr/local/bin/*` when the bot is
  configured to bypass permissions.
- Added regression coverage for the OpenCode permission-flag path.
- Refreshed the public root README so it now presents ControlMesh as a
  file-backed memory substrate plus first-class multi-agent runtime, and added
  the current product visual to the homepage.

## Upgrade Notes

- Release this version with tag `v0.24.5`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.5`.
- No config migration is required.
- Existing bots should be restarted after upgrade so the refreshed OpenCode
  permission handling is picked up by long-running services.

## Verification

- Targeted regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/cli/test_providers.py tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py`
- Full release pytest suite is expected as part of the formal release flow.
