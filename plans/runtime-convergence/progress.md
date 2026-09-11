# Progress

## Current

Published baseline `ae9861152eadb4e0fae1b40054df5191ef2ff752` includes cross-device native
Agent communication and has verified green CI
[34622269044](https://github.com/muqiao215/ControlMesh/actions/runs/34622269044).
Two OpenCode Agents used scoped MCP send/ask_parent/receive/answer with the coordinator
on ARM64 and execution on x64. Original-session recall and outcome reconciliation after
coordinator reopen passed without executing another native command.

Current increment: automatic device initial mailbox input, compact dispatch bindings and
atomic reservation/consumption are implemented. CI-version Bun with the qualified Docker
image passed 192 core tests / 2,500 assertions; TS, Web build, nine Python protocol tests,
Ruff and the 512-module/57-field ownership drift check passed. Real ARM64-coordinator/x64
OpenCode initial-input acceptance and independent readback passed, including lost completion,
model-free recovery and original-session recall without redelivery. Publication of this
increment is being completed; earlier CI is not its acceptance.

Full goal active; CM-R0 through CM-R6 remain in progress and CM-R7 is not activated.
Python v0.43.0 remains the released/installed production runtime. The private TS kernel now
supports a qualified OpenCode read profile, native continuation, device coordination and
explicit recovery of a result lost between the device and coordinator. Other provider,
write/sandbox, transport, store and product owners remain required for full migration.
One-shot routing/result handling and host execution shipped at `0b01ea2` with exact-commit
green CI 34597493500. Per-execution container lifecycle and original-directory mapping shipped
with exact-SHA green CI at `8fd3f2f`. The OpenCode read profile now has real container/native
auth/state/continuation acceptance; general write, other provider and production ingress
qualification remain open.

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
- Container OpenCode read driver: narrowly selected persistent native data/cache, read-only
  auth overlay, temporary HOME/config and runtime-bound preflight/dispatch. A real Git project
  passed trusted TaskIngress -> model preflight -> native task -> coordinator/runner reopen ->
  same-session resume -> confirmed result. Headless Viewer independently revalidated the first
  native reference. The second turn recalled a marker without reinjection and read the changed
  PROJECT.md. Both episodes were done and both effects confirmed. The production writer and
  scheduler/transport startup were not switched.

Container native verification: strict TS and CI-version Bun 1.3.11 full core passed **140 tests /
2,019 assertions**, including actual directory/resource mounts and both original and new provider
binding checks. The subsequent worker suite passes **12 tests / 135 assertions**, including
host/container admission separation; strict TS and both Python CI-workflow tests also pass.
Real acceptance on **2026-09-11 13:21:49–13:22:35 UTC** used x64 OpenCode 1.18.29 with the
previously selected M3 provider, a pinned Node/Git image, one model probe and two task turns
(three model invocations total, nine native commands). The cache generation remained 1 after
reopening. All owner-labelled containers were independently absent afterward; the credential
file was unchanged. Private raw evidence, image recipe/digest and canary live outside Git in
the workspace's `outputs/runtime-convergence/container-native-*`. No transcript was copied
into the follow-up prompt, and no provider credentials entered the image or coordinator database.

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
container execution, while permitting future additional gates. Follow-up `f9337d9` has
exact-SHA green CI 34601215864, freshly verified completed/success.

Container directory follow-up: an explicit native layout preserves original canonical project
paths without mounting their ancestors. The container plan, inspected Docker workdir and PID 1
agree before provider execution. Reserved runtime/control paths cannot be shadowed. Strict TS
passed; CI-version Bun 1.3.11 container suite passed **12 tests / 52 assertions**, including nine
real-daemon cases, in 19.21 seconds. The new cases verify a Unicode/space-containing native cwd,
nested write permissions, adjacent host-file exclusion and rejection of a changed Docker workdir
before launch. No model/auth probe or production runtime switch occurred in this follow-up.

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
artifact owners, native provider write and other image/auth/state profiles, other persisted runtime stores,
writer exclusion and rollback, device-local History adoption, device-native Agent communication and mailbox application,
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

## Local task execution entrypoint — 2026-09-11

Schema 8 adds durable local runs. `LocalTaskRuntime` binds queued work to the task revision
and trusted provider profile, persists claims atomically with execution episodes, shares
configured controller concurrency limits, and retains outcomes across restart. Its
OpenCode adapter uses one durable preflight and the qualified native container driver.
The private stdio entrypoint accepts bounded requests with explicit request IDs; metadata
does not call models and duplicate execution requests never redispatch. Cancellation,
controller stop and uncertain results retain the existing kernel reconciliation rules.
At this entrypoint milestone `tell` persisted a pending message only; the subsequent native
mailbox integration below adds verified delivery and recovery.

The first real adoption attempt passed preflight but was refused with
`native_worktree_changed`. OpenCode rewrites the shared `global` project row when its
no-Git probe runs; empty Git repositories use that same project ID. The worker had used
the probe's `/` as the adopted session's read-permission base. The attempt remains
unknown in its original private coordinator, all six containers were recorded removed,
and no resume/retry was issued against that uncertain task. The fix derives global
session worktrees from their bound directory, retains native worktrees for other projects,
and refuses broken Git discovery. The regression covers a changed/removed probe path,
nested empty-Git workspace, mismatched session directory and broken `.git` pointer.

Corrected real acceptance ran **2026-09-11 14:08:50–14:09:31 UTC** through the actual
stdio executable in separate processes. Headless History discovery/revalidation selected
an existing controlled OpenCode 1.18.29/M3 session. First execution recalled its earlier
marker and read the current project; after controller exit/restart, an explicit resume
recalled the same marker without reinjection and read the changed file. Both task episodes
and local runs completed. Inspection, submission and enqueue/replay made zero model calls;
one probe plus two turns made three model invocations/nine native commands. Preflight
generation remained 1. Replaying the first enqueue after restart added no native calls.
All nine owned containers were independently absent via Docker inspect.

Final local verification: strict TS and the 512-module/57-field ownership drift check
passed. CI Bun 1.3.11 ran **154 tests / 2081 assertions across 21 files, zero failures,
32.18 seconds**, including real Docker and process recovery. The four focused native/
local-entry suites passed **29 tests / 204 assertions**. An intermediate full run exposed
a test-only `/proc` cleanup race: it reread a process after already observing termination
and treated dead/empty state as live. The helper now recognizes terminal states and asserts
the completed poll without extending its deadline. Full verification passed after that fix.

Private logs and scripts remain in `outputs/runtime-convergence/local-runtime-*` in the
workspace, not this repository. Production Python, live tasks, service installation,
default writer and release version are unchanged. The failed attempt is retained separately
as `local-runtime-acceptance-before-worktree-fix.*`; successful acceptance does not erase it.

## Native mailbox delivery — 2026-09-11

Local OpenCode execution now includes an attributed, ordered mailbox prefix in its actual
native input. Schema 9 adds effect-bound message reservations. The worker records receipt
with the original dispatch manifest, then consumes only after independently verifying the
native user input and terminal reply. Consumption, effect confirmation and task completion
share one transaction. Native reconciliation uses the original batch after interruption;
generic acknowledgement cannot bypass it, and TTL expiry cannot cause uncertain delivery
to be replayed. A fitting prefix keeps message bytes/order intact; later and overflow
messages remain pending and their count appears in the result. Stdio has message/status
inspection. Native Agent-originating send/ask/answer and device delivery remain open.

Real acceptance **2026-09-11 14:33:59–14:34:50 UTC** used the actual stdio entrypoint,
headless History revalidation and existing OpenCode 1.18.29/M3 session. A message sent
after enqueue supplied a new token absent from the task prompt. CM verified its presence
in native input, the reply contained it, and the message became consumed. Duplicate send
returned the same ID. After actual controller exit/restart, the next turn recalled the
token from native history without redelivery and read the changed current file. Two runs
completed with one probe/two task turns (three model calls/nine native commands), readiness
generation 1 and zero extra replay calls. All nine containers were independently absent.
This real send used the configured human-request ingress; Agent provenance is covered by
directed tests; the subsequent native Agent-originating acceptance is recorded below.

Verification: strict TS and the unchanged 512-module/57-field ownership baseline passed.
CI Bun 1.3.11 full core passed **161 tests / 2144 assertions / 21 files / 32.97 seconds**,
including real containers, process ownership and schema upgrades. After strengthening the
delivery helper's live-lease and trusted-reconciliation guards, the three affected native/
mailbox/local-control suites passed **29 tests / 246 assertions / 2.32 seconds**. Coverage
includes ordered Agent-origin context, late messages, fitting prefixes, oversized first
message refusal, scope loss, atomic reservation rollback, lost completion/reopen after TTL,
receipt/payload/native-input alteration, idempotent recovery and schema-8 preservation.

Private evidence: workspace `outputs/runtime-convergence/native-mailbox-acceptance.*`.
The existing production service, provider account settings and live task writer were not
changed. The whole migration remains active.

## Native Agent communication — 2026-09-11

The qualified local OpenCode read owner now exposes an optional scoped MCP channel.
Private configuration binds task peers and parent; model arguments cannot supply an actor,
source origin, lease or new peer. A generated Node stdio client connects to one per-episode
Unix socket using a private capability file. Both host and container tests cover paths
longer than Linux's socket-path limit. The task channel is mounted read-only, and its
client/profile identity participates in readiness and dispatch binding. Preflight does
not enable communication tools.

Schema 10 persists logical calls before application and distinguishes unresolved calls
from completed duplicates. Current scopes and execution authority guard both fresh calls
and cached responses. Receive waits outside transactions; reserved messages cannot expire
into replay. The native driver closes admission, then matches actual OpenCode tool names,
arguments and outputs to all recorded calls. Input-batch and tool-received message
consumption precede effect/task completion in one transaction. Recovery checks the same
original records with no model invocation. Tests cover lost terminal commit, fabricated
native output, revoked scope, cancelled task, changed client, duplicate in-flight receive
and schema-9 reservation preservation.

Real acceptance **2026-09-11 15:30:48–15:31:29 UTC** used OpenCode 1.18.29/M3 and the
existing pinned native image. The parent resumed the controlled existing session; the child
was a distinct native Agent. All four tools appeared in five actual native tool records.
Three messages (tell, question, answer) retained `agent_message` origin and causal answer
identity and became consumed. The parent recalled an old marker absent from the new
prompts, while the child's new token reached the parent through actual tools. Both Agents
read the current project file and completed. Controller exit/reopen and replay of the
original enqueue produced no additional model call. Two per-task qualified profiles used
one preflight each and one task turn each: **four native model-run commands, thirteen native commands total**
including a separate model-free native MCP discovery. A native task command can make several
provider requests during its tool loop; these counts are not a provider billing/request audit.
Independent readback matched all
five native tool records and confirmed all thirteen immutable container IDs absent and
all per-episode capability/socket files removed.

Verification: strict TS passes. CI Bun 1.3.11 full core with actual Docker enabled passes
**175 tests / 2,269 assertions / 23 files / 35.12 seconds**, zero failures or skips. After
tightening channel-directory admission and synchronous authorization checks, the affected
broker/worker suites passed again; no extra paid native probe was needed. Raw scripts,
results and independent verification remain in private workspace
`outputs/runtime-convergence/native-agent-*`. An auxiliary Docker-absence check initially
matched a capitalized diagnostic; the real client uses lowercase. Correcting only that
case normalization confirmed removal without rerunning any provider execution.

## Next

Connect device-native Agent communication and mailbox delivery to actual execution;
extend provider/write profiles with real native permission and outcome verification.
Then continue stores, History adoption, SpecMesh lifecycle and the production writer switch.
The current Node-image process profile is not a substitute for native provider qualification.

## Device-native communication — 2026-09-12

Implemented scoped native device calls, coordinator peer/parent projection, shared private
IPC with a remote backend, bounded native call receipts, and atomic completion/recovery
consumption using the original coordinator journal. Long receives permit independent
renewals and recheck revoked/stale authority. The device adapter qualifies preflight through
its actual runner. Initial device input-prefix batches and general fleet/provider rollout
remain open; this is not production cutover.

Checks so far: strict TS; 512-module/57-field ownership regeneration/check; Python protocol
9 passed; generated Python Ruff and Web build passed. CI Bun 1.3.11 full runtime with real
Docker passed 181 tests / 2393 assertions / 23 files / 36.38 seconds. A final focused pass
will include the default-preflight runner regression. New device/native tests use real HTTP
and Node stdio IPC with synthetic native records; they cover actual tool-parts matching,
lost completion/reopen, changed tool output, original session continuation, duplicate/lost
send receipts, receive/renewal concurrency, revocation and stale or forged authority.

Development corrections: the schema-writing helper initially had a Python brace typo
(no schema writes occurred); two commands used the wrong working directory and were
corrected. A Bun test assertion was attached before asynchronous revocation could run;
settling the promise into a value allowed the intended concurrent operation, and the test
passed. Generated model hashes required the expected ownership refresh. Real acceptance and its independent verification are recorded below.


Real OpenCode 1.18.29/M3 acceptance ran 2026-09-11 16:15:25–16:17:22 UTC
(2026-09-12 local time): ARM64 Rock 5C coordinator, x64 PC running two native Agents in
the pinned qualified container. The parent warmed an original session, then resumed it
while the child sent a fresh token and question. All four native tools occurred in six
verified calls. Both Agents read the changed project file; the parent recalled its marker
without prompt reinjection. The parent completion request was deliberately interrupted;
coordinator and local DB reopened, and explicit reconciliation consumed original received
messages without a new native command. Three effects and local records completed; all
three Agent-origin messages were consumed with question/answer causation intact.

Two model preflight commands plus three task commands produced fifteen native commands
and five native model-run commands. Each task can contain multiple provider requests;
provider billing/request counts were not measured. Both readiness generations remained 1.
The final statistics query mistakenly selected `provider_checks.status` instead of `state`.
That reporting failure occurred after completion/recovery; the raw failed result is retained.
A separate, model-free verifier reproduced the query error, reread actual native parts,
checked result/manifest hashes, session recall and coordinator outcomes, and passed.
It independently confirmed all fifteen container IDs absent, per-episode channels removed,
and the temporary remote directory/process absent. The explicit revoke step was not reached
because of that reporting error; the ephemeral coordinator, registration database and
endpoint were removed instead. The private script was corrected without rerunning Agents.

Private evidence: `outputs/runtime-convergence/device-agent-acceptance.{ts,json,log}` and
`device-agent-independent-verification.{ts,json}` in the shared task workspace. A final
fixture update initially omitted the report's runtime digest; adding the same explicit
fixture runtime identity corrected it, and focused verification passed. Production Python
0.43.0, live task ownership, services and installation remain unchanged. No release tag
or full-migration completion is claimed.

Final focused device-native verification (including runtime identity and exact completion
receipt replay): 23 passed / 319 assertions / 3.04 seconds. Strict TS, ownership drift and
whitespace checks passed after all source changes. Exact-SHA remote CI remains a separate
publication check.

Publication follow-up: 0645f9d was pushed, but exact-SHA CI 34621617071 failed two timing
checks while protocol/SDK/Web, package/install, Ruff, Mypy and Python 3.12 passed. The MCP
container fixture had a five-second total budget including Docker setup and both Node
processes, unlike the adjacent twenty-second container fixture. CI reported anchor_failed
without detailed outcome fields. Its test budget now matches the adjacent fixture and
failure assertions print the full outcome; runtime lease/enforcement deadlines are unchanged.
Using CI's pinned Node image locally: 16 tests / 69 assertions / 24.47 seconds passed.
The failed Python 3.11 test asserted completion after a fixed 200 ms, but the job was still
running. It now waits for observed completion with a bounded deadline. The adjacent running
restart fixture now waits for observed startup and drains its detached child, eliminating a
closed-event-loop warning. Host-job tests: 10 passed; Ruff and TS passed. New exact-SHA CI
must verify these test corrections; the earlier failed run is not treated as green.
That follow-up subsequently passed at ae9861152eadb4e0fae1b40054df5191ef2ff752,
CI 34622269044, as recorded in Current.

## Device initial input increment

The device reads its bounded ordered mailbox prefix before preflight. The full batch stays
in its local manifest; coordinator references and result proofs carry IDs/digest and the
actual native user-message ID. Dispatch atomically reserves the exact current prefix.
Completion/recovery consumes the initial batch before later MCP deliveries. Rejected
unstarted dispatch can release only through the coordinator's effect-free check and fence
advance; a committed dispatch with a lost response stays unknown. No storage version bump
is needed: existing reservation tables and the device ledger's text phase support this.

Verification: 192 core tests / 2,500 assertions / 37.28 seconds on CI Bun 1.3.11 with the
qualified Docker image. The 34 device tests cover bounded prefixes, later arrivals, combined
initial/MCP delivery, transaction rollback, changed input/proof/content, expiry during
preparation, lost dispatch acknowledgement and model-free recovery. A new test initially
expected an unavailable result for a retry of an uncertain task; the existing admission API
correctly rejects with task_not_admitted, and the test now asserts that contract.

Real acceptance ran 2026-09-11 16:53:49–16:55:12 UTC (September 12 locally), using an ARM64
coordinator and x64 OpenCode 1.18.29/M3 in the qualified container. A marker existed only in
the queued message, outside the task prompts. The first native input and answer verified it.
The completion request was deliberately withheld; coordinator/local database reopen and
explicit recovery consumed the original message without any new native command. A second
turn resumed the same session, recalled the marker, read the changed file and received no
duplicate batch. Both effects/local records completed; readiness stayed at generation 1.
One model preflight plus two task turns used nine native commands and three native model-run
commands; provider API/billing counts were not measured. The device credential was revoked.
Independent readback verified both actual native inputs/answers, prior-record hashes and
final coordinator state, and found all nine container IDs and temporary remote artifacts/
processes absent. No production installation, writer or service was changed.

Private evidence in the shared task workspace: outputs/runtime-convergence/device-mailbox-
acceptance.{ts,json,log} and device-mailbox-independent-verification.{ts,json}. An earlier
preparation-only attempt used the wrong send API shape and made zero native/model calls;
its raw report remains in its unique work directory. The readback script was corrected for
the marker label and for inspecting an earlier turn after a later turn exists; native
execution was not repeated for either readback correction. This closes the qualified device
initial-input acceptance, not the complete runtime migration or production cutover.
