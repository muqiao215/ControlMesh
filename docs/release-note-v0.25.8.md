# ControlMesh v0.25.8

This patch release hardens TaskHub recovery semantics and starts decoupling Telegram frontstage message handling from long-running execution.

## Highlights

- Background tasks now carry stable `idempotency_key` values so duplicate create/route calls can attach to the same in-flight run instead of spawning accidental reruns.
- `/continue` semantics are now explicit: attach inspects current task state without rerunning, while resume follow-up continues the same background session with a new prompt.
- Detached task recovery now closes the `detached -> stale -> recovering -> done/failed` loop from durable artifacts and lease state, including deduplicated recovered delivery.
- Telegram message handling now enqueues frontstage turns into a per-session background queue instead of awaiting the full provider run inside the transport handler.
- Added a small detached test runner/status pair under `tools/user_tools/` so unstable frontstage sessions can still kick off file-backed test runs and inspect results later.

## Upgrade Notes

- Release this version with tag `v0.25.8`; `pyproject.toml` and `controlmesh/__init__.py` are aligned to `0.25.8`.
- Full regression coverage for this patch is expected to come from GitHub Actions after tag push rather than local foreground test runs.
