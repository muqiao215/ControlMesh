# Persistent local TypeScript control

Status: implemented candidate; full verification/release status is in [progress](progress.md).
This is the existing TS runtime's local process entry, not a Python bridge or a new task store.
Interactive terminal product acceptance and the production default switch remain separate.

## Start and reconnect

Use an already qualified private `controlmesh.local_runtime.v1` profile. The existing
Python `~/.controlmesh/config.json` is not this format. The selected profile fixes provider,
workspace, source, grants, native history and optional SpecMesh/delivery bindings; a caller
cannot override them in a socket packet. Configuration replacement revokes admission.

Run from the ControlMesh checkout with the pinned Bun/pnpm toolchain:

```bash
install -d -m 700 "/run/user/$(id -u)/controlmesh"
CM_SOCKET="/run/user/$(id -u)/controlmesh/runtime.sock"
pnpm runtime --socket "$CM_SOCKET" serve --config /absolute/private/profile.json
```

`serve` stays in the foreground as a service process and prints one readiness record. Its
stdin can be closed; closing a client terminal does not stop the service. An existing process
supervisor can own this foreground command, but this checkpoint installs no systemd unit,
cron or startup hook and does not replace the installed Python `cm`.

In another terminal, use the same socket:

```bash
pnpm runtime --socket "$CM_SOCKET" status
pnpm runtime --socket "$CM_SOCKET" tasks
pnpm runtime --socket "$CM_SOCKET" new task-1 --prompt-file /absolute/request.md
pnpm runtime --socket "$CM_SOCKET" enqueue task-1 --revision 1
pnpm runtime --socket "$CM_SOCKET" inspect task-1
pnpm runtime --socket "$CM_SOCKET" events task-1
```

`status` exposes a copy of the registered project, Provider/model names, registered write
roots and integration presence. It omits credentials, environment values and native storage
paths. Registration is not a readiness/quota report; execution still performs preflight.
`new` reads this current registration, uses its project/model, and requires `--provider NAME`
when more than one Provider is registered. Explicit `--model` or `--project` must match the
selected registration. Unknown overrides fail before task creation. Configuration changes
still revoke the service's authority; this read does not issue a grant or permit.

Creation does not enqueue implicitly. Once explicitly queued, work runs in the service and
the submitting client may exit. Inspect the current revision before `resume` or `cancel`;
both require `--revision N`. Resume preserves the original task/native binding and returns
a new waiting revision; enqueue that revision explicitly. `tell` delivers a follow-up via
the existing mailbox. None of these commands reinterpret an unknown outcome as a retry.

Task lists show status, configured provider/model and the latest queue outcome or task title.
`--after ID --limit N` provides bounded local-principal pages. Explicit task/event reads use
the kernel's existing read/admin authorization. `events TASK --after N` preserves event
sequence and origin: creation, authorization, schedule and recovery remain distinct events.
Human output neutralizes terminal controls; `--json` preserves data through escaped JSON.
For machine parsing through pnpm, use `pnpm --silent runtime --socket "$CM_SOCKET" --json ...`
so pnpm's own script banner does not precede the JSON response. Direct Bun/`cm-runtime`
invocation produces only the command response.

## Agent and advanced commands

`request --file /absolute/request.json` forwards an existing private control operation.
The file can retain its explicit `id`; conflicting `--request-id` is rejected. Existing
history search/adoption, SpecMesh handoff/verification, reconciliation and topology controls
continue through LocalRuntimeControl. There is no generic shell or arbitrary filesystem API.

Each connection is independent and requests may overlap. A long `drain` cannot block another
connection's `cancel`. Frames are bounded to 64 KiB; responses to 8 MiB; pending commands to
128, connections to 32 and in-flight requests per connection to eight. Malformed UTF-8/JSON
and excess input do not become a prompt. The command-line client sends once, with no retry.

A timeout after sending reports `local_control_response_unknown` and the request ID. The
operation may still be running or have committed. Inspect the original task/run or retry
the identical idempotent operation with its original ID and unchanged body; do not create
a fresh task to guess the outcome. Native uncertainty still uses explicit retained-result
reconciliation. A client disconnect cancels only that connection's reply.

## Ownership and restart

