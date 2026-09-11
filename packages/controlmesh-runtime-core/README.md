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
stores, authenticated coordinator/worker transport, two actual devices, the full native
continuation matrix, SpecMesh lifecycle admission, full rollback and production-writer exclusion.
Mailbox application references are reports until the native adapter independently verifies
them. A coordinator fence cannot prevent an uncooperative external program's side effect.
