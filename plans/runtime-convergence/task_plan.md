# Runtime convergence: full TypeScript migration and multi-device Agent execution

## Status and ownership

Status: in_progress; full implementation explicitly authorized on 2026-09-11. Owner: CM maintainers/primary coordinating Agent. User authorizes this direction; existing Python ownership remains factual until each migration gate passes. Do not interpret the old read-only-first roadmap as a permanent ban on the approved runtime port.

## Goal

Move runtime authority to TypeScript without losing task correctness, provider enforcement, local/native session context, transport delivery or recoverability. Coordinate concurrent Agents across devices with attributable, bounded message exchange. A green facade prototype is not runtime completion.

## Observed baseline

- `controlmesh/tasks/{hub,registry,models}.py` own existing persisted tasks and transitions.
- `controlmesh/tasks/{native_sessions,native_commands}.py` implement OpenCode identity/revision checks and explicit native adoption; prior native-session-adoption records real terminal completion, not merely mocked tests.
- `controlmesh/cli/`, `controlmesh/runtime/`, `controlmesh/messenger/`, `controlmesh/workspace/` retain process, policy, delivery and filesystem behavior.
- `schemas/controlmesh/` and `packages/controlmesh-{protocol,sdk,runtime-facade,plugin-api}/` contain the protocol/product foundation and private parity candidate; they are not a second authorized task store.
- Cron's new field transactions protect cooperating writers, and observer ownership prevents duplicate runs within one instance. Neither establishes a distributed execution lease.

## Requirements

1. Preserve persisted task IDs/statuses, provenance, model/provider selection, grants and artifact ownership during migration. Add explicit schema/storage version and migration journal; never infer authority from a user-facing prompt.
2. Use one authoritative writer per migrated area. During shadow comparison TS must not issue external tools or duplicate delivery. Route production traffic only after that area passes parity/recovery gates.
3. Admit operations through authenticated principals, scope checks, expected revision and idempotency key; define create/tell/resume/cancel separately. Reject stale ownership with a monotonic fencing token checked at side-effect boundaries.
4. Model device identity, capabilities, trusted workspace mappings and presence separately from task identity. Keep tokens/credential stores device-local; don't copy a provider's private session database as a transport protocol.
5. Durable Agent messages carry message ID, sender, recipient/task, correlation/causation, sequence, origin, scope and expiry. Delivery is at-least-once with idempotent application; acknowledgement means persisted receipt, not successful execution. Bound fan-out, recursion, queues and retries.
6. Quota/auth/model preflight has typed unavailable/degraded/ready outcomes, explicit expiry and bounded probes. Model history is a candidate source, not proof of current quota. Quota failures wait for evidenced reset or operator action rather than creating repeated cron prompts.
7. Preserve native session semantics: explicit session/store/device/directory/revision binding, no silent fallback to fresh conversation, no transcript text promoted to instructions/permissions. Native clients outside CM do not honor CM advisory locks.
8. SpecMesh plugin checks and History retrieval have independent tool APIs; a missing/unknown required gate fails closed. Human UI displays task progress, output, blocking reason, decision and next action first.

## Phases and exit gates

