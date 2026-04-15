# Current Goal
Implement `harness-promotion-bridge-v1` as the first post-summary promotion hardening cut: accept only controller-owned review facts plus latest task/line summaries, evaluate promotion eligibility explicitly, and write back controller-approved canonical state into the narrow line-file surface.

# Current Status
completed

# Frozen Boundaries
- do not reopen `Harness Runtime Completion Pack v1`
- do not reopen the sealed evidence plane or summary plane
- do not let raw execution evidence self-promote
- do not let replay/query outputs promote canonical truth directly
- do not add worker/controller/orchestrator automation
- do not add transport/provider/UI/dashboard behavior
- do not expand canonical write-back beyond line `task_plan.md` and `progress.md`
- do not add automatic/background-triggered promotion
- do not let latest summaries author canonical prose directly
- do not auto-write `findings.md`

# Ready Queue
1. checkpoint `harness-promotion-bridge-v1` as closed
2. require any broader promotion workflow or richer canonical target surface to open as a new scope

# Non-goals
- raw execution evidence promotion
- replay/query-result promotion
- worker-side promotion
- summary query/history work
- orchestrator-triggered automatic promotion
- transport/provider logic
- UI/dashboard surfaces
- SQLite or alternate canonical storage

# Completion Condition
- one input can carry review fact plus latest task/line summaries plus controller-approved write-back text without execution plan/result dependencies
- promotion bridge exposes an explicit eligibility gate before any canonical write-back
- canonical write-back updates only `plans/<line>/task_plan.md` and `plans/<line>/progress.md`
- promotion v1 rejects non-controller submissions and review/summary identity drift
- canonical notes keep human text intact and only replace the machine-owned provenance sub-block
- focused tests cover eligibility, write-back shape, and forbidden authority shortcuts

# Completed Work
1. Added `SummaryPromotionInput` in `controlmesh_runtime/promotion_bridge.py` as the narrow review-plus-latest-summaries promotion contract.
2. Added `PromotionEligibility` in `controlmesh_runtime/promotion_bridge.py` to make promotion gating explicit before canonical writes.
3. Added `PromotionBridge.evaluate_summary_promotion(...)` in `controlmesh_runtime/promotion_bridge.py` to compute bounded status/checkpoint/write-target outcomes without mutating files.
4. Added `PromotionBridge.promote_summary(...)` in `controlmesh_runtime/promotion_bridge.py` to write only:
   - `plans/<line>/task_plan.md`
   - `plans/<line>/progress.md`
   - machine-owned provenance inside `# Notes` without clobbering human notes
5. Kept latest task/line summaries as eligibility and provenance inputs only:
   - canonical `Latest Completed` and `Next Action` come from controller-approved text
   - summary ids remain machine provenance in `# Notes`
6. Exported the new promotion v1 surface through `controlmesh_runtime/__init__.py`.
7. Added focused tests in `tests/controlmesh_runtime/test_promotion_bridge.py` for:
   - review-plus-summary promotion without execution-result dependency
   - non-controller rejection
   - cross-identity drift rejection
   - unapproved task-summary kind rejection

# Verification
- `uv run pytest tests/controlmesh_runtime/test_promotion_bridge.py -q` -> `9 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `173 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
