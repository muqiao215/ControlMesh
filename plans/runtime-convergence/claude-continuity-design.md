# Claude native continuity

Part of the full CM-R3/R6 migration; OpenCode acceptance does not close other providers.

The local CLI is Claude Code 2.1.263. Existing oneshot-command.ts deliberately disables
Claude persistence. Keep that one-shot contract; add a distinct verified native execution
profile rather than silently changing ephemeral execution or passing --continue.

First establish a provider-specific native store reader and independent History candidate.
Claude uses a project JSONL transcript, not OpenCode's SQLite tables. Version-2 identity binds
device, canonical source file identity, UUID, canonical workspace and full raw content bytes.
Partial/malformed or concurrently changed source bytes must reject continuity inspection.
Display parsers remain tolerant; executable context selection is deliberately stricter.
Only the local runtime configuration selects the native store/project path. History returns
context, no source authority, model readiness, permissions or claims of task completion.

Then implement a pinned Claude native profile, explicit --session-id/--resume identity,
closed tool/configuration environment, model preflight with the shared durable quota budget,
retained completion evidence and current-files/SpecMesh validation. Reuse the existing kernel,
process owner, task/device journals and mailbox authority; do not build a second task writer.
The native provider's permission/session history must not replace current CM-issued grants.

Acceptance requires independent Python/TS byte-protocol fixtures, real existing-source
readback, malformed/replaced/edited/foreign-session rejection, exact appended-turn lineage,
then actual current-file reads and same-session recall with model-free lost-result recovery.
Use owned controlled projects for real execution, never append to arbitrary user history.
History remains headless and stdlib-only. Native clients outside CM do not honor its locks.

## Readiness implementation

ClaudePreflight qualifies local CLI 2.1.263, creates an owned private temporary HOME/config,
uses safe mode and explicit credential environment, disables built-in tools/MCP/hooks/plugins,
and requests a single nonpersistent native sentinel turn. Native init and assistant/result
records must agree on the selected model/session; tools/MCP/plugins must be empty. Different
models, extra turns, tool content, absent completion or malformed evidence cannot mark ready.
Unknown environment keys and any unqualified host managed-configuration directory reject
instead of loading them. The accepted host has no /etc/claude-code directory.

ProviderPreflightService.ensureClaude binds the selected credential environment digest and
permission profile before shared-cache admission. Native error fields classify quota/auth;
assistant prose does not. Confirmed zoned reset dates allow bounded waiting, including fractional
seconds; a missing zone remains unknown. Three-probe budget, expiry, lost-permit uncertainty and
explicit operator retry semantics are shared with OpenCode. Host readiness does not qualify a
future container/native execution profile; the actual execution owner must bind that profile.

Actual one-model-call probe passed with the existing selected MiniMax-M3 profile. Independent
readback confirmed zero native tools/MCP/plugins, one persisted permit generation, no repeated
probe on the second check and no remaining owned temporary directories/processes. The stricter
final observer rechecked retained native output without another model. Current readiness expiry
is unchanged. Full Claude original-session execution, workspace/grant/container qualification,
mailbox/retained-turn recovery and normal local/device configuration remain required next work.

## Native append and workspace boundary qualification

`ClaudeSessionStore.baseline` records the original reference, complete prefix byte/row lengths
and idle chain leaf. `verifyTurn` rereads that same configured file, proves unchanged old bytes
and file identity, then verifies exactly one new human input, UUID/parent continuity, main-session
attachments, tool-use/result pairing, selected model and final model-message output. It rejects
pending queue entries, incomplete calls, reused IDs, foreign branches and unsupported compaction.
Tool evidence remains separate from authorization and current-file/semantic acceptance.

Actual native session creation and explicit resume in separate processes recalled the original
random marker. A subsequent current-file turn reported native success with zero tools and an
incorrect answer. Independent revalidation of the retained third-turn baseline/outcome rejected
that answer with no new model invocation. This is actual source-verifier evidence; the CM worker,
successful required reads, staged writes and lost-result reconciliation remain unaccepted.