| ID | Deliverable / implementation seam | Exit evidence | State |
|---|---|---|---|
| CM-R0 | Inventory real owners and versioned payloads; extend existing lifecycle/provider/gate goldens | Reproducible baseline plus ledger of every persisted field and side effect | in_progress |
| CM-R1 | TS execution kernel behind existing facade; transitions, events, cancellation, deadlines, process supervision | Python/TS differential traces for success, failure, timeout, cancel, crash/restart; zero duplicate side effects in shadow mode | in_progress: transactional kernel, durable local queue, private stdio and persistent local service/CLI implemented; full process/provider/transport parity and terminal interface pending |
| CM-R2 | Transactional state migration and startup recovery | Dry-run migration counts/digests, interrupted migration replay, rollback compatibility, corrupt-input refusal | in_progress: snapshot migration plus persisted native manifests/reconciliation; other stores/cutover pending |
| CM-R3 | Provider/transport/workspace/grant ports | Actual adapter smoke for each supported provider; grants enforced natively; process tree cleanup and result-delivery reconciliation | in_progress: source/grant/one-shot/container ports; real host/container OpenCode read and local TaskHub and device staged-write/recovery profiles with native auth/state; durable terminal outbox and Feishu text send/readback verified with local HTTP; other provider/write/source profiles, production transport acceptance and remaining transports pending |
| CM-R4 | Device coordinator and worker execution authority | Two-device lease expiry, fencing, clock skew, network partition and worker restart tests; stale worker cannot write or redeliver | in_progress: real ARM64/x64 native writes, retained-proposal recovery and current SpecMesh reads/writes accepted; normal configured startup/control, two task-bound native sessions and linked handoffs accepted; persistent scheduling, real parallel native mailbox exchange and no-replay restart recovery accepted; other profiles and rollout pending |
| CM-R5 | Agent mailbox and task dependency exchange | Duplicate/out-of-order/replayed messages, bounded broadcast, cancellation propagation and backpressure evidence | in_progress: local/device native initial input and actual Agent MCP send/ask/receive/answer accepted with atomic consumption and recovery; real ARM64 coordinator/x64 interrupted completion, reopen and original-session recall passed; local/device topology dispatch and native input integrated; full native topology acceptance pending |
| CM-R6 | History headless candidate + native adoption + SpecMesh lifecycle hooks | Real continuation canary binds provider session, current repo and approved task scope; see HV-H3 / SM-P2 | in_progress: real same-session recall/current-file and post-SIGKILL continuation passed; normal device-local adoption of an unmanaged native session and model-free recovery accepted; independent SpecMesh start/handoff gate and five-file real native consumption and post-publication continuity recheck accepted locally and on an actual device worker; reviewed closeout and full matrix remain |
| CM-R7 | Staged default switch and Python retirement | Canary -> selected device -> default rollout; telemetry and rollback thresholds met; old writer disabled before new writer activation | planned |

## Acceptance matrix

- CM-A01: repeated submit with same identity and body returns one task; conflicting body rejects.
- CM-A02: lose coordinator/worker after external side effect but before acknowledgement; recovery reconciles outcome before retry.
- CM-A03: expired lease and delayed old worker output cannot overwrite new owner or complete canceled task.
- CM-A04: quota/auth failure does not advance completed state, trigger unbounded probes or create duplicate user messages.
- CM-A05: trace provenance distinguishes human request, schedule, agent message and recovery replay. Scheduler content never appears as a newly authorized human instruction.
- CM-A06: resumes preserve original provider session and current authorization; missing source or changed revision blocks and explains reinspection.
- CM-A07: native writes or uncommitted repository changes invalidate stale acceptance. Unknown external outcomes stay unknown.
- CM-A08: upgrade/restart retains task/artifact lineage and does not revive explicitly canceled tasks.
- CM-A09: device disconnect/backlog limits and loop budget tested without real browser accounts.
- CM-A10: clean install, upgrade, packaged assets, protocol schema, TS typecheck and CI all bind the released SHA.

## Rollback and failure policy

Before migrating live data, snapshot format/version/digests and rehearse rollback on synthetic copies. Stop admission, fence old workers and reconcile in-flight side effects before switching writer. Never dual-write production tasks to Python JSON and a TS prototype. Retain a compatibility reader until migrated artifacts and events can be read after rollback. Freeze rollout on duplicate external actions, missing events, grant expansion, unresolved completion or repeated quota probes; do not automatically roll back by rerunning tasks.

## Dependencies and plan authority

- History discovery/context contract: https://github.com/muqiao215/Codex-Claude-History-Viewer/blob/main/plans/agent-handoff-service/task_plan.md
- Independent workflow gate: https://github.com/muqiao215/specmesh/blob/main/plans/independent-plugin-port/task_plan.md
- Ops operational canary is private and remains in Ops-Vault's fleet-workflow-rollout plan; do not publish inventory or credentials here.

## Non-goals for the current release

No claim that full TS migration or distributed coordination has completed. A scoped real TS OpenCode continuation canary has passed; it does not close all provider/device/SpecMesh gates. No production browser-account execution from writing this plan. Prior verified Python native OpenCode adoption remains completed historical evidence, with its documented cross-client locking limit.

## Next Step

