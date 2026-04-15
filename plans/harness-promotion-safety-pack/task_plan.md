# Current Goal
Implement the `Promotion Safety Pack` as one coherent bridge-hardening package: structured promotion write intent, write-time freshness guard, file-backed promotion receipts, and canonical section writer contracts.

# Current Status
completed

# Frozen Boundaries
- do not reopen `Harness Runtime Completion Pack v1`
- do not reopen the sealed evidence plane, summary plane, or promotion plane
- do not let raw execution evidence self-promote
- do not let replay/query outputs promote canonical truth directly
- do not add worker/controller/orchestrator automation
- do not add transport/provider/UI/dashboard behavior
- do not expand canonical write-back beyond line `task_plan.md` and `progress.md`
- do not change promotion-bridge v1 prose ownership rules
- do not add automatic/background-triggered promotion

# Ready Queue
1. checkpoint `Promotion Safety Pack` as closed
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
- new canonical write targets

# Completion Condition
- `PromotionWriteIntent` structures what will be written before canonical mutation
- write intent binds review id, task summary id, line summary id, checkpoint token, allowed sections, allowed write shapes, and controller-approved prose
- `CanonicalSectionWriter` accepts only fixed section/shape patches and rejects out-of-contract targets
- promotion summary path performs a write-time freshness guard before applying section patches
- `PromotionReceipt` records line, written sections, review id, task summary id, line summary id, timestamp, and write result
- focused tests cover structured intent, write-time freshness, receipt persistence, and section-writer rejection

# Completed Work
1. Added `PromotionWriteIntent` in `controlmesh_runtime/promotion_bridge.py`.
2. Added `CanonicalSectionWriter` and section-patch contracts in `controlmesh_runtime/canonical_section_writer.py`.
3. Added `PromotionReceipt` in `controlmesh_runtime/promotion_receipt.py`.
4. Added `review_id` to `ReviewRecord` so promotion receipts can cite a typed review source.
5. Added promotion receipt persistence to `RuntimeStore`.
6. Updated `PromotionBridge.evaluate_summary_promotion(...)` to return structured write intent.
7. Updated `PromotionBridge.promote_summary(...)` to:
   - recheck summary freshness at write time
   - write through `CanonicalSectionWriter`
   - persist a `PromotionReceipt`
8. Kept promotion-bridge v1 boundaries intact:
   - summaries remain provenance and eligibility inputs
   - canonical prose remains controller-approved
   - canonical write-back remains line `task_plan.md` plus `progress.md`

# Verification
- `uv run pytest tests/controlmesh_runtime/test_promotion_bridge.py -q` -> `13 passed`
- `uv run pytest tests/controlmesh_runtime -q` -> `177 passed`
- `uv run ruff check controlmesh_runtime tests/controlmesh_runtime` -> `All checks passed`
