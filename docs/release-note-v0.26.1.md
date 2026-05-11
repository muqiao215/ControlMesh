# ControlMesh v0.26.1

This is a fast follow-up release for a startup regression in `v0.26.0`.

## Fix

- Restored the missing `TaskHub._reconcile_loop()` implementation referenced by `TaskHub.start_maintenance()`.
- This prevents the bot supervisor from crashing immediately after startup on installations that picked up `v0.26.0`.

## Impact

- `v0.26.0` could reach transport startup and then crash the main runtime during maintenance-task initialization.
- `v0.26.1` is the safe upgrade target for hosts that have not yet been hot-patched locally.

## Upgrade Notes

- Release this version with tag `v0.26.1`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.26.1`.
- Hosts with a local hot patch in `controlmesh/tasks/hub.py` can upgrade to this release to return to a package-managed state.