Complete physical input/output delivery and real topology/native continuation acceptance.
The qualified ARM64 peer was confirmed offline on 2026-09-13; no remote canary started.
While it is unavailable, continue CM-R3. Ordinary local runtime configuration now
registers Claude/OpenCode/Codex; Codex has readiness, History candidates, exact-UUID
adoption and retained-result reconciliation. The installed 0.154.0 binary plus real
headless Viewer have passed configured adoption and context-preserving continuation
across reopen against a synthetic loopback model endpoint. This does not qualify live
account behavior or native tool permissions. Gemini 0.59 JSONL snapshot/baseline reading
is implemented and qualified against its installed recording service; stream/text-turn
verification now matches persisted messages and successful terminal output. Persistent
registration, process/grant enforcement and actual native model execution remain. Codex
fresh-session creation, interrupted lineage qualification, effective native sandbox
behavior, and broader Codex topology qualification remain. Local native Codex pipeline
worker/reviewer execution and parent artifact acceptance after reopen, plus concurrent
fanout workers with lost-observation recovery and a third native merger, are qualified
against loopback model fixtures. Native director/judge happy paths now pass through the
normal scheduler; repair/error branches and physical-device combinations remain. Codex current-file read receipts,
staged write publication and retained publication recovery are now registered. SpecMesh
start/post-publication checks and recovery checks are registered; reviewed closeout remains
a separate gate. Installed-native fixtures do not qualify real-account or cross-device write behavior.
Codex initial mailbox delivery and retained consumption recovery are now integrated;
active messaging is registered through the shared broker. Installed-native send/ask/receive/answer,
local two-session concurrent question/answer and retained recovery pass against loopback
model fixtures; physical device and real-account qualification remain pending. Complete these
owners without presenting one-shot execution or a transcript reader as full continuity.
The configured coordinator now issues a versioned snapshot reference; device assignments
bind it, and authenticated chunk reads require the current assignment and execution lease.
Configured workers opt in with bootstrap_files, persist interrupted receipt and publish
verified inputs before dispatch. Topology routes now opt in through source_files; enqueue captures the snapshot and assigns
it atomically. Controlled HTTP interruption/retry and topology restart are tested; actual
two-device/native acceptance remains open. Do not confuse
these fixtures with physical delivery or real Agent continuity.

Continue remaining native/source/artifact, provider/transport/store/terminal and CM-R0–CM-R7
rollout requirements. Complex topology continuation remains unaccepted; no guarded
attempt/session may be replayed. Production Python ownership and release gates remain.

Current implementation and native evidence belong in progress.md and its retained archive,
not in competing historical next-step instructions. Scoped native acceptance does not
qualify every provider, device, source or grant profile. Keep original failed attempts and
perform recovery from retained output without replaying uncertain work.

Relevant implementation designs:

- [Native writes](native-write-design.md): staged publication, completion and reconciliation.
- [Claude continuity](claude-continuity-design.md): task/session binding and retained output.
- [Ownership inventory](python-ownership.json): 512 Python module owners and 57 task fields;
  this is a baseline inventory, not a completed parity score.

## Current topology checkpoint — 2026-09-12

Pipeline, fanout, director and judge now have explicit transactional local queue steps.
Director/judge bind normalized decisions to accepted controller episode/effect output,
current checkpoint and expected round. Schema 20 freezes controller task/role and
budgets; same-role resumes retain child identities through assignment generations.
Judge service repair/interruption loops are capped durably (default one each), including
after restart. Terminal queue transitions now atomically seal accepted results and finish
idle root tasks via schema 21. The completion event is an internal topology reduction;
it does not create a provider episode or assert real native acceptance.

Parent artifact completion now requires a registered workspace/file profile, actual accepted
child read/write completion evidence and matching current bytes. A live permit binds those
checks to the exact parent/topology revisions. Adopted SpecMesh requirements are rechecked
with the independent plugin's check operation and exact source hash. This establishes file
delivery; reviewed project closeout remains unknown/pending.

Explicit root topology reopen now archives the terminal run and starts a new execution
under the same TaskHub identity (schema 22). Child assignment execution IDs prevent old
results from entering a new run; native continuity uses the existing explicit resume.
Frozen policy limits survive, while per-execution counters reset only on this explicit
new run. Restart alone never reopens completed work.

Native/aggregate assignment source is explicit in schema 23. Nested topology results
now bind their own completion and current descendant evidence; all 16 parent/child
combinations and same-tree reopen pass focused fixtures. File requirements trace to
actual leaf tool receipts. This does not establish automatic service or device dispatch.

