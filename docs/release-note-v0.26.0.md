# ControlMesh v0.26.0

This release is a stability-focused runtime upgrade. It hardens detached task execution and recovery, tightens provider/model validation so invalid background runs fail before execution, and makes workspace skill sync resilient to symlink loop and broken-link states.

## Highlights

- TaskHub and Telegram frontstage execution are more durable: duplicate task submissions attach instead of rerunning, `/continue` now splits cleanly into attach vs resume semantics, and detached task recovery closes the `detached -> stale -> recovering -> done/failed` loop from durable artifacts.
- Telegram frontstage message handling now queues provider work per session instead of keeping the transport handler blocked on long-running execution.
- Explicit provider/model bindings now fail fast for incompatible combinations, including background task paths. A `provider=codex` task can no longer silently launch with an OpenCode-style model such as `zhipuai/glm-5.1`.
- Workspace skill sync and its repair tooling now treat broken and looping symlinks as recoverable garbage state instead of crashing sync/cleanup/doctor flows.

## Scope Notes

- This release improves runtime stability and validation inside ControlMesh itself.
- It does **not** claim that host-managed private-sync topology has already been migrated. Canonical skill-target governance still needs to be finalized separately at the managed configuration layer.

## Upgrade Notes

- Release this version with tag `v0.26.0`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.26.0`.
- Full regression coverage for this release is expected to come from GitHub Actions after tag push rather than local long-running foreground test execution.
