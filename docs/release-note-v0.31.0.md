# ControlMesh v0.31.0

This release finishes the TaskHub assistant-slot execution boundary and hardens the operator surfaces around release approval prompts and interrupt discoverability.

## Highlights

- TaskHub background execution remains assistant-slot based.
  - Background tasks resolve to executable assistant slots such as `codex_default`, `opencode_default`, `claude_default`, and `gemini_default`.
  - Raw provider/model tokens still do not act as TaskHub runner authority.
- Release approval prompt handling is hardened.
  - Approval helper text no longer assumes every host-job runner exposes the same inspection surface.
  - Missing optional runner methods now degrade safely instead of crashing the foreground message path.
- `/interrupt` is surfaced earlier and more consistently.
  - Telegram popup command ordering now places `/interrupt` near the front.
  - Telegram queued-message indicators now tell the user they can use `/interrupt`.
  - Feishu command guidance and shared ControlMesh command summaries now include `/interrupt`.

## Why v0.31.0 exists

`v0.30.0` fixed the core TaskHub boundary:

1. ControlMesh should not treat raw `provider/model` as background execution authority
2. background execution should bind to real assistant commands through slots
3. native model/provider/gateway/auth ownership belongs to each assistant CLI

After that release line, two operational follow-ups remained important enough for a new minor line:

1. one runtime crash path still existed in release approval helper code on some installed hosts
2. `/interrupt` was implemented correctly but not discoverable enough in active chat surfaces

`v0.31.0` closes those gaps.

## Impact

- ControlMesh still does not act as a model/provider registry for TaskHub execution.
- Foreground message handling is more resilient when optional host-job runner capabilities are absent.
- Interrupt controls are easier to discover before users reach destructive stop/cancel paths.
- Shared help surfaces now better match the intended operator workflow:
  - interrupt current work
  - keep the queue when appropriate
  - use stronger stop/cancel controls only when needed

## Verification

- `uv run pytest tests/multiagent/test_plan_review_loop.py -q -k 'pending_release_approval_text or approve_phase or release_publish_phase'`
- `uv run pytest tests/messenger/test_commands.py tests/messenger/telegram/test_middleware.py tests/messenger/telegram/test_app.py tests/messenger/feishu/test_bot.py tests/orchestrator/test_commands.py -q -k 'controlmesh_registry_mentions_interrupt or cmd_controlmesh or help or tasks_new or session_prompt_runs_foreground_without_taskhub'`

## Upgrade Notes

- Release this version with tag `v0.31.0`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.31.0`.
- Public publishing should continue through the GitHub Actions `Publish to PyPI` workflow triggered by pushing `v0.31.0`.
- GitHub Release should continue to be created or updated only after PyPI publish succeeds and the artifact is visible.