A separate CLI qualification used two harmless files in an owned project: `dontAsk` and an exact
Read allow rule still permitted reading the ungranted file. Do not weaken CM grants or route
restrictive tasks through this host profile. The next owner should provide explicitly scoped
CM workspace MCP operations with native built-ins disabled and independently recorded tool
receipts. Reuse the current private channel, staged workspace and task/effect/lease ownership.
The ordinary peer-message client must not silently acquire file capabilities. Reads must retain
path/content freshness; writes must stay staged until current authority authorizes publication.
The configured MCP profile needs its own native qualification: safe mode used for zero-tool
preflight disables MCP, so preflight's profile cannot be silently reused as execution proof.

## Scoped workspace capability implementation

`NativeWorkspaceFiles` now owns explicit file reads and staged CAS write/exact-edit operations.
The trusted caller supplies the task/effect binding, synchronous authority callback, current
source/grant check and existing `WorkspaceStage`. MCP arguments cannot select those owners.
The separate `workspace.v1` private client advertises three file tools and no peer messages;
the ordinary message broker rejects this profile. Native built-in tools must remain disabled.

The scope pins workspace/journal identities, registered source snapshots, granted tool names
and staged write roots. Reads preserve UTF-8/BOM bytes in bounded pages and require complete,
same-current-revision coverage for every required file. CAS and unique-match edits cannot
silently overwrite changed contents. Writes use anchored stage-directory descriptors and
atomic replacement; existing stage seal/promotion retains publication authority.

Private receipts persist intent before mutation, then the observed response. Identical retry
returns the original durable response even after reopening. An interrupted pending write stays
unknown; trusted reconciliation can accept already matching staged bytes without writing again.
Acceptance independently matches native tool inputs/results to every receipt and final staged
hash. Missing native evidence or an unrecorded final change rejects. This is file-operation
evidence, not an automatic task completion or grant issuer.

This profile bounds one execution to 256 logical requests, 2,048 read bytes per page, 8,192 text
bytes per write/edit argument, and 4 MiB per existing file. A large required-file set may exceed
the total request budget even though each file fits the file-size bound; the future execution
admission must account for required read coverage. The actual native qualification used one
small registered file and one staged output, not an unrestricted development workspace.

## Actual MCP qualification and remaining integration

The installed CLI's static `--mcp-config` attempts exposed no tools or servers. One model turn
therefore produced tool-looking prose without real calls and failed qualification. Subsequent
control-only inspections sent zero user messages: `initialize`, dynamic `mcp_set_servers`, then
`mcp_status` established a connected workspace server with exactly the three expected tools.
The execution owner must verify this control response before sending any user input; do not
spend another model turn merely to discover that MCP failed to connect.

One isolated actual CLI 2.1.263/MiniMax-M3 turn then read the registered current file, received
an explicit denial for an ungranted file, and wrote the correct content into the stage. Its
original JSONL contains all three real calls/results, including the error result. The unchanged
append verifier and the workspace receipt verifier independently accepted that evidence, found
zero built-in tools, and confirmed that canonical output was absent. Rechecking after the
bounded-read performance change used zero model commands. Existing credential environment
values were passed unchanged; actual HTTP authentication headers were not inspected.

The original private dynamic helper established the protocol shape. Its supervised repository
implementation and current native evidence are described below. Workspace tools plus an isolated
native proof do not establish normal worker recovery, publication, container/device qualification
or CM-R7 readiness.

## Supervised control lifecycle

`ClaudeControlRunner` now invokes the pinned CLI version and starts `claude-control-process.ts`
inside the existing process supervisor's anchored group. Input is private structured stdin;
prompt text never enters shell arguments. The native command fixes bare mode, disabled built-ins,
empty static MCP configuration, explicit model and exact `--session-id`/`--resume`. Environment
keys are limited to selected credentials/proxy/CA settings; HOME/config are explicit private
directories outside the workspace. Executable and directory identities are rechecked with the
enclosing synchronous lease/source/grant callback, including between version and execution.

