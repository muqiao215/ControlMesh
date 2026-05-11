# ControlMesh v0.28.0

This release changes `/mesh` from a background-planning entrypoint into a bounded autonomous execution handoff owned by the foreground agent.

## Fixes

- Moved `plan_with_files` planning back to the foreground control path.
  - `/mesh` no longer submits planning as a TaskHub background workunit.
  - The foreground now writes the executable plan and only phase execution enters TaskHub.
- Added lightweight persisted foreground handoff state.
  - Frontstage sessions now keep `active_intent`, `active_repo`, and `active_constraints`.
  - `/mesh` reads that state directly instead of guessing the task by replaying foreground history.
- Tightened `/mesh` handoff semantics.
  - `/mesh <prompt>` updates the current active intent and starts bounded auto-run.
  - Bare `/mesh` or handoff text like “开始全自动” now asks for one-line clarification only when no active intent exists.
  - High-friction requirement questionnaires are removed from the normal path.
- Standardized bounded-auto planning output.
  - Foreground planning now enforces explicit phases.
  - Mesh plans are capped at five phases.
  - Default boundaries deny `git push`, release/publish, production operations, and other external high-side-effect actions.
- Improved user-facing startup feedback.
  - `/mesh` now reports the accepted objective, repo/boundary context, plan readiness, and phase-1 execution state instead of saying planning is running in background.
- Kept `/agents run ...` as a compatibility shim on top of the new foreground-planned `/mesh` flow.
- Reclassified normalized worker artifacts as success-with-warning instead of task failure.
  - Runtime artifact normalization no longer surfaces to users as `failed` when a consumable result exists.
  - Frontstage delivery now renders this path as completed-with-warnings.
- Added runtime canonical TOOL_RESULT backfill for reconciled and legacy task artifacts.
  - If a worker only leaves `RESULT.md` / legacy evidence and runtime can still recover a consumable result, TaskHub now generates canonical `TOOL_RESULT.json`.
  - Reconcile and inbox consumption paths now stay centered on one canonical result format.

## Impact

- `/mesh` now behaves like an execution-mode switch, not a requirement compiler.
- The foreground agent becomes the source of truth for current task handoff state.
- TaskHub remains responsible for execution/review/repair phases, not for initial task understanding.
- Background task execution success is now separated from artifact-protocol compliance.
- Legacy artifact recovery degrades to warnings when runtime can produce a canonical result, and only remains repair/failure when no consumable result exists.

## Verification

- `uv run pytest -q tests/session/test_manager.py tests/orchestrator/test_core.py tests/multiagent/test_commands.py tests/multiagent/test_plan_review_loop.py tests/tasks/test_evidence.py tests/bus/test_adapters.py tests/tasks/test_hub.py tests/tasks/test_hub_runtime_events.py`