The Linux Unix socket lives in a real, owner-only directory; the socket is mode 0600. This
is a trusted local-user control surface with the profile's authority, not a public Web API.
Do not expose/forward the socket or its containing directory to untrusted Agent sandboxes.
Socket path length must be below 104 bytes. Other platforms are unqualified.

An inherited-descriptor `flock` is acquired before opening a profile that might auto-start
work. A second listener cannot silently remove the first one's socket. SIGKILL releases the
OS lock; a new owner removes a leftover socket only after an authoritative connection refusal
and an unchanged inode check. Bun 1.3.11 reports ENOENT for the verified orphaned-socket case;
both ENOENT and ECONNREFUSED require those checks. A timeout or permission failure does not.
Lock files remain in place; their mere existence is not evidence of a running service.

Clean shutdown stops only this runtime's owned execution, drains outstanding control
operations, closes the listener and removes only its own unchanged socket. SQLite queue,
events, receipts and native recovery records persist. Restart processes queued work through
the existing lease/fence owner; canceled, completed, blocked and uncertain attempts are not
automatically turned into new native inputs. No production data migration occurs here.

## Verification boundary

Tests use actual process startup, independent CLI clients, Unix sockets, OS file locks,
SQLite and SIGKILL/restart. A configured Docker test uses the actual file broker, native
verifier, queue and staged publication, with a synthetic Claude process: two turns preserve
the original session after service restart and read the changed project file. This is
service integration evidence, not new real-model memory or physical multi-device acceptance.

The full goal still includes remaining provider/transport/store owners, terminal editing and
rendering, initial workspace distribution, real complex continuation, physical end-to-end
acceptance, reviewed SpecMesh closeout, packaging, release/install and the staged default switch.

## Interactive client prototype

`pnpm runtime --socket "$CM_SOCKET" ui` opens the Bun/OpenTUI client in a TTY. It does
not start a second service. Plain text in new-task mode submits and then enqueues only
the acknowledged revision. `/open TASK` selects existing work; `/resume TEXT` registers
a new round and `/enqueue` explicitly executes it. `/tell TEXT` uses the task mailbox.
`/events` preserves the event view during polling. `/model PROVIDER` chooses among the
registered providers for new work only; it does not change an existing native session.

On an unacknowledged mutation, the client retains the exact packet in memory and blocks
new mutations. `/retry` explicitly resends that same ID/body through runtime idempotency;
it never creates a fresh task or automatically enqueues a follow-on step. Read commands
remain available. The request ID is displayed; retained packets and drafts are currently
process-local, so client restart does not restore them. `/quit` detaches without stopping
the service. This remains an interactive prototype: full terminal-product gates, native
borrowing, real-model acceptance and installed-entry cutover are pending.

Task pages in the interactive client support `/more`; refresh keeps the current page.
Event view advances the service sequence cursor on each refresh, showing at most 200
records in memory and disclosing dropped display records. `/events` restarts history
reading; `/more` catches up another bounded batch. These are lifecycle events, not
live provider-token output.

### Native history in the terminal

`/history claude QUERY` searches the configured headless History catalog.
`/refresh-history claude` explicitly refreshes that catalog; polling/search does not
schedule refresh or execute a model. `/adopt claude SESSION_ID` prepares a task-bound
context handle and shows it without submitting a task. The next plain-text input becomes
the new task prompt; original historical messages are not resubmitted. `/new` discards
the selection. Model changes are refused while a prepared context is selected.

The local runtime history ports support explicitly registered Claude and OpenCode providers.
OpenCode searches its registered SQLite source directly; `/refresh-history opencode` returns
`native_history_refresh_unsupported` because that source needs no derived-cache refresh.
Other provider names remain unqualified. Provider-native
execution still uses the existing registry/baseline checks and enqueue preflight. Terminal
integration tests do not establish real-model memory recall.

### Agent-facing continuity commands

The noninteractive CLI exposes `history-search --provider NAME [--query TEXT]`,
`history-refresh --provider NAME`, `prepare-adoption TASK --provider NAME --session ID`,
`handoff TASK`, and `verify TASK`. Use `--json` and a stable `--request-id` for scripted
steps. `prepare-adoption` returns context only; pass its `result.native_session` JSON as
`new TASK --provider NAME --adoption JSON --prompt TEXT`. The handle is bound to the
prepared task/provider/model/workspace and is revalidated by the runtime. Raw native
references are not accepted by this flag. Use subprocess argument arrays rather than
constructing shell command strings from returned JSON. Creation does not enqueue.

