# Progress

## Current

Full goal active. CM-R0 through CM-R6 are in progress. The private TS kernel executes a concrete local OpenCode read profile with native continuation and headless History integration. An authenticated coordinator/worker port now also has real x64/ARM64 synthetic acceptance. Python remains the released production runtime; no writer cutover or new runtime release is claimed.

Current checkpoint: source/grant policy ports and trusted task issuance now feed the qualified native read worker/reconciler. The new issuance path passed real OpenCode SIGKILL/reopen/reconcile/same-session continuation while preserving provenance, narrowing grant and reply identity. Full production migration remains incomplete.

## Done

Source/grant checkpoint: TS execution context validation/issuance and async-local binding;
source-aware sandbox policy; provider flag mapping; narrowing submit grants; reply identity
checks; trusted TaskIngress with immutable channel binding, atomic task/grant/source/event
creation and original-trace idempotent replay. Unknown sources, forged body authority,
malformed persisted context and unsupported controller confirmation are denied before
native commands. The low-level kernel and legacy import preserve their separate ownership.

Verification: live Python oracle agrees on 689 policy/mapping/issuance/reply cases, including
native static tool expressions. Original Python grant/provenance golden tests passed (4).
Strict TS and the full core suite passed (96 tests / 1,291 assertions), including the
expanded authorization cases. Ruff/format and 512-module/57-field ownership baseline are current.

Actual OpenCode 1.18.29 / M3 acceptance on 2026-09-11 exercised TaskIngress, native dispatch,
SIGKILL after original observation, independent reconciliation (16 ms, no additional model
calls) and same-session continuation with marker recall and a changed current file read.
One issuance event, two manifests, two original observations and two confirmed effects;
source, narrowing grant and pinned reply identity were preserved. This is a controlled local
profile, not fleet-native or production default-switch evidence.

Native reconciliation checkpoint 6255eef5d8622e7647ddbaa3eed1a0e52300a6ce has exact-SHA
green CI 34584034790.

Native reconciliation checkpoint: SQLite schema 5 adds execution manifests and original effect observations. Dispatch and its manifest commit together before model execution; acceptance preserves the original observation and commits the result/task/event/receipt together. Native task/grant/config/session/workspace/file evidence is independently rechecked. Missing manifests, changed files/history/authorization, cancelled work and missing required reads remain unaccepted. Read-profile behavior is qualified against OpenCode 1.18.29.

Verification: strict TypeScript check; actual Bun 1.3.11 ran 84 core tests / 406 assertions. This includes a real OS worker killed after durable observation, transactional manifest failure before model execution, reconstruction without in-memory baselines and rejection of stale evidence. Python ownership inventory is unchanged/current (512 modules, 57 persisted TaskEntry fields).

Real native acceptance on 2026-09-11 used OpenCode 1.18.29 / M3. The harness suspended the worker immediately after its original observation committed and killed that process before task completion. A new process reopened SQLite and reconciled the original native read in 14 ms with zero model calls for reconciliation; repeated acceptance reused its receipt. A subsequent episode continued the same native session, recalled the earlier marker without reinjection and read the changed project file. Two original observations and two manifests remained, with two confirmed effects. No production writer/service cutover.

The first real trial reconciled successfully but its follow-up model reused an old answer without reading the changed file. CM rejected that episode and retained it as unknown. Upstream source confirms a custom Agent prompt replaces the model's default prompt. The worker now explicitly supplies and inspects the current-turn required-read instructions, while retaining mandatory native read evidence. A new controlled trial passed; the old unknown task was not automatically rerun.

Device checkpoint 5d76d8a164e8f0c2dbfe4cbe7619cb2e4dd0e609 has exact-SHA green CI 34581145600.

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

Connect the ported provider/source/grant policy to real launchers and native execution over
the device transport; its current adapter runs before returning its first observation, so
native preparation/manifest dispatch and immediate observation durability need explicit
hooks. Finish other persisted-store/recovery owners and independent SpecMesh checks against
current checkout state. Keep released Python ownership until every activation gate passes.
