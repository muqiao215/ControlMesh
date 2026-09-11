# Progress

## Current

Full goal active. CM-R0 through CM-R6 are in progress. The private TS kernel executes a concrete local OpenCode read profile with native continuation and headless History integration. An authenticated coordinator/worker port now also has real x64/ARM64 synthetic acceptance. Python remains the released production runtime; no writer cutover or new runtime release is claimed.

## Done

Pushed checkpoints have exact-SHA green CI: kernel/mailbox f65cc27 (34550244752), process supervision 011510e (34572737074), persisted preflight 62d63ef454d99d246fdb186dd7d37e3ece2c121e (34575403674). The workflows include complete Python 3.11/3.12 suites, protocol/golden/SDK/Web, build and installed-wheel smoke. Commit history retains earlier implementation details.

Native execution checkpoint 45c7ebae7d28694958f3708b2259a95becea93fd has exact-SHA green CI 34578358722; paired Viewer native-reference commit ce912f8c3572a007424650d71136e254e96c7c2e has green CI 34578340190.

Device checkpoint: persisted digest-bound assignments and revocations; configured credential/device/owner mapping; bounded private HTTP commands; conservative suspend-aware lease windows; lease deadline passed to the process anchor; local workspace/executable maps; explicit cross-device mailbox peers; atomic observed-effect completion. JSON Schemas, generated models and bundled Web schemas are synchronized. Schema v1/v2/v3 upgrade to v4 is additive; no live Python store is migrated.

Verification for the device checkpoint: strict TS typecheck; actual CI-version Bun 1.3.11 ran 77 core tests / 330 assertions; Python protocol 9 tests and generated-model Ruff passed. A SIGSTOP-frozen controller's real process family exited at its device lease deadline. Actual x64 Linux + ARM64 Linux/Bun 1.4.1 canary used authenticated pinned-SSH forwarding: one concurrent claimant, another device's post-expiry reclaim, old-fence refusal, distinct local workspace reads, cross-device message receipt/application, remote process termination on partition, and coordinator reopen preserving unknown outcomes with no automatic retry. Device revocation and stale credentials are also covered, including reconstruction and revocation during a slow request body. The synthetic driver makes no model/provider-account/browser/bot calls.

Current implementation adds native-reference v2, Python-compatible Linux session flocks, a headless History client and OpenCodeWorker. The worker verifies task/source/grant/model/native bindings, passes bounded stdin verbatim, persists unaccepted observations, and checks native append lineage/output/required reads before atomic effect confirmation and completion. Explicit resume keeps original native lineage. Cancelled/unknown work is not auto-resumable. Execution quota errors revoke matching readiness without overwriting newer probes.

Verification: strict TS check and 65 core tests (276 assertions) passed on actual Bun 1.3.11. Viewer full Python suite passed 195 tests. The identical cross-repository synthetic fixture verifies content hashing with Unicode/null/REAL data; regression cases cover old-content edits, store/device changes, concurrent input, lost completion, cancellation and unsafe resumed permissions.

Real native acceptance on 2026-09-11: OpenCode 1.18.29 / minimax-cn-coding-plan/MiniMax-M3; first turn remembered a marker and read PROJECT.md; Viewer returned a headless candidate and CM independently revalidated it; second kernel episode resumed the same native session, recalled the marker without reinjection and read the changed file. Two effects were confirmed. The first failed canary exposed CLI quoting and relative read-permission semantics; it remained unknown and was not automatically repeated. These are controlled same-device/provider results, not full migration acceptance.

Baseline: 512 Python source owners and 57 serialized TaskEntry fields. Strict snapshot import/export preserves unknown fields and cancelled tasks. Read-only live snapshot preview found one done and two cancelled tasks, no active work; no task folder or writer changes.

## Remaining

Complete CM-R0 through CM-R7: all source/grant/provider/transport owners, other persisted stores, explicit reconciliation and migration exclusion/rollback, production provider/grant adapters over the device port, fleet presence/rotation/fairness/rollout, mailbox native application, independent SpecMesh lifecycle gates, production/default switch, release/install/running alignment. Native continuation and two-device synthetic canaries close only their stated matrix cases.

## Issues

No blocking condition. Legacy TaskRegistry construction performs destructive orphan cleanup; never construct it against live migration input. Standalone native clients ignore CM advisory locks; unexpected native changes invalidate acceptance rather than being silently adopted. Process groups provide lifecycle containment, not hostile-code isolation.

## Next

Implement explicit native outcome reconciliation; connect provider/source/grant enforcement to the device transport; integrate SpecMesh's independent checks against current checkout state. Keep released Python ownership until every activation gate passes.
