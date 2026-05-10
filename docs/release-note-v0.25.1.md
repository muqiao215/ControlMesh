# ControlMesh v0.25.1

This patch release stabilizes upgrade behavior for PyPI and `uv tool` installs, and fixes service-managed restart handling so `/restart` and `/upgrade` reliably hand control back to the installed supervisor.

## Highlights

- `/restart` and `/upgrade` now explicitly request a service-level restart when ControlMesh is running under a service manager, instead of relying on an in-process restart marker path that could leave the managed runtime in a bad state.
- `/upgrade` now freezes a single `target_version` before execution. `/upgrade vX.Y.Z` uses that exact version, while `/upgrade` without a version resolves the latest release first and then upgrades to that pinned target.
- `uv tool` upgrades now use `uv tool install --force-reinstall --refresh controlmesh==<target_version>` so the installed tool environment is rebuilt against the requested version instead of floating through prior constraints.
- Upgrade verification now inspects a fresh subprocess after installation, rejects polluted source-import runtimes, and records both `requested_version` and `resolved_target_version` in upgrade output for auditability.

## Upgrade Notes

- Release this version with tag `v0.25.1`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.1`.
- For packaged installs, `/upgrade` no longer resolves a new latest version during retry. The resolved target is fixed at the start of the workflow.
- `uv tool` users should now see deterministic reinstall behavior against the pinned target version, with post-upgrade validation performed from a fresh interpreter process.
- Pushing tag `v0.25.1` should trigger the existing GitHub Actions `Publish to PyPI` workflow.

## Verification

- Focused upgrade regression coverage passes with `uv run pytest tests/infra/test_install.py tests/infra/test_updater.py -q`.
- Formal publishing should still push `main` first, then `v0.25.1`, then create the GitHub Release from the verified remote tag.
