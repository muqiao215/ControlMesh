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

Publish registered-context CLI changes, then connect the interactive terminal frontend to the
same service. The persistent service f1832aa passed full local regression (803 tests / 10317
assertions) and CI 34711514218. Task/event reads, independent clients, execution-time cancellation,
SIGKILL/restart and synthetic-container session continuity have focused evidence. The next
terminal frontend must use this same runtime, profile, grants, queue and native recovery owner.
The e2b16e3 publication checkpoint passed CI 34709699732. Initial workspace distribution and
two physical devices remain required. Continue remaining
native/source/artifact, provider/transport/store/terminal and CM-R0–CM-R7 rollout requirements.
Complex topology continuation remains unaccepted; no guarded attempt/session may be replayed.

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
