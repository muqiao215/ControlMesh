# Confirmed Facts
- The runtime already has typed recovery decisions, execution plans/results, a boxed local executor, and execution evidence landing.
- What is missing is one real straight-line loop that binds those pieces together.
- Policy-auto does not mean runtime-runnable; the loop must preserve stop outputs instead of reinterpreting them as runnable retries.

# Blockers
- None.

# Risks
- The loop can sprawl into retries, multi-worker behavior, or provider-specific recovery if it is not held to one cycle.
- If stop conditions are softened, the boxed runtime boundaries will erode quickly.
- Deeper adaptive recovery and cross-cycle state remain deferred, so this loop is intentionally terminal after one result.

# Deferred
- multi-worker recovery
- provider-specific recovery
- adaptive retry policy
- multi-cycle or stateful retry orchestration

# Decision Records
- 2026-04-14: This block exists to close one bounded recovery path only, not to build the full recovery system.
- 2026-04-15: The loop preserves orchestrator stop outputs as terminal cycle outcomes rather than treating policy-auto as engine-runnable.

# Verification
- `uv run pytest tests/controlmesh_runtime/test_recovery_thin_loop.py -q` -> `4 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
