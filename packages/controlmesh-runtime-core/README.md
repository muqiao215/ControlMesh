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
  Qualified local profiles include reads and explicitly registered staged workspace writes; unavailable admission never
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
  local foreground read or staged-write profile. It checks current persisted grants and native resolved
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
  explicit native verification after interruption and commits an accepted outcome with
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

`FeishuTextDelivery` supports chat-addressed text, quoted replies and replies in an explicitly
identified existing Feishu topic. It checks
HTTP/API success, message ID, selected app sender, chat, text and creation time. Readback also
rejects deleted/updated messages. Shapes follow the installed official Lark SDK and the
[send](https://open.feishu.cn/document/server-docs/im-v1/message/create) and
[get](https://open.feishu.cn/document/server-docs/im-v1/message/get) contracts. Responses are
bounded, redirects denied and errors omit provider bodies/tokens. Tests use real loopback
HTTP and fixture credentials; no real Feishu chat was contacted. Cards/files, creation of
new topics, other transports and production ingress remain required ports. API
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
milliseconds); expiry or app mismatch blocks before HTTP. Alternatively, replace `token_file`
with `app_credentials_file`, pointing to an owner-only file with `app_id` and `app_secret`.
Both fields together are rejected. `FeishuTenantCredentials` then uses the selected app's
[tenant-token endpoint](https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal).
Tokens stay in this runtime instance's memory; concurrent callers share one refresh.
Expiry uses a monotonic clock from request start, with early refresh but no artificial
minimum lifetime. Credential-file rotation invalidates the old cache and in-flight refresh;
prepared HTTP operations also recheck their token before sending. One canceled waiter
does not cancel other callers. Stop aborts and drains all refreshes, including superseded ones.
Authentication rejection waits for explicit `retry_delivery` or credential rotation;
transient/timeout failures have a 30-second cooldown and no background retry loop.
Startup/inspection do not read credentials or contact an auth endpoint. Errors/control
replies never contain tokens, secrets or provider response bodies. This supports self-built
app tenant credentials; user OAuth and marketplace-app authorization remain separate owners.

Optional `delivery.replies` pins reply targets by task ID, for example:

```json
{
  "task-id": {
    "chat_id": "oc_selected_chat",
    "message_id": "om_original_message",
    "thread_id": "th_existing_topic",
    "reply_in_thread": true
  }
}
```

For a quoted reply outside a topic, use `thread_id: ""` and `reply_in_thread: false`.
The private control entrypoint derives the reply grant and stored task thread from this
trusted configuration; conflicting task-body chat/thread metadata is rejected. `topic_id`
stays empty for this port; the native Feishu topic ID occupies `thread_id`. Before dispatch,
GET verifies the original message's chat/topic and deletion state. POST then uses the
[reply endpoint](https://open.feishu.cn/document/server-docs/im-v1/message/reply), with no
fallback to ordinary chat delivery. Both send acknowledgement and recovery readback must
match the parent, root and topic. The reply profile is included in the adapter binding
digest, so changing it cannot silently reuse an existing task route.

Before enqueueing, `bind_delivery` takes `task_id`, `expected_revision`, `adapter_id` and
optional `output_policy` (`summarized_only` by default; `full` only when explicit). Enabling
an adapter creates no task routes. `drain` runs queued work and drains bound results, reporting
separate delivery counts; `drain_deliveries` does only the latter. `deliveries` lists a task's
states and distinguishes observed from accepted receipts. `retry_delivery` admits only an
unstarted blocked record; `reconcile_delivery` requires the original `remote_message_id`;
`revoke_delivery` disables that task's route. These are private control operations, not new
public Web/SDK mutations.

SIGTERM/SIGINT stop execution, delivery and credential refresh before closing storage or
awaiting control replies. Intentional input-stream closure is a clean exit; unrelated stream
and persistence failures remain errors. A real stdio process test holds an HTTP request,
signals the child and verifies a prompt clean exit with the uncertain delivery preserved.

## Authenticated headless Feishu ingress

The private candidate can accept signed text events without opening Web. Configure
`source.transport: "fs"`, a selected Feishu delivery adapter, and the following `inbound`
object in its private runtime configuration:

```json
{
  "inbound": {
    "credentials_file": "/absolute/private-event-credentials.json",
    "allowed_senders": ["ou_selected_user"],
    "allowed_chats": ["oc_selected_chat"],
    "bot_open_id": "ou_selected_bot",
    "require_group_mention": true,
    "path": "/feishu/events",
    "port": 8788
  }
}
```

The mode-0600 event credential file contains `app_id`, `verification_token` and
`encrypt_key`; the app must match the selected delivery app. Changing either private file
requires restarting the candidate. Sender/chat allowlists are explicit; empty lists admit
nobody. This port verifies the signature over original HTTP bytes, checks timestamp/token/
app identity, and supports encrypted AES-CBC event envelopes and token-authenticated URL
verification. Only allowlisted human text messages enter the inbox; group mentions must
identify the configured bot.

```sh
bun packages/controlmesh-runtime-core/scripts/serve-feishu.ts /absolute/private-config.json
```

The listener binds only `127.0.0.1`; a separately configured ingress proxy is needed for
provider delivery. The JSON-lines controller also exposes `start_inbound`, `inbound_status`,
`drain_inbound` and `retry_inbound` (with `receipt_id`). Their request bodies cannot replace
the configured port, app, identity or execution authority.

Schema 12 retains normalized messages and event/message aliases before returning the HTTP
receipt. Duplicate events return the same receipt. Creating/resuming the conversation task,
binding the original reply destination, enqueuing work and marking input applied share one
transaction. An HTTP receipt means persisted input; `applied` means queued task input,
not successful Agent execution. Inspect task/run and delivery status separately. Completed
turns resume their original native session; active turns defer subsequent messages. Unknown
effects require reconciliation. Blocked input requires explicit retry and is never rewritten.
The inbox admits at most 128 unprocessed records; a blocked conversation does not prevent
independent conversations from progressing. Processing is event-driven, with no cron/model
polling. Applied event history currently remains stored; automatic retention is not implemented.

Reply identity comes from the verified conversation-opening event and stays pinned across
turns. Direct-message execution uses the qualified OpenCode read container. Host runners
still admit only local foreground input, and group messages retain their controller-approval
requirement; that approval path remains to be ported. Other event types, attachments, cards,
long-connection subscription, legacy conversation-ID adoption and production cutover remain
in the migration plan. HTTP fixtures do not establish real Feishu-account acceptance.

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
| `workspace` | Canonical directory, exact `read_files`, subset `required_reads`, optional canonical directory list `write_roots` |

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

## Local staged workspace writes and recovery

The optional `workspace.write_roots` private registration grants read/edit inside literal
canonical directories; it does not come from task input. The portable task grant must permit
the native edit/write/apply_patch family. Empty or absent roots retain read-only execution.
Git metadata and existing symlink aliases are denied. The runner overlays private staged
roots at their original paths; only the current controller publishes canonical files.
Each file has a recoverable journal; the complete batch is not atomic. Conflicting external
edits are retained. Limits and unresolved profiles are in
[the native write design](../../plans/runtime-convergence/native-write-design.md).

A failed completion can leave an interrupted run with an original retained proposal. Inspect
the current task revision/effect, then obtain the evidence binding through private control:

```json
{"id":"inspect-recovery-1","op":"inspect_reconciliation","task_id":"example","expected_revision":4,"effect_id":"original-effect"}
```

For `reconcile_task`, send a new stable `id`, the same `task_id`/`expected_revision`, and
`candidate` equal to the returned four-field binding (`episode_id`, `effect_id`,
`manifest_digest`, `observation_digest`). Do not invent these values. Acceptance rereads the
original native/file evidence and resumes only that sealed proposal. It never invokes a
model. Schema 13 reserves request identity before publication and workflow verification;
conflicting reuse rejects, including after restart. A successful receipt is replayable
without rewriting files. Inspection needs no provider credentials; acceptance requires the
original current registered profile and native evidence. Unsealed outcomes remain unknown.

The optional SpecMesh gate runs again after publication and can validate owned continuity
document changes. Current structural pass is recorded separately from independent semantic
closeout. A real two-turn normal local TaskHub canary exercised edits, completion loss,
reopen/reconciliation and original-session recall. The device write owner also has real
acceptance; see Device-local workspace writes below for its separate integration boundary.

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
continuation matrix, externally verified SpecMesh closeout, full rollback and production-writer exclusion.

## Optional independent SpecMesh gate

The private candidate config accepts an optional `specmesh` object:

```json
{"directory":"/absolute/independent/specmesh","python":"/absolute/python3","task_path":"plans/current-task","timeout_ms":15000}
```

Use the independent SpecMesh v1.2.1 snapshot profile (qualified source
`5fab9f0f824352ef6d32b72cc8a31050e6499b5f`). `directory` is a canonical checkout root;
Python 3.11+ and POSIX descriptor support are required by this optional executable profile.
`task_path` is a relative directory or null, selected by the trusted local configuration.
It is not chosen from an incoming message. Timeout must be 1000–60000 ms; at most four
concurrent checks run. Package and Python identity changes require an explicit runtime
restart. This adapter trusts the configured Python installation and plugin code.

The gate invokes the real standalone capability/check commands, validates their JSON, and
requires structural pass before native preflight. Add every selected AGENTS/PROJECT,
architecture/decision and task continuity file as an absolute path to the existing `workspace.read_files` and
`workspace.required_reads` registration. It never expands those permissions from document
links. The Agent's normal native-read verifier then checks actual consumption on each turn.
File content, identity, absence, HEAD and implementation changes revoke the observation.
The read profile does not permit modifying continuity files during a turn. Explicit local
write roots permit owned changes; the adapter rechecks the current snapshot after publication
before completion. It does not promote structural pass to independently reviewed closeout.
Git tracking/modified metadata describes the plugin's inspection snapshot; it is not a
review or a persistent lock on the Git index.

Private control requests accept only the current owned task ID:

```json
{"id":"handoff-1","op":"prepare_handoff","task_id":"task-1"}
{"id":"verify-1","op":"verify_specmesh","task_id":"task-1"}
```

Responses include task revision, snapshot digest, `gate_passed` and the independent result.
Only `pass` sets the gate flag. A self-reported passed acceptance manifest remains `unknown`;
these operations do not finish/resume a task, issue authority or launch a model. No service
or public Web/API default is changed. Markdown-only SpecMesh use remains independent.

Reproduce paired tests with `CM_SPECMESH_TEST_ROOT=/absolute/specmesh bun test
packages/controlmesh-runtime-core/test/specmesh-port.test.ts`; without that explicit source
the five paired cases are reported skipped. CI checks out the pinned source and requires
all seven cases. A real local OpenCode canary also verified five current document reads per
turn and original-session recall across runtime reopen; full migration remains open.
Generic mailbox application references remain reports; qualified native OpenCode reservations
require matching input or tool records. Device tool receipts are checked against the coordinator journal. A coordinator fence cannot prevent an
uncooperative external program's side effect.

The authenticated worker transport and a real x64/ARM64 synthetic two-device canary are
now implemented. Remaining fleet work includes other native provider/grant profiles and
their reconciliation, durable presence/capability revision and topology/dependency policy,
credential rotation/re-enrollment, unattended service rollout and activation/rollback.
Qualified OpenCode read and staged-write profiles now have a real remote `DeviceAdapter`; assigning a
capability is not a provider tool grant. Other adapters must independently enforce current source,
grant, native-session and workspace rules and verify native evidence before returning a
result. Remote completion is an authenticated worker report, not protection against a
compromised device that fabricates evidence.

## Device-local workspace writes

`OpenCodeDeviceOptions.write_roots` registers literal relative directories under the worker's
trusted logical workspace mapping. Absent/empty roots retain reads. Use the matching
`OpenCodeStagedContainerRunner` and an owner-only `state_home` outside the project and its
ancestors; both adapters now validate that layout before spending a preflight. The task's
portable grant must permit the shared edit/write/apply_patch permission and selected roots.
The optional `specmesh: SpecMeshPort` runs independent checks before preflight and after owned
publication; every selected continuity reference must already be in `required_reads`.

The worker retains actual native files, store identity, v2 manifest, sealed proposal and
write journal locally. `DeviceEvidenceRef.workspace_write` sends only the profile digest
and workflow binding. `DeviceNativeResult.workspace_write` carries the matching profile,
proposal digest, changed count and optional structural SpecMesh result. A missing/substituted
proof cannot complete or reconcile a write task. Read-count metadata reflects actual reads,
including authorized files beyond the fixed required-read registration; it issues no grants.

Publication drains concurrent renewal and obtains current coordinator authorization before
any canonical file replacement. Synchronous file steps also check the local conservative
lease deadline and scope. Recovery re-fetches its original current challenge, validates the
retained native/proposal evidence, and resumes only the original journal. Native execution is
unavailable during recovery. A partition/revocation/cancellation at confirmation rejects;
files applied before later cancellation or completion loss remain an unknown outcome to
reconcile. Neither immediate remote revocation nor atomic multi-file transactions is claimed.

An actual ARM64 coordinator/x64 OpenCode worker passed two-turn edits/current-document reads,
coordinator reconstruction and original-proposal recovery without another model invocation.
See the repository native-write design for limits. Normal device startup/control and the
installed workflow remain pending; the existing device script is a synthetic test driver.

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
