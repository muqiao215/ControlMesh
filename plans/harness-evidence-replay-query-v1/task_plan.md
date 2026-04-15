# Current Goal
Implement the first bounded execution-evidence replay/query surface over archived `RuntimeEvent` evidence, using the typed runtime episode identity as the only legal join key.

# Current Status
completed

# Frozen Boundaries
- do not reopen `Harness Runtime Completion Pack v1`
- do not reopen `typed cross-evidence identity hardening`
- do not add SQLite, dual-write, migration code, or backend abstraction
- do not add broad/global query, cross-line search, worker history search, dashboard APIs, or SQL-like user queries
- do not trigger orchestrator, recovery, event publication, worker mutation, or canonical promotion from replay/query
- do not depend on transport, CLI, UI, provider identity, or canonical plan prose

# Ready Queue
1. hold this replay/query v1 scope closed
2. open any broader query/indexing/storage pressure as a separate scope

# Non-goals
- SQLite migration
- global query language
- dashboard/read-model product
- replay-driven recovery
- promotion or review adjudication
- store layout rewrite
- multi-worker orchestration

# Completion Condition
- execution payloads carry the full typed evidence identity needed by replay/query
- packet-level replay/query returns one bounded episode by packet id
- task-level query returns limited bounded episode aggregation by task id
- replay validation reports evidence-shape anomalies without mutating truth
- hidden joins through filenames, text, transport, CLI, or canonical prose remain forbidden

# Completed Work
- added `line` to typed execution payloads so replay can reconstruct `RuntimeEvidenceIdentity`
- added `ExecutionEvidenceReplayQuerySurface`
- added packet-level `query_packet_episode`
- added packet-level `validate_packet_replay`
- added task-level `query_task_episodes`
- added focused tests for identity reconstruction, anomaly reporting, task bounds, and drift rejection

# Verification
- focused replay/query verification -> `30 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `166 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