`handoff` and `verify` exit 1 when `gate_passed` is not true, even if the socket operation
completed successfully. Inspect the JSON gate result for details; a transport success
alone does not authorize continuation or prove reviewed closeout. No command loads the
interactive renderer or depends on the Web UI.

## Codex configured continuity profile

The candidate profile accepts a `codex` registration alongside the other providers:

```json
"codex": {
  "executable": "/absolute/path/to/native/codex",
  "cli_version": "0.154.0",
  "codex_home": "/absolute/private/codex-home",
  "model": "selected-model",
  "environment": {},
  "timeout_ms": 60000
}
```

Register the native executable, not an npm wrapper requiring an unregistered Node path.
The existing canonical `codex_home/sessions` tree supplies explicitly selected rollout
records; credentials come from the private auth.json snapshot or qualified API environment.
An OPENAI_BASE_URL override uses the same explicit native backend in probe and resume.
The shared `history` registration enables `history-search`, `history-refresh` and
`prepare-adoption TASK --provider codex --session UUID`. Pass the returned native_session
handle to `new TASK --provider codex --adoption JSON`, then explicitly `enqueue`.
`resume` also requires a later enqueue. Closing/reopening the service preserves the
adoption and execution journal; retained-result recovery does not call the model.

This profile currently runs already-adopted sessions under native read-only settings.
Configured read_files and required_reads are supported when codex.node_executable
is an explicit absolute Node/Bun executable for the private MCP client. Read completion
contracts require exact native receipts and current file hashes. Registered workspace.write_roots
also enables staged write/edit through that client. Native shell settings remain read-only;
the controller owns promotion. The optional SpecMesh profile checks before execution and after publication, including recovery. Preserve governed project requirements. The existing Python production entrypoint
and released default are unchanged; full native sandbox/real-account qualification is
still required by the runtime-convergence acceptance matrix.

Codex retained verification uses persisted message phases to distinguish commentary from
the final answer, because exec JSON does not expose that phase. Every emitted agent
message must match the ordered native history; only the final answer becomes the task
result. The installed-native test also attempts apply_patch inside its temporary
read-only workspace and verifies rejection plus absence of the file. This narrow
qualification does not enable file completion profiles or broader tool/network grants.

Codex now receives pending mailbox messages at the start of a queued native turn. The
input preserves sender/origin metadata and does not change task permissions. Dispatch
reserves the exact batch; verified native user-message identity and full input equality
permit atomic consumption with completion. Reconciliation uses the original batch and
refuses changed mailbox content without another model call. Already consumed messages
are not appended to the next turn. Codex also accepts the existing communication.tasks configuration for active messaging.
It registers only send/ask_parent/receive/answer on one controller-owned MCP server,
with per-tool approval and fixed task peers/parent. The broker retains task/lease checks,
call budgets and origin attribution. Native MCP result text/arguments must match the
existing durable journal before completion or recovery. Installed-native send/ask/receive/answer and recovery have passed against loopback
model fixtures. Two distinct native sessions also exchanged a question concurrently and
recovered without replay. This is local CLI qualification, not physical multi-device
or real-account acceptance.
No new protocol or second message store is used.

