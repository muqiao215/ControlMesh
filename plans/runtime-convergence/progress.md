# Progress

## Current

Full goal active; CM-R0 through CM-R6 remain in progress and CM-R7 is not activated.
Python v0.43.0 remains the released/installed production runtime. The private TS kernel now
supports a qualified OpenCode read profile, native continuation, device coordination and
explicit recovery of a result lost between the device and coordinator. Other provider,
write/sandbox, transport, store and product owners remain required for full migration.
One-shot routing/result handling and host execution shipped at `0b01ea2` with exact-commit
green CI 34597493500. The next implemented unit is actual per-execution container lifecycle
and its one-shot integration; native provider image/auth/state qualification remains open.

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
- One-shot execution: OpenCode/Claw use their own command builders; unsupported SDK engines
  return a typed error instead of silently running Claude. Grants are applied inside command
  construction after the provider verb. Native errors and missing completion cannot become
  success merely because a CLI exits zero. OpenCode stdin is literal and its trusted stderr
  quota record aborts retries with reset metadata preserved. Original exit/cancel causes hold.
  The TS host port uses actual process supervision and current source/grant/readiness/workspace
  checks; scheduler/native-adoption/container/delivery ownership is not implied.
- Container execution: a pinned image, nonroot process, read-only root, specific writable
  project mounts, explicit network, namespace/capability/resource restrictions and inspected
  identity precede launch. An inner PID 1 watcher expires a boot-bound lease independently of
  the host. Actual tests cover write/network boundaries, quota abort, detached descendants,
  concurrent cancellation, controller SIGKILL/SIGSTOP, lost create acknowledgement and cleanup.
  Versioned, durable intent/identity records prevent replay. Unconfirmed creation with no
  observed immutable ID remains unknown; absence cannot close a still-pending daemon request.
  Cleanup resolves only the original owned container and never starts it. The one-shot caller
  retains source/confirmation/native tool checks while outer isolation enforces network/roots.

Container local verification: strict TS and CI-version Bun 1.3.11 passed **132 core tests /
1,987 assertions**, including real Docker execution and the existing **410 live Python/TS
one-shot comparisons**. The container file has two planning/lease unit cases and seven cases
using the actual daemon; the native CLI in its quota case is a controlled fixture. Docker
29.1.3 on x64 Linux used the pinned Node 22 image recorded in findings. All actual containers
created by acceptance are removed. Unknown-create fixtures intentionally retain uncertainty
in their isolated test records and issue no provider call. Reboot protection is a boot-ID
fault/unit check, not a physical machine reboot acceptance. A new required CI container job
will run the actual daemon tests independently of optional local image availability.

Ruff, ownership check and whitespace checks passed. No Python source changed in the container
batch. Previous one-shot Mypy and full Python 3.11/3.12 suites passed at `0b01ea2` in CI.
No new real account/model calls, production scheduler runs, installation or default switch
were performed. Final exact-commit CI is verified after publication.

Initial container commit `6b6b221` passed its actual-container and product/build gates in CI
34600620577. Both Python versions had one failure / 5,732 passes because the workflow test
still required the old exact job set. The test now requires all mandatory gates, including
container execution, while permitting future additional gates. Follow-up exact-commit CI
must pass before publication is recorded as green.

Prior device-recovery verification included Python protocol **9 passed**, generated-model
Ruff and Web build. Canonical schemas and TS/Python/Web generated assets remain synchronized.
Tests cover lost original observation,
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

Device recovery commit `e86604a543216be53424b74e2dfcf48f9881a53c` has exact-SHA green CI
34593893922. Local HEAD and origin/main matched after publication.
Earlier implementation history is in Git; it is not duplicated here.

## Remaining

All original CM-R0–CM-R7 gates remain authoritative: remaining provider/transport/workspace/
artifact owners, native provider write and container image/auth/state qualification, other persisted runtime stores,
writer exclusion and rollback, existing History session adoption, native mailbox application,
independent SpecMesh current-checkout/lifecycle gates, fleet enrollment/rotation/fairness and
real topology execution, terminal product work, default TS switch, Python retirement and
release/install/running alignment. A qualified native read profile and isolated process tests do not
establish complete production migration.

## Issues

No blocking condition. Never construct legacy TaskRegistry against live migration input:
its constructor performs orphan cleanup. Standalone native clients do not honor CM advisory
locks. Remote authentication attests the reporting device, not its honesty; native/file
verification describes the device snapshot checked before report delivery. The read profile
and task evidence do not automatically promote history into authoritative project truth.

## Next

Verify container publication CI, then qualify actual provider images with scoped credentials
and persistent native state, preserving native directory identity for real continuation.
Connect the implemented execution owners to task/transport ingress and native mailbox work,
then continue stores, History adoption, SpecMesh lifecycle and the production writer switch.
The current Node-image process profile is not a substitute for native provider qualification.
