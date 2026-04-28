# ControlMesh v0.24.2

Compared to `v0.24.1`, this patch release fixes the OpenCode model-selection
path so Telegram `/model` no longer drops users onto the wrong OpenCode model
or reuses an incompatible provider session immediately after switching.

## Highlights

- OpenCode runtime defaults now reuse the locally configured OpenCode model
  from `opencode.jsonc` instead of hardcoding the Telegram selector to
  `openai/gpt-4.1`.
- Telegram `/model` can now surface OpenCode defaults like
  `zhipuai/glm-5.1` when that is the real local runtime default.
- Switching from `codex` into runtime-backed providers such as `opencode`
  now resets the target provider-local session bucket, preventing the first
  follow-up message from hitting a stale cross-provider resume path and
  returning `Session Error`.

## Upgrade Notes

- Release this version with tag `v0.24.2`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.2`.
- No config migration is required, but existing bots should be restarted after
  upgrade so the refreshed runtime default model is picked up from the local
  OpenCode config.

## Verification

- Targeted regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/cli/test_auth.py tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py`
- Full release pytest suite is still expected as part of the formal release
  flow.
