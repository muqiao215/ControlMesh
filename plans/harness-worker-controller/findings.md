# Confirmed Facts
- The runtime already has typed worker state, recovery contracts, execution contracts, and a boxed local engine.
- What is missing is a formal control surface that can create, await, inspect, restart, and terminate workers.
- Without this block, ControlMesh remains the implicit worker-control center.
- The sealed foundation was sufficient to land a real block-1 implementation without reopening Phase 24+.
- `controlmesh.team.runtime_control.TeamRuntimeController` was already the right thin substrate for ControlMesh-side worker lifecycle operations.
- The harness adapter can stay runtime-owned by translating ControlMesh runtime facts into `WorkerState` instead of leaking team-runtime payloads upward.
- The minimal error envelope needed both a narrow controller code (`NOT_FOUND` / `INVALID_REQUEST` / `CONFLICT` / `TIMEOUT` / `INTERNAL`) and an existing runtime `FailureClass`.

# Blockers
- None.

# Risks
- The controller can sprawl into transport or orchestration if its scope is not kept narrow.
- Missing error-classification discipline would leak adapter specifics upward.
- Restart currently remains `terminate -> create`; no richer recovery semantics were added in this block.

# Deferred
- multi-worker control
- provider-specific worker behavior
- orchestrator ownership
- recovery-loop ownership
- promotion behavior
- transport/CLI integration

# Decision Records
- 2026-04-14: This block is the first completion-pack block because later runtime closure depends on a real worker-control substrate.
- 2026-04-15: Block 1 froze the minimum worker surface as a protocol plus ControlMesh adapter, not as a broader controller/orchestrator hybrid.
- 2026-04-15: `await_ready` was kept as a thin polling read over persisted ControlMesh runtime state instead of adding new event-bus or recovery behavior.
- 2026-04-15: Error normalization uses `WorkerControllerErrorCode` and `FailureClass` only; it does not introduce transport-specific or provider-specific failure taxonomies.

# Verification
- `uv run pytest tests/controlmesh_runtime/test_worker_controller.py -q` -> `7 passed`
- `uv run pytest tests/controlmesh_runtime/test_worker_controller.py tests/team/test_runtime_control.py -q` -> `24 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `137 passed`
- `uv run ruff check controlmesh_runtime/worker_controller.py tests/controlmesh_runtime/test_worker_controller.py` -> `All checks passed!`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed!`
