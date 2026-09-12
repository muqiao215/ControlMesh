# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 remains the production Python
writer. No release, installation, live migration or default/service switch has occurred.
The 512-module/57-field ledger is an inventory, not completed parity.

Published cd4a47f matches origin/main and has successful CI 34694128788. This schema-26
increment closes a real native-input gap: Agents now receive frozen role/stage/output
contracts and prior results through verified native mailbox delivery. Full local verification
passed: 688 tests / 8937 assertions, 68 files, 220.41s, exit 0; inventory drift and typecheck
passed (/tmp/cm-topology-input-final.log). A final visibility check then made missing device
context visibly block its schedule; its full device-topology suite and typecheck passed
(33 tests / 322 assertions, 4.84s, /tmp/cm-topology-input-visibility.log). Publication/CI remain pending.

## Done

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

1. Publish/verify this input-delivery increment; investigate native task-contract failure
   recovery using retained evidence, without replaying the failed reviewer attempt.
2. Complete real native topology and current-source acceptance, remote root artifact
   validation, reviewed SpecMesh closeout and pending candidate-input migration.
3. Complete remaining provider, transport, store and terminal owners and the parity ledger.
4. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

No replay of guarded native failures or browser-account/cron/bot canaries. Keep tasks
77f04609/7738c5eb canceled. Observation timeout does not prove execution has stopped.
Add topology-input-native-acceptance-20260912 to the guarded attempts. Its reviewer is
stale with reconciliation required; do not invoke the script again or send another prompt
to its sessions. The original script and full test process both reached terminal states.
The canary is not accepted; its report records actual native calls and do_not_replay=true.
Retained operator workspace: outputs/runtime-convergence/topology-input-native-acceptance-20260912.{json,log,ts}.
Schema 26 rollback requires a pre-upgrade backup. Legacy pending assignments without a
frozen input block; remote root file completion still requires a future remote artifact gate.

## Next

Publish this tested native-input increment, then distinguish provable task-contract failure
from uncertain external execution using retained native evidence. Finish real topology,
source and artifact acceptance and all remaining CM-R0–CM-R7 owners and rollout gates.
Do not replace the full goal with these scoped checks or mark the failed canary accepted.

## Retained evidence

[topology-scheduling.md](topology-scheduling.md) covers local/device configuration, controls,
input delivery, recovery and limits. Earlier guarded attempts remain in
[progress-through-6146dab.md](progress-through-6146dab.md); use targeted searches.
Durable boundaries are in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
