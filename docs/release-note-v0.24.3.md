# ControlMesh v0.24.3

Compared to `v0.24.2`, this patch release fixes OpenCode CLI compatibility on
hosts running `opencode 1.14.24`, where ControlMesh's machine-readable
invocation path was still passing a removed `--quiet` flag.

## Highlights

- `OpenCodeCLI` now uses `opencode run --format json` without `--quiet`, which
  matches the current OpenCode CLI surface on qiaobird-class hosts.
- Telegram and other ControlMesh OpenCode entrypoints can now reach configured
  models such as `zhipuai/glm-5.1` again instead of failing immediately with
  OpenCode help output.
- Added regression coverage to lock the OpenCode command shape so future
  releases do not reintroduce the removed flag.

## Upgrade Notes

- Release this version with tag `v0.24.3`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.3`.
- No config migration is required.
- Existing bots should be restarted after upgrade so the refreshed OpenCode
  adapter is picked up by long-running services.

## Verification

- Targeted regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/cli/test_providers.py tests/cli/test_auth.py tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py tests/orchestrator/test_core.py`
- Full release pytest suite is expected as part of the formal release flow.
