# ControlMesh v0.27.0

This release upgrades TaskHub from canonical `TOOL_RESULT.json` storage to a usable main-agent consumption loop.

## Fixes

- Added runtime-owned agent inbox lifecycle buckets.
  - Background task results now flow through `pending`, `delivered_to_parent`, `consumed`, and `failed` inbox states instead of a flat append-only stream.
- Bound TaskHub result delivery to `tool_use_id`.
  - Canonical task results are now tracked per `tool_use_id`, which prevents duplicate re-enqueue and duplicate parent consumption during reconcile/recovery.
- Added explicit controller-consumption writeback.
  - `tool_result_created_at`, `tool_result_enqueued_at`, `tool_result_delivered_at`, and `tool_result_consumed_at` are now persisted in the task registry.
- Made detached-task reconcile repair missing inbox state.
  - If `TOOL_RESULT.json` exists but inbox state is missing, reconcile now re-enqueues the canonical result without rerunning the worker.
- Extended runtime lifecycle events for the message-ledger path.
  - TaskHub now records `tool_result_created`, `inbox_enqueued`, `delivered_to_parent`, and `consumed_by_parent` in the runtime event substrate.
- Tightened failure naming for the execution path.
  - Runtime-generated execution failures in this slice now use `tool_execution_failed`, leaving `artifact_protocol_failed` for degraded legacy artifact fallback.

## Impact

- `TOOL_RESULT.json` is no longer just the TaskHub authority; it now has a stable handoff path into the main agent inbox.
- A background task is now recoverable beyond execution completion: canonical result creation, inbox enqueue, delivery, and parent consumption are all independently observable.
- Transport remains projection-only.
  - Telegram, Matrix, and Feishu still render human text, not raw canonical JSON.

## Upgrade Notes

- Release this version with tag `v0.27.0`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.27.0`.
- Verified locally with:
  - `uv run pytest tests/runtime/test_store.py tests/tasks/test_hub_runtime_events.py tests/tasks/test_hub.py -q`
