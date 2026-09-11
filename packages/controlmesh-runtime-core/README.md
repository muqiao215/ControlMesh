# Transactional runtime core (migration in progress)

This is the actual TypeScript state/coordination kernel for the approved runtime migration.
It accepts lifecycle operations, uses a versioned Bun SQLite database, and is exercised by
independent OS processes. It is not the older fixture-case-switching facade candidate.
It has an explicit private candidate startup route and does not yet replace Python TaskHub.
Track completion in [the repository plan](../../plans/runtime-convergence/task_plan.md).

## Current behavior

- `RuntimeKernel` creates waiting tasks, claims execution episodes, starts/renews/finishes
  them, explicitly resumes completed work, cancels tasks, and records uncertain outcomes
  after a running lease expires or the native observation cannot be accepted.
- `TaskIngress` issues provenance and a narrowing task grant from a configured trusted
  channel. It rejects task-body authority and mismatched command origins, commits task/
  grant/source/event/receipts together and retains the original trace on replay/restart.
  It is an internal coordinator entrypoint, not a remote task creation endpoint.
- `LocalTaskRuntime` connects that ingress to durable bounded queues, one preflight and
  actual native execution. Schema 8 retains run receipts across process restarts. Shared
  controller limits, atomic claims and binding/revision checks prevent duplicate execution;
  blocked quota does not repeatedly probe. Inspection/submission/enqueue never launch models.
- `OpenCodeTaskAdapter` selects only a registered workspace/model/container profile and
  uses the same current grant and configuration checks before preflight and native dispatch.
  The qualified source is local foreground read-only work; unavailable admission never
  silently falls back to another model or host runtime.
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
- Local OpenCode execution includes an ordered mailbox prefix in the actual native input.
  Schema 9 reserves messages against the dispatch effect and manifest; generic acknowledgements
  cannot consume them. Verified input/reply, message consumption and task completion commit
  together. Reconciliation verifies that original input after restart without resending it.
  Reserved messages remain bound after expiry; other pending messages keep their normal TTL.
- Optional local native MCP communication supplies task-scoped send/ask_parent/receive/answer.
  Schema 10 retains logical call receipts and verifies them against actual OpenCode tool
  records before consuming messages. Reopening does not replay unresolved calls. The client
  sees one task/episode capability; peer and sender authority cannot be supplied by the model.
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
  route or native adoption semantics. It can use the independently verified container owner
  for network/write-root restrictions; this is not five-provider model qualification.
  Unsupported SDK engines cannot fall back to Claude.
- `ContainerProcessSupervisor` owns one labelled, digest-pinned Docker container per execution.
  It verifies actual mounts, user, namespaces, capabilities, network and resource limits before
  starting a compiled TS PID 1 helper. The helper expires work independently of the host using
  a read-only, boot-bound lease. Cancellation and controller death do not leave detached native
  descendants running or interrupt peer containers. Durable intent/identity records prevent
  replay; explicit `cleanupExpired` removes the original container without running it again.
  Unconfirmed creation or unavailable cleanup remains uncertain. This local Linux/Node image
  profile still requires real provider image, auth, native-directory and startup qualification.
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
- `OpenCodeReadContainerRunner` runs that qualified read driver in distinct containers while
  preserving original project and native data/cache paths. Only OpenCode subdirectories are
  mounted; a read-only auth-file overlay protects credentials inside writable session data.
  HOME/config stay temporary. Preflight and dispatch bind the actual image/profile/resource
  digest, so host readiness cannot qualify a different container. A real Git-project canary
  passed same-session recall/current-file reads after coordinator and runner reopen, with
  headless Viewer revalidation and two confirmed kernel results. General writes and other
  source/provider profiles still need qualification.
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

## Durable terminal-result delivery

`DeliveryOutbox` projects accepted `task.done`, `task.failed` and `task.cancelled` events
into schema-11 outbox records. Projection and insertion are transactional; a restart can
catch up without executing a model. Routes must be explicitly bound while a task is
waiting. Each route pins the issued grant's transport/chat/topic/thread, source context,
output policy and selected adapter. A result body cannot select a destination or turn a
scheduled result into user authorization. No missing-target broadcast fallback exists.
At most 128 unresolved records are projected; later events stay durable. A task's later
result cannot overtake its unresolved earlier delivery.

