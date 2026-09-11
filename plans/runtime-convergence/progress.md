# Progress

## Current

Full goal active; CM-R0 through CM-R6 remain in progress and CM-R7 is not activated.
Python v0.43.0 remains the released/installed production runtime. The private TS kernel now
supports a qualified OpenCode read profile, native continuation, device coordination and
explicit recovery of a result lost between the device and coordinator. Other provider,
write/sandbox, transport, store and product owners remain required for full migration.

## Done

- Transactional TS kernel: task revisions, fenced episodes, immutable dispatch/observation
  evidence, idempotent receipts, cancellation, deadlines, unknown-outcome recovery and mailbox.
  Snapshot import/export preserves all 57 serialized TaskEntry fields and unknown fields;
  the complete Python source inventory tracks 512 modules. This inventory is not a claim
  that those owners have all been ported.
- Process ownership: guarded Linux process groups, independent process anchor, cancellation
  and lease expiry, including frozen-controller and partition tests. This provides lifecycle
  control; hostile-code isolation still needs the actual sandbox/provider launchers.
- Source/grant ports: trusted TaskIngress, immutable provenance and grant narrowing, reply
  identity, provider policy/mapping; 689 live Python/TS differential cases agree. Typed
  native quota/auth/model preflight is durable and bounded. Unknown/denied quota does not
  become repeated model calls or newly authorized human prompts.
- Native OpenCode 1.18.29 read profile: same-session continuation, native-reference v2,
  headless Viewer inspection with independent native revalidation, original file/permission/
  source evidence and explicit local reconciliation. Required current-turn native reads are
  verified; successful model output alone does not complete the task.
- Device coordinator/worker: credential and capability binding, logical workspace maps,
  durable revocation, fenced leases, explicit peer messages, device-local manifests and
  native handles. Actual x64/ARM64 runs cover claim/reclaim/partition and native continuation.
- New device recovery: schema 7 persists a trusted, expiring challenge. The configured
  adapter rereads original device/native/file evidence without any model, CLI or preflight
  invocation. Agent reports and recovery acceptance keep distinct provenance. Missing original
  observation, confirmed result, terminal task and receipt commit together; existing
  observations cannot be replaced. Receipt replay also updates the matching local record.
  Current cancellation, task/assignment/grant/configuration changes, device revocation,
  challenge expiry and invalid evidence prevent acceptance.

Latest local verification: strict TS passed; actual CI-version Bun 1.3.11 ran **117 core tests /
1,510 assertions**, all passed. Python protocol **9 passed**; generated-model Ruff, Web build,
source ownership regeneration/check and diff whitespace check passed. Canonical schemas and
TS/Python/Web generated assets are synchronized. Tests cover lost original observation,
already delivered observation, recovery acknowledgement loss, reconstruction, cancellation,
expiry, revoked devices, changed files/native rows/configuration, conflicting evidence,
atomic rollback and additive schema-6-to-7 migration preserving device records.

Actual acceptance on **2026-09-11 11:20:38–11:21:58 UTC**: ARM64 Rock 5C coordinator and x64
OpenCode 1.18.29/M3 worker. After the first native answer was retained locally, the coordinator
stopped before receiving it. Coordinator process and local worker database reopened; lease
expiry left the task unknown. An explicit recovery request accepted the original result in
**130 ms with zero OpenCode commands/model calls**, then replayed the same receipt. The
original observation digest remained unchanged. A following episode resumed the same native
session, recalled the marker without reinjection and read the changed PROJECT.md. Two device
records completed, two coordinator effects confirmed, preflight generation stayed 1 and
source/grant/report/recovery provenance held. No provider credentials or native file paths
were copied to the coordinator. This is not evidence of an ARM64 provider executing natively.

The ephemeral device credential was revoked. Independent SSH inspection confirmed the
canary artifact directory absent and no matching coordinator process. Private evidence and
bundled-source hash are retained outside Git under the workspace's
`outputs/runtime-convergence/device-recovery-*`; the accepted implementation is the final
source used by that canary. History Viewer, SpecMesh and Ops repositories were unchanged.

Previous device-native commit `10e96df8f3b2516c5671bf85121a133fa5f91024` has exact-SHA green CI
34589616324. This recovery change still needs its own commit/push and exact-SHA CI conclusion.
Earlier implementation history is in Git; it is not duplicated here.

## Remaining

All original CM-R0–CM-R7 gates remain authoritative: remaining provider/transport/workspace/
artifact owners, native write and actual sandbox execution, other persisted runtime stores,
writer exclusion and rollback, existing History session adoption, native mailbox application,
independent SpecMesh current-checkout/lifecycle gates, fleet enrollment/rotation/fairness and
real topology execution, terminal product work, default TS switch, Python retirement and
release/install/running alignment. A read-only native profile and 117 passing tests do not
establish complete production migration.

## Issues

No blocking condition. Never construct legacy TaskRegistry against live migration input:
its constructor performs orphan cleanup. Standalone native clients do not honor CM advisory
locks. Remote authentication attests the reporting device, not its honesty; native/file
verification describes the device snapshot checked before report delivery. The read profile
and task evidence do not automatically promote history into authoritative project truth.

## Next

Commit/push the verified recovery path and inspect its exact-SHA CI. Continue with actual
sandbox/provider launchers and remaining transport/store owners, then History adoption,
SpecMesh lifecycle integration and the production writer switch under the full plan's gates.
