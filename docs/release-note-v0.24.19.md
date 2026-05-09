# ControlMesh v0.24.19

Compared to `v0.24.18`, this patch release hardens runtime import provenance and foreground lifecycle isolation so that installed tool runtimes and background task processes are less likely to be disrupted by path skew or aggressive cleanup paths.

## Highlights

- Runtime import provenance is now hardened so that running ControlMesh from installed tooling is less likely to accidentally import stale source-tree code due to `PYTHONPATH`, working-directory, or path-based import drift.
- Foreground timeout/error/recovery paths now kill only the active `process_label` instead of `kill_all(chat_id)`, preventing background task CLIs running under the same `chat_id` from being terminated by a foreground timeout.
- Label-abort state is now consumed by `CLIService` and Gemini streaming paths, making label-scoped abort a real semantic abort path rather than only a physical process kill.

## Upgrade Notes

- Release this version with tag `v0.24.19`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.19`.
- Existing installs do not need config changes. Background task processes started before this upgrade are not affected.

## Verification

- Focused validation passed with `uv run pytest tests/infra/test_install.py tests/infra/test_service_linux.py tests/test_main.py -q` (113 passed).
- Focused validation passed with `uv run pytest tests/cli/test_process_registry.py tests/cli/test_service_extended.py tests/cli/test_gemini_provider.py tests/orchestrator/test_flows.py -q` (119 passed).
- Focused lint passed with `uv run ruff check controlmesh/cli/process_registry.py controlmesh/cli/service.py controlmesh/cli/gemini_provider.py controlmesh/orchestrator/flows.py tests/cli/test_process_registry.py tests/cli/test_service_extended.py tests/cli/test_gemini_provider.py tests/orchestrator/test_flows.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
