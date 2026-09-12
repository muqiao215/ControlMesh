# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. This is substantial runtime development, not
release-only work. Installed CM 0.43.0 remains the production Python writer. No live
migration, release, installation, service switch or default cutover has occurred.
The 512-module/57-field ledger is a source inventory, not a completed parity score.
The phase acceptance matrix remains in task_plan.md.

The current increment adds nested aggregate assignment, completion and same-tree reopen.
Full pinned verification passed; confirm remote publication and CI for this containing
commit separately from local acceptance. Previous main 73a1a26 has verified successful
remote CI 34689320168.

## Done

- Native and aggregate children have explicit assignment sources in schema 23. A nested
  execution is bound before its work runs; orchestration tasks cannot be admitted to the
  ordinary native queue. All four parent and child kinds have local composition paths.
- Aggregate completion recursively verifies current child/descendant results, and binds
  them to the assigned parent role without fabricating a native episode. Parent cancel
  blocks descendant authority; unknown in-flight evidence remains available for recovery.
- Same-tree reopen preserves task IDs, child generations, frozen policy and native leaf
  sessions. Archive/reopen/reassignment failure rolls back all changes together.
- Required parent files are verified against actual leaf broker receipts and current
  canonical bytes through nested executions. SpecMesh source check remains independent;
  file delivery does not establish reviewed project closeout.
- Current focused gate: 27 pass, 0 fail, 287 assertions in 3.82s. Typecheck passed.
  Evidence: /tmp/cm-aggregate-focused.log. Affected prior suites: 50 pass, 0 fail,
  411 assertions in 3.11s (/tmp/cm-aggregate-existing.log). These are controlled fixtures.
- The initial full run found an unintended task:read requirement at native claim. The
  guard now retains original ownership/execute semantics. Real process and aggregate
  recheck: 33 pass, 0 fail, 305 assertions in 4.93s (/tmp/cm-aggregate-recheck.log).
- Final full pinned gate: 590 pass, 0 fail, 8139 assertions across 65 files in 210.14s
  (exit 0), including inventory drift and typecheck. Evidence: /tmp/cm-aggregate-full.log.
  Initial failed evidence remains in /tmp/cm-aggregate-full-initial.log. No model input
  or production database migration was performed by this increment.
- Earlier local queue composition, transactional terminal completion, explicit root reopen,
  scoped native/History/SpecMesh acceptance and device foundations remain in place. Full
  provider/source/device coverage and product rollout are still required.

## Remaining

1. Bounded automatic service scheduling and explicit malformed-output recovery.
2. Device topology queues with current assignment/revision/authority enforcement.
3. Reviewed SpecMesh project closeout, separate from file delivery.
4. Real native topology/source-revision profiles and all remaining provider, transport,
   store and terminal product owners; complete ownership/parity evidence.
5. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

Do not replay failed native acceptance attempts or launch browser-account/cron/bot canaries
as a convenience test. Keep canceled tasks 77f04609/7738c5eb canceled. An observation
timeout does not establish that the original execution stopped. Candidate schema is now
23; rollback requires a pre-upgrade backup, not changing a populated database version.

Historical next-step instructions in task_plan.md were stale and competing; they have
been replaced by one current next action. Actual native failures and scoped acceptances
remain preserved in the linked archive rather than being relabeled as full completion.

## Next

Publish verified nested aggregate support directly to main. Then
implement bounded automatic scheduling/recovery and device topology integration. Do not mark the full migration complete for this increment.

## Retained evidence

Detailed earlier execution, native acceptance failures/recoveries and exact commits/logs
remain in [progress-through-6146dab.md](progress-through-6146dab.md). Search that archive
for the relevant owner. Durable implementation is in docs/ARCHITECTURE.md; findings and
native design files carry the specific ownership boundaries. Previous reopen gate:
563 pass, 0 fail, 7852 assertions across 64 files in 206.38s (exit 0), recorded in
/tmp/cm-topology-reopen-full.log at 73a1a26.
