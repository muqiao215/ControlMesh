# Confirmed Facts
- Execution evidence already lands in a typed file-backed namespace.
- Read-surface boundaries already limit the first legal views to packet-level and bounded task-level access.
- Evidence is currently archive-first and not yet a practical tool for review/handoff consumption.
- A narrow read surface can stay fully read-only by consuming `RuntimeStore.load_execution_evidence` and decoding payloads through typed extraction.
- Packet evidence must enforce single-task integrity (`task_id`) to avoid ambiguous task-level aggregation.
- Latest review and summary can be exposed as bounded facts without changing canonical truth ownership.

# Blockers
- None.

# Risks
- Query ambition can expand quickly into SQLite or global search if packet/task boundaries are not enforced.
- Read output can be mistaken for canonical truth if promotion boundaries are not kept separate.
- Summary-path conventions are now aligned on `controlmesh_state/summaries/{task|line}/`, but future drift between writer and reader remains a risk.

# Deferred
- replay tools
- global query
- SQLite-backed reads
- cross-line/cross-worker aggregation
- dashboard query APIs

# Decision Records
- 2026-04-14: This block exists to make archived evidence usable without widening the runtime into a broad query product.
- 2026-04-15: Block 5 implemented only packet/task bounded views and latest fact reads; no replay, no global query, no SQLite.
- 2026-04-15: Read surface remains an evidence consumer and does not write runtime/canonical files.

# Verification
- `uv run pytest tests/controlmesh_runtime/test_execution_read_surface.py -q` -> `5 passed`
- `uv run pytest tests/controlmesh_runtime/test_execution_evidence_store.py -q` -> `6 passed`
- `uv run ruff check controlmesh_runtime/__init__.py controlmesh_runtime/execution_read_surface.py tests/controlmesh_runtime/test_execution_read_surface.py` -> `All checks passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
