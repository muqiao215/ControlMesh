# ControlMesh v0.24.20

Compared to `v0.24.19`, this patch release hardens OpenCode runtime detection and model discovery so that the active provider can be inferred reliably and users are presented with an accurate model list.

## Highlights

- OpenCode default-model resolution no longer falls back to the misleading hardcoded `openai/gpt-4.1` when no runtime default is actually known.
- `/model` for OpenCode now performs live model discovery using the real opencode CLI surface and presents a real model list instead of a single synthetic default button.
- OpenCode runtime detection and auth parsing are hardened to understand the official newer config/auth layout, including runtime blocks and multi-provider configs, so the active provider can be inferred more reliably.

## Upgrade Notes

- Release this version with tag `v0.24.20`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.20`.
- Existing installs do not need config changes. OpenCode users will now see an accurate live model list instead of a synthetic fallback.

## Verification

- Focused validation passed with `uv run pytest tests/cli/test_auth.py tests/cli/test_opencode_discovery.py tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py -q` (143 passed).
- Focused lint passed with `uv run ruff check controlmesh/cli/auth.py controlmesh/cli/opencode_discovery.py controlmesh/orchestrator/providers.py controlmesh/orchestrator/selectors/model_selector.py tests/cli/test_auth.py tests/cli/test_opencode_discovery.py tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.