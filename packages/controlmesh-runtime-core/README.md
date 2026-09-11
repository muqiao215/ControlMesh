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
- `TaskIngress` issues provenance and a narrowing task grant from a configured trusted
  channel. It rejects task-body authority and mismatched command origins, commits task/
  grant/source/event/receipts together and retains the original trace on replay/restart.
  It is an internal coordinator entrypoint, not a remote task creation endpoint.
- `execution-context`, `execution-policy` and `execution-grants` port the existing source
  enums, sandbox floors, provider flag mapping, submit grants and pinned reply checks.
  An async-local scope keeps concurrent task provenance separate. New TS ingress denies
  unknown sources and malformed persisted identities instead of implicitly issuing legacy
  host compatibility. Tool mapping alone is not process admission; an approval-only grant
  still needs controller confirmation and is refused by the current native launcher.
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
- `OneShotProviderProcess` ports stateless host execution for explicit Claude, Codex,
  Gemini, OpenCode and Claw command shapes. Commands and native output semantics agree
  with the live Python one-shot owner; real fixture processes cover stdin, quota abort,
  incomplete/error output and cancellation. A trusted caller must synchronously recheck
  its current provider readiness and task authority. It has no scheduler/TaskHub startup
  route or native adoption semantics, and does not claim an actual container sandbox or
  five-provider model qualification. Unsupported SDK engines cannot fall back to Claude.
- `HistoryClient` uses Viewer's explicit headless native-reference command. CM independently
  rereads its own configured native store, checks a content-bound v2 reference, and never
  treats candidate text as authorization. The read-only digest includes older messages.
- `OpenCodeWorker` connects the kernel to real OpenCode execution for an explicitly issued
  local foreground read profile. It checks current persisted grants and native resolved
  agent/session permissions, passes the prompt through bounded stdin, verifies native
  append lineage and required current-file reads, and atomically confirms the result.
  A real same-session marker-recall/current-file canary passed; see the active plan.
- `OpenCodeExecution` is the shared native driver for that local adapter and the new
  `OpenCodeDeviceAdapter`. The device adapter consumes coordinator-issued task provenance
  and grants, maps locally configured literal read paths, and binds its local preflight,
  native store and credential revision. Worker events remain agent-origin.
- Before native dispatch, it atomically stores the task/provider/grant binding, native
  baseline row hashes, permission attestation and bounded file fingerprints. Original
  observations are retained separately from accepted results. `NativeReconciler` performs
  explicit read-only verification after interruption and commits an accepted outcome with
  a current revision and evidence-bound receipt. It does not call a model or run the CLI.
  Missing/inconsistent evidence or an unperformed required read stays unknown.
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
- Prepared device adapters persist full manifests and original observations in a device-local
  `DeviceExecutionJournal`. The coordinator stores bounded digest references; native session
  paths and credentials are not transported. Verified session handles resolve on the original
  device after restart, and explicit kernel resume reuses the same native conversation.
  Unstarted preparation failures release their lease; started/lost outcomes remain uncertain.

`Principal` is an internal admission object constructed by trusted ingress. Never accept
its identity, scopes, origin or device from an unauthenticated JSON request. The kernel is
not itself an authentication service. Its low-level state methods do not issue provider
grants. New trusted task submissions use `TaskIngress`; migration uses its separate strict
snapshot path. Valid legacy contexts remain readable, but incomplete context cannot reach
the native worker and new ingress cannot choose `legacy_compat` as a fallback.

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
The authorization suite also invokes the live Python owners for 689 input/output pairs
covering source/sandbox policy, provider mapping, narrowing issuance and reply identity.
It keeps the original goldens and separately exercises stricter TS admission rules. Native
static tool expressions are retained; portable grant tokens have their own bounded format.

Remaining before activation: reconciliation for the other execution profiles and abandonment policy, tell/ask and general resume integration,
provider adapter/permission parity and non-Linux supervision, transport delivery, all other Python
stores, other provider profiles over the device transport, the full native
continuation matrix, SpecMesh lifecycle admission, full rollback and production-writer exclusion.
Mailbox application references are reports until the native adapter independently verifies
them. A coordinator fence cannot prevent an uncooperative external program's side effect.

