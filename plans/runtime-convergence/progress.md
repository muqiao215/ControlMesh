# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. This is substantial runtime development, not
release-only work. Installed CM 0.43.0 remains the production Python writer. No live
migration, release, installation, service switch or default cutover has occurred.
The 512-module/57-field ledger is a source inventory, not a completed parity score.
The phase acceptance matrix remains in task_plan.md.

Current published main fcdc818 has verified successful CI 34690365494. The current
increment implements read-only topology result preview, explicit bounded malformed-output
recovery and optional pipeline/fanout repair/interruption caps. Automatic scheduler startup,
registration and control wiring are still pending. This increment passed the full pinned
gate: 612 tests / 8283 assertions across 66 files, 209.12s, exit 0. Code publication and
remote CI are separate from this local acceptance; installed CM remains unchanged.

## Done

- Preview and collection share assignment/proof checks; preview writes no acceptance or
  command receipt. Result regeneration requires a typed JSON/schema/role/round failure,
  rather than any thrown exception. Valid output and corrupt/uncertain evidence reject.
- Explicit retry atomically archives rejected proof identity and reuses the same native
  task/session. Two retries per child/parent execution survive restart. Quota deadlines
  reject early retry; unstarted blocked work preserves its input. Cancelled/unknown tasks
  remain blocked. No automatic model retry is introduced.
- Optional pipeline/fanout repair and parent-interruption caps use persisted checkpoints;
  unsupported worker statuses still reject. Service policy freezing is not yet wired.
- Focused queue/result tests: 23 pass, 0 fail, 137 assertions (958ms). Controller/budget:
  32 pass, 0 fail, 208 assertions (1473ms). Logs: /tmp/cm-topology-recovery-focused.log
  and /tmp/cm-topology-budgets-focused.log. Typecheck passed. Controlled fixtures only.
- Current full gate: 612 pass, 0 fail, 8283 assertions, 66 files, 209.12s (exit 0),
  including Python owner inventory and typecheck. Log: /tmp/cm-topology-recovery-full.log.
  These checks did not send new native-model prompts or migrate production data.

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
- Previous nested aggregate focused gate: 27 pass, 0 fail, 287 assertions in 3.82s. Typecheck passed.
  Evidence: /tmp/cm-aggregate-focused.log. Affected prior suites: 50 pass, 0 fail,
  411 assertions in 3.11s (/tmp/cm-aggregate-existing.log). These are controlled fixtures.
- The initial full run found an unintended task:read requirement at native claim. The
  guard now retains original ownership/execute semantics. Real process and aggregate
  recheck: 33 pass, 0 fail, 305 assertions in 4.93s (/tmp/cm-aggregate-recheck.log).
- Previous nested aggregate full pinned gate: 590 pass, 0 fail, 8139 assertions across 65 files in 210.14s
  (exit 0), including inventory drift and typecheck. Evidence: /tmp/cm-aggregate-full.log.
  Initial failed evidence remains in /tmp/cm-aggregate-full-initial.log. No model input
  or production database migration was performed by this increment.
- Earlier local queue composition, transactional terminal completion, explicit root reopen,
  scoped native/History/SpecMesh acceptance and device foundations remain in place. Full
  provider/source/device coverage and product rollout are still required.

## Remaining

1. Bounded automatic scheduling, immutable plan registration and explicit recovery controls
   through normal isolated local runtime startup (the queue primitives are implemented).
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

Wire automatic scheduling/recovery into normal local runtime startup/control, using the
verified preview/retry primitives and frozen schedule registration. Continue
device topology integration and all remaining CM-R0–CM-R7 gates; this increment does not
complete the full migration.

## Retained evidence

Detailed earlier execution, native acceptance failures/recoveries and exact commits/logs
remain in [progress-through-6146dab.md](progress-through-6146dab.md). Search that archive
for the relevant owner. Durable implementation is in docs/ARCHITECTURE.md; findings and
native design files carry the specific ownership boundaries. Previous reopen gate:
563 pass, 0 fail, 7852 assertions across 64 files in 206.38s (exit 0), recorded in
/tmp/cm-topology-reopen-full.log at 73a1a26.
