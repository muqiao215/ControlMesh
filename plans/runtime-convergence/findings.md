# Findings

## Normal project continuation controls — 2026-09-12

The kernel already archived a completed topology and retained its task identity, but
normal local/coordinator controls exposed no reopen operation. A completed scheduler
also rejected ordinary activation. The new explicit operation verifies the existing
schedule, task and topology revisions, archives with the existing kernel owner, then
activates ordinary dispatch in one transaction. It does not retry blocked model output
or resume cancelled tasks. The frozen role plan and controller budgets remain in force.
Archived root executions are readable through the same private operator surface.

Initial focused tests found a new guard incorrectly querying a state column on
topology_device_runs. Device state is derived by the registered execution owner, unlike
local_runs. The guard now uses runtime.inspect for existing native assignments. This
does not introduce a duplicate state owner or change the database version.

Focused local/nested/device continuation checks passed: 103 tests / 1143 assertions /
14.75s. The configured coordinator/container fixture also passed: 1 / 53 / 20.40s. It
completed artifacts after restart, then used reopen_schedule to dispatch a second run.
Both native manifests used resume=true and retained the original worker/reviewer session
IDs. The original input prefix and archive stayed unchanged; replay of the operator
request did not create a third run. Docker, MCP, file receipts, source verification and
configuration controls are actual; the Claude executable and transcripts are synthetic.
This does not qualify real-model memory or physical multi-device behavior.
Full final-source runtime gate passed: 740 tests / 9683 assertions / 71 files / 264.78s,
exit 0, with typecheck passing. Log: /tmp/cm-schedule-reopen-full.log.