Current recovery foundation adds read-only result preview, typed malformed-output
classification, explicit same-session retry with a durable two-retry ceiling and optional
pipeline/fanout repair/interruption caps. Schema 24 now adds frozen schedule registration, background local service startup/control,
explicit recovery and origin-attributed automatic transitions. Schema 25 adds device topology
dispatch through the existing worker lifecycle, frozen routes and atomic episode/admission
bindings. Normal coordinator controls, restart and bounded recovery are implemented. Real
native topology, remote artifact/current-source and reviewed closeout acceptance remain next. Continue all remaining CM-R0–CM-R7 provider/transport/store, native source
revision and release/install gates; explicit local queue tests do not narrow that scope.
There is no production writer switch, release or installed-version alignment yet.

Local scheduling control and limits: [topology-scheduling.md](topology-scheduling.md).

Schema 28 adds opt-in canonical publication of accepted device artifacts. The scheduler
captures exact write-file baselines before dispatch and uses the existing durable staging
journal under current lease authority. Local conflicts block; already delivered paths are
verified without rewriting; pause/restart resumes the original proposal. Sparse snapshots
exclude unrelated files. The standalone SpecMesh gate checks both sides of publication.
Controlled integration is positive; physical end-to-end transfer/publication and reviewed
closeout remain pending, alongside initial workspace distribution and the full migration.


Schema 26 closes the native-input gap by freezing assigned role/stage/output contracts and
prior results, delivered through existing verified mailbox input. Missing/altered input
fails before claim; oversized input blocks rather than truncates. The real topology canary
is only partially positive and remains unaccepted; its failed reviewer and skipped reopen
are documented in progress.md. No production writer or installed-version switch occurred.

### Gemini failure classification checkpoint (2026-09-13)

Typed native failures and supervised retry interruption are implemented and locally
verified (12 tests, typecheck). CM-R3 remains in progress: Gemini native grant enforcement,
preflight and actual account-backed execution are not established by these fixtures.
Continue these owners before declaring Gemini provider parity or switching defaults.

Gemini admission follow-up: installed policy-engine qualification demonstrates that
--admin-policy can be ignored when system TOML exists. Require effective-policy admission
and immutable configuration through execution; do not remove restrictive-grant refusal
based on command construction alone. See findings/progress dated 2026-09-13.

Gemini profile checkpoint: explicit UUID command and exact-tool TOML rendering implemented;
installed engine qualification passes. Integrate profile only with registered session
identity, effective-policy verification and immutable execution configuration. CM-R3
remains in progress; no default/provider admission change at this checkpoint.

Open regression gate (2026-09-13): broad optional Docker suite observed reviewer unknown
in publish_received=true topology; isolated and paired reruns pass. Preserve this as
unresolved, capture classified reason with the added diagnostics on recurrence, and
require a clean broad gate before cutover. See progress for exact logs and counts.

Full-gate update: d5fa32b passes the complete local runtime-core gate (890/30/0,
10905 assertions). Prior container reviewer uncertainty did not recur in broad order;
its root cause remains unconfirmed. This satisfies the current regression rerun only,
not the still-open native/provider/physical-device and cutover acceptance matrix.

CM-R2 backstage events checkpoint: schema-30 principal-scoped session event storage and
legacy/typed session key support implemented, with direct Python key comparison and
322-test migration regression. Still required: lossless legacy JSONL import, production
event producer/API wiring, rollback/export qualification. This does not close CM-R2.

Backstage import checkpoint: atomic caller-supplied JSONL import/export and lossless
integer round-trip implemented. Remaining migration work includes explicit file snapshot
selection, dry-run/cutover command, production event producer wiring and rollback
qualification; unsupported numeric forms must remain visible refusals.

Backstage file migration checkpoint: explicit read-only preview and digest-bound apply
command implemented and subprocess-tested. Remaining: actual producer/control wiring,
operational cutover/export rollback qualification and unsupported numeric-form handling.
No operator files are migrated automatically.

Backstage producer checkpoint: TS kernel task.* summaries and authenticated local
session-events query/CLI are wired and tested. Remaining Python frontstage/orchestrator
and route-candidate/inbox producer parity must still be implemented before full cutover.
Legacy partial-context tasks retain task events without inferred session projection.

Session-history operational checkpoint: record/byte-bounded cursor paging is wired
through local control and CLI, with large-payload and concurrent-insert regression
coverage. This supports lightweight history retrieval; remaining event producers and
full runtime migration gates stay open.

Host-job migration checkpoint: model decoding and terminal merge ported with 85-pair
live Python differential coverage. Next owners are transactional persistence, source
file authority/import, process supervision/approval and interrupted-job reconciliation.
This checkpoint does not enable host command execution or complete host-job parity.