The authenticated worker transport and a real x64/ARM64 synthetic two-device canary are
now implemented. Remaining fleet work includes other native provider/grant profiles and
remote reconciliation, durable presence/capability revision and topology/dependency policy,
credential rotation/re-enrollment, unattended service rollout and activation/rollback.
The qualified OpenCode read profile now has a real remote `DeviceAdapter`; assigning a
capability is not a provider tool grant. Other adapters must independently enforce current source,
grant, native-session and workspace rules and verify native evidence before returning a
result. Remote completion is an authenticated worker report, not protection against a
compromised device that fabricates evidence.

## Device transport contract

`schemas/controlmesh/v1/device-*.schema.json` owns the private command/response/lease-window
shapes. Operations are queue, inspect, claim, start, renew, release, dispatch, observe, complete,
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

## Native interruption recovery

SQLite schema 5 adds immutable execution manifests and original effect observations. The
manifest is committed with dispatch, before a provider invocation. A manifest failure
rolls back episode start/dispatch; observation storage failure cannot leave half a receipt.
The current native read profile is qualified against OpenCode 1.18.29. File evidence is
bounded to 80 files, 4 MiB each and 16 MiB total; manifests are bounded to 16 MiB. Fingerprints
include canonical path, file identity, metadata and SHA256, with descriptor/no-follow reads.

After the current episode becomes unknown, a trusted owner calls `NativeReconciler.inspect`
and explicitly `accept` with the observed revision and manifest/observation digests. The
verifier rechecks the original task, current authorization, native-store identity, baseline
and append lineage, permissions, workspace identity and required reads under the native
advisory lock. Cancellation, changed evidence and another unresolved effect reject the
decision. Commit records the accepted result, task outcome and reconciliation event together;
receipt replay does not execute the provider or manufacture new execution authority.

An actual worker SIGKILL after native observation but before task completion passed this
flow with OpenCode/M3; a new process verified the original result without another model call,
then continued the same session and read a changed current project file. The initial trial
also reproduced a model reusing old file contents without a new read. CM rejected it. The
issued Agent instructions now describe each required current-turn read, and native debug
inspection checks that the instructions actually reached the selected Agent. Native read
evidence remains mandatory even if the model ignores that guidance. No old unknown task was
automatically rerun to obtain the successful trial.

## Device-local native evidence

SQLite schema 6 adds `device_execution_records`. This is an execution device's evidence
ledger, not a second task authority. It binds device/task/episode/fence/assignment/workspace
and job digest, retains full manifests (16 MiB maximum), original observations and verified
results (4 MiB each), and records preparation/dispatch/observation/verification/completion.
An existing device episode cannot be prepared twice. A failed/lost dispatch acknowledgement
never permits another native call; local observations survive loss of coordinator connectivity.

Native dispatch atomically starts the coordinator episode and records its manifest reference.
Observation/result/handle references must all match that dispatch and each other. The original
observation digest and output digest are checked before accepting a device result. JSON Schema
owns these wire shapes. Native results carry at most 64 KiB of text and an opaque session
handle; full native references, file paths and permission evidence remain local. A handle is
bound to its original device/task/workspace and verified result digest.

A real ARM64 coordinator + x64 native worker run passed OpenCode 1.18.29/M3 continuation
across worker database reopen: same session, marker recall without reinjection, changed-file
read and unchanged task grants. Preflight remained generation 1. The reverse topology was
chosen because that ARM64 device had an older CLI and no native provider authentication;
credentials were not copied. The temporary coordinator, forwarding and credential were
removed/revoked after acceptance. This does not establish ARM64 provider execution.

Remaining recovery gap: when the coordinator never received a device's original observation,
the local journal retains it, but explicit remote verification/attestation and trusted
reconciliation admission are still needed. Do not automatically retry that operation or
claim that local `NativeReconciler` already verifies evidence on a different device. General
provider/write/sandbox profiles, History adoption into a remote handle, production services
and the full migration/cutover gates remain open.