One sender reserves an attempt before issuing HTTP. Controllers share at most four active
sends in the coordinator database. Shutdown aborts/drains HTTP before closing storage.
Lost/expired sends stay unknown and are never reclaimed for automatic resend. The original
remote acknowledgement is retained
before accepting sent state. If local acceptance fails, explicit readback of that acknowledged
message can reconcile without POST/model execution. No original acknowledgement means no
automatic reconciliation; a similar message is insufficient. A remote receipt is assigned
once per adapter. Credential/preparation failure blocks before send and requires explicit retry.

`FeishuTextDelivery` is the first concrete adapter, for chat-addressed plain text. It checks
HTTP/API success, message ID, selected app sender, chat, text and creation time. Readback also
rejects deleted/updated messages. Shapes follow the installed official Lark SDK and the
[send](https://open.feishu.cn/document/server-docs/im-v1/message/create) and
[get](https://open.feishu.cn/document/server-docs/im-v1/message/get) contracts. Responses are
bounded, redirects denied and errors omit provider bodies/tokens. Tests use real loopback
HTTP and fixture credentials; no real Feishu chat was contacted. Thread/reply, cards/files,
other transports, token refresh and production ingress remain required ports. API
acknowledgement is not end-user read status.

The private local entrypoint accepts optional delivery configuration. Its `source.transport`
must match the intended reply channel (for example `fs`). The selected app must be explicit;
credentials are not discovered or bound automatically.

```json
{
  "delivery": {
    "kind": "feishu_text",
    "adapter_id": "selected-feishu-app",
    "app_id": "cli_explicitly_selected_app",
    "token_file": "/absolute/private/tenant-token.json"
  }
}
```

The owner-only token file contains `app_id`, `tenant_access_token` and `expires_at` (Unix
milliseconds); expiry or app mismatch blocks before HTTP. Startup/inspection do not read
the token and control replies never contain it. Token issuance/refresh remains external.
Before enqueueing, `bind_delivery` takes `task_id`, `expected_revision`, `adapter_id` and
optional `output_policy` (`summarized_only` by default; `full` only when explicit). Enabling
an adapter creates no task routes. `drain` runs queued work and drains bound results, reporting
separate delivery counts; `drain_deliveries` does only the latter. `deliveries` lists a task's
states and distinguishes observed from accepted receipts. `retry_delivery` admits only an
unstarted blocked record; `reconcile_delivery` requires the original `remote_message_id`;
`revoke_delivery` disables that task's route. These are private control operations, not new
public Web/SDK mutations.

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

## Private local coordinator entrypoint

From the repository root, run:

```sh
bun packages/controlmesh-runtime-core/scripts/local-runtime.ts /absolute/private-config.json
```

Configuration uses `schema_version: "controlmesh.local_runtime.v1"` and `mode: "candidate"`.
The canonical absolute file must be owned by the current user with mode `0600`; its
`state_root` must be a separate existing directory with mode `0700`. Known Python state
markers are refused. Configuration changes revoke admission until restart. Do not point
this candidate at the production home or treat marker checks as writer-cutover proof.

The remaining fields bind trusted local registration:

| Field | Required configuration |
| --- | --- |
| `principal_id`, `device_id` | Stable local owner/device identifiers |
| `source` | `human_request` command origin, `user` origin, `local_foreground` source scope and explicit `transport`; this profile does not admit cron or Agent-origin ingress |
| `limits` | Optional `parallelism` (1–16), `max_pending` (1–1024), `lease_ms` (1000–300000); controllers in one database must agree |
| `opencode` | Explicit executable, selected model, CLI version `1.18.29`, private `native_configuration`, string-valued environment with absolute XDG data/cache homes |
| `opencode.container` | Local Docker executable/socket, available immutable image ID, native-compatible Node executable and resource bounds; native OpenCode and Git must exist in the image |
| `opencode.timeout_ms` | Optional native turn deadline, 1000–300000 ms; default 60000 |
| `communication` | Optional native Node executable and trusted task-to-peer/parent registration, described below |
| `workspace` | Canonical directory, exact `read_files`, and the granted subset `required_reads` |

Keep configuration and native credentials outside Git. The adapter uses the existing
native store and read-only auth file, not copied transcripts or credentials in an image.
Status can be inspected even when native credentials or the provider executable are absent.

For native Agent communication, add this registration to the private configuration before
submitting the named tasks. The model cannot add peers or change parent relationships:

```json
{
  "communication": {
    "node_executable": "/usr/local/bin/node",
    "tasks": {
      "parent": { "peer_tasks": ["child"], "parent_task": null },
      "child": { "peer_tasks": ["parent"], "parent_task": "parent" }
    }
  }
}
```

OpenCode receives `controlmesh_send`, `controlmesh_ask_parent`, `controlmesh_receive` and
`controlmesh_answer`. Every call supplies a logical `request_id`. Send takes `recipient_task`
and `text`; ask_parent takes `text`; answer takes the received question's `message_id` as
`question_id` plus `text`. Receive may specify `wait_ms` from 0 to 10000 and returns an ordered
message prefix. Reuse an ID only for the same operation and arguments; a later receive uses
a new ID. Each execution allows at most 32 calls, each task at most 16 configured peers,
and message text at most 4096 UTF-8 bytes. Existing queue and causal-loop budgets also apply.
Operation-level refusals return `ok: false`; they are not successful message delivery.

The runtime prepares a private task channel, starts a per-execution Unix socket broker and
mounts that channel read-only for the native Node client. Normal shutdown removes socket and capability files; the checked client remains for profile identity. A changed
client requires a new qualified profile. Preflight never enables communication tools.
This registration qualifies local foreground OpenCode reads plus scoped messaging.
The device adapter uses the same private channel over the authenticated worker port;
production ingress and the full fleet rollout remain separate migration work.

Each stdin line is one request with a unique `id` and an `op`. Responses carry that ID,
`ok`, and either `result` or a safe error code; concurrent responses may arrive out of order.
Supported operations are `submit`, `inspect_task`, `enqueue`, `inspect_run`, `resume`,
`cancel`, `tell`, `inspect_message`, `mailbox_status`, and `drain`. For example, after submitting a registered waiting task:

```json
{"id":"inspect-1","op":"inspect_task","task_id":"example"}
{"id":"execute-1","op":"enqueue","task_id":"example","expected_revision":1}
{"id":"work-1","op":"drain"}
```

`enqueue` returns a persisted run ID without invoking a model. `drain` advances the queue
and reports queued/running counts; it does not wait for another controller's active work.
Repeating `execute-1` with its original body returns the original run's current state,
including after restart. A changed body with the same ID is rejected. Blocked runs are
not automatically retried. `tell` first returns a pending receipt. The next qualified local
OpenCode turn includes an ordered prefix of those messages in its native input. Inspect a
message using `task_id` and `message_id`, or query `mailbox_status` for `pending_count`.
`consumed` means CM verified the native input and terminal reply; it does not prove semantic
compliance with every instruction. `mailbox_pending_count` in the execution result makes
later or overflow messages visible for a subsequent explicit resume. A batch has at most
32 messages and the full input is at most 65,536 bytes; content is never truncated or skipped
to fit. Agent-origin context retains its sender and cannot issue additional permissions.
SIGINT/SIGTERM stop owned work; interrupted
external effects require reconciliation. EOF does not automatically execute pending work.

## Evidence and remaining work

`pnpm test:runtime-core` checks the Python source/serializer baseline, strict TS types,
transactional state, cancellation, fencing, clock rollback, concurrent OS-process claims,
SIGKILL before commit, lost external receipts, permission revocation and bounded mailboxes.
All fixtures are synthetic; these tests do not touch provider accounts or operator state.
The authorization suite also invokes the live Python owners for 689 input/output pairs
covering source/sandbox policy, provider mapping, narrowing issuance and reply identity.
It keeps the original goldens and separately exercises stricter TS admission rules. Native
static tool expressions are retained; portable grant tokens have their own bounded format.

Remaining before activation: reconciliation for the other execution profiles and abandonment policy, general resume integration,
provider adapter/permission parity and non-Linux supervision, remaining transport delivery/ingress, all other Python
stores, other provider profiles over the device transport, the full native
continuation matrix, SpecMesh lifecycle admission, full rollback and production-writer exclusion.
Generic mailbox application references remain reports; qualified native OpenCode reservations
require matching input or tool records. Device tool receipts are checked against the coordinator journal. A coordinator fence cannot prevent an
uncooperative external program's side effect.

The authenticated worker transport and a real x64/ARM64 synthetic two-device canary are
now implemented. Remaining fleet work includes other native provider/grant profiles and
their reconciliation, durable presence/capability revision and topology/dependency policy,
credential rotation/re-enrollment, unattended service rollout and activation/rollback.
The qualified OpenCode read profile now has a real remote `DeviceAdapter`; assigning a
capability is not a provider tool grant. Other adapters must independently enforce current source,
grant, native-session and workspace rules and verify native evidence before returning a
result. Remote completion is an authenticated worker report, not protection against a
compromised device that fabricates evidence.

## Device transport contract

`schemas/controlmesh/v1/device-*.schema.json` owns the private command/response/lease-window
shapes. Operations are queue, inspect, claim, start, renew, release, dispatch, observe, complete,
unknown, native_call and bounded mailbox send/read/ack. Operator task creation, assignment, cancellation
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

SQLite schema 7 now supports the lost-observation gap for the qualified native read adapter.
A trusted, expiring recovery challenge binds the original dispatch and device evidence.
`DeviceReconciliation` invokes the configured device-local verifier without acquiring an
execution lease or calling the model; the coordinator atomically retains the original
observation, accepted result, terminal task and receipt. A real ARM64 coordinator/x64 OpenCode
worker acceptance recovered the original result and subsequently resumed the same session.
Authentication attests the reporting device, not the honesty of a compromised worker.
General provider/write/source profiles, History adoption into a remote handle, production
services and the full migration/cutover gates remain open.

Device-native communication uses an optional `communication` profile in
`OpenCodeDeviceAdapter`. Its task, peers and parent must exactly match the coordinator's
trusted assignment (`peer_tasks`, `parent_task`); job input cannot override that policy.
The profile participates in native/container readiness and grants. The default preflight
uses the same runner as execution, including its container runtime identity.

The device broker carries no coordinator credential into the native MCP client. Its
worker forwards calls with the current lease and fixed effect ID. The coordinator retains
logical calls and message reservations in the existing schema-10 journal, while the device
retains full native evidence. A result supplies at most 32 call receipts containing only
IDs/tool names and input/output hashes. Every recorded call must match; missing, altered
or unresolved calls prevent completion and recovery. No device-local task/mailbox store
is created. Messages arriving during a run can be received with the native tool.

Before model preflight, device execution reads an ordered mailbox prefix through the
lease-bound `native_input` command. The full input stays in the local manifest; wire
references contain only ordered message IDs and a batch digest. Dispatch reserves that
exact prefix in the same transaction as starting the episode. A changed, expired, skipped
or already reserved prefix rejects dispatch. Later arrivals stay available to native MCP
receive or a subsequent episode. Size limits keep a fitting prefix without truncating a
message; an oversized first message rejects before spending a model probe.

The device verifies the actual native user input and returns its message ID with the batch
proof. Completion or recovery consumes this initial batch before later MCP deliveries, in
the same transaction as accepting the result. A lost completion can reconcile retained
evidence without executing again. A rejected dispatch may release the episode only after
the coordinator atomically proves it has no effects and advances its fence; the retained
local record then becomes `released`. Lost acknowledgement of a committed dispatch still
requires reconciliation and never permits a repeated native call.

Receive waits up to ten seconds outside transactions, with independent lease renewals.
Identical concurrent calls coalesce, completed logical calls reuse their original response,
and unresolved calls after restart cannot execute again. Revocation, changed assignment,
cancellation and stale authority also reject cached responses. Verification consumes
reservations atomically with completion or explicit recovery; recovery invokes no model.

Real ARM64 coordinator/x64 container acceptance covers two OpenCode 1.18.29/M3 Agents:
original parent-session recall, fresh child context over all four tools, coordinator reopen
and reconciliation after a deliberately interrupted completion. Six native calls and three
messages were verified; recovery issued no native command. The private statistics script
failed after acceptance on a wrong column name; independent readback verified the native
records, final coordinator state and removal of all temporary containers/remote processes
without repeating execution. Detailed results and remaining scope are in the active plan.
