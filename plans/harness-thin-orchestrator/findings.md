# Confirmed Facts
- The runtime already has a written orchestrator boundary and typed execution objects.
- What is missing is the minimal code surface that stitches those objects into one bounded path.
- The current first engine remains useful as a pure plan/preflight helper, but it must not stay the authority for real step/result emission once worker-controller execution exists.
- Action mapping had to be frozen explicitly at the orchestrator seam so policy/runtime semantics do not leak into the ControlMesh adapter.

# Blockers
- None.

# Risks
- The orchestrator can drift into policy evaluation or canonical promotion if the seam is not held narrow.
- Event publication concerns can leak in if typed payload evidence is not kept as the only output path.
- Identity joins across `packet_id` / `task_id` / `plan_id` remain intentionally narrow and local to this block; broader join semantics stay outside the pack.

# Deferred
- multi-worker orchestration
- transport/provider orchestration
- store/event-bus infrastructure
- deeper identity-proof contracts across review/result/summary promotion

# Decision Records
- 2026-04-14: This block stays thin by design and exists only to close the runtime loop between decisions, plans, execution, and results.
- 2026-04-15: The thin orchestrator is the single authority for real worker-controller step execution; the engine remains plan/preflight only.
- 2026-04-15: Runtime-runnable action mapping is frozen at the orchestrator seam instead of being inferred downstream.

# Verification
- `uv run pytest tests/controlmesh_runtime/test_thin_orchestrator.py -q` -> `4 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
