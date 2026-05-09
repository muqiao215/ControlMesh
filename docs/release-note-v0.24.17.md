# ControlMesh v0.24.17

Compared to `v0.24.16`, this patch release fixes an OpenCode provider visibility drift regression when ControlMesh service runtime environment injection did not match the user's `~/.controlmesh/.env` secret configuration.

## Highlights

- Linux systemd service installs now include `EnvironmentFile=-~/.controlmesh/.env`, so service-managed bot runtimes load ControlMesh secret environment values by default.
- OpenCode auth detection now reports a diagnostic when auth keys exist in `~/.controlmesh/.env` but are missing from the current process environment.
- `/model` now keeps installed-but-unauthenticated runtime providers visible in an auth-needed disabled state instead of hiding them.
- The model selector includes provider-specific hint text so users can distinguish a missing install from an auth/environment loading issue.

## Upgrade Notes

- Release this version with tag `v0.24.17`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.17`.
- Existing installs do not need config changes. Linux service installs or reinstalls will include the optional ControlMesh env file binding.
- If OpenCode appears as auth-needed after upgrade, verify that the relevant auth key is present in `~/.controlmesh/.env` and restart the service so systemd reloads the environment.

## Verification

- Focused validation passed with `uv run pytest tests/infra/test_service_linux.py tests/cli/test_auth.py tests/orchestrator/test_model_selector.py tests/orchestrator/test_providers.py -q`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
