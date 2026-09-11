# Transactional runtime core (migration in progress)

This is the actual TypeScript state/coordination kernel for the approved runtime migration.
It accepts lifecycle operations, uses a versioned Bun SQLite database, and is exercised by
independent OS processes. It is not the older fixture-case-switching facade candidate.
It is private, has no production startup route, and does not yet replace Python TaskHub.
Track completion in [the repository plan](../../plans/runtime-convergence/task_plan.md).

## Current behavior

- `RuntimeKernel` creates waiting tasks, claims execution episodes, starts/renews/finishes
  them, explicitly resumes completed work, cancels tasks, and records uncertain outcomes
  after a running lease expires or the native observation cannot be accepted.
- Every command receipt binds principal, origin, device and canonical request content.
  Task revisions and fencing tokens are checked in the transaction; revoked scopes are
  rechecked before returning cached private results.
- One local coordinator database owns tasks, episodes, effects, events, messages, receipts
  and migration journal. SQLite is not a network filesystem or a device transport.
- The external-effect record is written before dispatch. A repeated dispatch command
  returns `dispatch_permitted: false`. Losing the outcome requires reconciliation; it
  cannot automatically rerun the provider or declare task completion.
- `AgentMailbox` separates pending, received and consumed. It preserves ordered gaps,
  attributes ingress provenance, binds acknowledgement to the current episode, and bounds
  message bytes, live queue, lifetime, initiation, fan-out and causal depth.
- JSON Schema defines the versioned lease/message wire shapes. Generated types and actual
  runtime validation use the existing protocol package. This adds no public mutation API.
- `ProcessSupervisor` runs a provider under a detached Linux anchor. The anchor survives
  provider exit until the supervisor reaps the group; controller disconnection or missed
  renewals also stop it. Group signals verify the live leader's start time, group and
  session before issuance. Deadlines, cancellation, authority loss, bounded stdout/stderr
  and native-error aborts are exercised with real processes, including descendants that
  ignore SIGTERM. A provider process group is lifecycle containment, not a sandbox against
  programs deliberately creating a new session or other external side effects.
- `ProviderPreflightService` invokes a bounded, tool-denied native OpenCode probe and
  persists device/model/config/credential-bound readiness. Quota/auth/unknown outcomes
  pause; transient retries are bounded. Actual execution failures revoke matching cached
  readiness. A cached observation is never a tool grant.
- `HistoryClient` uses Viewer's explicit headless native-reference command. CM independently
  rereads its own configured native store, checks a content-bound v2 reference, and never
  treats candidate text as authorization. The read-only digest includes older messages.
- `OpenCodeWorker` connects the kernel to real OpenCode execution for an explicitly issued
  local foreground read profile. It checks current persisted grants and native resolved
  agent/session permissions, passes the prompt through bounded stdin, verifies native
  append lineage and required current-file reads, and atomically confirms the result.
  A real same-session marker-recall/current-file canary passed; see the active plan.
- `DeviceCoordinator` provides an explicitly started, Bearer-authenticated private worker
  port on loopback. Pinned SSH forwarding carries it to a second device. Trusted local
  registrations bind credential hashes to owners, device IDs, capabilities and logical
  workspaces. Device requests cannot choose identity, scopes, executable code or local
  paths. Assignment digests bind the input inspected before claim; task-authority changes
  invalidate it. Revocation is durable and rechecked after asynchronous request reads.
- `DeviceClient` does not follow redirects or automatically retry mutations. Worker
  deadlines start before sending a lease request and subtract network delay and a safety
  margin. Linux uptime includes suspend; a stopped/expired authority cannot revive.
  `DeviceWorker` supplies `runProcess` to locally registered adapters with the current
  lease deadline passed directly to the process anchor, even if its controller freezes.
  Cross-device mailbox peers must be explicitly assigned.

`Principal` is an internal admission object constructed by trusted ingress. Never accept
its identity, scopes, origin or device from an unauthenticated JSON request. The kernel is
not itself an authentication service. Its state methods do not issue provider grants.

## Snapshot migration

`LegacyMigration` imports a reviewed snapshot into an empty, explicit database. It keeps
all unknown row/envelope fields and cancelled statuses. All active imports require
reconciliation before execution. Import and journal are one transaction; retries require
the same digest. Both original and compatibility snapshots can be retrieved. Neither
export nor import authorizes restarting a legacy writer. Task folders are never opened
or cleaned by this importer.

Read-only preview (no persistent destination):

```sh
bun packages/controlmesh-runtime-core/scripts/legacy-snapshot.ts \
  --source /absolute/path/to/tasks-snapshot.json --source-id reviewed-snapshot
```

To import a synthetic/offline copy, additionally supply `--import`, an absolute
`--destination`, the preview's canonical `--expected-digest`, and the owning `--principal`.
The target directory must exist. No automatic live-home path or writer cutover is offered.

## Evidence and remaining work

`pnpm test:runtime-core` checks the Python source/serializer baseline, strict TS types,
transactional state, cancellation, fencing, clock rollback, concurrent OS-process claims,
SIGKILL before commit, lost external receipts, permission revocation and bounded mailboxes.
All fixtures are synthetic; these tests do not touch provider accounts or operator state.

Remaining before activation: operator/native reconciliation, tell/ask and general resume integration,
provider adapter/permission parity and non-Linux supervision, transport delivery, all other Python
stores, native provider integration with the device transport, the full native
continuation matrix, SpecMesh lifecycle admission, full rollback and production-writer exclusion.
Mailbox application references are reports until the native adapter independently verifies
them. A coordinator fence cannot prevent an uncooperative external program's side effect.

The authenticated worker transport and a real x64/ARM64 synthetic two-device canary are
now implemented. Remaining fleet work includes the actual native provider/grant adapters
over this transport, durable presence/capability revision and topology/dependency policy,
credential rotation/re-enrollment, unattended service rollout and activation/rollback.
The local `OpenCodeWorker` is not yet a remote `DeviceAdapter`; assigning a capability is
not a provider tool grant. Production adapters must independently enforce current source,
grant, native-session and workspace rules and verify native evidence before returning a
result. Remote completion is an authenticated worker report, not protection against a
compromised device that fabricates evidence.

## Device transport contract

`schemas/controlmesh/v1/device-*.schema.json` owns the private command/response/lease-window
shapes. Operations are queue, inspect, claim, start, renew, dispatch, observe, complete,
unknown and bounded mailbox send/read/ack. Operator task creation, assignment, cancellation
and revocation remain trusted local methods. `complete` atomically confirms one observed
effect and finishes the episode; it does not execute an external action on receipt replay.

Limits: 128 configured devices, 32 queued jobs returned, 32 KiB assigned inputs, 256 KiB
request bodies, 3-second body read, 8 in-flight requests and 64 requests/second per device,
0.5–30-second wire leases. HTTP rejects browser-origin requests and content encodings;
credentials remain in local configuration. The existing public SDK/Web gain no mutations.
SQLite schema 3 adds assignments; schema 4 adds durable device revocations. No database is
shared with a worker. The current queue scan is bounded to 1,024 waiting assignments per
owner; large fleet pagination/fairness remains required before production activation.

`scripts/device-canary-worker.ts` is an explicit synthetic acceptance driver, not a service
entrypoint. It reads an owner-only mode-0600 configuration and runs only its fixed read/
hold fixture. It never loads a model credential, sends bot traffic or starts a scheduler.