`ClaudeControlSession` correlates initialize/register/status responses, verifies the one dynamic
workspace server's command, tool names and connected state, and only then returns one user frame.
An empty/pending table has at most six bounded control checks. Unexpected native permission
requests, tools, model/session/configuration, malformed or duplicate completion fail admission
or completion. The helper wraps native rows separately from its own input/exit/abort evidence,
so a provider row cannot impersonate the owner. Complete abort evidence distinguishes input
withheld from input attempted; missing evidence remains unknown. `observeClaudeControl` replays
retained evidence without native execution and classifies quota only from native error fields.
Original JSONL, required reads, tool receipts and task completion remain separate checks.

Actual explicit resume through this repository driver restored the earlier controlled session,
read its current PROJECT.md and wrote a staged value containing both its original random marker
and current file bytes. The new prompt did not contain the marker. A single shared-cache native
preflight preceded one resumed task input; two real tool calls were retained. Independent source,
control, receipt, file and private-kernel readback accepted the result with zero new model calls,
and found no owned process or canonical output. The original pre-turn JSONL prefix, including
the earlier failed read, remained unchanged. That failed historical turn was not rerun or
retroactively declared successful. Its old latest-turn verifier must not be run against the
now-longer source without selecting the appropriate retained prefix.

## Normal local task and recovery ownership

`ClaudeTaskAdapter` now connects normal configuration and `LocalTaskRuntime` to the qualified
driver. Registration intersects current task grants with literal reads/staged write roots, rejects
unsupported source/network/confirmation profiles, and checks required-read page budget before
preflight. Session lookup uses the configured private native catalog; duplicate UUIDs across
project directories reject. No transcript path or historical permission becomes authority.

`controlmesh.claude_dispatch.v1` binds the task/configuration, original source baseline, input,
workspace scope and stage. Original process output is stored once in a private fsynced file;
the kernel keeps a bounded digest/reference observation. `ClaudeTaskEvidence` checks that raw
outcome, native JSONL, current publication authority and durable file receipts. The retained file
owner cannot execute tools. `ClaudeTaskReconciler` can admit already-retained output after loss
of kernel observation and reuse a sealed/applied stage; no native runner exists in that path.
The optional independent SpecMesh port checks start/publication and retains closeout=false.

Real normal-startup validation qualified native parallel-tool edges: result parents may be their
exact pending tool owner with matching sourceToolAssistantUUID. Ordinary rows retain the linear
tip rule, and API message transitions require pending tools to be resolved. This handles native
parallel flush order without accepting arbitrary branches or relaxing original-prefix identity.

Actual same-session recall/current-file publication and retained recovery passed scoped readback.
The strict fixture prompt did not fully pass: a first missing newline was corrected in the second
turn, which added prose before JSON. Preserve both defects in the acceptance record; source/tool
evidence is not automatic semantic verification of the user's requested result.

## Scoped native peer communication

Optional local communication registration now supplies Claude peers/parent and the same explicitly
configured Node executable. The adapter creates a separate NativeAgentBroker alongside the file
channel. Native control verifies both `workspace` and `controlmesh` MCP servers, their exact
commands/identities/tool tables and the init record before sending input. The message server gains
no file tools; the workspace server gains no peer tools. Without communication configuration the
old one-server command and manifest remain valid. Unsupported message grants reject at admission.

The existing NativeAgentScope is persisted in the Claude dispatch and rechecked against current
configuration, original client digest and task identity. The existing journal owns all message
mutations, fixed sender/episode/fence, bounded waits and request deduplication. Original Claude
tool blocks normalize into journal verification separately from file verification. Consumption
occurs in the same kernel transaction as completion; a lost finish leaves receipt state recoverable.
Reconciliation verifies/consumes the same original rows without a broker or model invocation.

Actual two-Claude-session read-only workspace trial passed: concurrent normal queue execution,
seven current SpecMesh documents per task, six native message calls, private marker exchange via
question/answer/acknowledgement, three consumed messages, one preflight and two native task inputs.
Independent raw-source/control/file/journal verification used zero native commands and found no
owned process. Existing one-shot behavior and OpenCode-specific manifests remain intact.

