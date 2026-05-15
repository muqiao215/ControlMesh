# ControlMesh v0.31.3

This patch release finishes the public release handoff for the recent release-monitor and messenger work, while cleaning up one persistent operator pain point in the task list.

## Highlights

- Hardened the Feishu preview progress reporter.
  - `FeishuCardPreviewReporter` now tolerates agent-event reporting paths without crashing on missing `on_agent_event` handling.
  - This closes a runtime regression that could break Feishu-side progress preview updates during multi-agent work.
- Clarified `feishu-auth-kit` as a first-party ControlMesh module.
  - ControlMesh docs and module references now state that the extracted `feishu-auth-kit` repository is part of the same first-party Feishu runtime surface.
  - This makes the plugin story explicit without pretending it is a third-party integration detached from ControlMesh.
- Cleaned the release monitor template for public release gating.
  - The tracked template source used by release monitor cron setup no longer exposes an internal `AGENTS.md` artifact to the public release gate.
  - Release monitor template readers now consume a dedicated rules template file instead.
- Hid stale fake-waiting tasks from the active waiting list.
  - Historical residue with `waiting` status but completed timestamps no longer shows up under `Waiting for answer`.
  - True `waiting_for_parent_input` cases still remain actionable and visible.

## Why v0.31.3 exists

`v0.31.2` finished the release-monitor handoff shape, but the surrounding operator surface still had three rough edges:

1. a Feishu reporter regression could break message-side progress updates
2. the release monitor template still looked like an internal artifact to the public release gate
3. stale historical waiting tasks cluttered the active waiting view and made real blocked work harder to see

`v0.31.3` is a narrow patch to close those gaps without changing the release-monitor architecture again.

## Impact

- Feishu progress preview is safer in live multi-agent runs.
- The first-party ownership of `feishu-auth-kit` is documented clearly in ControlMesh.
- Public release gating no longer trips on the release monitor template source layout.
- Operators see fewer false waiting tasks in the foreground status surface.

## Verification

- `uv run --python 3.12 pytest tests/messenger/feishu tests/orchestrator tests/test_main.py -q -k 'feishu or plugin or progress_preview or on_agent_event'`
- `uv run pytest tests/orchestrator/test_task_selector.py tests/tasks/test_hub.py -q -k 'waiting or task_selector or resume_from_waiting or forward_question'`
- `uv run --python 3.12 pytest tests/messenger/feishu tests/multiagent tests/orchestrator -q -k 'feishu or reporter or on_agent_event'`

## Upgrade Notes

- `v0.31.3` is already aligned in `pyproject.toml` and `controlmesh/__init__.py`.
- PyPI publication for `0.31.3` is complete; the remaining public-release step is the GitHub Release creation/update for tag `v0.31.3`.
