# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 is still the production Python
writer. There has been no live migration, release, installation or default/service switch.
The 512-module/57-field ledger is an inventory, not a completed parity score.

Published 725f22c has verified successful CI 34691621283. Current local work adds automatic
topology scheduling through normal isolated configuration and JSON-lines control, with
candidate database schema 24. Full pinned verification passed: 645 tests / 8529 assertions
across 67 files, 213.47s, exit 0. Remote publication/CI are separate from local acceptance.
This does not establish device topology integration or real native-model topology acceptance.

## Done

- Immutable schedule plans bind existing task IDs, roles, budgets and aggregate graph.
  Registration is paused; activation and optional background startup are explicit. Model
  decisions cannot add tasks/roles/grants. External/overlapping assignments reject.
- Pipeline, fanout, director and judge progress through existing atomic local compositions,
  including all 16 nested combinations. Aggregates wait for actual parent dispatch.
  Preview does not accept output; committed steps revalidate task/checkpoint/effect state.
- Fenced schedule leases serialize async artifact admission. Pause or a replacement owner
  invalidates pending publication. Normal shutdown retains active plan state; paused,
  blocked and completed states persist. Already-admitted native work keeps its lifecycle.
- Private normal startup exposes register/activate/pause/inspect, answer and explicit retry
  controls. Optional EOF keepalive and signal shutdown work in the actual CLI process.
  Automatic transition events record schedule origin without changing actor authorization.
- Existing bounded malformed-output recovery retains rejected proof and original sessions;
  polling never retries blocked native work. Unknown/cancelled work remains unreplayable.
  Frozen repair/interruption policy stops loops; two explicit native retries survive restart.
- Focused gate: 68 pass, 0 fail, 462 assertions across 3 files, 6.62s. Typecheck passed.
  Evidence: /tmp/cm-topology-service-focused.log. Controlled resolvers/negative artifact
  fixture and a credential-free actual CLI test; no new native-model prompts.
- Current full gate: 645 pass, 0 fail, 8529 assertions across 67 files in 213.47s (exit 0),
  including inventory drift and typecheck. Evidence: /tmp/cm-topology-scheduler-full.log.
- Previous full recovery gate at 725f22c: 612 pass, 0 fail, 8283 assertions across 66 files,
  209.12s, /tmp/cm-topology-recovery-full.log. Earlier aggregate/reopen evidence and actual
  scoped native/device/History/SpecMesh acceptances remain in Git and the archive below.

## Remaining

1. Bind immutable topology plans to device coordinator/worker queues and recovery.
2. Real native topology/source-revision acceptance and reviewed SpecMesh project closeout.
3. Remaining provider, transport, store and terminal product owners; complete parity ledger.
4. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

Do not replay failed native acceptance attempts or launch browser-account/cron/bot canaries.
Keep canceled tasks 77f04609/7738c5eb canceled. An observation timeout does not prove that
an execution stopped. Candidate schema 24 rollback requires a pre-upgrade backup.
Full verification process completed with exit 0; do not repeat unchanged checks.

## Next

Implement device topology assignment/dispatch using the published local schedule contract,
then qualify real native topology execution and source revision handling. Complete all remaining
CM-R0–CM-R7 owners; this local service does not replace full migration acceptance.

## Retained evidence

The local service contract and controls are in [topology-scheduling.md](topology-scheduling.md).
Detailed earlier execution and original native failures/recoveries remain in
[progress-through-6146dab.md](progress-through-6146dab.md). Search that archive for the
relevant owner. Current durable runtime boundaries are in docs/ARCHITECTURE.md.
