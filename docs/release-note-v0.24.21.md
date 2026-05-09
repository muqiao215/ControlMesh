# ControlMesh v0.24.21

Compared to `v0.24.20`, this patch release fixes two runtime compatibility issues that caused startup or session-resume failures on specific host configurations.

## Highlights

- Claude provider now detects root/EUID==0 at build time and silently falls back from `bypassPermissions` to `default` rather than letting the `claude` CLI reject the combination at startup with a hard error.
- Codex `exec resume` no longer injects `--sandbox` or `--dangerously-bypass-approvals-and-sandbox` flags, since Codex CLI 0.128.0 does not support `--sandbox` on the `exec resume` subcommand (only on `exec`). This fixes session resume failures with `unexpected argument '--sandbox' found`.
- Regression coverage now locks both behaviors.

## Upgrade Notes

- Release this version with tag `v0.24.21`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.21`.
- Existing installs do not need config changes. Under root-hosted ControlMesh, Claude provider will now use `default` permission mode silently instead of hard-failing. Codex resume works on Codex CLI 0.128.0 hosts.

## Verification

- Focused validation passed with `uv run pytest tests/cli/test_codex_provider.py tests/cli/test_claude_provider.py tests/cli/test_providers.py -q` (167 passed).
- Focused lint passed with `uv run ruff check controlmesh/cli/codex_provider.py controlmesh/cli/claude_provider.py tests/cli/test_codex_provider.py tests/cli/test_claude_provider.py tests/cli/test_providers.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.