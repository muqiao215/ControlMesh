# Current Goal
Close `Runtime Control Surface Pack` as one bounded implementation package that adds a controlled `signal/query/update` surface over the existing autonomous runtime loop without creating a second runtime.

# Current Status
completed

# Frozen Boundaries
- do not create a second runtime package or parallel control plane
- do not add daemon or system wiring
- do not add broader transport/provider ingress beyond the thin CLI surface
- do not add multi-worker orchestration
- do not add SQLite
- do not add UI or dashboard work
- do not widen packet/task reads into broad query or replay redesign

# Ready Queue
1. hold Runtime Control Surface Pack closed
2. require any daemonization, broader transport ingress, or control-surface hardening to open as a new scope

# Non-goals
- daemon/system integration
- HTTP or websocket control service
- broader transport/provider behavior
- multi-worker orchestration
- SQLite
- broad query or dashboard work

# Completion Condition
- one additive runtime control surface exists inside `controlmesh_runtime/`
- `signal`, `query`, and `update` exist as typed runtime verbs
- control-plane observations/materializations land as append-only `ControlEvent` records
- trace and span identity propagate through control events and promotion receipts
- canonical mutation remains controller-owned through `PromotionController.reconcile()`
- CLI exposes `controlmesh runtime run|signal|query|update`
- focused runtime verification passes
- repo-wide `pytest` is fresh green
- repo-wide `ruff` is fresh green

# Completed Work
- added `SignalAction`, `QueryAction`, `UpdateAction`, `ControlEventKind`, and `ControlEvent`
- added lightweight trace helpers with `TraceContext`, `root_trace(...)`, and `child_trace(...)`
- extended `RuntimeStore` with append/load/latest helpers for control events and promotion receipts
- made summary materialization append task and line observation control events
- made promotion receipts carry evidence identity plus trace/span metadata
- added `PromotionController.reconcile()` as the single controller-owned canonical mutation surface above review plus latest summaries
- added `runtime_message_api.signal(...)`, `query(...)`, and `update(...)`
- routed autonomous promotion through `PromotionController` instead of direct bridge mutation
- extended CLI ingress to expose `controlmesh runtime signal`, `controlmesh runtime query`, and `controlmesh runtime update`

# Verification
- `uv run pytest tests/controlmesh_runtime/test_store.py tests/controlmesh_runtime/test_runtime_message_api.py tests/controlmesh_runtime/summary/test_runtime.py tests/controlmesh_runtime/test_promotion_bridge.py tests/controlmesh_runtime/test_autonomous_runtime_loop.py tests/cli/test_runtime_ingress_cli.py -q` -> `43 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `197 passed`
- `uv run ruff check controlmesh_runtime controlmesh/cli_commands/runtime.py tests/controlmesh_runtime tests/cli/test_runtime_ingress_cli.py` -> `All checks passed!`
- `uv run pytest -x -q` -> `3941 passed, 3 skipped in 1207.41s (0:20:07)`
- `uv run ruff check .` -> `All checks passed!`
