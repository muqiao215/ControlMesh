# ControlMesh v0.31.2

This patch release closes the remaining gap in the release waiting path: release-phase CI and PyPI publish waits now hand off to a dedicated 30-second monitor cron backed by TaskHub, instead of relying on foreground watch loops or ad hoc manual chaining.

## Highlights

- Release waiting now arms a dedicated monitor cron before guarded side-effect steps.
  - Before `push_tag`, ControlMesh now creates a short-lived `CI` monitor.
  - Before `gh_release_create`, ControlMesh now creates a short-lived `Publish to PyPI` monitor.
- Monitor waits are explicit controller state, not implicit foreground polling.
  - `/mesh status` now shows release monitor status, target workflow, cadence, and related release step.
  - Pending release approval prompts no longer surface those later release steps before the monitor has actually succeeded.
- Monitor completion now returns control back to the main conversation with the exact next release command.
  - Successful monitor handoff returns the next `approve <step_id> <target>`.
  - Failed monitor handoff keeps the release blocked and returns concise failure guidance.
- Monitor cron submissions now auto-disable after the first TaskHub handoff.
  - This keeps the monitor bounded and prevents repeated re-submission every 30 seconds after it has already started its one monitoring task.

## Why v0.31.2 exists

`v0.31.1` introduced the monitor cron surface, but the release controller still did not fully wire release waiting through it. In practice, that meant the product had the right primitive but not the finished release-phase behavior:

1. release gate steps could still depend on foreground/manual monitoring
2. monitor results were not yet the canonical handoff back into the main release conversation
3. monitor jobs needed one-shot disable semantics after TaskHub submit to stay bounded

`v0.31.2` finishes that wiring without expanding TaskHub scope or adding a new release scheduler.

## Impact

- Release-phase waiting is now productized around:
  - a bounded monitor cron
  - TaskHub background execution
  - terminal result handoff back to the foreground controller
- Foreground release flow no longer has to actively watch CI/PyPI to keep moving.
- Release approval guidance is better scoped to the current real gate, instead of exposing downstream approval steps too early.

## Verification

- `uv run pytest tests/multiagent/test_plan_review_loop.py tests/cron/test_observer.py -q`
- `uv run pytest tests/multiagent/test_plan_review_loop.py tests/multiagent/test_release_gate.py tests/cron/test_observer.py tests/cron/test_cron_monitor_tool.py tests/orchestrator/test_commands.py -q`
- `uv run ruff check controlmesh/multiagent/plan_review_loop.py tests/multiagent/test_plan_review_loop.py tests/cron/test_observer.py controlmesh/cron/observer.py`

## Upgrade Notes

- Release this version with tag `v0.31.2`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.31.2`.
- Public publishing should continue through the GitHub Actions `Publish to PyPI` workflow triggered by pushing `v0.31.2`.
- GitHub Release should continue to be created or updated only after PyPI publish succeeds and the artifact is visible.
