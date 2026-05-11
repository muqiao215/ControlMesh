# ControlMesh v0.26.3

This release makes `TOOL_RESULT.json` the canonical TaskHub result source.

## Fixes

- Switched TaskHub result authority from worker files to the runtime ledger.
  - `TOOL_RESULT.json` is now the first-class source for evaluation, reconcile, and controller-side consumption.
- Kept human-facing transport output as projection text only.
  - Telegram, Matrix, and Feishu delivery still render readable summaries and do not expose raw `tool_result` JSON.
- Preserved compatibility with older worker artifacts.
  - Legacy `EVIDENCE.json`, `RESULT.md`, and `TASKMEMORY.md` remain available as fallback input when canonical `TOOL_RESULT.json` is missing.
- Moved generated evidence projection under `generated/`.
  - Runtime-generated evidence now lands at `generated/EVIDENCE.json`.
- Started shifting failure taxonomy onto the canonical result lifecycle.
  - This release introduces `tool_result`-centric failure handling while keeping `artifact_protocol_failed` only for legacy fallback/degraded paths.

## Impact

- `RESULT.md` is no longer treated as the authority for task completion or recovery.
- Detached-task reconcile is now driven by `TOOL_RESULT.json` lifecycle state rather than by markdown artifact presence.
- This is the first controlled step toward full ledger-first task runtime semantics without forcing a worker-prompt rewrite.

## Upgrade Notes

- Release this version with tag `v0.26.3`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.26.3`.
- Verified locally with:
  - `uv run pytest tests/tasks/test_hub_runtime_events.py tests/tasks/test_evidence.py tests/tasks/test_hub.py tests/bus/test_adapters.py -q`
