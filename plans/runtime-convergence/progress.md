# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 remains the production Python
writer. No release, installation, live migration or default/service switch has occurred.
The 512-module/57-field ledger is an inventory, not completed parity.

Prior publication 049ebb7: exact-commit CI 34698466927 passed all required
jobs, including both Python versions, protocol/SDK/Web, container execution and isolated
installed-wheel smoke. It includes canonical device artifact verification and fixes the
bundled-schema drift that made the preceding 8d5dae2 CI fail.

Normal continuation controls are published at c7f46ce; exact-commit CI 34699492179 passed.
Current work integrates native structured topology results into local/device Claude
dispatch and evidence. Replacement full gate passed: 753 tests / 9722 assertions / 72 files /
282.51s, before final CLI dialect and native terminal fixes. Draft 7 scoped checks then
passed: 26 tests / 164 assertions / 37.20s. The native integration identified a real parser
defect: Claude can end at a successful StructuredOutput receipt, with no prose final.
Its JSONL also contains a structured_output attachment. The corrected stream/source parser
now verifies the retained actual worker output and an idle original session, using zero
new model inputs and without modifying the unknown task journal. It proves eight file
reads and one matching successful StructuredOutput call, not full parent completion.
Latest focused source/control/contract checks: 41 tests / 198 assertions / 15.29s; typecheck
passed. Full final-source runtime gate passed: 755 tests / 9744 assertions / 72 files / 284.03s,
exit 0 (/tmp/cm-structured-terminal-full.log), including configured container continuation.

A fresh real terminal-shape canary then accepted the worker through the full CM device
path (eight reads, native result/source, SpecMesh and container cleanup). The merger failed
native structured generation after five attempts: each emitted schema_version as string
"1", but the contract requires numeric 1. Native terminal reason was
structured_output_retry_exhausted; this is not provider quota. Its worker journal stays
unknown and the parent never completed; no continuation inputs occurred. Report:
structured-topology-terminal-native-acceptance-20260912 (accepted=false, do_not_replay=true).
No further real-model inputs are being issued in this checkpoint. Generation now explicitly
types schema_version as integer while acceptance continues rejecting strings. The 755-test
gate precedes this final additive schema hint; final typecheck and scoped/container checks
passed: 48 tests / 251 assertions / 4 files / 53.83s (/tmp/cm-structured-version-final.log).

Current implementation adds private local/coordinator reopen_schedule and
inspect_schedule_run controls. Explicit continuation archives the verified terminal run,
retains TaskHub/native identities and frozen roles/budgets, and activates the next normal
scheduler pass. Schedule/task/topology revisions, ownership and idle members are checked
transactionally. Duplicate requests return the original receipt without starting another
run. Full runtime gate passed: 740 tests / 9683 assertions / 71 files / 264.78s, exit 0
(/tmp/cm-schedule-reopen-full.log), with typecheck passing. Focused local/nested/device
checks: 103 / 1143 / 14.75s. Configured container continuation: 1 / 53 / 20.40s, retaining
both original session IDs with resume=true in second-run manifests. The native executable
is synthetic in that fixture; real-model continuation remains open.

A separate bounded native structured-output probe passed with actual Claude 2.1.263 and
MiniMax-M3: one input, two native turns, only StructuredOutput advertised/called, correct
schema fact and verified session/model identity. The pinned container was removed and
temporary credentials deleted. No prior native session was replayed. The capability is now integrated into the candidate control/evidence path with workspace
MCP; full real topology continuation remains unaccepted.

The published artifact increment enables canonical root acceptance for device-native results through
normal coordinator startup. Explicit device/workspace provenance and actual completed
run/effect evidence must match current files on the coordinator. Automatic file transfer
and remote-only final workspaces are still pending. Also fixed snapshot/contract file order
and refused within-workspace symlink aliases. Typecheck passes. Focused local/aggregate:
42 tests / 348 assertions / 9.12s. Device proof negatives: 9 / 65 / 2.35s. Full runtime gate
passed: 707 / 9114 / 71 files / 249.57s, exit 0 (/tmp/cm-device-artifact-full.log), including
the actual configured container path. Isolated-wheel Alpha smoke passed
(/tmp/cm-device-artifact-alpha.log); the production installation was untouched.
The first real canary stopped at schedule registration with zero native execution. The
corrected worker/merger canary has finished unsuccessfully: one preflight and one worker
turn occurred. Eight required files were read, but the final response included prose and
a Markdown fence around JSON. The scheduler blocked at team_result_invalid_json; merger
inspection returned assignment_unavailable. No merger turn, root completion or native
continuation occurred. Both reports are retained with do_not_replay=true. Neither artifact
canary remains running. Controlled tests do not substitute for this failed gate.

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

1. Publish the structured-output compatibility fix after final regression, then finish
   genuine topology continuation and artifact acceptance. Existing continuation control
   and canonical artifact publication both have passing exact-commit CI.
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
Also guarded: device-artifact[-configured]-native-acceptance-20260912 reports/scripts in
the same operator directory. The configured attempt ended at structured-result collection;
do not replay its worker session or relabel it as an artifact/continuation success.
Schema 26 rollback requires a pre-upgrade backup. Legacy pending assignments without a
frozen input block. Root artifact acceptance now supports already-delivered canonical files;
automatic transfer and remote-only final workspaces still need implementation/acceptance.

## Next

Publish verified normal root-reopen controls, then implement reliable structured native
results and genuine topology continuation. Complete remaining provider/transport/store/
terminal owners, file transport and rollout gates.
Do not replace the full goal with this scoped recovery or mark the original canary accepted.

## Retained evidence

[topology-scheduling.md](topology-scheduling.md) covers local/device configuration, controls,
input delivery, recovery and limits. Earlier guarded attempts remain in
[progress-through-6146dab.md](progress-through-6146dab.md); use targeted searches.
Durable boundaries are in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