Host-job storage checkpoint: schema-31 transactional store, principal isolation, revision
checks, receipt replay and bound job identity implemented. Legacy authority-file import,
approval/dispatch and interrupted-process reconciliation remain required; no stored PID
or approval metadata grants native process authority.

Host-job import checkpoint: explicit directory/index snapshot selection, stable source
digests and create-only import implemented against Python-generated files. Cross-file
generation proof is absent in the legacy format; imported execution state needs separate
reconciliation. Operational CLI, approval/process runner and control wiring remain open.

Host-job operational import checkpoint: preview/digest-bound apply CLI is implemented
and subprocess tested. Pending owners remain runner approval, native process identity,
interruption reconciliation and configured runtime controls. No real jobs are restarted
by migration or by reading an imported running status.

Host approval checkpoint: current-version, exact-next-step human decision receipts and
verification implemented. Imported approval metadata cannot satisfy them. Remaining
work: actual control issuance, existing-kernel dispatch binding, supervised execution
and interrupted-result reconciliation; approvals alone never launch commands.

Host control checkpoint: configured list/detail/step-approval operations and CLI wired
with principal isolation, restart/replay and revision tests. Remaining execution owners
are kernel-bound dispatch, native process supervision and uncertain-result reconciliation.

Host execution checkpoint: an approved single local-foreground step can run through
existing kernel lease/effect supervision with actual exit/cancel/no-replay tests. Next:
retained-result recovery, configured resolver/dispatch, multi-step progression, and
non-foreground/container/device source profiles. Full host runner parity remains open.

Host recovery checkpoint: retained actual exit results can reconcile atomically without
re-execution, with historical approval/current running-snapshot validation and rollback
fault injection. Next action: wire approved host execution and recovery into configured
local task dispatch, then multi-step progression. Production cutover and full migration
remain open; no Python writer replacement is claimed.

Configured host checkpoint: normal submit/enqueue and recovery controls now support
explicit host registration and individually approved multistep progression. Next owner:
command-specific SpecMesh admission/completion evidence, then remaining host source and
device profiles. The existing native SpecMesh read verifier is not host command evidence.

Host workflow checkpoint: independent start/end checks and same-profile recovery checks
are wired and qualified against the actual standalone plugin. Next: complete remaining
host execution source/container/device profiles against Python behavior, then continue
all unresolved provider/transport/terminal and rollout owners in CM-R0–R7.

### Host parity revalidation

Use [host-parity.md](host-parity.md) for the remaining host owners and exit evidence.
The Python host runner intentionally refuses isolation-required sources; creating a
container-host variant is not a prerequisite for matching that owner. Next implementation
priority is explicit cancellation/job-state convergence, followed by normal workunit
creation/advancement and durable long-running execution/logs. Full provider/device and
production rollout gates remain unchanged.

Running host cancellation checkpoint: normal control cancellation retains actual process
outcome and projects cancelled job/step without confirming effects. Next: queued-step
cancellation and crash-window reconciliation, then the remaining host-parity.md owners.
Full baseline at b361e0a passed 918/30/0; later cancellation fix has focused regression.

Pending host cancellation checkpoint: cancellation of an unclaimed waiting task now
atomically updates its currently approved pending step and queue; stale/forged references
cannot affect other execution. Next: claimed-but-unstarted and retained-outcome cancellation
recovery windows, then remaining host-parity.md owners and full CM-R0–R7 acceptance.

Host cancellation recovery checkpoint: leased-but-unstarted tasks cancel atomically;
retained cancelled outcomes converge through bounded normal recovery after reopen, with
corrupt-evidence refusal and idempotency checks. Next: remaining host workunit creation,
automatic authorized step advancement and durable long-running process/log ownership,
then continue all original CM-R0–R7 acceptance and release gates.

Retained host-output checkpoint: normal control/CLI can read bounded per-stream output
with strict principal isolation and execution-bound cursors. Remaining log owner is
durable streaming during execution and long-job persistence, alongside normal workunit
creation/automatic advancement and the unchanged full migration/release matrix.

New host workflow checkpoint: normal controls/CLI create fresh definitions and atomically
start an explicitly approved step. Legacy import is no longer required for this path.
Next: automatic advancement for authorized steps and parity for Python workunit routing,
plus durable long-running execution/logs; original full migration matrix stays open.

