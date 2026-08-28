# Findings

## Baseline

- Worktree started clean on branch `main` at `6d52099`.
- Cached `origin/main` matched local HEAD before the required live remote fetch.
- Live `git fetch origin main --prune` confirmed remote `main` is exactly `6d52099`; no
  upstream work needs merging.
- Recent completed work established the task-lifecycle TypeScript parity gate while keeping
  Python as production and rollback owner and public mutation surfaces read-only.

## Requirements Map

- Identity authority: `packet_id + task_id + line + plan_id`.
- Writeback authority: runtime owner only, current execution episode only.
- Promotion authority: controller only, with identity/status/freshness recheck at commit.
- Patch candidates: task-local evidence plus `proposed_*`, never direct canonical writes.
- Fault inventory: first success, identical duplicate, conflicting duplicate, wrong owner,
  stale episode, identity cross-wire, unsuccessful status, TOCTOU freshness, controller
  accept/reject, interrupted delivery retry.

## Research Findings

- Project memory confirms Python owns result writeback, recovery, promotion, and rollback;
  public OpenAPI/SDK/Web must stay read-only and `MUTATION_API_REVIEW.md` remains Deferred.
- The canonical typed evidence identity already exists in
  `controlmesh_runtime/evidence_identity.py` and is shared by review, execution result,
  summary, replay, and promotion paths.
- Existing promotion safety is concentrated in `promotion_bridge.py`,
  `promotion_controller.py`, `canonical_section_writer.py`, and `promotion_receipt.py`.
- Existing result writeback surfaces appear split between TaskHub result delivery and team
  dispatch result recording; this requires a targeted ownership audit rather than assuming
  either layer alone is authoritative.
- There is already substantial unit coverage for promotion identity/completion and runtime
  owner attachment. The new work must unify production paths into a normalized matrix and
  fill only missing episode/idempotency/TOCTOU/writeback gaps.
- `RuntimeEvidenceIdentity` is exactly the required immutable four-field tuple. Recovery
  plans derive it directly; results require `plan_id == evidence_identity.plan_id`, but the
  result contract alone does not prove current runtime owner or latest episode.
- `RuntimeStore.append_execution_evidence` validates typed payload shape but appends JSONL
  without identity-level idempotency/conflict enforcement. Review records are keyed only by
  task ID on disk, while promotion validation compensates by comparing their typed identity.
- `RecoveryExecutionStatus` distinguishes completed, failed, aborted, partial, pending,
  running, approved, and human-gated outcomes; promotion must explicitly admit only
  `COMPLETED` rather than infer success from result existence.
- Prior lifecycle plans are fully closed and intentionally do not authorize public mutation.
  The existing CI product gate is the correct integration seam for another Python golden.
- Legacy `PromotionInput` already enforces controller authority, four-field identity equality,
  and completed execution for pass outcomes. The active `PromotionController.reconcile ->
  promote_summary` path, however, accepts summaries/review without loading or validating the
  current execution result; this is a real promotion gap for failed/stale/cross-wired results.
- Summary promotion already rechecks stored summary IDs twice: eligibility time and the
  writer's immediate `pre_write_check`. It does not yet recheck execution-result freshness,
  review identity, or current episode at that final boundary.
- Promotion idempotency exists for an identical pair of task/line summary IDs via a stored
  receipt. Canonical writer notes are upserted, but receipt/event behavior for conflicting
  or interrupted retries still requires focused audit.

## Technical Decisions

| Decision | Rationale |
|---|---|
| Enforce writeback in `RuntimeStore` | Every persisted execution-evidence producer crosses this Python-owned boundary. |
| Derive freshness from the latest persisted plan-created event | Reuses the canonical identity and makes recovery episodes supersede earlier packets without a parallel index. |
| Admit only one current `completed` result at promotion | Result existence and summary agreement are insufficient safety evidence. |
| Extend statuses with `cancelled` and `delivery_failed` | These distinct terminal failures must be machine-testable and cannot alias success. |
| Add the matrix to `pnpm test:golden` | Existing required product gate already owns committed-fixture drift checks. |

## Final Evidence Map

- First result and identical/conflicting retry: store append path and golden cases 1–3.
- Runtime owner and recovery freshness: persisted plan owner/latest episode checks and cases 4–5.
- Four-field cross-wire and non-success states: promotion validator and cases 6–7.
- Pre-write TOCTOU: writer hook revalidates execution, review, and summaries in case 8.
- Controller acceptance/audit and safe retry: cases 9–10 prove one receipt/event and unchanged canonical state on rejection.
- `test_execution` and `code_review` remain read-only evidence producers. `patch_candidate`
  remains task-local and may emit verification evidence plus `proposed_*`; none is ready for
  direct canonical promotion.

## Issues Encountered

| Issue | Resolution |
|---|---|
| First baseline findings patch missed the exact progress-list context | Re-read all three task files and applied a context-accurate patch. |
| Combined six-file read exceeded output context | Switched to bounded single-file reads. |
| Initial package script patch used stale line context | Re-read `package.json` and applied an exact patch; no partial file changes occurred. |
