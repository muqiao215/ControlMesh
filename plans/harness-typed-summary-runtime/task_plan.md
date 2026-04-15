# Current Goal
Implement real typed summary generation and landing for the narrow approved trigger set and subject scope so runtime compression becomes a working capability instead of a contract-only idea.

# Current Status
completed

# Frozen Boundaries
- do not widen subjects beyond task and line
- do not generate summaries for low-signal routine events
- do not make summaries canonical truth
- do not add summary query APIs in this block
- do not add revision graphs

# Ready Queue
1. checkpoint the block as first working summary runtime cut
2. keep broader summary subjects/query/promotion out of this pack

# Non-goals
- worker or global summaries
- summary query surfaces
- summary-driven promotion
- revision graphs
- model-driven broad summarization

# Completion Condition
- task and line summaries can be generated at the approved trigger moments
- summaries land under the separate summaries namespace
- latest-snapshot semantics remain intact
- focused tests cover trigger discipline, subject discipline, and landing shape

# Completed Work
1. Added deterministic summary runtime builder in `controlmesh_runtime/summary/runtime.py`.
2. Enforced trigger discipline per summary kind with `SummaryTrigger`.
3. Enforced subject discipline to task/line by stable `entity_id` mapping:
   - task kinds -> `task:<task_id>`
   - line checkpoint -> `line:<line>`
4. Added summaries landing support in `RuntimeStore`:
   - `controlmesh_state/summaries/`
   - `save_summary_record(...)`
   - `load_summary_record(...)`
   - latest snapshot semantics via overwrite on same `entity_id`.
5. Added focused runtime tests in `tests/controlmesh_runtime/summary/test_runtime.py`.

# Verification
- `uv run pytest tests/controlmesh_runtime/summary/test_contracts.py tests/controlmesh_runtime/summary/test_policy.py tests/controlmesh_runtime/summary/test_runtime.py tests/controlmesh_runtime/test_store.py -q` -> `22 passed`
- `uv run ruff check controlmesh_runtime/summary tests/controlmesh_runtime/summary controlmesh_runtime/store.py` -> `All checks passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
