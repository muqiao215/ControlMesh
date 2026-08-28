# Task: Result Writeback + Promotion Golden Gate

## Goal

Build an executable, production-Python-generated fault matrix proving that result writeback
and promotion accept only fresh, correctly owned, correctly identified successful results,
while duplicate, conflicting, stale, cross-wired, failed, cancelled, or delivery-failed
results cannot contaminate canonical state.

## Requirements

- Reuse the canonical identity tuple `packet_id + task_id + line + plan_id`; do not add a
  parallel identity model or fall back to filenames/text matching.
- Prove runtime owner exclusivity and current execution-episode freshness for writeback.
- Define deterministic idempotency for identical duplicate writeback and fail closed on
  conflicting payloads under the same idempotency identity.
- Reject wrong owner/task/line/plan/episode and retain normalized diagnostic evidence.
- Prevent failed, cancelled, and delivery_failed executions from completed promotion.
- Keep patch candidates task-local as evidence and `proposed_*`; only controller promotion
  may write canonical state.
- Recheck identity, status, and freshness immediately before canonical promotion.
- Prove controller acceptance preserves evidence/verification/audit data and rejection
  leaves canonical files unchanged.
- Prove interrupted delivery retries cannot create duplicate results, events, artifacts, or
  promotion.
- Generate stable normalized fixtures from production Python paths, provide drift checks,
  focused tests, and a required CI gate.
- Reassess `test_execution`, `code_review`, and `patch_candidate` readiness.
- Keep Python ownership and all public HTTP/SDK/Web surfaces read-only; keep
  `MUTATION_API_REVIEW.md` Deferred.

## Non-goals

- No TypeScript runtime ownership transfer.
- No public create/tell/resume/cancel or result-writeback API.
- No browser credential, remote Web, provider migration, or new task-type work.
- No broad refactor or persisted-format change unless unavoidable and compatibility-tested.

## Plan

- [x] Audit project memory, ownership paths, typed identity, recovery, delivery, promotion,
      current plans, and existing tests.
- [x] Map the ten required faults to existing evidence and identify only real gaps.
- [x] Implement missing production safety invariants at the narrow ownership boundary.
- [x] Implement deterministic Python golden generator, Schema, fixtures, and drift/diff gate.
- [x] Add focused tests and CI integration without exposing public mutations.
- [x] Reassess workunit readiness and update durable architecture/decision/status docs.
- [x] Run focused and complete local gates; inspect the final diff for safety and scope.
- [ ] Commit, push, and verify final GitHub Actions on exact HEAD.

## Success

All ten required fault families have executable evidence derived from production Python
paths; canonical state is proven immune to unauthorized, cross-wired, stale, unsuccessful,
conflicting, or repeated results; promotion is controller-only and freshness-checked at
commit time; fixture drift fails CI with actionable differences; full local and remote gates
are green; the worktree matches `origin/main`.

## Status

Current phase: local scope complete; commit/push and exact-HEAD CI verification.

## Next Step

Commit the verified scope, push `main`, and confirm the remote workflow on the exact commit.

## Decisions Made

| Decision | Rationale |
|---|---|
| Start from a clean `main` at `6d52099` | Local HEAD and cached `origin/main` match; remote fetch will confirm the live baseline. |
| Treat existing production Python paths as the oracle | The repository explicitly keeps lifecycle, writeback, recovery, promotion, and rollback Python-owned. |
| Keep patch candidates task-local | Golden acceptance proves evidence, verification commands, and `proposed_*` remain unchanged while only controller promotion mutates canonical files. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Planning findings/progress patch missed an exact list context | 1 | Re-read all task files and patch against their current content. |
| Combined read of six runtime files exceeded the output/context limit | 1 | Switched to bounded, single-file reads and immediate findings updates. |
| Full pytest rejected root `HANDOFF.md` as a superseded parallel authority | 1 | Removed it and retained handoff state in task-local `progress.md`, matching repository coordination rules. |
