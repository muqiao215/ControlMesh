# Current Goal
Implement the formal worker-control surface for the harness runtime: define and land the minimal controller operations plus the ControlMesh adapter so runtime execution has a real worker substrate to target.

# Current Status
completed

# Frozen Boundaries
- do not touch transport/provider logic
- do not add multi-worker coordination
- do not make ControlMesh the policy owner
- do not widen this cut into orchestrator or recovery-loop logic
- do not mutate canonical truth from the controller

# Ready Queue
1. checkpoint the block as runtime-ready substrate
2. hand orchestration dependency over to `plans/harness-thin-orchestrator/task_plan.md`

# Non-goals
- transport integration
- policy evaluation
- orchestrator flow
- summary generation
- promotion behavior

# Completion Condition
- a formal worker controller protocol exists
- a ControlMesh adapter exists for the minimal worker lifecycle actions
- minimal health/error classification exists
- focused tests cover create/await_ready/fetch_state/restart/terminate behavior

# Completed Work
- frozen a runtime-owned `WorkerController` protocol surface in `controlmesh_runtime/worker_controller.py`
- landed `ControlMeshWorkerController` over `controlmesh.team.runtime_control.TeamRuntimeController`
- mapped ControlMesh team runtime states into harness `WorkerState`
- added minimal `WorkerControllerErrorCode` + `WorkerControllerError.failure_class`
- covered create / await_ready / fetch_state / restart / terminate with focused tests

# Verification
- `uv run pytest tests/controlmesh_runtime/test_worker_controller.py -q` -> `7 passed`
- `uv run pytest tests/controlmesh_runtime/test_worker_controller.py tests/team/test_runtime_control.py -q` -> `24 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `137 passed`
- `uv run ruff check controlmesh_runtime/worker_controller.py tests/controlmesh_runtime/test_worker_controller.py` -> `All checks passed!`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed!`
