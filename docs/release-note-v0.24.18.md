# ControlMesh v0.24.18

Compared to `v0.24.17`, this patch release makes foreground turns less likely to be interrupted during long quiet work phases such as compiles, downloads, and waits.

## Highlights

- The foreground idle watchdog now waits 300 seconds before treating a quiet turn as idle instead of the previous 90-second threshold.
- The foreground max-runtime backstop now follows the configured `timeouts.normal` budget instead of using a hardcoded 600-second cap.
- Timeout messages now report the actual triggering budget, distinguishing idle watchdog timeouts from max-runtime backstop timeouts.
- Targeted regression coverage verifies custom normal timeout handling and foreground timeout reporting behavior.

## Upgrade Notes

- Release this version with tag `v0.24.18`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.24.18`.
- Existing installs do not need config changes. Deployments that already use a larger `timeouts.normal` value will now have foreground turns honor that runtime budget.

## Verification

- Focused validation passed with `uv run pytest tests/orchestrator/test_flows.py -q`.
- Focused lint passed with `uv run ruff check controlmesh/orchestrator/flows.py tests/orchestrator/test_flows.py`.
- Formal publishing should still run the repository release script, package build validation, and remote tag verification before creating the GitHub Release.
