# Current Goal
Implement `harness-summary-runtime-v1` as the first independent evidence consumer: deterministically materialize one task summary and one line summary from the same typed runtime evidence identity, then land both as latest snapshots under `controlmesh_state/summaries/`.

# Current Status
completed

# Frozen Boundaries
- do not reopen `Harness Runtime Completion Pack v1`
- do not reopen the sealed evidence plane or extend replay/query
- do not add summary query APIs
- do not add promotion, review handoff, or canonical truth writes
- do not couple summary runtime to worker/controller/orchestrator/recovery execution
- do not add transport/provider/UI/dashboard behavior
- do not add summary revision history or append-only archives

# Ready Queue
1. checkpoint `harness-summary-runtime-v1` as closed
2. require any broader summary consumer/query/promotion work to open as a new scope

# Non-goals
- broad summary kind support beyond the bounded task/line pair materialization cut
- summary query/read APIs
- summary-driven promotion
- replay enhancement
- worker/controller wiring
- transport/provider logic
- UI/dashboard surfaces
- SQLite or alternate storage

# Completion Condition
- one request can materialize a task summary and a line summary that share the same `RuntimeEvidenceIdentity`
- summary runtime rejects cross-identity drift between paired task/line inputs
- task summary lands at `controlmesh_state/summaries/task/<task_id>.json`
- line summary lands at `controlmesh_state/summaries/line/<line>.json`
- repeated materialization preserves latest-snapshot overwrite semantics
- focused tests cover paired materialization, drift rejection, and latest-snapshot behavior

# Completed Work
1. Added `SummaryMaterializationRequest` in `controlmesh_runtime/summary/runtime.py` to freeze the paired task/line summary request shape for one runtime evidence identity.
2. Added `SummaryMaterializationResult` in `controlmesh_runtime/summary/runtime.py` to keep the resulting task/line summary snapshots typed and identity-checked.
3. Added `SummaryRuntime` in `controlmesh_runtime/summary/runtime.py` as the thin materialization layer that:
   - reuses existing deterministic `build_summary_record(...)`
   - persists task and line snapshots through `RuntimeStore`
   - keeps latest-snapshot semantics
4. Exported the new summary runtime surface through:
   - `controlmesh_runtime/summary/__init__.py`
   - `controlmesh_runtime/__init__.py`
5. Added focused tests in `tests/controlmesh_runtime/summary/test_runtime.py` for:
   - paired task/line materialization
   - cross-identity drift rejection
   - latest-snapshot overwrite semantics on repeated materialization

# Verification
- `uv run pytest tests/controlmesh_runtime/summary/test_runtime.py -q` -> `9 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `169 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
