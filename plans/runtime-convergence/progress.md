# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 is still the production Python
writer. No release, installation, live migration or default/service switch has occurred.
The 512-module/57-field ledger is an inventory, not a completed parity score.

Published f45c1ab has successful CI 34692640944. This schema-25 increment adds
device topology execution, normal startup/control and coordinator-wide admission limits.
Full pinned verification passed: 680 tests / 8884 assertions across 68 files, 218.98s,
exit 0 (/tmp/cm-device-topology-full.log), including inventory drift and typecheck.
Remote publication/CI remain separate from local acceptance.

## Done

- Local scheduling supports four topologies, sixteen nested combinations, persisted
  registration, background startup, bounded recovery, origin and fenced completion.
- Device execution reuses authenticated coordinator/worker queues. Atomic claim binds the
  actual device/episode/fence and checks global admission capacity across worker restarts.
  Assignment and execution digests are rechecked before accepting child output.
- Explicit routes retain native handles on the issuing authorized device. Local queue or
  missing coordinator ownership cannot substitute for remote execution evidence.
- Released/expired admissions disappear from discovery. Explicit bounded recovery retains
  task IDs and rejected evidence; unknown effects and canceled work are not replayed.
- Normal coordinator configuration/control/CLI starts optional background scheduling and
  supports recovery/cancel without model credentials. EOF/SIGTERM behavior is verified.
- Schema 24 to 25 preserves paused registration, completed local proof and task identities;
  restarting does not reopen completed work or replay paused tasks.
- Focused gate: 72 pass / 675 assertions, 3 files, 9.35s, before the final cap addition;
  then 30 pass / 305 assertions, 1 file, 3.74s for device topology and negative cases.
  Logs: /tmp/cm-device-topology-control-focused.log and /tmp/cm-device-topology-negative.log.
- Current full pinned gate: 680 pass / 8884 assertions, 68 files, 218.98s, exit 0;
  inventory drift and typecheck passed. Log: /tmp/cm-device-topology-full.log.
- Prior full gate at f45c1ab: 645 pass / 8529 assertions, 67 files, 213.47s, exit 0.
  Log: /tmp/cm-topology-scheduler-full.log.

## Remaining

1. Verify publication and CI for this tested device topology increment.
2. Real native topology/current-source acceptance, remote root artifact validation and
   reviewed SpecMesh project closeout.
3. Remaining provider, transport, store and terminal owners; complete parity ledger.
4. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

No replay of guarded native failures or browser-account/cron/bot canaries. Keep tasks
77f04609/7738c5eb canceled. Observation timeout does not prove execution has stopped.
Schema 25 rollback requires a pre-upgrade backup. Device root file completion remains
blocked without a remote artifact gate. Controlled HTTP adapters are not native-model
acceptance. The original full verification completed with exit 0; do not repeat unchanged checks.

## Next

Verify remote publication/CI for this bounded device increment, then continue native
topology/current-source and remote artifact
acceptance, followed by all remaining CM-R0–CM-R7 owners and rollout gates.

## Retained evidence

[topology-scheduling.md](topology-scheduling.md) covers local and device configuration,
controls, recovery and current limits. Earlier execution and guarded native attempts remain
in [progress-through-6146dab.md](progress-through-6146dab.md); use targeted searches.
Durable ownership boundaries are in ../../docs/ARCHITECTURE.md.
