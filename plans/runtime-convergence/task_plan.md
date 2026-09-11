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
| CM-R1 | TS execution kernel behind existing facade; transitions, events, cancellation, deadlines, process supervision | Python/TS differential traces for success, failure, timeout, cancel, crash/restart; zero duplicate side effects in shadow mode | in_progress: transactional kernel implemented; process/provider parity pending |
| CM-R2 | Transactional state migration and startup recovery | Dry-run migration counts/digests, interrupted migration replay, rollback compatibility, corrupt-input refusal | in_progress: TaskHub snapshot import/export and rollback tests; other stores/cutover pending |
| CM-R3 | Provider/transport/workspace/grant ports | Actual adapter smoke for each supported provider; grants enforced natively; process tree cleanup and result-delivery reconciliation | in_progress: real OpenCode local read profile; remaining adapters, grants and transport ports pending |
| CM-R4 | Device coordinator and worker execution authority | Two-device lease expiry, fencing, clock skew, network partition and worker restart tests; stale worker cannot write or redeliver | in_progress: authenticated private transport and real x64/ARM64 synthetic canary passed; native fleet adapters and rollout pending |
| CM-R5 | Agent mailbox and task dependency exchange | Duplicate/out-of-order/replayed messages, bounded broadcast, cancellation propagation and backpressure evidence | in_progress: durable core mailbox tested; native/transport integration pending |
| CM-R6 | History headless candidate + native adoption + SpecMesh lifecycle hooks | Real continuation canary binds provider session, current repo and approved task scope; see HV-H3 / SM-P2 | in_progress: actual TS same-session recall/current-file canary passed; SpecMesh hooks and full matrix remain |
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

Continue from the concrete `OpenCodeWorker` and authenticated `DeviceCoordinator` paths: add explicit unknown-result reconciliation and connect production provider/grant/source profiles to the remote worker port. Integrate independent SpecMesh gates with current checkout snapshots. Complete the remaining ownership/side-effect audit against `python-ownership.json` (512 Python modules, 57 serialized TaskEntry fields); the inventory itself does not establish parity. Do not activate over live data before writer-exclusion and recovery gates.
