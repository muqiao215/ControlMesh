# AGY implementation: cron persistence owner, batch 1

Continue native conversation `def64a8d-18c9-49eb-abd4-82488284d15f`. The primary has
reviewed your revised cron-port-spec.md as design input. Implement this bounded batch
now; the full runtime migration remains open. Read current code, not only the proposal.

## Ownership

- `packages/controlmesh-runtime-core/src/database.ts` migration (current version 42;
  recheck before assigning 43), new `src/cron-store.ts` and `src/cron-migration.ts`.
- New focused cron persistence/migration tests, minimum existing schema-version test
  updates, relevant additive exports in `src/index.ts`, an offline cron migration script
  if needed, and `delegation/agy-cron-batch-1-result.md`.
- Do not edit Python hostjob bridge/CLI/tests (CBC owns them), global plan/progress,
  sibling reports, provider adapters or production cron files. Do not commit/push.

## Required implementation

1. Inspect Python CronJob, serialization, LockedJsonJobs and actual TS RuntimeDatabase
   transaction/migration conventions. Implement registry persistence preserving every
   Python field, coercion/default behavior and unknown fields through import/export.
   Preserve native IDs and distinctions between missing, null and empty values where
   current readers depend on them. No generated protocol edits without need.
2. Add schema migration and typed CronStore APIs for registry, stable scheduled
   occurrences and fenced attempts. Adapt the SQL proposal to actual code. Occurrence
   identity excludes fence/coordinator incarnation. Define and test schedule-revision
   changes at the same timestamp explicitly; a constraint conflict must not masquerade
   as a receipt for another definition. Changed immutable definitions reject.
3. Use the existing single-coordinator authority. Local SQLite transactions do not
   prove multi-device leader election. Reject stale attempt writes and duplicate active
   execution attempts. Unknown/missing completion is not proof of process termination;
   do not release dependency ownership or authorize retries on TTL alone.
4. Implement offline import/export with transactionally all-or-nothing validated
   ingestion and lossless roundtrip. Prefer complete caller-supplied snapshots and
   exclusive output creation; do not add unsound live dual-write synchronization across
   SQLite and JSON. Clearly document the remaining LockedJsonJobs cutover/rollback
   owner, and never point tests/scripts at real runtime state.
5. No timer, provider launch, network send or automatic scheduled retry in this batch.
   This is the persistence owner required by subsequent recurrence/ingress work, not a
   completed cron migration. Do not copy speculative sandbox/AGY claims as implemented.

## Acceptance and report

Use configured AGY model/global permissions. Run only focused new persistence/migration
tests, relevant existing database migration tests, and runtime-core typecheck. Use
separate OS processes against one temporary SQLite DB for meaningful concurrency
checks. Exercise reopening v42 data, retained unrelated tables, duplicate occurrence,
stale fence, unknown completion, changed definition, corrupt import rollback and actual
Python-reader roundtrip in a temporary directory. No full runtime/Python suite.

PATH prefix: `/home/muqiao/Documents/Codex/2026-09-06/new-chat/outputs/runtime-convergence/ci-bun-bin`.
UV_CACHE_DIR=/tmp/cm-runtime-uv-cache. Use existing .venv for Python reader checks.
Write exact commands, exit codes, log paths (`/tmp/cm-agy-cron-batch1-*.log`), changed
files, remaining gaps and native conversation ID in your result document. Stop on
auth/quota errors without loops. Do not spawn other workers or interact with accounts,
browsers, services, cancelled tasks or production state.