Codex 0.154.0 discovers these MCP tools through native tool_search, then calls the
mcp__controlmesh namespace. Per-tool approval configuration follows the
[official MCP options](https://learn.chatgpt.com/docs/extend/mcp?surface=cli); permission
is limited to the four broker-owned tools rather than a server-wide approval default.

Concurrent tasks waiting on the same in-flight provider preflight observe its cached
result within their own bounded deadline. Only the original permit launches a probe.
Cancellation stops a waiter without abandoning the probe owner; failures and unknown
outcomes are returned without automatic re-probing.

Codex exposes the separate controlmesh_workspace MCP server, defaulting to read_file. The
controller configures its allowed file list and required complete reads; task input names
these requirements as literal data. The private workspace journal and original source
snapshot are retained in the dispatch manifest. Every tool call checks the current
lease and matching dispatch digest. Native result content must match journal receipts,
and required reads must cover all current bytes before task completion or reconciliation.
A changed source blocks acceptance. This read profile composes with active messaging;
read_file is not a write or reviewed SpecMesh closeout capability.


With explicit registered write_roots, the workspace MCP server also exposes write_file
and edit_file. They operate on a private WorkspaceStage and require the expected content
hash. The execution manifest binds the stage reference and tool scope. CM verifies native
receipts and completion requirements, seals the proposal, retains the process observation,
then promotes under the current lease and native session lock. Only an applied proposal
can finish the task. Recovery persists its reservation before promotion and consumes the
retained proposal without a model call, including an already-published proposal whose task
confirmation was lost. Concurrent source changes block promotion/recovery rather than being
overwritten. Reviewed SpecMesh closeout remains a separate gate.


Codex uses the same independent SpecMeshPort.bind lifecycle as Claude/OpenCode. The start
check must pass and every plugin reference must already be in configured required_reads;
project assertions cannot add file permissions. The plugin binding is retained in the
Codex configuration digest. During publication, authority checks use the publication
phase so the pre-write document snapshot does not incorrectly revoke an owned change.
A fresh plugin check validates the resulting files before CM confirms the effect. Its
snapshot digest is retained with status=pass and closeout_verified=false. Recovery requires
the same configured plugin and checks the published result again without native execution.
Missing/blocked startup checks do not spend a provider probe; a blocked publication check
leaves retained work for reconciliation and does not imply rollback of already-published
files. Overall closeout still requires the explicit reviewed acceptance path.


Codex adopted sessions can participate in coordinator-assigned native topology tasks.
The adapter validates frozen topology context and prepares its required mailbox input
even when the ordinary inbox was empty. Attributed schedule input is consumed only with
the native user-message receipt. Parent artifact acceptance validates Codex task_completion
against the original contract and current bytes. An installed-native worker/reviewer
pipeline with sequential session continuation and parent completion after service reopen
is qualified on the local loopback fixture. This does not qualify remote Codex workers or
all topology modes; those remain runtime-convergence acceptance work.


Native fanout qualification also uses three separately seeded Codex sessions. Two workers
run concurrently and exchange a question/answer through their registered peer scopes.
A worker whose observation is lost must reconcile before collectWorkers can dispatch the
merger; the merger's frozen context includes both accepted worker summaries. The fixture
asserts two simultaneously running tasks, no replay during recovery, three distinct session
IDs and consumed schedule inputs. It uses a local synthetic model endpoint and supplies no
physical-device or real-account evidence.


The same three-session native fixture also drives the normal TopologyScheduler for
director_worker and debate_judge. The director resumes its original session after the
workers and returns an explicit complete decision; the judge selects a registered worker.
Each decision is built against the frozen output contract's round/role requirements and
is parsed by the production scheduler. Both workers still communicate through scoped MCP.
A completed scheduler drains again without new native requests. This qualifies these
local happy paths, not every repair/round/error branch or physical-device combination.

## Candidate backstage-event file migration

Use `bun packages/controlmesh-runtime-core/scripts/migrate-runtime-events.ts` with
`--source /absolute/events.jsonl --database /absolute/candidate.sqlite --principal OWNER
--session SESSION_KEY`. The default is read-only preview: it validates one selected
session's file and reports SHA-256, byte count, unique and duplicate event counts without
creating/upgrading the target. Repeat with `--apply --sha256 DIGEST_FROM_PREVIEW` to import
that exact snapshot. Existing event IDs with identical payloads replay; conflicting IDs
roll back the event batch. Opening an older candidate target on apply upgrades its schema.

The command does not discover files, start agents, replay tasks or modify source JSONL.
Malformed input and unsupported numeric representations are refusals. Production event
producer cutover is a separate pending migration gate.

### Session-scoped lifecycle summaries

`bun packages/controlmesh-runtime-core/scripts/cm-runtime.ts session-events --socket
/absolute/runtime.sock --session v2:terminal:s:main --limit 20` reads the configured
principal's session summaries (maximum 100). The result contains session_key, count and
JSONL, preserving imported large integers without lossy public JSON number conversion.
Valid-source task lifecycle changes write bounded summaries transactionally. Legacy
partial-context tasks remain available through task events; no session is inferred.

Session history pages also return `has_more` and `next_before`. To continue into older
history, pass `--before NEXT_BEFORE` with the same session. Each page is chronological
and contains at most 100 events / 2 MiB JSONL; newer writes do not shift older cursors.
The initial page covers newest events. A null next_before means there are no older
records in that principal/session at query time.

## Candidate host-job migration

Run `bun packages/controlmesh-runtime-core/scripts/migrate-host-job.ts` with
`--job-id JOB --database /absolute/candidate.sqlite --principal OWNER` plus exactly one
of `--job-directory /absolute/jobs/JOB` or `--legacy-index /absolute/host-jobs.json`.
Without --apply it previews the selected source and leaves the target unopened. Use
`--apply --digest SOURCE_DIGEST` from that preview to import. Source changes refuse;
existing live records are not overwritten. Replaying the same import returns the same
revision. The command reports `execution_authorized: false` even for historical running
or completed jobs; it never starts a command or attaches to an imported PID.

### Host-job control commands

Use the regular cm-runtime.ts CLI and configured `--socket` with `host-jobs`,
`inspect-host-job JOB`, or `approve-host-step JOB --step STEP --revision N`. Reads use
the configured principal; approval uses the configured human-request origin and current
version/definition. Request bodies cannot select an issuer or another principal. These
commands inspect/approve only; they do not run imported commands. Approval output is a
persisted decision receipt, not a process dispatch capability.

### Configured host execution

An explicit `host: { "shell": "/canonical/path/to/bash" }` registration enables the
local-foreground host profile; host-only configuration needs no model provider. The shell
must support bash `--noprofile --norc -c`. Commands run in the registered workspace with
fixed PATH/LANG and bounded supervision; this profile does not implement sandbox grants.

After explicit import and `approve_host_step`, submit a task with `provider: "host"` and
`host_job: { job_id, revision, step_id, approval }`, where approval is the returned receipt.
Use the normal submit/enqueue/inspect controls. Approve each next step at its current
HostJob revision; a completed step task does not automatically approve later commands.
Use inspect_reconciliation/reconcile_task for retained exit outcomes; restart alone never
re-executes an uncertain command. No native session or model probe is created for host jobs.

When SpecMesh is configured, the host runner checks the standalone plugin before dispatch
and after the command. The dispatch manifest binds the plugin profile and starting snapshot;
completion binds a fresh passing snapshot. Recovery requires the same profile and a current
passing check before accepting retained output. Failed checks preserve uncertain execution
without replay. This verifies project workflow state; it does not attest that a shell command
read Agent context or that project closeout was reviewed (`closeout_verified: false`).

### Retained host output

`host-output TASK --stream stdout --limit 4096` reads the latest retained host execution
output through `host_output`. Use returned `effect_id`, `observation_digest`, and
`next_offset` as `--effect`, `--digest`, and `--offset` for subsequent pages. Offsets count
Unicode code points; limit is 1–8192. Stderr is a separate stream. Output is scoped to the
configured principal even if that principal has general task-admin inspection rights.

`available: false` means no retained outcome yet, not successful empty output. Returned
task/effect state and actual process reason remain separate. This endpoint reads database
observations only; it does not open stored stdout_path/stderr_path. Output arrives after
process supervision returns; durable real-time streaming and long-job logs remain pending.

### Create a new host job without legacy import

With an explicit host registration, `create-host-job --file job.json` accepts this shape:

```json
{"job_id":"build","summary":"Build and validate","steps":[{"id":"build","command":"make"},{"id":"test","command":"make test"}]}
```

Allowed job fields are job_id, summary, plan_id, job_kind and steps. Each step accepts id,
title, command, kind and side_effect. The runtime supplies the registered workspace,
timestamps and approval_required=true. Creating a job does not execute it.

Approve the next step with `approve-host-step build --step build --revision 1`. Save the
returned receipt object (the JSON result field, not the whole response envelope), then run
`start-host-step --file approval.json`. Use `--socket` on all commands and retain explicit
`--request-id` values when retrying uncertain responses. Starting atomically creates and
enqueues a task; the response includes its task and run IDs. Read that task with inspect
or host-output. After completion, inspect-host-job gives the revision for the next approval.

Current workflow requires explicit approval/start for each step. It is not automatic
advancement or Python workunit heuristic routing. New command definitions cannot import
PID/state/approval metadata or select a different filesystem root.

### Run the remaining fixed host plan automatically

`run-host-job JOB --revision N --request-id RUN` explicitly authorizes and registers
automatic execution of all remaining pending steps at that job revision. Use the normal
`--socket`. Registration is durable but does not synchronously run commands; the existing
service tick/drain loop queues the next step. `inspect-host-plan RUN` reports progress.
Step-by-step approve/start remains available when whole-plan authorization is not wanted.

The run registration is an immutable command receipt, independently verified before
use. Derived step approvals bind ordered definitions and expected revisions. The next
step is queued only after the prior task/episode, confirmed effect and retained exit-0
observation agree. Manually marking a step completed cannot satisfy this check. Existing
step tasks are never automatically recreated or re-enqueued after failure/uncertainty.
The ordinary task recovery controls remain responsible for those cases.

Each tick scans at most 128 registrations with cursor progression; all steps use the
existing local parallelism and pending limits. Internal enqueue events carry the run and
approval IDs. Extra job mutations invalidate expected progression. This is local host
plan execution; it does not establish durable detached processes or multi-device host
execution parity.

### Ordinary host workunit routing

With explicit host registration, a normal submit containing a nonempty command and a
recognized workunit_kind (test_execution, long_shell, release_validation, uv_build,
git_write, repo_write, repo_publish, github_release, publish, release_publish) uses the
TS host path. Python command-field heuristics are also preserved; prompt text is never
examined for executable intent. Without host registration, normal provider routing stays.

The explicit local foreground command submission issues a current runtime step receipt
and creates its bound job/task atomically; it does not enqueue or execute automatically.
Use the normal enqueue control. Task ID is preserved; provider becomes host, while
host_route stores requested_provider, requested_model and reason. No provider model probe
is needed. Caller-supplied authority, mismatched workspace, isolation-required sources
and unenforceable grants cannot commit a runnable host task.

This preserves Python workunit classification, not its unbounded login-shell process
behavior. Current host source/environment/duration restrictions and long-job gaps remain.

### Live persisted host logs

`host-log TASK --limit 32` reads stored output chunks while a process is running or after
it ends. Poll using returned `effect_id` and `next_after` as `--effect` and `--after`.
`has_more` concerns currently saved chunks, not whether execution has finished; inspect
task_status/effect_state separately. Limit is at most 64 records and encoded page content
is bounded to 256 KiB. Unicode decoding happens before persistence.

Schema 32 stores up to 4096 chunks/1 MiB per effect; the current host supervisor's smaller
256-KiB raw-output limit still applies. Sink failures stop execution and remain an uncertain
outcome, never success. This adds durable streaming under the existing supervisor; long
process lifetime, larger log retention and orphan-process continuation remain separate
qualification gaps. Previous schema-31 TS runtimes cannot open upgraded state.


### Bounded host duration

Trusted host configuration accepts optional timeout_ms (1000..86400000). The default
remains 300000 ms; local lease_ms remains at most 300000. When explicit host timeout is
longer than the lease, the active owner renews before expiry up to the original claim's
absolute deadline. Changing this frozen policy on an existing candidate state refuses
with local_runtime_policy_conflict; it is not a live config-based budget extension.
Supervisor disconnect/cancellation still stops owned execution. This setting does not
establish detached long-job recovery or change provider duration policies.


### Explicit host environment

host.environment is an optional object of process environment names and string values.
It overrides the /usr/bin:/bin PATH and C.UTF-8 LANG baseline. Configure toolchain PATH
explicitly; controller environment and shell login files are not automatically inherited.
At most 128 entries, 32 KiB per value and 128 KiB serialized total are accepted; NUL and
invalid names refuse. Environment changes invalidate queued execution bindings and refuse
retained-result acceptance under a different profile. Values stay in the private config;
execution manifests carry a digest. This is trusted executable configuration, including
any shell-affecting variables, not an untrusted per-task parameter.


### Independent host owner (candidate opt-in)

Set host.detached to true to give each claimed host step an independent execution process.
Control service stop/restart no longer cancels that step; explicit task cancellation does.
Use host.timeout_ms for the total budget and limits.lease_ms for renewable ownership.
Default detached is false. Management drain may return while a detached run is active;
inspect its durable state and logs. Only the claimed host step is transferred: advancing
later plan steps still requires a running management service. Worker death and launch
uncertainty do not authorize command replay. This candidate has not been enabled in
production or qualified for all source/device/provider profiles.