Read-only inspection of the installed Claude help confirms a --json-schema option.
Current claudeControlCommand only requests stream-json framing, and final evidence binds
the result string to the native assistant text. Stream framing does not enforce the
task's JSON result contract. Native structured-output behavior under the current bare/
empty-tool grant and configured provider remains to be investigated and verified before
integrating it; parsing a convenient substring from a failed response is not acceptance.
The [official CLI documentation](https://code.claude.com/docs/en/headless#get-structured-output)
also distinguishes stream framing from schema validation and the structured_output field.

A bounded independent native probe now confirms Claude 2.1.263 / configured MiniMax-M3
with stream-json plus --json-schema under bare/empty-tool/dontAsk mode. One input used
two native turns. Init advertised only StructuredOutput, no MCP servers or plugins; the
native transcript records that exact tool and its successful result. structured_output
matched the random schema fact and the final text was its JSON encoding. Session/model/
version/tool-table identity was rechecked from retained stdout without another invocation.
The isolated pinned container was removed, the temporary credential file deleted, and
production/native project sessions were untouched. Guarded operator artifact:
outputs/runtime-convergence/claude-structured-output-probe-20260912.{ts,json,attempt.json}.
This proves the installed provider capability, not CM's integration with dynamically
registered MCP, topology schema references, completion receipts or real continuation.

## Canonical device artifacts and completion order — 2026-09-12

The local artifact gate had read local_runs directly and rejected every device-native
result. It now resolves the actual execution owner through topologyExecution. Remote file
witnesses require an explicit device-to-logical-workspace map, current assignment/lease,
confirmed effect, matching original device evidence/native handle, and a validated child
completion contract. The coordinator still reads its actual canonical destination; matching
remote hashes alone never complete a root. Device-local paths and source stores stay local.
Normal device startup supplies this gate, including independent current SpecMesh checks.
It does not transport files or verify an exclusively remote final workspace.

snapshotReads returns sorted canonical paths. Indexing that array by unsorted task-contract
order could pair a digest with the wrong file. Capture now looks up each exact requested
path and preserves contract order; an internal symlink alias cannot replace that path.
Missing destination files receive a specific status code without exposing a private path.

Controlled HTTP/file-owner checks cover delivery followed by restart, absent/wrong source
maps, revocation, native handle changes, resumed children, current bytes, internal/external
symlinks and unsorted multi-file requirements. A separate actual-container fixture uses
normal coordinator/worker startup, synthetic Claude/native records and real file tools,
then finishes after explicit fixture delivery and coordinator restart with no new turn.
Full runtime gate: 707 pass / 9114 assertions / 71 files / 249.57s, exit 0.

Prior 8d5dae2 CI 34696701829 failed in bundled-dashboard drift checks: main.js embeds the
protocol registry and the new native failure schema had not been rebuilt into it. The
pinned Web build adds 39 schema lines. Isolated-wheel read-only Alpha smoke now passes,
including installed imports, CLI/HTTP/SDK reads and packaged dashboard assets; production
installation and services were untouched. GH log cache used a task-local XDG cache after
the default read-only cache prevented downloading the log.

The first real artifact canary stopped at invalid schedule registration; both candidate
stores prove zero provider checks, executions, episodes or effects. Its original record is
retained. The corrected bounded script includes fanout's required merger/controller, with
one preflight and at most two native inputs. It finished unsuccessfully: one provider
preflight and one worker execution were recorded. The worker read all eight required
files and reached native done, but surrounded its result JSON with prose and a Markdown
code fence. The scheduler correctly blocked with team_result_invalid_json before assigning
the merger; the operator script then surfaced assignment_unavailable. No merger turn or
root artifact completion occurred. Both attempts are retained and guarded against replay.
This is a negative real-model acceptance result, not a passed multi-device or continuation
gate. The helper process is terminal; there is no pending canary to poll or restart.

## Confirmed native read-contract failures — 2026-09-12

The retained real reviewer turn ended with matching session/input and zero workspace calls.
The prior verifier threw required-read-missing before returning a result, so normal task
handling marked this known negative as uncertain execution. ClaudeTaskEvidence now verifies
all actual calls first and emits a narrow native_task_failure only without write staging or
communication authority. Kernel, device wire results and reconciliation preserve `failed`.
The scheduler settles the execution without automatic retry. Failure cannot claim completion,
publication or SpecMesh success; other providers and uncertain effects retain existing rules.

Controlled local tests cover explicit same-session continuation after a known failure,
consumed input, lost observation, idempotent recovery and refusal under write/message scope.
Actual containers with synthetic Claude/native transcripts verify device completion and
recovery without rebuilding or calling the provider. The tool table is unchanged; read-only
authority remains enforced by NativeWorkspaceFiles, not inferred from advertised MCP names.

Retained real evidence was then reconciled using normal configured recovery: reviewer became
failed, seven missing files were recorded, original session retained, native/project bytes
unchanged, input consumed and duplicate acceptance emitted no events. No model, tool broker
or build ran; one local flock helper acquired the existing session lock. An initial guard
had rejected even flock before acceptance; its failed record is preserved. This is recovery
of a real failed turn, not successful topology execution or the planned native reopen test.
Operator-only reports: topology-read-failure-reconciliation[-lock]-20260912.{json,ts} under
outputs/runtime-convergence in the originating workspace. No session store or credentials
are part of this commit.

Verification: full runtime gate 697 pass / 9018 assertions / 69 files / 236.71s, then a
scoped resume-error cleanup passed kernel/local Claude tests (31 / 188 / 4.30s) and typecheck.
Python protocol tests: 9 pass; generated TS/Python protocol bytes reproduce unchanged.
The new generated Python model required updating only its source hash in the 512-module
inventory. Initial fixture failures (MCP advertisement, write completion under read-only
grants, and nested task snapshot shape) were corrected without loosening runtime guards.
A wrong-workdir launch was stopped at exit 130; protocol regeneration initially hit the
read-only default UV cache, then passed with the established task-local cache override.

## Atomic root completion and retained evidence — 2026-09-12

All four local queue compositions invoke the same terminal completion helper. Candidate
schema 21 adds topology_completions, binding the pre-completion parent revision, topology
revision/checkpoint, state digest, accepted inputs digest and reduced result. The kernel
refuses a bare terminal checkpoint without that privately issued proof. Revalidation
uses actual local run/episode/effect bindings and normalized output, not model status alone.
Current assignment generations must all be accepted and still current; older generation
rows remain immutable audit input. Extra queued work or unresolved effects block closure.

The parent must be idle, owned by the calling principal and not itself an assigned child.
The helper records no provider episode, effect or native session. Task status, preview,
fence and task.done/task.failed event are updated atomically with the checkpoint, proof
and child acceptance. The event carries source=topology_reduction; normal DeliveryOutbox
projection preserves the originating command provenance and does not make a new request.
Fault injection proves an event insert failure leaves no partial completion or acceptance;
replay after database reopen emits one terminal event and triggers no extra model call.

This is not yet the completion owner for a root with explicit artifact/SpecMesh requirements:
success rejects with topology_completion_gate_required until that verification is connected.
A declared failure still closes as failed without claiming artifacts exist. Nested aggregate
results and explicit topology reopen are also pending; ordinary provider resume rejects an
already completed topology. These checks preserve the missing work instead of silently
using a reduced completed status to bypass it. Schema-20 upgrades do not manufacture proofs
for pre-existing terminal checkpoints.

Focused tests: 30 pass, 0 fail, 197 assertions across three topology composition files.
Coverage includes successful/failing reductions, rollback/restart/replay, resumed or changed
worker evidence, queued-parent rejection, artifact success refusal/failure reporting, and
one durable outbox projection. The adapter never sends a message and fixtures invoke no model.

## Durable controller identity, budgets and actual local queue — 2026-09-12

`RuntimeControlTopology` composes both pure policies with the existing LocalTaskRuntime.
Schema 20 stores controller task/role and frozen director/judge budgets in topology_controls.
The controller's initial task must be an unassigned waiting task at the expected revision;
normal queue admission or another topology assignment prevents concurrent takeover.
Same-role reassignment must reuse the original task. Children retain their independently
issued grants; this service does not create authority or select an unapproved session.

`TopologyTaskQueue.collectDecision` reads the accepted episode/effect of its actual stored
run. `readTeamControlDecision` validates full JSON, output digest, topology and expected
round; a director dispatch after planning targets the next round, other decisions target
the current round. Worker batches map dispatching/candidate_round to collecting envelopes.
Plain worker result bindings retain their existing shape. Generic RuntimeTopology mutation
refuses managed control rows, so an alternate checkpoint write cannot reset their budgets.

Collection, current-batch policy and all next-task admissions share one transaction.
A missing next batch, queue capacity failure, changed role identity or wrong decision
rolls back accepted output and the topology transition. Old command receipts replay once;
current actor ownership and scopes are rechecked. Model evidence remains an assertion,
separate from the proven task/output binding.

Python's pure judge policy does not bound repeated repair or parent interruption. The
local service now freezes explicit caps (default one each) and counts persisted repairing/
waiting_parent checkpoints. Exhaustion stores a failed summary with no extra dispatch;
it does not relabel the original accepted model decision. Parent completion, a polling
service and device topology scheduling remain separate unimplemented owners.

Synthetic actual-queue tests cover controller/native identity across database reopen,
latest repaired candidate evidence, round-2 decisions, repeated-repair and parent caps,
total dispatch cap, wrong assignment metadata, partial/missing batch refusal, rollback,
controller identity/scopes/cancellation and schema-19 upgrade. They invoke no real model.

## Director/judge decisions and repaired candidate evidence — 2026-09-12

The control-decision boundary has 778 raw JSON cases compared to real Python models;
64 director flows cover round, parent interruption, repair and total-dispatch budgets;
48 judge flows cover selection, next round, final-round escalation, repair and resume.
These are pure policy checks. No model calls, provider acceptance, persisted policy
configuration or authenticated controller-result admission is added by this increment.

A real Python reproduction returned old:a after a same-round repair had produced new:a.
`TeamDebateJudgeRuntime._round_results` gathered every collecting checkpoint in the
formal round; winner selection then chose the first matching role. Both Python and TS
now slice after the latest candidate_round checkpoint for that round. A regression
checks winner evidence, failure evidence and latest-batch rollup/artifact counts.
Older checkpoints remain intact. Legacy states without a batch marker retain the
previous full-round lookup. Director's existing source preference is unchanged.

Python judge currently has a formal-round limit but lacks a service repair/interruption
cap. Preserve that explicit limitation until the bounded service owner is implemented.
Director limits are immutable within one policy object, not yet durably bound to a task.

The expanded Python gate initially passed 184 tests and failed two runtime-recovery
tests because their snapshot advisor resolved the operator's real CM workspace despite
a temporary team state root. An autouse resolver fixture isolates this test module;
all 186 team/protocol tests now pass. No production state permission was added.

## Normal container queue and parallel-turn counting — 2026-09-12

The normal Claude task adapter now selects container readiness/execution explicitly from trusted
local configuration. Concrete container mode rejects injected host/probe drivers. State and
helper assets are runtime-owned; the task manifest binds the original helper and two exact
container execution IDs. Retained recovery verifies the original removed-container records and
helper without rebuilding from current source or invoking a provider. A missing image blocks
before a task input and never falls back to host. Image Node may be absent on the host.

Real native normal-queue execution succeeded at the provider but exposed an incorrect CM budget
comparison: --max-turns=16, reported num_turns=19, 21 streamed assistant blocks, 13 distinct model
message IDs and 12 tool-use rounds. The first model response supplied seven parallel read blocks
sharing one ID. There were 18 tools: eight reads and ten write attempts, nine rejected for missing
expected_sha256 before a correct explicit-null creation. No file was published while evidence
was rejected. Native success and a final DONE alone did not establish CM completion.

The [official loop documentation](https://code.claude.com/docs/en/agent-sdk/agent-loop) distinguishes
content blocks sharing a message ID from tool-use turns counted by maxTurns. CM now counts actual
model/tool rounds in the control stream and independently in the verified original source.
Missing/revisited IDs and actual excess rounds reject; reported num_turns remains bounded metadata.
The saved original source/control evidence established 13/12 rounds, within the existing limit.
No limit was increased and no extra native input was sent.

After parser correction, the retained result was published through normal reconciliation.
Deliberate task.done loss, reopening and repeating the same acceptance request did not change
native bytes, container records or the canonical inode. Independent raw-source/receipt/state/file
readback verified one preflight generation/input, all 18 calls, seven current docs and four absent
container IDs. Preserve the original failed report; the recovered and independently verified
reports are separate. Repeated same-shape tool failures remain a concrete no-progress-detection gap.

## Claude container qualification — 2026-09-12

The existing pinned Linux image provides /usr/local/bin/node, not /usr/bin/node. MCP clients
must use the image-owned Node while the host broker runs independently; normal configuration's
current host-Node existence check therefore needs an explicit container execution profile.
The concrete runner mounts the canonical native executable and current Bun read-only, plus a
private hash-named bundle of the control helper. Runtime identity pins binaries, helper/source
revision, native directories, project and channels. Assets cannot overlap native/control state.
No entire CM checkout is mounted. Native HOME/config are writable and project mounts read-only;
host file capabilities and staged publication retain mutation authority.

One real native preflight and one original-session input passed. A write lacking expected_sha256
was rejected before mutation; the same native turn corrected it. All ten original native calls
match receipts, seven current continuity references were read and the output combines a prior
session marker with a changed file fact absent from the prompt. Independent retained readback
confirmed one publication, unchanged original source prefix, four removed immutable container
IDs and no owned processes, without invoking a model. The verifier's unused function-valued
digest expression was removed before its first execution. Supervisor record.outcome excludes
the returned container_id/cleanup envelope; comparison must remove only those envelope fields.

Actual Docker tests also qualified cancellation of a hanging native descendant, MCP grant
denial, read-only project enforcement and a disposable preflight HOME without task/native mounts.
Normal local/device dispatch and recovery remain separate work: a configured container profile
alone cannot relax source policy, and retained recovery must not restart the provider.

## Native max-turns resume adds a synthetic pair — 2026-09-12

The bounded corrective input did succeed in the original native session: 10 turns, eight reads
and one correctly preconditioned write, exact old marker plus newly changed file fact. CM initially
rejected its source as unsupported_native_content. Actual CLI 2.1.263 inserts a user isMeta record
containing "Continue from where you left off." and a zero-token <synthetic> stop_sequence answer
"No response requested." immediately after the prior max_turns_reached attachment and before the
submitted task input. These two records are native padding, not another model turn or task input.

The strict reader now accepts the observed stop only with resolved tools/no queued input, positive
integer maxTurns and turnCount=maxTurns+1. It accepts only the exact pinned synthetic pair with
correct identity/parent chain, zero input/output usage and an ensuing explicit input. Partial,
altered, misplaced or tool-bearing padding still rejects. Completion requires a subsequent actual
model end_turn; the failed turn cannot become successful evidence. This preserves the entire raw
prefix without replacing files, weakening tool grants or invoking another native attempt.

The original result was recovered from retained evidence. Deliberate task.done loss after canonical
publication, reopen and repeated acceptance passed with zero native execution, stable native bytes
and canonical inode. A diagnostic JSON digest incorrectly received Buffer after those assertions;
preserve that failed report. Separate read-only verification uses a byte SHA-256, matches all nine
original tools to durable receipts, confirms one effect/task completion and no remaining processes.

History refresh/search uses its existing independent CLI with a private derived cache. Canonical
existing ancestors are checked before mkdir, including future directories, so source/cache symlink
aliases cannot put derived state into the native source. A missing source may be registered before
first provider use, but must be canonical when queried. Full History indexing/backlog/daemon limits
remain separate work; the scoped CM subprocess timeout is not proof of a bounded resident service.

## Actual adoption failure: missing write precondition looked like a conflict — 2026-09-12

The real History CLI successfully refreshed/searched the configured original Claude JSONL and
prepared a context-only handle. Normal local submit resolved that handle after reopening, and
Claude resumed the original session. However, all 32 attempted write_file calls omitted the
schema-required expected_sha256 property. JavaScript undefined failed the comparison with null
for a missing target and surfaced workspace_tool_content_changed. The model interpreted that
as concurrent modification, repeatedly reread PROJECT.md and retried without repairing its input.
Native completion was error_max_turns at the configured limit of 64 (num_turns 65). There was no
canonical output; no actual task-completion or retained-success recovery claim is justified.

The narrow correction distinguishes a missing precondition from a changed file, explains explicit
null/current sha256 and the required new request_id, and durably retains that failure response.
It does not infer write permission/preconditions or silently repair model arguments. A real MCP
regression proves no write before correction, identical failure after reopening, rejection of
changed arguments under the old request_id, successful explicit creation, and continued rejection
of null over an existing file. Native semantic no-progress detection is a remaining runtime gap;
the current turn/request budgets bound work but allowed many identical mistakes in this trial.

## Original adoption integration seam — 2026-09-12

`DeviceNativeAdoptions` already persists opaque device/task/workspace/capability-bound context
handles in `device_native_adoptions`. Before this increment the local task/control path had no
adoption operations; ClaudeHistoryClient only validated an explicit UUID/file. History's existing headless JSONL CLI
supports explicit refresh/search with a separate derived cache and no Web server. A fresh cache
does not refresh during search; report explicit freshness/refresh semantics rather than silently
claiming that empty results describe all native history. Reuse the current registry for the local
device and provider-specific source adapters; do not create a second task/adoption store.

## Claude native concurrent peer tools — 2026-09-12

The existing message MCP service can be registered beside Claude's workspace service; no merged
tool owner or second mailbox is required. Fixed native control now verifies both exact servers,
commands, tool names and init tables before one input. Missing or expanded tables withhold input.
Configuration supplies peer/parent identities and current grants must include all four message
capabilities. The effect manifest records the same NativeAgentScope already used by OpenCode;
Claude's native result verifier normalizes only its actual communication tool namespace, checks
all durable journal responses and atomically consumes delivered messages with task completion.
Recovery reuses those original calls; no broker/provider runner is reachable from reconciliation.

Actual two-session native trial passed in the normal local configuration: parent alone received
a random marker in its prompt; child asked, received and acknowledged the marker over three
durable agent_message records. Both original source files contain their three real communication
calls and current seven-file reads. The original dispatch intervals overlap. A single explicitly
admitted shared preflight preceded two task inputs, and independent raw/control/file/journal
readback used zero native commands. No owned processes remain. This establishes the scoped local
read-and-message profile, not concurrent writes, mixed-provider topologies or remote Claude.

## Normal Claude queue and actual parallel lineage — 2026-09-12

The normal local Claude adapter and recovery port now share one provider-specific retained
dispatch/evidence path. Raw process output is kept privately and fsynced before the compact kernel
observation. Explicit reconciliation can admit that existing output after observation loss, then
verify/publish without starting any model or replaying tools. Retained file scopes are read-only
and preserve the original dispatch snapshots while verifying already-applied staged publication.

Real CLI 2.1.263 emitted multiple tool-use chunks with the same API message ID, interleaved with
parallel results. Each result's parentUuid/sourceToolAssistantUUID points to its own pending tool
chunk, not necessarily the last flushed record. A universal linear-parent check falsely rejected
the first ordinary seven-file trial. The narrow fix recognizes only exact pending-tool edges;
other messages still require the current tip, duplicate/unowned results reject, and new API
message IDs cannot appear before existing pending tools resolve. Original raw bytes were retained;
repair/recovery used those same bytes, not another first-turn model call.

Scoped real startup/resume/recovery/publication evidence passed independent model-free readback.
Two task inputs ran in one original native session, with seven continuity documents required;
the second read nine files including the two result artifacts. Native tool counts were 10 and 14.
Two ready generations ran because the repair interval exceeded readiness TTL. This differs from
a failed probe retry: successful readiness expired before the second task was admitted.

Content acceptance remains separate. The first native write omitted the requested newline.
The second original-session turn repaired exact file bytes and recalled the marker absent from
its new prompt, but included prose before JSON despite the JSON-only request. Preserve the failed
strict fixture reports; runtime completion/SpecMesh structural pass cannot prove semantic adherence
to every prompt constraint. No production service, default, installed package or writer changed.

## Supervised native Claude resume — 2026-09-12

The repository control driver passed a real explicit resume of the owned test JSONL. Its input
omitted the original marker; two actual MCP tools read PROJECT.md and wrote the correct marker
plus current-file contents into the stage. The original file and canonical output remained
unchanged/absent. Independent readback matched the control envelope, native source append, tool
receipts and original kernel observation; verification used zero model commands. One shared
preflight model command and one resumed task input ran. Provider billing request counts were not
measured. The private qualification task is not claimed completed by a normal task adapter.

The native config directory previously created inside the owned synthetic HOME had mode 0775;
it was narrowed to 0700 before admitting the new driver. No real user configuration directory
was changed. An explicit session lease uses only session_id plus native store path, so its type
now accepts both native providers without changing the lock key or locking semantics. External
native clients still do not honor CM advisory locks.

Control records alone must not become a task queue. Correlated dynamic MCP admission precedes
the sole input frame. Separate owner envelopes prove whether input was attempted; complete
pre-input aborts are distinguishable from lost outcome after input. Unexpected native records
are retained and reject success. Version/executable/config-directory changes and raw environment
injection reject before the task process. Cancellation tests reap a real owned child and its
descendant without a replay. A source read initially used an incorrect test/history filename;
the actual process tests are process.test.ts/supervisor.test.ts, and provider paths should be
discovered before reading. This did not affect execution or create additional model calls.

## CM workspace tools and native MCP startup — 2026-09-12

Static CLI MCP configuration repeatedly reported empty tool/server tables, including in
control-only inspection. The one static model attempt returned tool-looking text with zero
calls; preserve it as a failed trial. Native dynamic `mcp_set_servers` followed by `mcp_status`
connected the exact private workspace server before any user input. Those discovery probes
sent zero user messages and used no model turns. The successful isolated dynamic trial used
one user message and retained three real calls: authorized read, denied read, staged write.

Independent original JSONL verification matched all native inputs/results against private
durable receipts and the kernel's original manifest scope. It confirmed complete current-file
consumption, one retained denial, correct staged contents and no canonical output publication.
The private kernel task was not promoted to completed; normal Claude worker wiring remains
absent. A successful tool trial must not be reported as native resume or lost-result recovery.

Workspace receipt ownership is separate from the existing Agent message journal. It pins a
task/effect scope, writes intent before stage mutation and preserves unknown outcomes on lost
receipt. Exact retries survive reopen; trusted reconciliation inspects bytes without repeating
the write. Unrecognized journal entries reject acceptance and are preserved. Request budgets
also survive reopen. Source metadata is rechecked at each operation, with full source hashes
and final same-revision page coverage verified at acceptance, avoiding repeated hashing of
every registered file for every page. Larger files can exceed the total 256-request coverage
budget; future normal task admission must validate that aggregate bound.

The last test tool output was lost during context exhaustion. No matching process remained;
the deterministic targeted suite was rerun and passed, followed by zero-model verification of
the retained native trial. Native execution itself was not repeated. Initial test-fixture import
and chat_id omissions were corrected without changing runtime admission rules.

## Claude append and file-permission qualification — 2026-09-12

The actual pinned CLI does not make `--allowedTools Read(//absolute/file)` a closed read scope:
with `--tools Read --permission-mode dontAsk`, both the allowed and explicitly ungranted
synthetic file were read. CM cannot authorize a restrictive grant using that profile. Use a
CM-controlled workspace capability with built-in tools disabled; qualify the configured MCP
profile separately because safe mode disables MCP. Existing grant rejection remains in place.

Actual persisted native rows include queue enqueue/dequeue, UUID-bearing token-reminder
attachments in the parent chain, assistant blocks and last-prompt/mode metadata. The final
native result corresponds to the final model message, not all preceding assistant text. The
verifier handles this shape and preserves raw prefix bytes; unknown compaction/branching rejects.

An actual same-session current-file trial returned successful prose containing a wrong value,
without any tool use. The verifier raised `native_turn_content_mismatch`; subsequent rechecking
used the already retained outcome, found zero tool calls and made zero additional model calls.
Do not equate a native successful result or marker recall with current-file consumption. The
real tool-call/result path still needs a qualified workspace-owner trial; synthetic tool-chain
tests do not close it. The persisted test source is owned, and no arbitrary user history was
appended. An initial source read used the wrong package prefix; all code is under
`packages/controlmesh-runtime-core`, not `packages/runtime-core`.

## Claude shared preflight — 2026-09-12

Local Claude supports safe mode while retaining the existing auth-token credential mode. Its
bare mode documents a narrower authentication path; using bare and silently remapping the
user's auth token to a different credential kind would change the selected native profile.
The qualified probe instead uses an isolated HOME/config, safe mode, explicit native empty
tools/MCP configuration and disabled persistence. Host managed settings are not assumed safe:
unqualified managed configuration rejects. Native init exposes the actually selected model,
tools/MCP/plugins; native result and assistant content must independently agree on the sentinel.

A reset-budget regression exposed a shared parser defect: ISO timestamps with fractional
seconds lost their timezone suffix, leaving a valid reset unknown. The native-error parser now
retains fractional seconds and a verified zone; zoneless timestamps still never become local
retry dates. Tests cover equivalent UTC/offset instants and the actual Claude three-probe budget.
An initial test used the database constructor without its required path; corrected to an isolated
in-memory database. No extra native model call was made for fixture/parser fixes.

## Claude native source identity — 2026-09-12

The current one-shot Claude command disables persistence; treating successful execution as
native memory continuity would be false. Local Claude Code 2.1.263 uses main-session JSONL
with messages, attachments, system and metadata rows. Added a distinct content-bound reference
and an independently implemented History reader, without changing the one-shot contract.
The full raw-byte digest detects historical edits and avoids Python/JS large-number rounding.
Mixed sessions/projects, sidechains and partial/changed input reject continuity inspection.
Real readback agreed in 197 ms with unchanged bytes/mtime and zero provider calls. The first
TypeScript test run caught an over-broad unknown type in a fixture; narrowing that fixture
fixed the typecheck. Runtime execution and model readiness remain explicitly unproven here.

## Persistent device scheduling — 2026-09-12

- A fixed first page can starve later assignments: the protocol now scans at most 1024 candidates
  and returns at most 32 matching jobs with a cursor. A regression crosses 1025 foreign jobs.
- Unstarted lease release changes task revision. Scheduler identity therefore uses explicit
  assignment generation plus execution projection; a quota wait does not manufacture new work.
  Legacy assignment digests remain compatible and replayed assignment IDs retain their receipt.
- A local owner lease must renew independently of awaited network discovery. Admission checks
  that lease at native/file/message boundaries; concurrent manual execution cannot bypass it.
- Readiness inspection/reset does not run a provider. Confirmed pre-execution reset dates may
  schedule bounded retries; unknown effects cannot. Operator retries first verify the coordinator
  has no active episode or pending reconciliation. Persisted pause survives stdin EOF and restart.
- Final review found two queue-control defects: an unavailable old assignment could block discovery,
  and rejected competing start could persist enabled policy before lease acquisition. Known removed
  assignments now become superseded; lease acquisition and explicit-start receipt are transactional.
  Targeted regressions pass. A documentation patch initially failed its context check atomically;
  it was corrected without changing code or repeating the real canary.
- Independent real-trial readback proves 11,366 ms of overlapping OpenCode first turns, bidirectional
  native messages, one attempt per assignment and zero model replay in recovery. The temporary
  remote coordinator database was deleted after authenticated terminal snapshots and cleanup;
  independent post-trial verification uses retained local/native records, not that removed database.

## Normal native device startup and control

The old device script registered a synthetic adapter; direct library canaries did not expose
normal configured native startup. `device-runtime-config.ts` now owns private coordinator/
worker configuration, persistent role/principal/device identity, local workspace/capability
selection and task-specific native factories. The coordinator never loads the worker's
provider profile. The shared stdio transport preserves the existing local TaskHub shutdown
behavior. Current configuration is rechecked after slow request-body reads and during native
Agent calls, rather than only at server startup.

Worker control reservations and completion receipts reuse the existing transaction owner.
Reservation inspection and acquisition must be in one SQLite transaction; otherwise two
processes can both pass the initial missing-receipt check. Reopening a pending run leaves
it unknown, while explicit original-challenge recovery remains replayable. Inspection exposes
effect IDs so an Agent can request recovery without reading private SQLite tables itself.

Two initial synthetic-control tests labeled their fixture provider `opencode`; the existing
native manifest gate correctly prevented the synthetic adapter from starting. They now use
an explicit fixture provider. Actual native behavior was separately accepted through the
normal configured entrypoint, with unmodified real OpenCode execution.

Real ARM64 coordinator/x64 worker acceptance on 2026-09-11 23:07:49–23:10:22 UTC covered
writer A -> writer B -> original writer A, two native sessions/three task turns. A's first
lost observation was recovered after both processes reopened without another model turn.
The outgoing native MCP messages appear in the next task's actual native input, and the
second handoff retains causation while decreasing its hop budget. A's final native turn
recalls its marker without reinjection. Eighteen owned containers and the exact temporary
remote process/directory were independently checked absent. Three preflight generations
(A 2, B 1) include A's expired readiness before its later turn; no expiry was extended.
Provider billing/API request counts remain unmeasured. Independent structural SpecMesh
checks are not reviewed semantic closeout or complete migration acceptance.

## Device protocol and packaged dashboard synchronization

Commit `80b330c` omitted the regenerated `controlmesh/web_static/assets/main.js` after
adding device write contracts. Both product CI jobs passed their behavior checks but failed
the final packaged-asset drift gate. The Web imports the SDK's protocol validators, so a
protocol-only change can require a dashboard rebuild. Rebuild through the Web package with
CI's Bun 1.3.11; running the build script from the repository root also changes generated
module-path comments. The corrected package-directory build matches the full diff produced
by CI run 34654692522. Preserve the drift gate; this correction does not change UI behavior,
the installed production writer, or the accepted native execution path.

## Authenticated ingress and conversation recovery

The Python HTTP listener in messenger/feishu/inbound.py passes decoded events onward;
its challenge branch precedes downstream message handling. The TS receiver instead owns
raw-byte signature verification, token/app checks, encryption and bounded allowlists.
The installed official SDK uses SHA256(timestamp + nonce + encrypt_key + original bytes)
and AES-CBC with a SHA256-derived key. A cross-language SDK decryption test verifies the
fixture. Native group grants require controller approval; no amount of signature validity
can supply that approval, so the current private startup blocks before native state/probe.

Integration tests exposed two queue defects during this port: deferred messages filled the
first 16-row selection and starved unrelated conversations; after restart, draining an old
queued task did not trigger application of its already-received follow-up. The bounded
128-row scan now skips deferred conversations, caps applied work, and the pump retries only
after actual queue progress or new input. Events, task creation, route binding and enqueue
compose in one SQLite transaction. Admission failure rolls the task side back and keeps
the verified input blocked for explicit operator retry. Provider duplicates cannot trigger
quota retries or duplicate execution/delivery.

Real Docker testing twice exposed heartbeat expiry during preparation (before Agent launch).
The supervisor now separates preparation's current task/deadline checks from the execution
heartbeat, armed after the durable launch marker. Tests deliberately delay image preparation
beyond one heartbeat, revoke authority during preparation, and suspend/kill a running
controller. Slow authorized preparation succeeds; revocation and expired running authority
still prevent execution or stop the existing process. No host-runner fallback was added.

Earlier test failures were a URL-encoded Chinese cwd in the Python SDK subprocess and a
cold HTTP integration fixture exceeding Bun's default five-second test deadline. fileURLToPath
fixes the former; the real HTTP test has a bounded 15-second deadline. Full CI-version core
validation then passed 290 tests / 3,322 assertions. The two-turn real native ingress canary
is tracked separately from fixture tests and must be inspected before claiming continuity.

## Feishu credentials, replies and stdio shutdown

Python `messenger/feishu/bot.py:_get_tenant_access_token` has no refresh lock and computes
`now + max(expire - 60, 60)`, which can retain an actually short-lived token for too long.
It also raises with the provider response body. The TS owner shares concurrent refresh,
validates HTTP/API response and real TTL, sanitizes errors, binds selected app/file revision,
and leaves credentials device-local. This is an intentional correction, not literal parity
with that TTL floor. The official installed SDK's `core/token/access_token_response.py`
defines `tenant_access_token` and `expire` for this endpoint.

Python's ordinary message POST accepts `reply_to_message_id` in its payload; the official
installed SDK models a separate message `reply` endpoint with `content`, `msg_type`,
`reply_in_thread`, and `uuid`. The TS port uses that endpoint, verifies the parent before
sending, and retains root/parent/topic checks during readback. It does not reinterpret
arbitrary task text or legacy topic metadata as a reply grant.

Actual SIGTERM testing found that stopping only Agent execution left an HTTP delivery
pending, and destroying stdin was reported as a startup failure (exit 2). All owned work
now stops together; only expected stream-closure errors caused by our own signal handler
are suppressed. The test requires exit 0, empty stderr, a correlated interrupted control
reply and an `unknown` durable delivery. Other errors remain visible.

During implementation, `python` was absent (used `python3`); the first compile consequently
found the not-yet-written startup accessor. Test scaffolding initially used an async resolver
and omitted local-runtime scopes; these fixture errors were corrected without changing gates.

## Terminal delivery owner under migration

Python bus/bus.py owns injection, locking and output routing. Its unicast path falls back
to broadcasting on another transport when the target transport is absent; its adapters
return no persisted delivery receipt, so exception swallowing cannot prove delivery.
Feishu bot.py's message sender returns None for HTTP/decode failure and does not validate
the API code before extracting a message ID. The new TS terminal-result owner uses durable
kernel task.done/failed/cancelled events and an explicit task route instead. Event projection
and outbox insertion share a transaction; an interrupted sender never causes model replay.
This is a deliberate delivery-policy correction, not byte-identical routing parity. The
existing Python production bus and bot remain authoritative until the complete port and
cutover gates pass.

Native Agent communication: `NativeAgentJournal` records each logical tool request
before applying it, binds it to the dispatched task/episode manifest, assigns
`agent_message` provenance internally, and refuses replay of an unresolved request.
Schema 10 separates tool-delivered reservations from schema-9 input-delivery reservations.
The first strict TS check found request-ID narrowing lost across a closure; retain a
validated local value before entering the transaction. Completion/replay also needs the
current message scopes, not only the scopes checked at request creation. Existing migration
fixtures must drop new dependent tables before emulating old schemas. The local broker,
client, permission profile, worker and native verifier are now integrated and accepted.

The task-scoped stdio MCP client reaches a per-execution Unix socket broker. The task's
channel directory is stable for native profile identity, while socket and capability names
are fresh per episode. Trusted configuration supplies authorized
peers and parent; model arguments may not supply a principal, sender lease or origin.
The client digest and communication scope are retained in the native manifest. The broker
rechecks execution authority before every operation and cached reply, coalesces live
duplicates, and refuses pending receipts left by a lost broker. Bounded receive waits run
outside database transactions. Actual native tool names/inputs/outputs are matched to the
durable journal before completion. Existing input-batch consumption precedes later
tool-received messages in the same transaction. Recovery uses original native tool evidence
and the original manifest without a new native turn. Device wiring remains required.

OpenCode 1.18.29's [MCP catalog](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.29/packages/opencode/src/mcp/catalog.ts)
combines server and tool names; CM registers `controlmesh` with `send`, `ask_parent`,
`receive` and `answer`. Its [session tool adapter](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.29/packages/opencode/src/session/tools.ts)
asks permission using the combined name and stores flattened MCP text as native tool
output. CM returns one bounded text result and compares it with the journal. The client
follows [MCP stdio framing](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
with bounded newline-delimited JSON-RPC and no logs on stdout. It negotiates initialization,
lists only four tools and opens no TCP listener.

Linux Unix-domain socket paths are short, while the real workspace is deeply nested.
Opening the canonical task directory and addressing its socket through `/proc/self/fd`
preserves the same mounted inode in host and container without exposing an ancestor mount.
Actual Node and Docker tests prove the connection and reject writes to the mounted client.
Real OpenCode MCP discovery then connected successfully without any model call.

The initial native image had OpenCode but no Git. A Git-capable image was required to preserve
the provider's real repository worktree identity, not just cwd in an unversioned fixture.
Real container acceptance now uses pinned image identity, original paths and native auth/state:
two distinct task turns plus a tool-denied model probe, with only three model calls. After the
coordinator and runner reopened, the native session recalled its original marker and read the
changed project file. Source/grant/result evidence remains issued and verified by the TS owners.

OpenCode data contains both its SQLite session store and `auth.json`. Mounting the native data
directory read-write with a nested regular-file read-only auth mount permits native messages
while rejecting credential overwrite/unlink. Only OpenCode data/cache subdirectories are
mounted; neighboring data and the host HOME/config are absent. Runtime cache/manifest identity
now includes an optional runtime digest, preserving old host records while preventing them
from qualifying a container. Model/config/credential/device fields keep their existing meaning.

Container native continuation needs its original absolute directory: OpenCode session rows,
native read evidence and the CM manifest all bind that path. The container's previous fixed
`/workspace` mount changed it. An explicit `native` layout now preserves the canonical project
path and nested write roots; the default remains `portable`. It does not mount any ancestor
directory. Actual Docker tests cover a project path with spaces and Unicode, deny writes outside
its granted root, and confirm an adjacent private host file is absent. A deliberately altered
Docker working directory is rejected before launch and its owned container is removed.
This is directory compatibility, not authenticated model/session continuation acceptance.

Container ownership baseline: `infra/docker.py:DockerManager` shares one persistent sidecar
between Agents, mounts the whole CM home plus selected native auth stores, and reports setup
failure as `None`. Source policy separately blocks required-sandbox work on that failure;
the log's host fallback wording alone does not prove cron bypass. `cli/base.py:docker_wrap`
only wraps an exec client, with no per-execution immutable container/process identity.

The TS path now uses a separate nonroot container per execution and an inner PID 1 lease
watcher. Image, actual isolation settings, specific project mounts, boot ID, engine ID and
original container identity are checked. This is a deliberate owner change, not a claim of
full shared-home/auth compatibility. No native credentials or production workspaces were
mounted for this batch. `no_network` blocks model-client networking too; provider profiles
must not silently waive that grant. Existing native histories need a compatible directory
mapping and scoped persistent state before container adoption can be accepted.

The new helper is compiled from TS for the image's Node runtime. The current local fixture
image is pinned at `node@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5`.
Docker 29.1.3 was available with seccomp/AppArmor/cgroup namespace support and no cached
images before setup. Pulling this fixture image did not start any production service.
Actual tests cover nested writable mounts, network isolation, exact stdin, quota abort,
concurrent cancellation, detached descendants, host SIGKILL/SIGSTOP and explicit cleanup.

A monotonic expiry alone is insufficient across reboot: the init watcher and cleanup now
bind to Linux boot ID. A second gap is delayed container creation after an observation
timeout. Absence is not conclusive while create is uncertain; original identity is durably
recorded before removal, and an execution directory cannot be reused after cleanup. Tests
distinguish lost acknowledgement of a created container from a still-unconfirmed absence.

CI 34600620577 accepted the actual container job but exposed a stale exact-set assertion in
`tests/webhook/test_ci_workflow_webhook.py`. Each full Python matrix had that single failure
and 5,732 passes. Require the complete mandatory set including container execution as a
subset, preserving protection against omitted gates while allowing new gates to be added.

One-shot owner baseline: `cron/execution.py:build_cmd` and `parse_result` both defaulted to Claude
for any unregistered provider. Their tables included only Claude/Gemini/Codex, despite
param_resolver accepting OpenCode/Claw/OpenAI Agents. A pure Python reproduction requested
OpenCode and observed a Claude binary lookup with zero subprocesses. Existing tests even
asserted this fallback. The one-shot runner also marked any zero exit code successful
without consulting native error/terminal result semantics. Both behaviors are now corrected
in the Python owner and independently ported to TS. The live oracle covers 410 command/output
cases; these compare actual code paths but are not native model acceptance for five providers.
OpenAI Agents is an optional SDK backend, not a CLI; it needs its own owner, not a fabricated
binary or a switch to another provider. Generic Docker exec client termination does not
prove termination of the process inside the container; its actual lifecycle port is separate.

One-shot grants now live in command construction, preserving the position after `exec`/`run`
and refusing controller approval even when the other grant fields are unrestricted. The TS
host owner requires current source/grant/readiness checks and a stable workspace inode.
It reports cancellation, timeout, authority loss and nonzero exits without replacing their
cause with missing-output errors. Zero-exit incomplete/native-error responses cannot succeed.
OpenCode uses exact stdin and trusted live stderr for early quota abort; assistant/tool prose
remains data. The installed OpenCode 1.18.29 help confirms the emitted run/format/log/auto flags.

The first Python real-child quota test took 10 seconds because the global safety fixture
intentionally mocks all group signals. This was a test isolation conflict, not evidence of a
production cleanup failure. Its local fixture now tracks and terminates only its own exact
child and always reaps it; global signal protection remains. Regression also found old Codex
success fixtures missing `turn.completed` and an exit-code precedence change; the fixture and
status handling were corrected. Generic one-shot output does not establish durable native
session identity, native tool enforcement or successful side-effect reconciliation.

Remote recovery now separates a trusted acceptance request from its device evidence report.
Schema 7 retains the challenge across reconstruction; its registration digest prevents a
changed credential/capability catalog from inheriting earlier authority. The report can
complete only the exact original unknown operation and expires within 30 seconds. Worker
report events stay agent-origin, terminal reconciliation events are recovery-origin, and
request issuance retains the original trusted origin. It never creates a fresh human prompt.

The shared NativeResultVerification rereads original native rows, permissions, source/grant,
file identities and content while holding the device-local lock. It has no provider runner,
model or preflight dependency. The coordinator receives bounded references and result text;
late observation admission and task completion occur atomically. Recovery receipts also let
the device acknowledge its retained evidence after an ambiguous network response. This does
not prove a compromised worker honest, and standalone native clients ignore CM advisory locks.

The initial strict TS check exposed three generated-interface/index-signature mismatches;
validated values and object spreads fixed them. The original 37 affected tests passed, then
new HTTP/native fixtures covered missing/delivered observations, process reconstruction,
expiry/revocation/cancellation, stale native/files/configuration, tampered reports, receipt loss
and transactional rollback. The final 117-test core suite passed. Actual ARM64 coordinator /
x64 OpenCode recovery passed: coordinator stopped before original-observation delivery, both
sides reopened, explicit reconciliation took 130 ms with zero OpenCode commands, then the
same native conversation recalled its earlier marker and read the changed file. Original
evidence hashes and preflight generation were preserved. Temporary remote resources were
independently verified absent after credential revocation and cleanup.

Native device execution now uses one OpenCodeExecution driver shared with the local worker.
The execution projection comes from the coordinator's stored task, not assignment input;
literal file access and native configuration remain locally configured. Source/grant/input
validation runs before model preflight. Preflight and actual execution inherit device lease
deadlines and advisory native locks remain device-local.

The full native manifest can be much larger than the device protocol's 256 KiB request
limit. Schema 6 retains it in a device-local evidence ledger, with immutable job/assignment/
workspace binding and original observation/verified-result digests. Only bounded references
cross the wire. Native result handles point to a verified result on the original device and
are task/workspace-bound. Lost original-observation delivery retains local evidence; lost
completion acknowledgement can leave the coordinator done while the local record is unknown.
An explicit next episode can resolve the verified handle without replaying the old model call.

The real dual-device run used Rock 5C for coordination because its installed OpenCode was
1.14.48 and its native auth file was absent. The x64 worker used qualified 1.18.29/M3 with
its existing local credentials. Both native turns completed across worker reopen, using
the same session and one preflight generation. Worker events retained agent origin; original
task source/grant and current file reads were checked. The remote credential was revoked and
cleanup independently confirmed no remaining canary coordinator process or artifact directory.

Post-run review added coordinator-side schema/reference consistency checks for native
manifest, observation, result, output digest and continuation handle. Final deterministic
HTTP/native fixtures exercise these additional rejection paths. The actual execution path
was verified before these final guards; this distinction is retained rather than calling
that real run an exact-final-source test of the new rejection branches.

Still open: other providers/write profiles, native History adoption and independent SpecMesh
lifecycle hooks; the real sandbox/transport launchers and remaining stores still need ports.
The source/grant parity below establishes policy calculations, not those launchers.

The source/grant owners are `controlmesh/bus/envelope.py`, `execution_policy.py` and
`execution_grants.py`, not the provider SDK facade. TS now independently ports their valid
stored formats, source sandbox decisions, native mapping, submit narrowing and reply checks.
A live 689-case Python oracle covers all origin/scope/readiness combinations plus provider/
grant/config combinations, source issuance and pinned delivery identity. This proves these
policy computations, not all Python provider/transport execution behavior.

Two legacy shortcuts require stricter admission: Python submit-grant issuance treats an
unknown source string as not requiring a sandbox; mapping returns a floor for an otherwise
empty controller-required grant. New TS issuance rejects unknown scopes, and actual native
admission checks controller confirmation separately from flag mapping. Static native tool
expressions such as `Bash(rm *)` are distinct from the portable grant token grammar and must
remain intact during deny union. Persisted valid v1 fields keep their names; new decoders
reject coercions and bound token arrays, while snapshot migration retains original data.

`TaskIngress` binds a trusted configured channel to command origin. It overwrites no body
authority: a supplied context/grant is rejected, and new grants can only narrow the source
floor. Creation and authorization events/receipts are atomic. Raw source IDs are hashed
before persistence; retry identity excludes the generated trace so restart reuses the
original issuance. Native success/reconciliation fixtures now use this real ingress.

The actual OpenCode/M3 canary for this path preserved issued context, denied bash/edit/write
and pinned reply identity across a worker SIGKILL, native reconciliation and same-session
continuation. It generated one authorization event and independently proved marker recall
and the changed current file read. No production TaskHub writer, bot, scheduler or account
browser operation was involved. The prepared device adapter now retains manifests before dispatch and original observations
before transport; device recovery consumes these originals rather than reconstructing them
from transcript summaries.

The roadmap is grounded in repository code, existing contracts and prior recorded acceptance, not the prototype archive alone. Implementation status and remaining gates are in task_plan.md. No new runtime migration or fleet rollout is claimed complete by this plan.

2026-09-11 implementation: TaskRegistry.__init__ calls orphan cleanup and may delete folders; its cached JSON writes are not a cross-device store. InterAgentBus is explicitly in-memory and trims message history. Existing TS lifecycle parity switches on fixture case IDs and is not a callable production lifecycle. These are source observations, not completion evidence.

The generated source baseline now inventories all 512 Python modules under `controlmesh`/`controlmesh_runtime` and selected model fields. The actual `TaskEntry.to_dict()` fixture has 57 serialized fields; `original_prompt` is not serialized, and `thread_id` is conditional. Snapshot import preserves unknown fields without passing through a lossy reconstruction. Active imported tasks remain non-executable until explicit reconciliation; cancelled tasks retain their status.

Two different persisted subsystems remain in scope: TaskHub's registry/task folders and `controlmesh_runtime/store.py`'s task packets, workers, reviews, control/runtime/execution events, summaries and promotion receipts. The latter is not retired by adding the new kernel. All additional owners appear in the source ledger, including CLI commands, topology/transport ingress and generated protocol modules.

`controlmesh/cli/service.py:resolve_runtime_provider_target` currently logs a failed explicit OpenCode probe and continues with the requested model. Existing native-adoption checks are stronger. The TS port must reconcile these different admission paths rather than copy the fail-open path as desired behavior. Quota classification currently lives in `cli/opencode_quota.py` and only trusts native error records; ordinary assistant/tool text must not trigger it.

The new kernel's transactional fences prevent stale coordinator writes. They do not prove an external tool honors fences. External dispatch is recorded first and identical retries cannot obtain another dispatch permit. Expired running episodes become outcome-unknown and require reconciliation. Provider/native enforcement and actual process ownership remain required.

Process ownership now has real Linux evidence: a detached Bun anchor remains the process-group leader while the native provider and descendants run, ignores TERM during the cleanup grace period, and kills its own verified group if controller IPC disappears or renewals stop. The parent verifies start time/group/session before signals. The anchor avoids losing group identity when a provider exits ahead of its descendants. This is not a hostile-process sandbox; isolated containers/native policy still own that boundary. Kernel cancellation was connected to the supervision admission callback and stopped a real synthetic process family while preserving cancelled state.

Read-only local snapshot preview found three tasks (one done, two cancelled), no active tasks. Preview used an in-memory destination, did not construct TaskRegistry, transfer writer authority or modify folders. No private task IDs/payloads are recorded here.

Native provider acceptance on 2026-09-11 used installed OpenCode 1.18.29. Recent SpecMesh history used `minimax-cn-coding-plan/MiniMax-M3`, while the configured default was `zai-coding-plan/glm-4.5-air`; inspecting only the default misses an actually used model. A tool-denied native probe of M3 succeeded, and the TS preflight service reused its durable result both on a second request and after reopening SQLite (generation remained 1). This is model availability evidence, not native conversation continuation.

The installed native permission inspector adds one external-directory exception for its own tool-output directory after catch-all deny. Probe verification permits only that exact native exception and rejects any other effective allow/ask rule or unexpected tool override. `OPENCODE_PERMISSION` takes a JSON object: a JSON string produced character-indexed permission keys and was rejected during development. Native CLI inspection, rather than the expected configuration text, decides whether model invocation is admitted.

The native quota fault canary connected OpenCode to a loopback synthetic provider with only fixture credentials. One HTTP request returned `insufficient_quota` with an explicit timezone-qualified reset; the supervisor recognized the trusted native stderr record and terminated the process after 3.95 seconds, before SDK retries. Cached quota/auth/unknown outcomes block automatic repeated probes; transient failures have a three-attempt budget. No real account quota was exhausted and no existing native conversation was resumed for these checks.

Native continuation v2 now hashes all selected session/message/part columns and content, including old edits that v1's latest-message/count/max-time revision can miss. Store identity binds device, resolved path and file identity. Viewer and CM independently calculate the same byte protocol and share a synthetic fixture covering Unicode, null and REAL cells. The headless Viewer CLI and CM's independent revalidation agreed on an actual local SpecMesh history in 192 ms, without Web or source writes.

Actual OpenCode 1.18.29 exposed two incorrect prototype assumptions: noninteractive positional arguments are re-quoted by `cli/cmd/run.ts:280`, and `tool/read.ts:237` checks paths relative to the native worktree. The worker now sends bounded stdin verbatim and maps exact read files to native-relative patterns. The first failed acceptance remained stale/unknown, and its external operation was not automatically repeated. Source code also confirms session permissions merge after agent permissions; both are checked before continuation. Project and home `.opencode` custom-tool discovery is isolated while preserving explicit native data/auth/cache paths.

The corrected real acceptance used a controlled local project and the actual TS worker, not the Python runtime. First turn stored a marker and read PROJECT.md. Viewer headlessly inspected the resulting native session; CM revalidated it. The second kernel episode used the same native session, recalled the marker without reinjection, and read the changed current project value. Both effects were confirmed and both episodes reached done. This establishes scoped same-provider, same-device native continuation with explicit read grants; it does not establish cross-provider memory, hostile-client exclusion, full SpecMesh gates, general write grants or production TS cutover.

The device port is a separate trusted-worker surface, not an SDK/Web mutation switch. Credential hashes map to configured principals/devices; assignment digests bind inspected work; every lease operation checks the current assignment and revocation. A cached claim/start/renew receipt is not current authority. Device events are agent-origin even when the owning principal is the human operator. Explicit peer task IDs permit cross-device mailbox delivery without exposing another device's execution assignment or workspace root.

Two timing gaps required code changes: Linux performance.now does not count suspend, and a fixed one-second anchor heartbeat can outlive a short device lease if the controller freezes. The worker uses `/proc/uptime` for its conservative deadline (request-send time plus server remaining duration minus margin), and the anchor receives the same host-clock deadline. Late IPC/HTTP renewals cannot revive an already expired authority. The current 25 ms anchor/100 ms controller polling and OS scheduling do not promise hard real-time external-effect exclusion. Canonical result writes still require a current coordinator fence.

The actual two-device synthetic run on 2026-09-11 used x64 and ARM64 Linux, distinct local workspace contents and authenticated SSH forwarding. Concurrent claim produced one owner; post-expiry ownership moved to the other device and the old fence failed. Both local-file read results were independently checked. A cross-device handoff preserved agent provenance and was explicitly received and consumed. Disconnecting the coordinator stopped the remote process; reopening preserved its unknown result and rejected automatic redispatch. Runtime credentials, private paths and raw acceptance artifacts remain outside the repository. No model calls, browser accounts, bot binding or production service startup were needed.

Full distributed Agent operation is still open. The qualified OpenCode read adapter now enforces source/grant checks locally over the device port; other providers and write/sandbox profiles remain unported. Device presence/capability revisions, re-enrollment/rotation, large-queue fairness, actual topology/dependency execution and unattended deployment remain. Revocation is already durable so restart cannot silently restore a denied device. Authentication proves a report's source, not the honesty of a compromised worker's claimed native result.

Native recovery initially lacked pre-execution evidence: the baseline row hashes and resolved permission profile were in worker memory, while effects stored only the intent digest and later output. Schema 5 now retains a bounded immutable manifest and original observation separately from accepted results. The manifest binds task/source/provider/grant, native-store/session baseline, resolved rules and canonical file identities/content digests. Reconciliation is explicit, revision/digest-bound and independently checks the native source under its advisory lock without model/CLI invocation. An older unknown operation with no manifest cannot be retroactively supplied invented evidence.

Real SIGKILL acceptance now covers the gap between durable native observation and terminal task commit: a separate process reopens the coordinator, confirms the reviewed original result, replays that acceptance idempotently and resumes the original native session. It recalls the original marker and reads the changed project file. This does not cover missing observations, unqualified providers/write profiles, hostile independent native clients, other stores or fleet-native admission; those remain full-goal requirements.

The initial follow-up returned an old project value without a new native read and correctly failed `required_native_read_unproven`. OpenCode 1.18.29 [LLM request preparation](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/llm/request.ts#L54) uses the custom Agent prompt in place of its provider default. The earlier two-sentence custom prompt omitted the required current-turn file list. The worker now issues that list and verifies the resolved Agent prompt before dispatch; tool permission rules and required native read evidence remain independent enforcement checks. Native's normal text loop does not force a read tool merely because a user requests one, so instructions alone are not completion evidence.

The actual local TaskHub entrypoint exposed an adoption-only ordering defect hidden by
the earlier fresh-session acceptance. A preflight opens a non-Git directory before an
existing-session worker reads its worktree. OpenCode 1.18.29's
[Project.fromDirectory](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/project/project.ts#L195)
updates the shared `global` project worktree each time; empty Git repositories also use
that ID. A content-bound session reference therefore does not make this shared project
row stable. Global worktree lookup now derives from the bound session directory and
local Git discovery. A genuine non-Git directory maps to `/`; a broken Git pointer or
discovery failure rejects. Other project IDs still use the native project worktree, and
session identity/current read/grant checks remain intact. The corrected actual stdio
startup plus process-restart canary passed; the original failed operation was not replayed.

The local queue is a new isolated candidate owner, not installed TaskHub parity. It admits
only a private configured local foreground read profile, requires an explicit drain, and
retains pending mail independently of native consumption. Filesystem marker checks avoid
accidental legacy-home use but are not production writer exclusion. Device fleet admission,
other stores and transport delivery still need their own migration and release gates.

Native mailbox integration now targets the actual local TaskHub execution path. The Python
`TaskHub.tell` appends parent updates for running tasks, while `pull_updates(mark_read=True)`
advances a file cursor. The TS mailbox already retains provenance/sequence/expiry, but its
generic consumed-evidence string is not independent proof of native delivery. Before this
integration, the OpenCode worker sent only `task.prompt`, and native reconciliation verified
exactly that text. Delivery therefore required an immutable batch in the dispatch manifest, actual
input verification, and atomic acknowledgement with task completion/reconciliation.
An in-flight reserved message must not become eligible for replay merely because its TTL
expires; expiry controls new delivery, while the original execution outcome controls recovery.

Device communication integration (2026-09-12): the coordinator's immutable device
manifest reference can carry the native scope without transferring native histories.
The same schema-10 journal then binds both local and remote calls. Device verification
reports bounded hashes derived from native parts, and coordinator completion/recovery
matches every call before consuming receipts. Device jobs now project trusted peer/parent
policy independently of arbitrary assignment input. No device task kernel is synthesized.
An additional execution seam was found: OpenCodeDeviceAdapter's default preflight ignored
its supplied runner and therefore could not qualify a container runtime digest. It now
uses that runner, with a regression fixture carrying a runtime identity. Automatic initial
mailbox prefix delivery still needs its device manifest/reservation seam; native receive
already handles queued and late messages.

Device initial mailbox integration (2026-09-12): full native input batches need not be
repeated inside every remote evidence reference. The reference now carries ordered IDs
and a batch digest; the coordinator reconstructs its own immutable message snapshot.
Native input is still verified against the full device-local manifest. Preparation reads
without acknowledging; reservation is atomic with dispatch. Prefix consumption must run
before dynamic native-tool delivery consumption, both in completion and reconciliation.
Queued updates arriving after preparation can remain outside the pinned prefix. Profile
and input-size validation happens before spending a native preflight permit.
# Independent SpecMesh integration — 2026-09-12

The original optional port could mix discovery bytes and later hashes while HEAD remained
unchanged. A fixture also proved `git status` can invoke a configured clean filter. The
independent SpecMesh v1.2.1 implementation now owns descriptor snapshots and bounded Git
plumbing; CM validates its explicit snapshot capability and pins the independent source in
CI. The normative Markdown standard remains 1.1.0.

The TS host gates preparation before provider preflight and checks current file/HEAD/code
identity at use. It does not treat assertions as permissions: every selected reference must
already be in the registered native required reads. Handoff/verify inspect a currently owned
task and recheck revision/fence. `verify_closeout` remains unknown without external evidence.
The host guards synchronous admission, bounded output/deadline and shutdown cancellation.

Paired tests exercise the actual independent CLI, a real local queue with synthetic task
execution, startup without native credentials, changed files/profile and owned subprocess
cleanup. The separate real OpenCode canary verifies native read tools and original-session
continuation, with five required reads on each of two turns. No production account replies
or native write permissions were involved. Read-profile acceptance does not close the
remaining provider/write/device, reviewer/evidence or production-cutover gates.

## Native workspace writes — 2026-09-12

OpenCode 1.18.29's native edit/write/apply_patch share the edit permission. The registry
selects apply_patch for some GPT models; permission inspection cannot independently allow
edit while denying write. Reject unrepresentable narrower portable grants. A patch move
has additional destination handling, so permission strings alone cannot establish write
confinement. The explicit profile uses original-path staged Docker mounts and disables
native snapshot, formatter and LSP execution. Official tagged implementation references:
[edit](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/edit.ts),
[write](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/write.ts),
[apply_patch](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/apply_patch.ts),
[registry](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/tool/registry.ts).

The two-turn real profile canary confirms native edit/write and original-session continuity,
not the normal TaskHub write entrypoint. It does not qualify native deletion or arbitrary
symlink-containing read roots. Independent readback uses the original SQLite records and
does not rerun Agent execution. Evidence lives in the private coordinating workspace under
outputs/runtime-convergence/workspace-write-native-profile.{ts,json,log} and
workspace-write-native-independent-verification.json; the verifier is
verify_workspace_write_native.py. Initial prepared-tree durability was added after this
native canary and is separately checked with actual Docker runner tests, avoiding another
model invocation just to test the filesystem guard.

The controller journal handles partial multi-file publication explicitly. A crash after
rename and before journal acknowledgement compares current content with the retained
proposal and acknowledges the already applied file without rewriting it. Prefix-checked
temporary files allow interrupted writes to finish; unrelated edits remain conflicts.
Descriptor-relative parent traversal stops a swapped parent from redirecting writes to an
unrelated path. Atomicity applies per file, not to the complete batch. RuntimeKernel lease
expiry and trusted recovery are tested; normal local/device adapter wiring remains open.

Preparation now fsyncs file data and directory entries and binds the initial staged snapshot.
A new runner attachment rejects changed bytes, new files and same-content identity changes.
The active runner intentionally permits its own later staged edits. This guard is a dispatch
condition, not a general lock against native clients outside the CM ownership protocol.


## Normal local TaskHub writes and recovery — 2026-09-12

The earlier explicit-stage canary did not exercise the ordinary task owner. Trusted write
roots now flow through local startup/queue/adapter/shared execution; v2 manifests retain the
actual stage and workflow binding while v1 read manifests remain compatible. Execution must
pin canonical input, but publication must accept its own changed files. Separate authority
callbacks preserve lease/grant/source/config checks without falsely revoking owned output.
After publication the independent SpecMesh service checks current documents again.

Native patch results retain metadata.files (filePath/type/movePath). Verify both endpoints
and require every proposed path to have completed native tool evidence. Container projection
limits writes; explicit alias denies are also needed because writable mounts do not enforce
native read permissions. Real M3 acceptance covers edit/write; patch deletion/moves are
currently fixture evidence. This distinction remains in the design and progress.

An async recovery gap allowed request-ID conflict detection only after filesystem publication.
Schema 13 reserves the canonical command identity first. Completion consumes the reservation
atomically with the receipt; a failed workflow check retains it across restart. Cancellation
under another request ID still revokes task authority. Seven old-schema tests initially left
the new table present while reducing user_version; reconstructing the old table set fixed
those fixtures without weakening production migration. Full core regression then passed.

Real TaskHub acceptance retained the original proposal after a deliberately lost completion,
reopened, reconciled with no new native call, replayed the receipt without rewriting files,
and continued the same original session against updated PROJECT/code. Post-write checks are
structural, not independent reviewed completion. Its actual schema-12 database subsequently
upgraded to 13 and replayed the receipt without changing events/native messages/containers.
Async reservation behavior is separately fixture-tested; the paid model was not rerun.

The initial container report queried SQLite, but actual container ownership uses private
per-container record.json files. Independent verification read those records and confirmed
all nine immutable container IDs absent. The initial report is preserved, and only the
reporting code/result was corrected. Native acceptance itself was not repeated.


## Device workspace integration — 2026-09-12

Device publication can reuse current coordinator lease renewal after retained observation;
it must serialize that explicit refresh with the heartbeat, then enforce the conservative
local monotonic deadline before each file operation. Recovery re-fetches the same current
challenge before touching files. An observed outcome may still precede cancellation or loss
of its completion response; no instantaneous remote-revocation guarantee is asserted.

DeviceEvidenceRef now distinguishes a write profile using digests only. The coordinator
requires matching published-proposal proof on normal completion and reconciliation. Native
store, stage, root paths and complete receipts remain device-local. Optional SpecMesh uses
its independent start and post-publication checks; source/profile changes revoke admission.
The original read-only adapter and manifests remain compatible.

Initial read regressions exposed optional undefined configuration members being fed to the
canonical digest; top-level absent options now normalize consistently. The existing 34-case
device read suite passes. The new SpecMesh fixture initially had an unborn Git HEAD and then
looked for results in the task row instead of the episode owner. Fixes create its isolated
committed baseline and inspect the actual episode; these did not weaken runtime checks.


The real device trial first put state_home above the project and was rejected before native
task dispatch, after one successful model preflight. The isolated device journal contained
zero task records and canonical files were unchanged. Correcting the fixture to sibling
state/project directories succeeded. WorkspaceStage now exposes the same location check to
both adapters before preflight, with cache-empty regression tests. The earlier preflight had
expired; current code performed one fresh probe rather than extending its timestamp. The
successful attempt used one probe/two task turns, and recovery used zero native commands.
Both attempts and cleanup remain recorded separately.

The wire read_count limit of 80 described the original fixed read registration. A write-root
profile can legitimately read more distinct in-scope files. The count is now a safe integer;
a fixture verifies 86 actual native reads while unchanged root/path/tool checks still enforce
scope. This metadata extension is fixture-qualified after the real six-file canary; no model
rerun is necessary to validate a numeric field bound.


## Device-local native adoption — 2026-09-12

History owns discovery and a content-bound reference; it does not issue runtime authority.
A worker-local adoption registry permits unmanaged native sessions without transferring
paths, credentials or native databases to the coordinator. Binding the selection to the
future task ID and exact local profile prevents another assignment from consuming it.
Execution and interrupted-turn recovery require different native checks: the former rejects
a changed baseline before preflight; the latter verifies the originally retained appended
turn. Re-querying History during recovery would silently replace that original baseline.
The asynchronous mailbox read is another external-client race window, so baseline validation
is repeated immediately before preflight; regression proves zero probes after an edit there.

Old-version test fixtures initially retained the new schema-14 table when declaring an older
PRAGMA version. Their table sets were corrected; production migrations still reject an
inconsistent existing schema. The independent Docker verifier initially expected capitalized
"No such object"; this installed CLI emits lowercase. The readback comparison was corrected
and repeated; the successful native execution was not rerun.

The actual controlled adoption session originated from a raw OpenCode CLI without TaskHub.
Headless discovery/prepare, normal task adoption, model-free reopen recovery and subsequent
original-session recall all passed. The current trial is same-host/separate-process; previous
physical ARM64/x64 tests cover the common device transport and staged publication path.
No evidence is promoted to installed production rollout or reviewed SpecMesh closeout.

## Explicit SpecMesh artifact candidates — 2026-09-12

Trusted profile may select requirements_path. The adapter requires a matching
source reference/hash, validates task-compatible file requirements and binds the
entire candidate into the revalidated observation. Unrequested candidates reject.
This transport is not automatic adoption: ingress still owns issued task contracts,
and runtime grants remain independently enforced. Paired Python/TS tests cover
current-source mutation and missing source proof; standalone source is d393c54.

## Explicit local adoption — 2026-09-12

LocalRuntimeControl.submit now optionally consumes the selected manifest SHA-256,
revalidates the configured independent port, and submits a cloned completion contract
through existing TaskIngress. Conflicting predeclared requirements fail rather than
being overwritten. The persisted source record remains asserted-candidate metadata;
no permission or completion claim is derived from it. The same snapshot is checked
again after History resolution and before synchronous submission. Ten paired tests
pass, including stable retry identity and source-record injection refusal. Device
control adoption and remaining provider completion gates are still separate work.
Remote CI lookup for 34679687668 timed out at the network layer; this is not proof
that the run stopped or failed. Packaging predecessor 34679508577 was verified success.

## Coordinator-local requirement adoption — 2026-09-12

A worker's private filesystem cannot be inspected as a coordinator-local path. The
optional coordinator profile selects its own canonical checkout. Shared adoption
logic freezes the selected requirements through normal ingress; existing assignment
projection carries only execution fields. Normal reopen plus authenticated loopback
queue tests prove the exact completion contract survives and the local path/source
metadata is not transported. This is not evidence of identical worker source code;
revision/content coordination must still be verified separately. No provider runs
are issued by discovery or adoption.

## OpenCode artifact requirements — 2026-09-12

OpenCode's verified native turn already provides successful file-tool evidence;
verifyWorkspaceTools now returns its scoped read/write paths for completion checks.
Completion validates actual resulting bytes in the existing stage and requires a
current-turn operation, so an old file's presence alone is insufficient. The same
helper runs in normal completion and retained recovery. Device results bind the
contract digest and ordered hashes through the existing coordinator checks. Contract
prompt augmentation is reproduced during recovery and leaves undeclared task prompts
unchanged. Existing grants remain the authority; requirements cannot extend them.

## CI dependency and ordinary-submit ordering — 2026-09-12

CI bb0d039 used SpecMesh5fab9f0, whose strict request schema rejects the newly selected
requirements_path. CI pin must move with the reviewed standalone contract source;
local checkout success did not verify the CI pairing. The same run exposed an added
await in ordinary submit after helper extraction. Stdin dispatch accepts multiple
commands, so an inspect could overtake a submission that previously ran synchronously.
Both controls now bypass async adoption when no source hash is selected. A test reads
the persisted task immediately after handle(submit), before awaiting its Promise.
First broader local run independently reproduced the ordering failure; focused rerun
passed after correction. Required asynchronous adoption remains explicit.

## Real OpenCode exact-byte acceptance — 2026-09-12

Three separately guarded tasks resumed the original TaskHub write session. Each
read the current fixture documents and returned the original marker. The model's
native write argument omitted the requested LF; resulting staged bytes likewise
lacked LF. A second task explicitly described the missing byte; a third requested
native apply_patch but still invoked write. Thus patch-tool behavior was not tested,
and neither CM byte loss nor the sole upstream root cause is established. Exact
completion SHA-256 rejected all three before canonical publication. Each task used
one ready preflight generation; all18 owned containers were independently absent.

Private evidence in the coordinating workspace: outputs/runtime-convergence/
opencode-contract{,-correction,-patch}-native-acceptance.{ts,json,log}, three wx
attempt guards, verify_opencode_contract_attempts.py and
opencode-contract-independent-readback.json. Never rerun the guarded scripts. No
native state copied and no original failure record overwritten. The first readback
assertion used case-sensitive Docker error text; lowercase comparison fixed the
verifier, without changing runtime or acceptance. These failed real runs do not
invalidate the demonstrated rejection behavior, but do not establish successful
artifact delivery, recovery acceptance or complete migration.

## Retained OpenCode tool availability — 2026-09-12

The third failed run's original permission_evidence.resolved.tools contains read,
edit and write but no apply_patch. CM's generic workspace instructions nevertheless
listed apply_patch as a tool to use. Shared native edit permission permits an available
write family; it does not establish each family member's availability for a model.
The instruction now directs execution to the actual exposed file tools and makes that
distinction explicit. Retained recovery already validates the saved prompt/permission
snapshot without regenerating it from current instructions, so old evidence is not
rewritten. This explains why a patch-based retry was not justified by the retained
catalog; it does not establish the root cause of missing LF in write arguments.

## Team phase ownership — 2026-09-12

Python TeamOrchestrator is a lazy persistence wrapper around phases.py, not a complete
topology dispatcher. Its transition graph allows repair to execute/verify/complete;
exceeding max_repair_attempts produces failed without incrementing the retained
attempt count. Terminal transitions reject; prior transition history is preserved.
Live differential tests cover every phase pair and five repair limit/count profiles.
The TS persistence owner uses existing scoped commands and SQLite transactions.
Failed writes roll back receipts and state; a stable retry after reopen returns the
original result, while changed body/stale revision/other owner/revoked scope reject.

Candidate database migration16 adds team_phases; no Python file is imported or
modified. Older candidate binaries refuse v16. Rollback requires the pre-upgrade
candidate backup, not hand-editing user_version or dropping populated team state.
Released Python remains production owner. Topology execution must still compose
this state with task admission and explicit runtime authority, not infer dispatch
permission from an approve phase.

## Pipeline/fanout handoff selection — 2026-09-12

Pipeline review independently falls back to worker evidence and worker artifacts
when each reviewer collection is empty. Fanout fallback considers completed results
from collecting checkpoints only; it retains first-to-last checkpoint order and
duplicate references. Explicit reducer selections override each collection separately.
All-failed output intentionally includes failed-worker evidence/artifacts for diagnosis
and names the failed roles in order. These are reference-selection semantics, not
proof verification or execution authorization. TS ports deep-copy selected references
so consumer edits do not mutate original normalized inputs. Python private reducer
methods are dynamically executed in the parity test, with real Pydantic result models.

## Normalized team result protocol — 2026-09-12

team-structured-result.schema.json defines the normalized packet and conditional
shape rules shared by protocol validators. TS decodeTeamResult supplies defaults,
normalizes known fields and drops unknown fields like the Python model. It enforces
available topology/substage combinations, director/judge collecting-only results,
parent-input consistency and repair hints. Python str.strip differs from JS trim
for U+001C–U+001F/U+0085 and U+FEFF; the adapter preserves the observed Python behavior.
Numeric conversion distinguishes integer version strings from floating confidence,
rejecting hexadecimal conversion and preserving tested boolean numeric coercion.

Live parity covers677 finite JSON cases, not every Pydantic coercion or Python-only
value. Nonfinite values are outside the JSON wire contract. The normalized schema
requires all defaulted fields; use the adapter for raw model envelopes. Neither
structural validation nor a referenced artifact proves execution success. Actual
TaskHub/topology identity, ownership and evidence checks must compose this boundary
before reducers are connected to task completion.

## Terminal result provenance

finish clears active_episode, so topology consumers must retain explicit episode/effect
identity. Reconciliation advances task fence while retaining original episode fence;
strict equality rejects recovered results. The new reader instead rejects any newer
episode and requires current task revision plus matching confirmed effect/episode output.
This proves runtime acceptance lineage, not the truth of model evidence references.

## Team result execution format

Local Claude/OpenCode adapters and device coordinator store the same accepted result
in effect and episode. Native text uses value.digest(text), including JSON canonical
string encoding; do not substitute raw-file SHA hashing. readTeamTaskResult checks
that digest before whole-document JSON parsing and role/topology/substage matching.
Expected assignment remains a trusted scheduler input until persistent topology
registration is wired; caller-supplied bindings must not authorize a team transition.

## Topology state migration boundary

Python TaskHub owns a task-local topology state JSON file. The TS candidate uses a
foreign-keyed task record with independent topology revision and command receipts.
Python empty role lists mean inherit on interrupt/resume; round and artifact counts
also survive interruption. Four real-spine sequences verify this behavior.
Normalized TS persistence requires all fields and ISO calendar timestamps, not all
Pydantic input coercions or accepted timestamp spellings. The complete state is
validated before storage; Python model_copy can defer cross-field failures until
its next read. Waiting-parent/current-checkpoint consistency fails immediately in TS.
Raw result fields remain an internal composition input, not a public completion API;
future task assignments must load accepted results through readTeamTaskResult.

## Topology child execution binding

LocalTaskRuntime.enqueue resolves a trusted adapter without launching a provider;
actual probes and execution happen only in tick/drain. TopologyTaskQueue inserts a
child assignment in the same transaction as enqueue, for existing independently
submitted tasks owned by the same principal. It grants no additional tools or roots.
The stored run lease supplies episode identity; a unique confirmed effect matching
the episode output supplies effect identity. Model role labels never select a task.
Ancestor checks also run in Kernel lease/publication and reconciliation. Cleanup is
explicitly exempt from parent activity, but still needs the exact live child lease,
so an interrupted effect can become unknown instead of waiting indefinitely.
A checkpoint change invalidates outstanding assignments; retry/repair requires a new
explicit assignment. Current one-child-per-role-per-checkpoint contract does not yet
implement automatic topology policy, multi-device assignment, or nested grant issuance.

The initial assignment table has one row per child, so cross-stage reuse of the same
TaskHub child ID remains unsupported. Do not replace native continuity with a fresh
conversation to work around it; add explicit assignment generations before claiming
repair/resume orchestration complete.

## Assignment generations resolve same-child reuse

Schema19 archives each replaced topology_tasks row with its generation, including the
accepted result/run binding. TopologyTaskQueue.resume calls existing Kernel.resume,
which keeps task ID, provider fields, source context, grant and retained native session.
Only a new checkpoint and terminal resolved child can enter a new generation. A done
child must first have collected output; failed native tasks still require the kernel's
no-unresolved-effects check. All archive/resume/queue writes roll back together.
This supersedes the initial same-child limitation above. Malformed done output still
needs an explicit reject/recovery path; do not reinterpret it as accepted just to resume.

## Pipeline policy and queue composition

Python permits completed/failed worker and repair passes; reviewer additionally
supports needs_parent_input and needs_repair. A terminal review falls back separately
for evidence/artifacts to the latest worker/repair result.127 live-Python sequences
verify the TS port, including code-point-based summary truncation.
RuntimePipeline selects the next stage from accepted output, but receives the next
independently authorized child identity explicitly. Collection, phase change and
queue admission share a transaction; replay returns the receipt without redispatch.
It advances one step only. Background repair budgets and parent TaskHub terminal
finalization remain separate owners; a completed topology is not a finished parent
native episode. The two full synthetic queue flows do not prove live-model acceptance.

CI34683858904 at e981aeb failed opencode-container's staged-runner test in
ContainerProcessSupervisor.engine (docker info, container_engine_unavailable), before
container launch. Later tests in that job passed. A single failed-job rerun was
requested; no cause or successful retry is proven yet. Local pipeline full gate passed.

## Stable fanout dispatch and batch acceptance

Python dispatches at parent substage dispatching, but worker envelopes use collecting.
TopologyTaskQueue now derives that expected result substage from the trusted stored
topology/parent stage; execution leases still bind the unchanged dispatch checkpoint.
RuntimeFanout collects the complete distinct assignment batch before advancing the
parent. Incomplete batches roll back earlier accepted flags, preserving slower workers.
Dispatch order controls checkpoint/evidence order independent of completion order.
Actual configured local parallelism bounds admission; queue-capacity failure rolls
back all workers and the dispatch checkpoint. Separate pure policy functions preserve
Python behavior, while the queue boundary additionally enforces complete role coverage.
The previously failing e981aeb CI container job passed its single requested rerun;
this establishes a successful retry, not a diagnosed cause of Docker-info failure.


## Parent artifact evidence and SpecMesh source ownership

File existence cannot establish an Agent read or write. The parent gate reuses accepted
child episode/effect results and NativeWorkspaceFiles completion proofs, including exact
mode/path/hash, while current canonical bytes and registered workspace identity remain
host-owned checks. It excludes remote native result packets from this local authority.
Preparation is an ephemeral capability, not an authorization JSON document: restart
repeats read-only verification and does not repeat a provider command. Child resume,
changed content/symlink, revoked profile or changed SpecMesh requirements invalidates it.

The standalone SpecMesh `verify_closeout` operation deliberately returns unknown even
with an otherwise valid acceptance manifest: host independent review remains required.
It emits no passing artifact candidate in that state. Existing `adoptSpecMeshCompletion`
uses `check` to adopt a reviewed requirements file, so parent file delivery uses the same
source operation and exact requirements hash. Treating verify_closeout unknown as pass
would have conflated file-contract verification with overall project acceptance.
The new fixture exercises actual file broker receipts and publication without a model;
it establishes this integration contract, not fresh native/model acceptance.

The task plan previously accumulated contradictory historical Next statements and old
test totals. Its current Next section now points to one active implementation seam;
retained native history remains in the existing progress archive and design files.


## Explicit topology reopen and execution-scoped assignments

Checkpoint names restart from cp_0001 in each topology execution. Checking only parent,
role and checkpoint could let retained work cross a reopen boundary. Schema 22 adds the
execution ID to assignments and checks it at ancestor authority, collection, finalization
and artifact-witness selection. Existing child rows remain reserved for explicit native
resume; generation history is preserved. Frozen controller/limit configuration is reused;
only an explicit new run resets its counters. Process restart does not do so.

The completion digest previously hashed SELECT * assignment rows. Adding a column would
therefore invalidate a legitimate schema 21 terminal proof after upgrade. The verifier now
hashes the exact original column projection while separately filtering by execution ID.
The migration fills IDs from the existing topology state and preserves old proof/history
JSON. A completed legacy run can then be archived and reopened without re-execution.

The first new fixture omitted the LocalTaskRuntime task:reconcile scope and was correctly
rejected before dispatch. Correcting the fixture yielded 13 passing reopen tests; additional
stale-execution, archive-integrity, control rollback and artifact tests brought the focused
gate to 31 passing tests/242 assertions. These use controlled provider fixtures, not fresh
native-model continuity acceptance. Early declared-topology mismatches now fail before
queue admission rather than being detected only when finishing the parent.

Remaining orchestration ownership: nested aggregate children need a completion source
binding independent of local native run/episode/effect rows. Current root completion and
reopen deliberately require root identity. The automatic scheduling owner also needs to
prevent scheduling an orchestration parent as an ordinary provider job; the existing
terminal gate detects a separately queued parent but is not early admission enforcement.


## Nested aggregate source and initialization authority

A topology result is not a native task episode and cannot be read through a fabricated
local_runs/episode/effect record. Schema 23 makes assignment kind explicit. New aggregate
reservations have no bound child execution until topology creation binds it; native queue
admission/claim refuses both reserved aggregates and initialized orchestration tasks.
The previous late parent-queued completion check remains defense in depth. A role asking
for a director/judge decision cannot be assigned an aggregate summarizer.

Nested results carry child task revision, topology revision and execution ID plus a digest
of the verified completion. Parent role and substage come from assignment authority.
Recursive verification uses an explicit bounded lineage; it rechecks descendants rather
than trusting old JSON after a leaf resume. Native digest projection stays compatible with
schema 22, while kind selects the verifier. File verification traverses the same accepted
aggregate tree to actual native leaf receipts; it does not turn summaries into file proof.

The parent-controlled aggregate resume temporarily removes the old edge inside one SQLite
transaction, invokes verified child reopen, then restores the new assignment generation.
No external execution occurs between those writes. The injected reassign failure restores
old child state, completion, assignment and history. Prepared control dispatch reuses the
frozen controller configuration after this nested reopen.

Focused evidence: 27 tests/287 assertions pass, including all 16 approved parent/child
combinations over two runs, two-level file delivery, cancelled ancestor admission/effects,
failed branch semantics, changed leaf/proof/identity refusal, cycle/control-role refusal and
schema 22 upgrade. Previous affected suites passed 50 tests/411 assertions. All provider
execution here is controlled fixture behavior, not fresh native-model acceptance. An initial
edit-script anchor failed before the remaining mutations; work resumed at that exact
statement. Typechecking then required narrowing a native-only test's result binding after
introducing the aggregate union; no native episode field was added to aggregate results.


The first full aggregate gate exposed a permission regression: assertNativeTask called
inspect and therefore required task:read during Kernel.claim, although existing execution
workers legitimately hold task:execute without task:read. The real process race and
post-observation crash tests both failed before claiming. The guard now checks ownership
through the private row and then orchestration type, retaining the old execution scope.
No worker permission was broadened. The failed full run remains in
/tmp/cm-aggregate-full-initial.log (588 pass, 2 fail); final verification must use the rerun.

## Automatic local topology scheduling design in progress

The scheduler must use an explicit immutable mapping of already-authorized task IDs to
roles, including aggregate child nodes. It must not mint grants, infer new task identities
from model output or treat inspection as provider execution. It will read accepted output
without collecting it to select the next authorized role, then call the existing atomic
composition operation which revalidates that output and its task/checkpoint revision.

Persistent schedule leases bind principal/device/origin and serialize asynchronous artifact
preparation and transition admission. Current task and topology revisions still fence every
actual operation. Unchanged polls do not emit prompts or notifications. A background loop
is optional in the isolated local configuration and must stop with the existing runtime.
Pause stops new topology transitions; admitted native work retains its existing lifecycle.

Malformed confirmed output may be retried only by an explicit recovery command, preserving
its rejected assignment/result binding and original native session. Blocked unstarted work
also needs explicit retry; uncertain or cancelled work cannot be replayed. Pipeline/fanout
repair and parent-interruption caps must finish from host budget policy instead of spinning
indefinitely. Existing director/judge immutable policy bounds remain authoritative.

## Explicit recovery foundation verified in isolation

The initial draft caught every preview exception as malformed output. That could confuse
execution/authority failure with a model contract failure. Recovery now admits only typed
JSON/schema/assignment errors produced after native completion evidence validation.
The draft also silently ignored a supplied prompt for unstarted work; that request now
rejects explicitly. Retrying unstarted work preserves the original submitted input.

The draft budget check could turn an unsupported worker request into a terminal accepted
result. Budgets now act only at reviewer/reducer decision stages; unsupported worker
statuses still fail the original state-machine rule. Pure transition defaults remain
unchanged, and frozen service registration remains outstanding.

Focused queue/native result gate: 23 pass / 137 assertions. Focused controller/budget gate:
32 pass / 208 assertions. Existing Python pipeline/fanout parity and controller checks also
passed (24 tests / 385 assertions before new cases were added). Logs are respectively
/tmp/cm-topology-recovery-focused.log and /tmp/cm-topology-budgets-focused.log.
These use controlled resolver fixtures, not additional live model/session prompts.

During implementation, typecheck found an optional retry prompt passed without narrowing;
that call is now guarded. One test-writing command used a repository-relative path from the
package working directory and failed before editing; corrected package-relative paths were
used next. The subsequent focused run includes the new cases. Full gate is recorded in
progress.md only after its actual process finishes.

Full pinned gate finished with exit 0: 612 pass, 0 fail, 8283 assertions across 66 files
in 209.12s (/tmp/cm-topology-recovery-full.log). Python inventory and runtime typecheck
also passed. Existing nested aggregate, terminal completion and same-tree reopen fixtures
remain green after adding rejected-assignment history. No production version switch.

## Local automatic scheduler implementation

Schema 24 adds immutable schedule membership, owner/device/origin, plan digest, revision,
mode and fenced leases. The normal private configuration/control/CLI now owns an optional
loop and explicit EOF keepalive. All four local topology kinds and all 16 nested kind pairs
progress through the existing atomic composition methods. Registration does not execute
providers; activation and configured background startup are distinct controls.

Review caught premature aggregate startup: a director's registered child was eligible
before being dispatched. Nodes now wait for the current actual parent reservation. Existing
control policies must exactly match registered frozen limits, and external assignments
cannot be silently attached. Shutdown preserves active plan mode while clearing loop/lease.
Automatic kernel transition events carry schedule provenance without changing actor grants.

Focused service verification: 68 pass, 0 fail, 462 assertions across scheduler, normal
local control and existing controller suites, 6.62s (/tmp/cm-topology-service-focused.log).
It includes real CLI EOF/SIGTERM behavior without credentials/native commands, two scheduler
instances over separate database connections, all local graph combinations, preserved
malformed/quota blocks, explicit recovery, parent answers and repair exhaustion. Typecheck
passed. Artifact pause fencing uses a controlled negative fixture; existing file evidence
acceptance remains in its own suites. No fresh native model acceptance is claimed.

Previous published 725f22c has verified successful remote CI 34691621283. The earlier
connection error happened before this turn's network grant; the subsequent exact-run query
succeeded. Current full pinned gate runs under /tmp/cm-topology-scheduler-full.log and must
be reported only after that original process reaches a terminal result.

Full scheduler gate completed with exit 0: 645 pass, 0 fail, 8529 assertions across 67 files
in 213.47s (/tmp/cm-topology-scheduler-full.log). Existing Python differential suites,
process/native/device fixtures, all older candidate upgrades and the new service gates
passed together. This is controlled automated evidence, not new real-model acceptance.


## Device topology integration and review

Published f45c1ab has verified successful remote CI 34692640944. Current schema-25 code
binds shared topology compositions to coordinator device assignments and actual worker
claims rather than local_runs. Normal coordinator configuration/control/daemon owns the
optional loop. The full pinned gate passed: 680 tests / 8884 assertions across 68 files in 218.98s,
exit 0, /tmp/cm-device-topology-full.log. Inventory drift and typecheck also passed.

The important difference from a local queue is that worker preflight releases the episode
without a coordinator-owned local run. The old device assignment must stop appearing in
discovery, otherwise worker scheduling can repeatedly probe the same quota failure.
Explicit topology recovery now archives the bound lease and creates a fresh assignment.
Review also found that independent worker caps did not enforce coordinator parallelism;
discovery and atomic claim now check the persisted global admission count.

Controlled focused gates passed: 72 tests / 675 assertions across device topology, normal
device control and local scheduler (9.35s), then 30 device topology tests / 305 assertions
(3.74s) after adding coordinator cap, expired/unknown work and native-device routing cases.
The latter native reference is schema-valid synthetic routing data, not real native proof.
Evidence: /tmp/cm-device-topology-control-focused.log and /tmp/cm-device-topology-negative.log.
Typecheck passed. One test-edit command used the package directory with a repository-relative
path and failed before writing; correcting the workdir/signature resolved it. Schema reads
initially omitted the canonical v1 directory; no schema was changed.

Remote artifact/current-source aggregation and reviewed SpecMesh project closeout remain
unimplemented here. Root completion with required files blocks instead of accepting remote
text as current local file evidence. Full CM-R0–CM-R7 and release/default switch remain open.


## Native topology context gap

Static trace after cd4a47f found that nativeInput only included the task prompt and pending
mailbox. Existing topology fixtures obtained current stage/role/round by directly reading
coordinator SQLite; a real device Agent cannot do this. Current work freezes a bounded
host-derived input per dispatched native run, including role/stage/output schema and
attributed prior checkpoint results. It is delivered by the existing native mailbox and
verified using its original input receipts. Schema 26 adds topology_native_inputs.
This is an actual execution gap, not a new user workflow or public API.

Input carries schedule provenance, zero forwarding hops and no fabricated sender episode.
The assigned child lease can obtain only its own frozen context. Real provider dispatch
must include that message; a missing batch is refused before native side effects. Oversize
context blocks rather than silently truncating earlier results. Native continuation still
uses the actual provider session. Current source/artifact verification remains separate.


Review corrected a concrete pipeline detail: the review checkpoint itself carries the
previous worker result. Excluding the current checkpoint left reviewers without that
result; focused tests caught the omission and now cover it and oversized-context refusal.
Focused input gate passed 74 tests / 618 assertions (7.55s), then 33 device admission tests /
319 assertions (3.94s). Full pinned gate passed 688 tests / 8936 assertions across 68 files
in 219.43s, exit 0, /tmp/cm-topology-input-full.log. Inventory drift and typecheck passed.

Real native canary `topology-input-native-acceptance-20260912` failed as a whole. A single
preflight succeeded. The worker made seven workspace read calls, completed, and consumed
its context with actual native proof. The reviewer made zero tool calls, retained its
received context, and failed workspace_tool_required_read_missing. Both native sessions
have exactly one user turn. No second execution/reopen ran and no replay was attempted.
The script is terminal; its operator-workspace report is guarded with do_not_replay=true.
Do not treat retained output or model claims as fulfilling missing reads. Future recovery
work must distinguish this known contract failure from uncertain side effects without
weakening required-read validation or automatically rerunning the failed attempt.


Next recovery seam, confirmed by code inspection: ClaudeTaskEvidence.verify establishes
terminal control output, original native session, exact native prompt, source identity and
turn bounds before NativeWorkspaceFiles verifies required reads. A required-read miss
throws before an evidence result is returned. ClaudeTaskAdapter and LocalTaskRuntime then
retain the dispatched effect as unknown/stale through their generic catch paths. Correct
recovery must not classify every RuntimeConflict as a known failure. It needs a separately
verified task-contract failure result after native/tool-receipt verification, preserving the
original session and missing requirements while refusing any unverified external side
effect. The recorded reviewer is read-only with zero file calls; do not replay it to test
this future implementation. Use retained data for inspection and controlled fault fixtures.

Final review also closed expired-context fallback: a required context whose message expired
must not become an undefined/empty mailbox input. The new negative case rejects before
native invocation. The full gate including this guard completed: 688 pass / 8937 assertions across 68 files,
220.41s, exit 0, /tmp/cm-topology-input-final.log. The original process is terminal.
Afterward a final device visibility check was verified with 33 device-topology tests / 322
assertions, 4.84s, plus typecheck (/tmp/cm-topology-input-visibility.log). Missing/corrupt
input now visibly blocks the schedule instead of remaining queued while discovery hides it.
The full log predates that final visibility check; remote CI binds the final published SHA.