Next connect container/device profiles. Remaining mixed-provider
and write topologies, provider/transport/store/product parity and CM-R7 gates stay open.

## Local History adoption contract

The private candidate's `scripts/local-runtime.ts` JSON-lines controller accepts optional trusted
configuration alongside an explicitly registered Claude profile:

```json
{"history":{"directory":"/absolute/path/to/Codex-Claude-History-Viewer","python":"/usr/bin/python3"}}
```

The installed `cm` command/public read-only API is not this candidate entry point. A calling Agent
uses the controller operations below; provider/source paths remain configuration-owned:

```json
{"id":"refresh-1","op":"refresh_history","provider":"claude"}
{"id":"search-1","op":"history_search","provider":"claude","query":"SpecMesh"}
{"id":"prepare-1","op":"prepare_adoption","provider":"claude","task_id":"continue-project","session_id":"<selected candidate UUID>"}
```

Preparation returns `authorization: context_only` and an opaque `native_session`. Pass that object
as the normal submit task's native_session with the same task/provider/model/workspace. Submission
and enqueue/drain remain separate explicit operations; search/refresh/prepare do not execute.
Handles persist across reopen. Source bytes are independently validated again at execution.
The local adapter currently qualifies Claude; unregistered providers reject without fallback.
Existing device OpenCode adoption remains supported through its own configured path.

Search reports freshness unknown and refresh_policy explicit; it never refreshes automatically.
The History process receives no provider credentials and uses a separate private derived cache.
Canonical ancestor checks reject path aliases before cache creation. Four pending requests,
10-second subprocess timeout, 20 candidates and 256 KiB output bound this CM interface; History's
complete indexing/backlog and resident-service budgets remain separate gates.

The native reader now recognizes the actual max_turns_reached attachment as a failed but resumable
boundary only when all tools/queued input are resolved. Native 2.1.263 emits an exact metadata
user/synthetic-assistant pair before the next explicit input; only that qualified pair is context
padding. It cannot contribute a model result or make the old failed turn successful. A real
corrective adoption input completed exact old-memory/current-file output with nine tools in ten
turns. Retained recovery, including an injected post-publication task.done loss, required no model
execution and preserved source bytes/file inode. Independent readback accepted the scoped result;
original failed attempts and the later diagnostic-report digest error remain recorded separately.

## Container and device execution owner (in progress)

Reuse ContainerProcessSupervisor for verified image/mount/isolation state, bounded resources,
in-namespace lease watchdog, exact container identity and retained cleanup recovery. Claude's
control helper and native process must run inside that boundary. Canonical project mounts remain
read-only: existing file MCP capabilities alone write the stage and the current owner publishes.
Private native HOME/config persistence and task-scoped file/message IPC are separate mounts;
provider binaries/helper code are immutable read-only resources. Never mount an entire checkout
of CM or relax source policy merely because a container-shaped profile is configured.

Fixed version/control commands, isolated preflight, native original-session reads/writes,
MCP registration and cancellation now have concrete runner qualification. The shared preflight
command builder rejects arbitrary commands/environment keys; its runtime digest binds the
immutable image and canonical executable. The execution runner mounts a private hash-named Bun
bundle of the existing control helper, image-owned Node for MCP clients, native HOME/config and
read-only project/channel resources. Profile, binary, helper and capability changes invalidate
dispatch. Actual Docker tests and one real native original-session continuation passed; a separate
model-free readback verified tool receipts, current-file output and four removed containers.
This is not normal local/device admission. Device integration must
reuse DeviceWorker's prepared dispatch/observe/result, current authority, mailbox/nativeCall and
publication/reconciliation interfaces; it must not create another local kernel inside a worker.
The current device configuration is OpenCode-specific and remains unchanged until those Claude
ports are qualified. Full provider/transport/store/topology/product and CM-R7 gates remain open.
