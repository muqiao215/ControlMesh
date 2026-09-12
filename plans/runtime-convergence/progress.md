# Runtime convergence progress

## Current

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 is still the production Python
writer. No release, installation, live migration or default/service switch has occurred.
The 512-module/57-field ledger is an inventory, not completed parity.

| Delivery area | Verified state | Remaining acceptance |
|---|---|---|
| Published CI baseline | e2b16e3; CI 34709699732 success | Verify persistent local service checkpoint after publication |
| TS runtime | Kernel, local/device execution, mailbox, topology and retained recovery; reconnectable local service/CLI with full local regression | Final CI; remaining provider/transport/store/terminal ownership and parity |
| Native continuation | Simple direct and streamed exact recall passed; earlier topology first runs and current artifacts passed | Full worker/merger continuation and complex-context acceptance still fail |
| Multi-device | Earlier physical ARM64/x64 evidence; bounded HTTP artifact inbox/upload/recovery; opt-in canonical publication with CI | Initial workspace distribution, physical transfer acceptance and full profiles |
| SpecMesh/History | Independent integration and scoped continuity evidence exist | Reviewed closeout and remaining full integration acceptance |
| Release/local alignment | Production still Python 0.43.0 | Full-goal acceptance, release/install, staged default switch |

Latest real attempt structured-topology-resume-native-acceptance-20260912 finished with
accepted=false after its first worker, zero successful required reads and no continuation.
Native read calls sent expected_sha256="missing" for existing files. The retained evidence
shows invalid read arguments, not a proven concurrent file change. The attempt and session
05a0e591-a529-4401-b28a-932b3e948f95 are guarded against replay. No new native model canary
was launched during this correction.

Current checkpoint adds a persistent local service and normal `pnpm runtime` command entry.
It reuses LocalTaskRuntime, task/event read authority and the existing native queue; clients
reconnect over a private Unix socket. OS-held listener locking precedes profile startup.
Client timeout never retries/cancels execution; another connection can cancel in-flight work.
CLI SIGKILL/restart, original task/cancellation retention and normal shutdown passed (four
CLI tests / 39 assertions / 5.85s). Socket cases passed for pages, concurrency, lock/path
protection, frame bounds and Chinese input. A configured Docker case passed one test /
161 assertions / 16.37s: automatic execution after client disconnect, service restart and
same-native-session continuation with changed current files. Claude is synthetic in that
case; it is not new model or physical-device acceptance. Typecheck passed. Full regression
passed 803 tests / 10317 assertions / 75 files / 447.07s, exit 0, at
/tmp/cm-runtime-service-full.log. Normal `pnpm runtime --help` also passed. Final commit/CI
remain pending. This changes no database or public protocol schema. Service usage and
limits: [local-control-service.md](local-control-service.md). No production service was changed.

The published e2b16e3 checkpoint connects accepted inbox bytes to optional canonical publication.
Database 28 and a sparse WorkspaceStage capture write-file baselines before child dispatch,
preserve unrelated local edits, reject conflicting changes and recover per-file progress.
All writes check scheduler authority. Independent SpecMesh checks bracket publication.
Focused tests passed: 19 stage tests / 82 assertions and 21 expanded HTTP/native-fixture
integration tests / 264 assertions / 57.43s. Configured Docker, restart, pause and independent
SpecMesh cases passed; typecheck passed. Log: /tmp/cm-canonical-configured.log.
Full regression: 789 passed / one test-double timeout / 790 cases / 10075 assertions /
73 files / 364.85s, exit 1 (/tmp/cm-canonical-full.log). The old preparation double omitted
the new step method; its correction and early-exit reporting passed the full scheduler file:
62 tests / 669 assertions / 25.88s (/tmp/cm-canonical-scheduler.log). Typecheck passed after
the correction. Production code was unchanged; final exact-commit CI 34709699732 passed.
The separate local runs were not represented as one green full run. No model input launched.

The preceding checkpoint implements opt-in native completion-file upload over the authenticated
worker port. Database 27 stores bounded chunks; terminal acceptance independently verifies
full bytes against the original completion evidence. Normal worker execution and explicit
retained-result recovery use the same receipts. Local read_artifact provides current accepted
bytes by task/effect/path. It does not overwrite canonical project files or copy native stores.

Focused checks passed: 94 tests / 975 assertions / four files; additional authority/budget/
upgrade checks: 8 tests / 31 assertions. Typecheck and nine Python protocol tests passed;
generated protocol models and bundled Web assets were rebuilt. Full runtime regression passed:
774 tests / 9918 assertions / 73 files / 323.71s, exit 0 (/tmp/cm-device-artifacts-full.log). Initial setup failures were an old-schema fixture
retaining the new table and the generated Python ownership hash needing regeneration.
Neither required weakening runtime checks. Controlled HTTP/native fixtures are not new
physical-host or model acceptance. No new model input was launched this turn.

Previously published native retry/read-guidance fixes passed 760 tests and exact-commit CI.

Remote release metadata and the installed Python environment were checked: CM v0.43.0
and local 0.43.0; History Viewer latest release v1.1.0, checkout 8070b9c (four later
commits); SpecMesh latest release v1.2.1, checkout d393c54 (two later commits). These
other checkouts were not modified; their latest source is not wholly in those releases.

Earlier complex-context diagnostics proved the old marker was present in actual upstream
continuation requests but did not establish successful model recall. Their observer errors
and the latest invalid read request must not be conflated with missing native history.
Detailed evidence and guarded attempts are in findings.md; no failed result was relabeled.

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

1. Publish the verified persistent service and check exact-commit CI; then connect the interactive terminal frontend to this owner.
2. Complete initial workspace distribution and physical transfer/publication acceptance. Finish real
   topology/current-source acceptance and reviewed SpecMesh closeout; guard failed attempts.
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
Schema 28 rollback requires a pre-upgrade backup. Legacy pending assignments without a
frozen input block. Automatic publication is opt-in, with a baseline captured before initial
dispatch; earlier in-flight schedules cannot acquire that baseline retroactively. Interrupted
multi-file publication can leave partial progress; inspect and explicitly recover its journal.

## Next

Publish the verified persistent service and check exact-commit CI. Connect the terminal
frontend to the same owner and qualify initial workspace delivery/two-device publication. Continue the other
runtime owners and full rollout gates. Do not return to repeated similar model probes.

## Retained evidence

[topology-scheduling.md](topology-scheduling.md) covers local/device configuration, controls,
input delivery, recovery and limits. Earlier guarded attempts remain in
[progress-through-6146dab.md](progress-through-6146dab.md); use targeted searches.
Durable boundaries are in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md).
