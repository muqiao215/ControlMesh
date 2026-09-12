# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 remains the production Python
writer. No release, installation, live migration or default/service switch has occurred.
The 512-module/57-field ledger is an inventory, not completed parity.

Published 12c9bba (native topology input delivery) has successful exact-SHA CI
34695456970. This increment fixes verified read-only Claude required-read failures across
local/device completion and recovery. Retained real reviewer recovery passed without
another model or tool invocation. Its original topology canary remains failed.

Full runtime gate passed: 697 tests, 9018 assertions, 69 files, 236.71s, exit 0
(/tmp/cm-native-failure-full2.log), including ownership drift and typecheck. A final scoped
change clears the previous missing-read error when explicitly resuming; kernel/local Claude
checks and typecheck then passed (31 tests, 188 assertions, 4.30s,
/tmp/cm-native-failure-resume.log). Python protocol: 9 pass. All four generated protocol
files reproduce unchanged. Publication and remote CI for this increment are pending.

## Done

- Real retained reviewer recovery: failed, no reconciliation needed, seven missing reads,
  original session and native/project bytes preserved, context consumed. Duplicate acceptance
  emitted no events. Zero model/broker/build calls; one local flock helper. The original
  topology canary remains failed and no native prompt was replayed.

- Local/device topology dispatch supports four root kinds and sixteen nested pairs, frozen
  plans/routes, bounded recovery, source-bound results and persisted global admission caps.
- New dispatch snapshots include role, stage, round, prior results and the shared output
  schema. Real Agents do not need coordinator SQLite access to learn their assignment.
- Assigned leases obtain only their own context. Missing/altered context rejects claim;
  device native dispatch cannot omit its delivery. Oversize input blocks before another
  role executes. The existing mailbox order, bounds and consumption proof remain intact.
- Focused input tests: 74 pass / 618 assertions, 3 files, 7.55s; subsequent claim/queue
  negatives: 33 pass / 319 assertions, 1 file, 3.94s. Logs:
  /tmp/cm-topology-input-focused.log and /tmp/cm-topology-input-admission.log.
- Full input gate including expired-message refusal: 688 pass / 8937 assertions, 68 files,
  220.41s, exit 0. Final missing-context visibility change: 33 device tests / 322 assertions,
  4.84s and typecheck passed. Remote CI will cover the published final source together.
- Real Claude/MiniMax-M3 worker consumed its topology input, read all seven required
  current documents and produced accepted structured output. A reviewer then received
  prior worker output but made zero file tool calls and failed required-read verification.
  One preflight and two task inputs occurred; the planned reopen/resume never ran.
- Prior cd4a47f full gate: 680 pass / 8884 assertions, 68 files, 218.98s, exit 0.
  Log: /tmp/cm-device-topology-full.log. Prior f45c1ab CI 34692640944 also succeeded.

## Remaining

1. Publish the verified known-failure increment and verify its remote SHA/CI.
2. Complete real native topology and current-source acceptance, remote root artifact
   validation, reviewed SpecMesh closeout and pending candidate-input migration.
3. Complete remaining provider, transport, store and terminal owners and the parity ledger.
4. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

No replay of guarded native failures or browser-account/cron/bot canaries. Keep tasks
77f04609/7738c5eb canceled. Observation timeout does not prove execution has stopped.
Add topology-input-native-acceptance-20260912 to the guarded attempts. Its reviewer is
now confirmed failed after retained-evidence recovery; do not invoke the original script
again or send another prompt to its sessions. The original script and full test process both reached terminal states.
The canary is not accepted; its report records actual native calls and do_not_replay=true.
Retained operator workspace: outputs/runtime-convergence/topology-input-native-acceptance-20260912.{json,log,ts}.
Schema 26 rollback requires a pre-upgrade backup. Legacy pending assignments without a
frozen input block; remote root file completion still requires a future remote artifact gate.

## Next

Publish the verified known-failure increment. Continue real topology, current-source and
remote artifact acceptance, then finish remaining CM-R0–CM-R7 owners and rollout gates.
Do not replace the full goal with this scoped recovery or mark the original canary accepted.

## Retained evidence

[topology-scheduling.md](topology-scheduling.md) covers local/device configuration, controls,
input delivery, recovery and limits. Earlier guarded attempts remain in
[progress-through-6146dab.md](progress-through-6146dab.md); use targeted searches.
Durable boundaries are in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