Graph authorization checkpoint: persisted whole-remaining-plan approval and derived step
receipts are implemented and exercised through actual command execution/reopen. Next:
explicit run-plan registration and bounded persistent automatic advancement, requiring
real prior task/effect completion, then remaining host/full migration acceptance owners.

Automatic local host-plan checkpoint: explicit durable run registration, bounded tick
advancement, prior-success evidence and between-step restart are implemented and tested.
Next: remaining Python workunit routing and durable long-running process/log owners in
host-parity.md; continue unchanged CM-R0–R7 multi-device/provider/terminal/release gates.

Ordinary workunit checkpoint: Python-equivalent classification and normal TS submit-to-
host routing are wired with atomic source/grant refusal and actual command verification.
Next: durable long-running process and streaming-log ownership, remaining source-profile
parity, then all outstanding provider/device/terminal/cutover gates in CM-R0–R7.

Streaming host log checkpoint: schema-32 durable chunks and normal control/CLI reads now
work before completion and after reopen; sink failures stop execution. Historical migration
regression passes. Next: bounded lease renewal/durable long-job execution ownership and
remaining environment/source parity, then full CM-R0–R7 native/device/terminal/cutover gates.


## Latest verification and next action

At b1de06f, the configured Docker/SpecMesh runtime regression passed 960 tests with 30
optional skips (990 total); see progress for limits. Independent host execution survives
management loss and obeys cancellation, expiry and owner-death handling. Same-approved-plan offline continuation now passes real success/failure and unrelated-queue
isolation tests; see the newer progress entry. Continue the remaining host/source and
provider/transport/device ownership matrix before any default runtime switch.
This next action does not supersede remaining provider/transport/device/migration/release
requirements or the CM-R7 production writer cutover gate.


Gemini checkpoint: loaded-rule validation now detects the installed 0.59 system-policy
suppression path with native engine evidence. Normal runtime registration/preflight,
configuration immutability, process/session integration and full account qualification
remain required. No grant mapping or default provider admission has been relaxed.


Gemini source-binding follow-up: bounded directory/file observation now wraps loaded-rule
qualification and catches configuration drift. Complete native settings/source discovery
and protected execution binding before changing the existing provider admission refusal.


Gemini native resolution checkpoint: policy source discovery and loading now use native
exports with settings/source drift checks. Next registration work must use an isolated,
version-bound CLI settings loader and protected execution configuration; this helper is
not yet a runnable Provider adapter or evidence of account-backed continuation.


Gemini settings checkpoint: isolated native settings probe now enforces fixed Node
read-only permissions and fresh loader state with digest-only settings output. Complete
identity-bound launcher and effective-policy/process integration before Provider admission.


Gemini settings runner checkpoint: supervised read-only loading with explicit environment
and registered runtime-file identity checks is implemented. Next registration requirements
remain complete native dependency/settings source discovery and joint effective-policy /
session/process binding; full Gemini execution and account qualification are still open.


Gemini settings dependency checkpoint: actual loaded-file discovery and pre-evaluation
registered-list refusal now pass on installed Node/Gemini. Continue source settings-file
binding and joint native policy/session execution registration; no full Provider acceptance.


Gemini source-file checkpoint: synchronous native settings/trust accesses are discovered,
registered and identity-checked across loading/supervision. Complete the unified settings /
effective-policy / session registration and actual process integration before normal
Gemini Provider admission or broader migration closure.


Joined Gemini admission checkpoint: the settings runner now loads native effective rules
from the same merged settings and checks registered policy sources, configuration drift
and the exact requested tool set. Resume argv matches the probe's --ignore-env profile.
Next is actual same-configuration process/session dispatch and normal task registration;
this checkpoint does not complete Gemini, the full migration or production rollout.


Gemini execution checkpoint: explicit-session supervised local compatibility execution
and model-free retained text verification are implemented, with quota-abort/cancel and
changed-adoption fixture coverage. Next is normal TaskHub/readiness/receipt registration
and protected real CLI qualification, then native account and full device/profile matrix.
No default runtime switch or full migration completion is established by this primitive.


Gemini task checkpoint: durable local queue, outcome confirmation and model-free restart
recovery are now wired through GeminiTaskAdapter. A second same-session fixture turn and
wrong-evidence/idempotency checks pass. Next: concrete readiness and ordinary configured
registration, real CLI/account qualification, then native receipt and multi-device profiles.
Full migration, physical transport/terminal acceptance and rollout remain open.
