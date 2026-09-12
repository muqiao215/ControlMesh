# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. This is substantial runtime development, not
release-only work. Installed CM 0.43.0 remains the production Python writer. No live
migration, release, installation, service switch or default cutover has occurred.
The 512-module/57-field ledger is a source inventory, not a completed parity score.
The phase acceptance matrix remains in task_plan.md.

The current increment adds explicit topology reopen and retained execution history to
all four local compositions. The full pinned gate passed; verify publication and CI
for this containing commit separately from local acceptance.
Previous main 63d841a has verified successful CI 34688699495.

## Done

- Explicit root reopen archives the old completion/state/configuration and advances
  task/topology revisions and fence under the same task ID. Schema 22 binds assignments
  to execution IDs; previous results/files cannot satisfy a new run. Controller/candidate
  queue admission rolls back with reopen on failure. Native identity uses child resume.
- New run counters reset under the original frozen limits; restarting the service does
  not reset them. Cancelled tasks cannot be reopened. Legacy schema 21 completion
  digests remain verifiable after upgrade.
- Current focused gate: 31 pass, 0 fail, 242 assertions across 2 files in 6.48s;
  runtime typecheck passed. Evidence: /tmp/cm-topology-reopen-focused.log. Four topology
  fixtures each complete three runs, with database restart and original child identity.
- Full pinned gate: 563 pass, 0 fail, 7852 assertions across 64 files in 206.38s
  (exit 0), including inventory drift and typecheck. Evidence:
  /tmp/cm-topology-reopen-full.log. No real provider/model input was submitted.

- Pipeline, fanout, director and judge compose accepted local child results with
  transactional queue transitions; budgets and assignment generations survive restart.
- Schema 21 seals current child run/episode/effect evidence with the terminal checkpoint
  and root completion. Event failure rolls back acceptance and finalization. Delivery
  projection consumes the topology result once, without inventing a provider episode.
- Parent file delivery now binds registered workspace/files, accepted child read/write
  evidence and current canonical bytes. Changed content, symlink, child revision,
  authority or requirements prevents completion. Restart repeats verification without
  repeating child execution; stored JSON cannot manufacture a live completion permit.
- Adopted SpecMesh file requirements retain their exact source path/hash through the
  independent plugin's check operation. This establishes file delivery only; reviewed
  project closeout remains unknown pending independent host acceptance.

## Remaining

1. Nested aggregate completion bindings; reviewed SpecMesh project closeout remains
   separate from file delivery.
2. Bounded automatic service scheduling and explicit malformed-output recovery.
3. Device topology queues with current assignment/revision/authority enforcement.
4. Real native topology/source-revision profiles and all remaining provider, transport,
   store and terminal product owners; complete ownership/parity evidence.
5. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

Do not replay failed native acceptance attempts or launch browser-account/cron/bot canaries
as a convenience test. Keep canceled tasks 77f04609/7738c5eb canceled. An observation
timeout does not establish that the original execution stopped. Candidate schema is now
22; rollback requires a pre-upgrade backup, not changing a populated database version.

Historical next-step instructions in task_plan.md were stale and competing; they have
been replaced by one current next action. Actual native failures and scoped acceptances
remain preserved in the linked archive rather than being relabeled as full completion.

## Next

Publish the verified explicit topology reopen directly to main. Then
implement nested aggregate binding, followed by automatic scheduling and device
topology integration. Do not mark the full migration complete for this increment.

## Retained evidence

Detailed earlier execution, native acceptance failures/recoveries and exact commits/logs
remain in [progress-through-6146dab.md](progress-through-6146dab.md). Search that archive
for the relevant owner. Durable implementation is in docs/ARCHITECTURE.md; findings and
native design files carry the specific ownership boundaries. Previous artifact gate:
546 pass, 0 fail, 7668 assertions across 63 files in 233.28s (exit 0), recorded in
/tmp/cm-topology-artifacts-full.log at 63d841a; its remote CI is verified above.
