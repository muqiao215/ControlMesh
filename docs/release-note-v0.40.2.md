# ControlMesh v0.40.2

This hotfix fixes Codex resumed-session command construction for current Codex CLI versions.

## Highlights

- Stops passing fresh-run-only `codex exec` flags such as `--color`, `--sandbox`, and `--full-auto` to `codex exec resume`.
- Keeps resume-compatible flags such as `--json`, `--model`, `-c`, `--image`, `--skip-git-repo-check`, and bypass mode.
- Filters custom Codex CLI parameters on resume so unsupported flags do not fail background task handoff or named-session follow-up.

## Verification

- `ruff check controlmesh/cli/codex_provider.py tests/cli/test_codex_provider.py`
- `pytest tests/cli/test_codex_provider.py`: 83 passed, 1 warning
- `pytest tests/test_cli_supervisor.py tests/test_cli_error_visibility.py tests/cli/test_executor_timeout.py tests/tasks/test_hub.py -q`: 88 passed

## Upgrade Notes

- Push tag `v0.40.2` to trigger the existing GitHub Actions `Publish to PyPI` workflow.
- GitHub Release creation remains gated on successful PyPI publication and PyPI visibility.
