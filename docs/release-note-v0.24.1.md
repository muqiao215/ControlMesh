# ControlMesh v0.24.1

Compared to `v0.24.0`, this patch release fixes a Codex model-menu regression
that could hide `gpt-5.5` from Telegram's `/model` selector even after the
runtime had already adopted `gpt-5.5` as the intended fallback baseline.

## Highlights

- Fixed Codex model cache behavior so older non-empty 5.x discovery catalogs no
  longer suppress the built-in baseline entries used by the productized model
  selector.
- Restored `gpt-5.5` visibility in Telegram `/model` menus when a stale
  `codex_models.json` still reports older 5.x models like `gpt-5.3-codex` and
  `gpt-5.4`.
- Added a regression test covering the exact stale-cache shape that previously
  left `/model` stuck on the older menu.

## Upgrade Notes

- Release this version with tag `v0.24.1`; `pyproject.toml` and
  `controlmesh/__init__.py` are aligned to `0.24.1`.
- Existing deployments do not need config changes. After upgrade/restart, the
  Codex cache will refresh and the Telegram model selector should expose the
  restored `gpt-5.5` baseline.

## Verification

- Targeted regression coverage:
  `uv run --python 3.12 --extra dev pytest -q tests/cli/test_codex_cache.py tests/orchestrator/test_model_selector.py`
- Full release pytest suite is still expected as part of the formal release
  flow.
