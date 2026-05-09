# ControlMesh v0.24.25

Compared to `v0.24.24`, this patch release hardens runtime-backed provider resolution so ControlMesh resolves real runtime models before execution and fails fast when a runtime provider target is incomplete.

## Highlights

- Runtime-backed providers now follow a unified target-resolution order: explicit submitted model first, route capability model next, live runtime discovery after that, and static fallback only as a last resort.
- OpenCode no longer drifts into a synthetic or empty default target when the submitted task or route omits a model. ControlMesh now reads the live OpenCode provider and discovers valid models from the real `opencode models` surface before execution.
- Background tasks no longer silently run for an hour with `provider=opencode` and no valid model. When ControlMesh cannot resolve a usable runtime target, it now fails immediately with explicit diagnostics such as `error:opencode_default_model_unresolved`.
- Named background sessions and foreground provider overrides now use the same runtime-backed resolution path, reducing drift between `/model`, task routing, and direct provider targeting.

## Upgrade Notes

- Release this version with tag `v0.24.25`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.25`.
- No config migration is required, but hosts routing background work to runtime-backed providers should now receive earlier and clearer failures when route definitions omit a required model.

## Verification

- Focused validation should pass with `uv run pytest tests/cli/test_opencode_discovery.py tests/cli/test_service_extended.py tests/tasks/test_hub.py tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py -q`.
- Focused lint should pass with `uv run ruff check controlmesh/cli/opencode_discovery.py controlmesh/cli/service.py controlmesh/orchestrator/core.py controlmesh/orchestrator/flows.py controlmesh/orchestrator/providers.py controlmesh/tasks/hub.py tests/cli/test_opencode_discovery.py tests/cli/test_service_extended.py tests/orchestrator/test_providers.py tests/tasks/test_hub.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
