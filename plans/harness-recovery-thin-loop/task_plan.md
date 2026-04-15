# Current Goal
Implement the thinnest recovery loop that runs one bounded straight-line recovery cycle over the existing decision, plan, result, and evidence objects.

# Current Status
completed

# Frozen Boundaries
- do not add concurrency
- do not add multi-worker coordination
- do not add provider-specific recovery
- do not bypass human-gate or stop boundaries
- do not fold promotion logic into the loop

# Ready Queue
1. checkpoint the block as first closed recovery path
2. hold any broader retry/multi-cycle recovery for a new scope

# Non-goals
- retries beyond the approved straight-line plan
- transport-specific recovery
- summary generation
- read-surface behavior
- canonical promotion

# Completion Condition
- one bounded recovery cycle runs end to end
- stop conditions remain explicit and terminal
- execution evidence is produced without extra truth mutation
- focused tests cover success, gate stop, unsupported stop, and failure stop paths

# Completed Work
- landed `controlmesh_runtime/recovery_thin_loop.py` with one-cycle request/outcome types
- wired `RecoveryContext -> evaluate_recovery_policy -> ThinOrchestrator -> RecoveryExecutionResult`
- kept policy-auto and runtime-runnable separate by preserving orchestrator stop outputs as terminal cycle outcomes
- kept the loop single-cycle, single-result, and non-promoting

# Verification
- `uv run pytest tests/controlmesh_runtime/test_recovery_thin_loop.py -q` -> `4 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
