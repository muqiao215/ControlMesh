# AGY batch 1 review 4 — snapshot replacement and retained execution lineage

Primary independently reran the earlier counterexamples: raw/null preservation and
read-only authority getter now pass. R3 completed exit 0, its 12 tests/114 assertions
and migration 24 tests/117 assertions passed. Two further actual regressions remain.
Repair these bounded issues in the same TS cron files. No broad rewrite or new workers.

## Reproduced on actual RuntimeDatabase(':memory:')

Start with a valid core job plus `obsolete:'old'`, import with `{replace:true}`.
Import the same core job WITHOUT obsolete with `{replace:true}`. Export still includes
obsolete. This is a merge, despite being called full snapshot replacement. The recorded
snapshot digest can therefore describe a different registry from actual stored data.

For that job, registerCoordinator('trusted'), createOccurrence, createAttempt at fence 1.
`removeJob(id)` returns true and `getAttempt(attemptId)` becomes null. FK cascades delete
running execution lineage, permitting recreation/replay while an external execution
could still be active. No external process was launched in this reproduction.

## Required changes

1. Explicit replace semantics for job raw records in complete snapshot import. Preserve
   ordinary patch/merge semantics separately. Removed fields really disappear under
   replacement; repeat identical complete imports have stable effective definition,
   digest and revision. Top-level metadata and job snapshot identity stay aligned. Test
   omitted fields/defaults, explicit null, unknown fields, and all-or-nothing rollback
   when a later job is invalid. Keep previous regression tests.
2. Remove definitions from active scheduling without deleting occurrences/attempts.
   Use a persistent archive/tombstone in the not-yet-released migration 43 rather than
   FK-cascading execution history away. list/get for active definitions and export omit
   archived jobs, while old attempts remain inspectable/reconcilable. Preserve the full
   lineage and stable IDs. Explicit recreation/restoration of the same job ID must use
   a new definition revision, cannot fire an occupied historical slot twice, and cannot
   erase an active/unknown attempt. Add complete CRUD/archive/restore and active attempt
   tests; merely forbidding every deletion forever is not the target product behavior.
   Archiving itself is not evidence that a worker terminated; cancellation stays with
   the execution owner. Do not add a runtime scheduler or provider call.
3. Verify the earlier snapshot/concurrency/publication tests cover their names: the bare
   read-only Database case must actually contend with a writer, not just export once;
   simulate failed/colliding export publication and prove no truncated final file or
   leaked temp remains. Preserve meaningful tests; don't reduce coverage to fit claims.

Focused tests/typecheck and relevant migration checks only. Raw logs
/tmp/cm-agy-cron-batch1-r4-*.log. Report under 120 lines mapping these defects to exact
tests. CBC independently owns cron-schedule.ts/recurrence fixtures and may change parser
dependencies/lockfile; don't touch those. No Python/CI/global-plan edits, commits/push,
production data, account/browser activity, service restarts or native provider probes.
