# Current Goal
Implement the single-writer promotion bridge that turns reviewed runtime evidence into canonical truth updates without sending the system back to ad hoc manual file edits.

# Current Status
completed

# Frozen Boundaries
- do not let workers call the bridge directly
- do not let execution evidence self-promote
- do not let summaries overwrite canonical truth automatically
- do not widen into a general workflow engine
- do not add transport or provider logic

# Ready Queue
1. checkpoint the block as first working truth-promotion surface
2. hold any broader workflow automation or richer truth-joins for later scope

# Non-goals
- worker-side promotion
- automatic summary promotion
- database-backed canonical state
- broader workflow automation
- UI-facing change control

# Completion Condition
- the promotion bridge accepts only approved controller-side inputs
- canonical file updates happen through one bounded surface
- focused tests cover single-writer discipline and forbidden direct mutations
- the runtime no longer depends on ad hoc manual file edits for truth promotion

# Completed Work
- landed `controlmesh_runtime/promotion_bridge.py` with controller-owned `PromotionInput`, `PromotionResult`, and `PromotionBridge`
- froze single-writer discipline through `PromotionSource.CONTROLLER`
- mapped reviewed runtime outcomes to canonical line status/checkpoint tokens
- landed bounded markdown section updates for `plans/<line>/task_plan.md` and `plans/<line>/progress.md`
- kept summary input as optional annotation only, not automatic truth authority

# Verification
- `uv run pytest tests/controlmesh_runtime/test_promotion_bridge.py -q` -> `3 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `159 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
