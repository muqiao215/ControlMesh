# Current Goal
Implement the narrow execution-evidence read surface that turns archived evidence into a usable runtime tool without drifting into broad query or database work.

# Current Status
completed

# Frozen Boundaries
- do not add global search
- do not add SQLite
- do not add replay tooling in this block
- do not widen beyond packet/task bounded reads
- do not treat read output as canonical truth

# Ready Queue
1. checkpoint the block as first working evidence read surface
2. hand promotion dependency over to `plans/harness-promotion-bridge/task_plan.md`

# Non-goals
- global query layer
- replay implementation
- SQLite-backed reads
- dashboard APIs
- cross-line/cross-worker search

# Completion Condition
- packet-level execution episode reads exist
- limited task-level aggregation exists
- latest review fact and latest summary can be read through the bounded surface
- focused tests cover view shape, evidence integrity, and non-ownership of truth

# Completed Work
- added `controlmesh_runtime/execution_read_surface.py` as a narrow read-only evidence surface
- landed packet-level `read_packet_execution_episode(packet_id)` over archived execution `RuntimeEvent` evidence
- landed bounded task-level `read_task_evidence(task_id, line, packet_limit)` aggregation
- wired latest review and latest summary snapshot reads from file-backed namespaces only
- exported the read surface in `controlmesh_runtime/__init__.py`

# Verification
- `uv run pytest tests/controlmesh_runtime/test_execution_read_surface.py -q` -> `5 passed`
- `uv run pytest tests/controlmesh_runtime/test_execution_evidence_store.py -q` -> `6 passed`
- `uv run ruff check controlmesh_runtime/__init__.py controlmesh_runtime/execution_read_surface.py tests/controlmesh_runtime/test_execution_read_surface.py` -> `All checks passed`
