# ControlMesh v0.31.1

This patch release tightens three operator-facing edges that remained after `v0.31.0`: runtime startup repair for stale provider/model bindings, release-approval prompt routing for ordinary follow-up messages, and a dedicated monitor cron entry for bounded release/CI wait windows.

## Highlights

- ControlMesh now repairs stale persisted provider/model bindings during startup.
  - If an installed runtime still carries an old invalid pair such as `provider=codex` with a non-Codex model target, startup can recover to the configured runtime target instead of remaining wedged.
  - `/model` repair is no longer blocked just because the model text string happens to match the stale persisted value.
- Ordinary follow-up messages no longer get mistaken for release approval commands.
  - Short replies such as `继续`, `可以`, `ok`, or `同意` are only treated as release approval guidance when ControlMesh is actually waiting on a pending release host-job approval gate.
  - Explicit `approve <step_id> <target>` handling remains unchanged.
- Release and CI waiting now has a dedicated monitor cron entry.
  - `cron_monitor.py` is the primary entry for short-lived release/CI monitors.
  - Monitor jobs default to TaskHub-backed execution with summarized terminal handoff back into the main conversation, instead of relying on foreground watch loops.

## Why v0.31.1 exists

`v0.31.0` finished the assistant-slot TaskHub execution boundary and improved release approval stability, but three operational follow-ups remained:

1. some installed runtimes could still persist an invalid provider/model binding across upgrades and fail to self-heal cleanly
2. the broad release-approval prompt guard was still too text-driven, so a normal message like `继续` could be intercepted outside a real approval gate
3. release waiting had a viable cron-based pattern, but the product surface still treated monitor creation too much like a generic recurring cron job

`v0.31.1` closes those gaps without changing the main runtime model.

## Impact

- Installed runtimes recover more reliably after old provider/model state drifts out of validity.
- Release approval prompts are narrower and better scoped to real waiting states.
- Monitor-style cron jobs now have a distinct entry and clearer semantics:
  - recurring cron for stable schedule-driven automation
  - monitor cron for bounded release/CI wait windows with TaskHub terminal handoff

## Verification

- `uv run pytest tests/test_main.py tests/orchestrator/test_model_selector.py -q`
- `uv run pytest tests/test_integration.py tests/multiagent/test_release_gate.py tests/multiagent/test_plan_review_loop.py -q`
- `uv run pytest tests/cron/test_cron_add_tool.py tests/cron/test_cron_monitor_tool.py tests/cli/test_cron_cli.py tests/orchestrator/test_commands.py -q`
- `uv run pytest tests/cron/test_observer.py tests/cron/test_manager_schema.py -q -k 'taskhub or execution_mode or monitor'`

## Upgrade Notes

- Release this version with tag `v0.31.1`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.31.1`.
- Public publishing should continue through the GitHub Actions `Publish to PyPI` workflow triggered by pushing `v0.31.1`.
- GitHub Release should continue to be created or updated only after PyPI publish succeeds and the artifact is visible.
