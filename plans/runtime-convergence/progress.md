# Progress

## Current

TopologyTaskQueue now binds already-authorized child tasks to a persisted role and
checkpoint, enqueues through LocalTaskRuntime, and collects only its stored run's
accepted episode/effect output. Candidate schema18 adds topology_tasks. Registration
and enqueue share a transaction; receipt replay never adds a run. Kernel claim,
lease/publication and reconciliation check the bounded ancestor chain. Cancellation
or changed checkpoints refuse further child effects; release/unknown bookkeeping
remains possible under the original lease. Focused23tests151assertions and typecheck
pass; expanded full runtime gate494pass0fail,6236assertions across54files in195.13s.
No production/default change. Previous7182236 CI confirmed successful.
Next: automatic pipeline/fanout/director/judge policy composition, same-child
assignment generations across resume/repair, cancellation UX,
and multi-device topology dispatch. Current queue composition is local and requires
independently authorized children; it does not derive new child grants from a parent.
Version18 rollback requires pre-upgrade backup; prior candidates reject the database.

Topology execution state now has a canonical normalized schema, TS checkpoint/
interruption/resume transitions, and private RuntimeTopology transactional storage.
Four topology sequences match the real Python spine. Version17 adds team_topologies;
version16 upgrade and historical upgrade fixtures preserve prior stores. Scope/task
revision/topology revision checks precede writes, and terminal or uncertain tasks
cannot advance topology. Generated protocol, Web bundle and ownership inventory
updated. Python protocol9tests pass; full pinned runtime gate488pass0fail,6205
assertions across53files in194.65s; typecheck and Web build pass.
Next: persistent child-task assignments and pipeline/fanout/director/judge dispatch
composition using readTeamTaskResult. This state store does not execute Agents.
No production migration or release. Older candidates reject version17; rollback uses
pre-upgrade database backup, never schema-version editing on populated state.

Team task-result reader connects accepted kernel output to normalized team results.
It checks text digest and the trusted scheduler's expected topology/substage/role;
whole-document JSON only. Normal completion and reconciliation survive database
reopen in synthetic execution tests, with no extra episode. Focused19tests780assertions
and typecheck pass. Full pinned runtime regression:485 pass,0 fail,6157 assertions
across52files in193.76s. Persistent topology assignment
and dispatch composition remain pending: this exported internal reader is not an
authenticated public assignment API or proof that model evidence references are true.

Kernel now exposes inspectCompletedEffect: scoped owner/revision checks, explicit
episode/effect binding, terminal accepted state, latest execution fence, confirmed
effects and equality of persisted episode/effect results, in one read transaction.
Kernel tests:16 pass,82 assertions; runtime typecheck passes. This is a read primitive,
not yet attached to topology dispatch. Next bind topology task registrations to this
reader and the normalized result decoder; retain full migration/release gates.
Latest preceding published SHA2228f92 and its two predecessors have successful CI.

Shared team-result boundary implemented: normalized JSON Schema plus TS raw-result
normalizer, with topology-specific substages, parent-flag/status consistency and
required repair hints.677 raw cases match live Python models; team suite5tests
1087assertions1.337s and Python protocol9tests0.71s pass. Generated TS/Python, Web
bundle and ownership inventory synchronized. Initial extended coercion test exposed
boolean/numeric/Unicode-strip differences, corrected against live Python results.
This remains a structural boundary; execution-spine identity/evidence admission is
not yet connected and no completed Agent claim is accepted as execution proof.

Topology result reductions: pipeline review/terminal and fanout reducer/all-failed
ported as internal normalized-data functions. Live Python comparison passes24
selection/status combinations and2failed-batch cases,64assertions; typecheck passes.
Input/reference immutability checked. No task completion/dispatch path is attached;
raw envelope validation and execution-spine migration remain next work.

Final team-phase increment gate:480pass0fail,5,387assertions192.73s across49files,
pinned Bun1.3.11 + Docker image + standalone SpecMesh. Process65158 exit0,
/tmp/cm-team-phase-full.log. Candidate v16 migration and all prior runtime tests
pass on this source. Team topology dispatch and production retirement remain open.

Team phase migration: pure transition and lazy state wrapper match live Python across
320 edge/repair combinations. Private RuntimeTeamPhases uses scoped ownership,
revision checks and transactional receipts; candidate DB v16 adds team_phases.
Storage/migration/process/device/delivery focused suite56pass718assertions4.43s.
New phase tests3pass344assertions; typecheck passed before final export addition.
Full pinned runtime gate in progress at /tmp/cm-team-phase-full.log.
This does not complete topology dispatch or enable production team execution.

Tool-availability instruction correction verified:12tests90assertions2.42s pass
(workspace profile and TaskHub staged-write/recovery), typecheck passes. No model
input; missing-LF live acceptance remains failed.

Retained evidence establishes apply_patch absent from actual resolved tool catalog.
Corrected generic workspace instructions that advertised the unavailable tool;
permissions and actual availability are now explicitly distinguished. No live model
retry. Existing retained snapshots stay unchanged and remain recovery inputs.

Real OpenCode declared-artifact acceptance FAILED (three distinct guarded tasks,
2026-09-12). Same original native session recalled its marker and consumed current
project value, but every resulting file omitted final LF; fixed SHA-256 requirements
blocked publication. Two explicit corrections did not fix it. The third prompt
requested apply_patch but native evidence shows write, so apply_patch was NOT tested.
Do not rerun these scripts or continue prompt-only retries. All18 owned containers
confirmed absent by live Docker inspect. Model-free readback proves each staged file
would match only after adding LF; canonical output remains absent. No requirement
was weakened and no failed attempt was marked done. Next investigate actual provider
tool construction/selection from retained evidence while progressing remaining ports;
this is not successful delivery or full native acceptance.

Final OpenCode completion/source-ordering gate passed:477tests0fail,5,043assertions,
192.17s, pinned Bun1.3.11 + Docker image + independent SpecMesh. Log
/tmp/cm-opencode-completion-final.log, process41734 exit0. This supersedes the
failed first run below. Current increment ready for source publication; no model
canary, package release, installation or production cutover performed.

Final-source retest running as41734 (/tmp/cm-opencode-completion-final.log).
First full gate: 476 pass / 1 fail, 5,039 assertions, 192.13s; the only failure
was ordinary stdin submit ordering after shared async adoption. Restored synchronous
unadopted submission in both controls and added a deterministic immediate-read
regression. Control/SpecMesh/device suites pass35tests246assertions15.82s. CI also
pinned old SpecMesh5fab9f0; pin now targets published d393c548a2a58989d65e6cdbd60a36e9a81a444f.
Remote runs34679687668/34679978697/34680201025 failed; do not describe them as pending.

OpenCode artifact-contract increment: normal execution, retained verification and
device result proofs now enforce declared requirements. Both local and device
registration check path scope before readiness; ingress admits Claude/OpenCode
contracts. 42 tests / 436 assertions / 11.15s pass, including unmet local/device
requirements refusing publication and recovery without extra native calls. Typecheck
passes. Full pinned Docker gate running as55688 at
/tmp/cm-opencode-completion-full.log; no live model input this increment.

Device coordinator adoption increment: optional coordinator-local SpecMesh profile
and shared local/device submit adopter implemented. Normal configured coordinator
reopen and HTTP queue projection preserve requirements without absolute source paths.
24 tests / 177 assertions / 14.31s pass (SpecMesh and device-control suites); typecheck
passes. This verifies contract distribution, not remote code revision equality or
real model execution. Prior full runtime gate 474 passed before this control-only
increment. Next: commit these control changes, then remaining provider completion
and multi-device content/revision gates.

Final explicit-adoption gate: pinned Bun 1.3.11 with verified Docker image and
independent SpecMesh checkout, 474 pass / 0 fail, 5,012 assertions in 189.16s
(`/tmp/cm-specmesh-adoption-full.log`, process15668 exit0). No real model input
was issued. This verifies the local adoption increment, not full migration.

Explicit local requirement adoption implemented: submit accepts the selected source
SHA-256, rereads/revalidates SpecMesh and persists the contract through TaskIngress.
10 paired tests pass / 44 assertions / 10.66s, including stale/conflicting sources,
idempotent retry and source-record injection refusal. Initial missing admission
callback and fixture scopes were corrected. Typecheck passed before the final
fixture correction; full pinned container gate follows. Packaging CI34679508577
is now success at 6fb218a; candidate CI34679687668 is still in progress.

2026-09-12 candidate transport verification: runtime suite 443 pass / 30 skip /
0 fail, 4,770 assertions, 52.20 seconds. Container image was not supplied, so this
run does not requalify container paths. Paired standalone tests and typecheck pass.
SpecMesh implementation pushed as d393c54 (57 standalone tests); both contract
mirrors match its source bytes. No automatic adoption or production cutover.

SpecMesh candidate integration: paired real Python/TS gate passes 9 tests / 37
assertions, including source mutation revocation and unrequested/unreferenced
candidate rejection. Initial new test literal widening failed TypeScript checking;
fixed explicit literal types. Adapter/schema changes remain pending broader
verification and independent SpecMesh documentation. Packaging correction pushed
as 6fb218a; remote CI must be checked at that SHA.

2026-09-12 update: main 7885871 passed the local 471-test runtime gate, but CI
34679141057 failed because bundled Web validators were stale after adding artifact
completion schemas. Rebuilt using pinned Bun 1.3.11; this corrects packaging only.
Independent SpecMesh requirement candidates and paired adapter verification remain
uncommitted work. Four real device attempts remain failed; full TS cutover and
release are not complete. The container-only status below is historical.

Current increment: **normal local Claude container dispatch and retained recovery**. Optional
trusted `claude.container` selects the concrete probe/control runners; host driver overrides are
refused. Image-owned Node no longer needs a host counterpart. Dispatch binds the runtime digest,
immutable retained helper and exact version/task execution IDs. Evidence checks both removed
supervisor records before publication. Recovery reads the original helper/result; it neither
rebuilds helpers nor starts Docker/model execution.

Normal startup tests cover two same-session Docker runs with one cached probe, changed current
files, unavailable-image refusal before task input, dropped observations, mutated image records
and idempotent recovery/publication. Final pinned full runtime gate **455/455**, zero failures,
4,832 assertions, 119.57s (`/tmp/cm-claude-container-queue-source-final.log`). Container/task focused
gate **20/20**, 150 assertions, 33.97s; turn/control/task gate **21/21**, 138 assertions, 10.98s
plus typecheck. The final source-reference stability check also passed **11/11**, 76 assertions,
3.61s and typecheck. Earlier full gates passed before the parallel/source-turn regressions.

One real CLI 2.1.263/MiniMax-M3 input used normal History refresh/search/adoption, normal queue,
isolated container readiness and independent SpecMesh checks. It recalled the original marker,
read seven current documents and wrote/read back the exact new current-file value. The initial
verifier wrongly compared reported num_turns=19 with max_turns=16. Original source/control show
13 model responses, 12 tool-use rounds and 18 tools (including nine rejected missing-hash writes).
Parallel content blocks share message IDs; reported num_turns is not the tool-round limit.
The corrected verifier checks actual model/tool rounds in both control and original JSONL.

The original failed attempt/report stays failed. Model-free recovery of that retained output
published the file; injected task.done loss, reopen and repeated acceptance then passed with
unchanged native bytes, container records and canonical inode. Independent verification accepted
all 18 matched receipts, one probe/one input, current SpecMesh reads, four absent container IDs
and no owned processes. Private evidence: coordinating workspace outputs/runtime-convergence/
claude-container-queue-{native,retained}-acceptance.{ts,json,log},
verify_claude_container_queue.ts and claude-container-queue-independent-verification.{json,log}.

Next: Claude DeviceWorker execution/adoption/publication/reconciliation using the existing device
ports, then remaining provider/transport/store/topology/product owners and CM-R7. Repeated semantic
tool failures still need no-progress detection; this trial did not fix that separate gap. Python
v0.43.0 remains production owner. No release/install/service/default switch. Predecessor
47f643ff72fb5898bccbd13725cf1df7b908bd9a has all required exact-SHA
[CI 34675060439](https://github.com/muqiao215/ControlMesh/actions/runs/34675060439) jobs successful.

## Previous concrete container qualification

Current increment: **concrete Claude container preflight and original-session execution**.
The pinned CLI and bundled control helper run through the existing ContainerProcessSupervisor.
Only the private native HOME/config are writable; the project, binaries/helper and task-specific
MCP directories are read-only. Existing host file capabilities stage changes and the current
kernel owner publishes them. The isolated readiness probe has a fresh private HOME, no native
session/project mount, fixed zero-tool command and the existing bounded readiness cache.

Real CLI 2.1.263/MiniMax-M3 acceptance resumed the previously owned original session, recalled
its original marker, read seven current continuity documents and wrote/read back the correct
marker plus a newly changed file fact. Neither fact was injected into the new prompt. Exactly
one model preflight and one task input ran. Ten native tools include one rejected write missing
expected_sha256 followed by a corrected write. The original source prefix remained unchanged.
Separate model-free verification matched all native calls to durable receipts, the confirmed
publication and canonical file, and verified all four owned container IDs absent and no owned
processes. Evidence: coordinating workspace outputs/runtime-convergence/
claude-container-{native-acceptance,independent-verification}.{json,log} and verifier source.

Validation: pinned full runtime gate **449/449**, zero failures, 4,784 assertions, 98.42s
(`/tmp/cm-claude-container-full.log`); focused container/preflight **13/13**, 110 assertions,
11.00s plus typecheck (`/tmp/cm-claude-container-final-focused.log`). Actual Docker tests cover
read-only project mounts, granted/denied MCP reads, owned-child cancellation/cleanup and isolated
readiness. Changed helpers, overlapping assets, arbitrary commands and environment expansion
reject before dispatch.

This qualifies the concrete runner, not normal local queue or DeviceWorker container admission.
Next wire the profile and runtime identity into normal configuration, dispatch/evidence/recovery
and the existing device ports. All remaining provider/transport/store/topology/product owners,
failed-effect abandonment and semantic no-progress detection remain open. CM-R7, installed Python
v0.43.0 and production writers/services/defaults remain unchanged. Predecessor
c364582a395f1454445316e78db429e85561e9a5 has successful exact-SHA
[CI 34673296092](https://github.com/muqiao215/ControlMesh/actions/runs/34673296092).

## Previous local History/Claude adoption increment

Current increment: **headless History/Claude adoption through the normal local task owner**.
Explicit refresh/search/prepare use the independent History CLI and the existing persistent
adoption registry. Preparation is context-only and cannot create tasks or probe a model; submit
resolves the task/device/workspace/model-bound handle through normal trusted ingress. Cache/source
overlap and symlink aliases reject before creating a derived cache; search never refreshes itself.

Actual original-session adoption now passes independent verification. One separately recorded
corrective native input resumed the same original JSONL after the earlier max-turns failure,
read seven current continuity references and the result, wrote the exact original-marker/current-
fact output, and finished in 10 native turns with nine tools. Neither marker nor new current fact
was present in the new task prompt. One preflight generation preceded that execution.
The verifier now recognizes the pinned max-turns stop and exact native synthetic resume pair;
failed historical turns remain failed, and incomplete/forged pairs or pending calls reject.

The new result was retained when unsupported synthetic padding initially blocked CM completion.
After the parser correction, zero-model reconciliation published that same retained output. An
injected loss of task.done then verified reopen/repeated acceptance with unchanged native bytes,
unchanged canonical inode and one confirmed effect. Independent read-only source/control/receipt/
database/file checks accepted the result and found no owned processes. The original failed reports
remain: the retained-acceptance script also hit a final diagnostic JSON-digest(Buffer) mistake
after all recovery assertions passed; the separate readback uses a byte SHA-256 and confirms state.

Final pinned runtime gate with Docker and independent SpecMesh: **443/443**, zero failures,
4,744 assertions, 87.69s (`/tmp/cm-claude-adoption-padding-final.log`). Chain tests **14/14**,
68 assertions, and typecheck passed after correcting a test-fixture TypeScript annotation.
Local History/max-turns focused gate was **17/17**, 98 assertions before synthetic-pair coverage.
Private evidence: `claude-history-adoption-{corrected,retained}-acceptance.{ts,json,log}`,
`verify_claude_history_adoption.ts`, `claude-history-adoption-independent-verification.{json,log}`.

Next: Claude container/device profiles and remaining provider/transport/store/topology/product
owners, then CM-R7 release and production cutover. Semantic no-progress detection and authoritative
failed-effect abandonment remain gaps; this increment does not close them or the full matrix.
Installed Python ControlMesh **v0.43.0** remains unchanged. Parser repair and recovery used no
additional native execution. No bot, cron, service, default or installation was introduced.
Predecessor 7d6e0a5ac33d00114a5ce94a31577ba87cc6f935
is pushed with successful exact-SHA [CI 34672709887](https://github.com/muqiao215/ControlMesh/actions/runs/34672709887).

## Previous Claude peer communication increment

Current increment: **Claude native peer communication through the normal local queue**. Optional
per-task communication registration binds the existing NativeAgentBroker/Journal to each Claude
effect. The native controller verifies two separate MCP servers and exact tool tables before
sending input. File capabilities stay separate from messaging; grants must authorize the message
tools, peer/parent identities come from registration, and task/tool inputs cannot choose a sender.
Original native calls must match every durable message receipt before atomic consumption/completion.
Explicit retained recovery uses the same journal verification and cannot send another message.

Actual CLI 2.1.263/MiniMax-M3: two separate sessions executed concurrently through normal local
configuration with independent SpecMesh checks and seven current documents required per task.
Only the parent prompt contained a random marker; child asked, received the answer, and sent an
acknowledgement containing that marker. Both tasks completed. Six real communication calls and
three consumed agent_message records match both original JSONLs and kernel receipts. The two
dispatches preceded either completion. One shared preflight and two native task inputs ran;
the model-free independent readback found no remaining owned processes. This trial is read-only
at the workspace layer; concurrent staged writes and external-device Claude are separate gates.

Validation: pinned full runtime gate with actual Docker/independent SpecMesh **435/435**, zero
failures, 4,671 assertions in 86.16 seconds. Focused control/task tests **20/20**, 134 assertions,
10.69 seconds plus typecheck. Tests cover missing/expanded MCP tables withholding input, peer
denial, distinct file/message request-ID ownership, question/answer, lost completion after
message receipt, idempotent recovery without execution, grant refusal and unobserved sends.
Logs `/tmp/cm-claude-peer-full.log` and `/tmp/cm-claude-peer-focused.log`; private actual evidence:
`claude-peer-native-acceptance.{ts,json,log}`, `verify_claude_peer.ts` and
`claude-peer-independent-verification.{json,log}` in the coordinating workspace.

Next: History candidate/adoption into the Claude task owner, then remaining container/device and
other-provider/transport/store/topology/product owners. All CM-R0–R7 requirements remain active;
no production writer, installation, service, bot, cron or default changed. Predecessor
20910913607a79811e3a6bd36fa0e5a657b78cea has successful exact-SHA
[CI 34670786335](https://github.com/muqiao215/ControlMesh/actions/runs/34670786335).

## Previous normal Claude queue and recovery increment

Current increment: **normal Claude task startup, original-session resume and retained recovery**.
`ClaudeTaskAdapter` uses the ordinary local queue/kernel, shared readiness cache, native session
lock, distinct Claude dispatch manifest, private fsynced original outcome, scoped workspace tools
and existing staged publication. `ClaudeTaskReconciler` reuses that evidence without a provider
runner. Local configuration explicitly selects registered Claude/OpenCode profiles; missing or
unqualified capabilities reject without fallback. Required-file budget rejects before preflight.

Actual CLI 2.1.263/MiniMax-M3 through `openLocalRuntime`/`LocalRuntimeControl` created one original
session and resumed it after reopening. The second prompt omitted the marker and recalled it
correctly; both turns consumed current SpecMesh references and published staged files. Original
JSONL bytes remained unchanged as a prefix. Recovery and repeat acceptance did not execute another
task input; repeat acceptance preserved native bytes and canonical inode. Two task inputs and two
readiness generations ran: repair outlasted the first ready TTL, so second admission renewed it.
Independent readback used zero native commands and found no owned process left running.

Keep acceptance boundaries explicit: the first native run was rejected by an overly linear parent
check when parallel tool results referenced their own calls. The verifier now accepts only exact
pending-tool edges with matching source owner; ordinary messages still extend the current tip,
and a new API message cannot advance while tools are pending. That retained result was recovered
without rerunning it. Its file lacked the requested newline; the resumed turn repaired both final
files, but prefixed the requested JSON with prose. **Scoped runtime-profile verification passed;
strict fixture-prompt acceptance remains failed.** SpecMesh structural checks are not semantic
task closeout. Original failed reports remain private and are not retroactively marked successful.

Validation: final pinned runtime gate with Docker and independent SpecMesh **431/431**, zero
failures, 4,624 assertions, 82.78 seconds. Focused chain/task suite **18/18**, 79 assertions and
typecheck passed; initial normal-adapter gate was 430/430 before the real parallel-chain fix.
Logs: `/tmp/cm-claude-normal-final.log`, `/tmp/cm-claude-parallel-focused.log`. Private evidence:
`claude-local-runtime-{acceptance,retained-acceptance,final-acceptance,independent-verification}`
and `verify_claude_local_runtime.ts` in the coordinating workspace. Raw input/state stays private.
Repository SpecMesh structural check passed seven references with only expected modified-fact
warnings (`/tmp/cm-claude-normal-specmesh.log`); semantic closeout remains pending.

Next: Claude peer-message capability integration, then remaining adoption/device/provider profiles
and all outstanding CM-R0–R7 owners. No production writer, service, release or installation changed.
Predecessor eda10daf0529a83b4a82c1002ee6637547a3a3f5 has successful exact-SHA
[CI 34668642661](https://github.com/muqiao215/ControlMesh/actions/runs/34668642661).

## Previous supervised Claude control increment

Current increment: **supervised Claude native control and actual resume**. The repository driver
now fixes command/environment/session identity, dynamically connects and verifies only the scoped
workspace MCP server, sends exactly one input, and retains owner-wrapped native evidence. Unknown
native permission requests, unexpected tools/model/session, partial or repeated results reject.
Complete pre-input aborts report input withheld; lost post-input output stays unknown.

Actual pinned CLI 2.1.263/MiniMax-M3 resume restored the controlled original session and used two
real tools to read current PROJECT.md and write the correct original-marker/current-content value
into the stage. The new prompt did not include the marker. Original JSONL prefix remained intact,
canonical output was absent, and independent source/control/tool/manifest readback passed with
zero new model commands and no remaining owned processes. One shared-cache preflight and one
resumed task input ran; no acceptance retry occurred. Normal task adapter/recovery is not yet wired.

Validation: final pinned runtime gate with Docker and independent SpecMesh **423/423**, zero
failures, 4,584 assertions, 81.03 seconds. Focused owned-process tests **9/9**, 54 assertions,
5.47 seconds and typecheck passed. SpecMesh structural check passed all seven references with
only expected uncommitted-task-fact warnings; semantic closeout remains pending. Logs
`/tmp/cm-claude-control-final.log` and `/tmp/cm-claude-control-targeted.log`.
Private evidence: `claude-control-resume-acceptance.{ts,json,log}`,
`claude-control-resume-independent-verification.{json,log}` and `verify_claude_control_resume.ts`
in the coordinating workspace. Raw source, prompts and runtime records remain private.

Next: actual Claude task admission, dispatch manifest, observation retention and model-free
task reconciliation through normal configuration. Keep the one-shot owner unchanged. All remaining
provider/transport/store/topology/product and CM-R7 release/cutover gates remain part of the full
goal. No production writer, service, release or installation changed. Workspace predecessor
7c522e2edc493c8ec4b2ae582de034525d16fcd7 has successful exact-SHA
[CI 34667679070](https://github.com/muqiao215/ControlMesh/actions/runs/34667679070).

## Previous scoped workspace file increment

Current increment: **CM-scoped native workspace file tools**. `NativeWorkspaceFiles` implements
explicit read scope, same-revision paged-read evidence, CAS writes/exact edits inside the existing
stage, durable pending/done receipts, idempotent reopen and inspection-only reconciliation.
`workspace.v1` uses the existing private MCP channel with three file tools and no peer messages.
The current task/effect/lease and grants remain the trusted enclosing caller's responsibility.

Actual isolated Claude Code 2.1.263/MiniMax-M3 execution used dynamic MCP registration, verified
the connected tool table before user input, and retained three native calls: read the required
current file, reject an ungranted file, write the correct staged output. Independent original
JSONL/receipt/manifest readback accepted all three and confirmed no canonical publication.
The later readback after the bounded-read optimization used zero model commands. The earlier
static-MCP model trial failed with zero actual tools; it remains recorded separately.

Current validation: pinned Bun 1.3.11 focused file/broker suite **14/14**, zero failures, 352
assertions in 1.92 seconds, and runtime-core typecheck passed. The full runtime-core gate with
actual Docker and independent SpecMesh passed **414/414**, zero failures, 4,530 assertions in
75.69 seconds. The repository SpecMesh structural check passed with seven references and only
the expected uncommitted-task-fact warnings; this is structural validation, not semantic closeout.
Logs: `/tmp/cm-workspace-files-targeted.log`, `/tmp/cm-workspace-files-full.log` and
`/tmp/cm-workspace-native-readback.log`. Private coordinating-workspace evidence includes
`claude-workspace-mcp-dynamic-run.json`, `claude-workspace-mcp-control-dynamic.json`, and
`claude-workspace-mcp-independent-verification.json`; no raw native state is committed.

Next: port the qualified control lifecycle into the supervised execution owner, then wire
normal Claude task startup, adoption/resume and retained-result reconciliation. This increment
does not close those gates. Installed production is still Python **v0.43.0**, verified locally;
no default, service, task writer or release switch occurred. The previous source increment
d86745c1c78b5ea735b60257479e98c262db4fb5 has exact-SHA successful
[CI 34665276826](https://github.com/muqiao215/ControlMesh/actions/runs/34665276826).
Full CM-R0–CM-R7 remains active.

## Previous Claude append verification increment

Current increment: **Claude original-transcript append verification**. `ClaudeSessionStore`
now captures an idle, byte-bound baseline and verifies exactly one appended input, the complete
parent/attachment/tool-result chain, selected model and final model-message output. Replaced
sources, changed old bytes, queued/unfinished input, duplicate identities, conflicting tools,
compaction and unqualified record types reject. This source verifier issues no tools or models.

Actual isolated CLI 2.1.263/MiniMax-M3 execution created a native session and resumed it in a
second process with exact random-marker recall. A third turn requested a current-file read:
the CLI reported success but made **zero Read calls** and guessed the wrong content. Acceptance
correctly rejected it. Independent model-free rechecking of the third turn proves the retained
baseline's source identity and old bytes are unchanged, and reproduces the rejection. It does
not establish current-file acceptance or CM worker recovery. Two seed/recall model commands
and one failed current-read command ran; no acceptance replay was used to manufacture a pass.

A separate owned two-file qualification found that native `dontAsk` plus a scoped Read allow
rule still read the ungranted file. Do not use those flags as a file-authority boundary. The next
implementation is the CM-controlled workspace tool path, then actual Claude worker/configuration,
staging and lost-result reconciliation. See `claude-continuity-design.md`.

Validation: pinned Bun 1.3.11 targeted Claude/native regression **28/28**, 157 assertions,
plus runtime-core typecheck. The full runtime-core gate with actual Docker and independent
SpecMesh passed **404/404**, zero failures, 4,220 assertions in 74.51 seconds. The repository
SpecMesh structural check passed with all seven task/core references and expected warnings
for the modified task facts; this is not semantic closeout. Full test log:
`/tmp/cm-claude-turn-full.log`. Private evidence in the coordinating workspace:
`claude-read-scope-acceptance.json`, `claude-persisted-turn-acceptance.json`,
`claude-persisted-read-{baseline,native}.json`, `claude-persisted-turn-independent-verification.json`.
No installed runtime/default was changed. Full CM-R0–CM-R7 remains active.

## Previous Claude readiness increment

Claude model preflight runs through the shared durable readiness budget.
Actual native Claude Code 2.1.263/MiniMax-M3 probe passed on 2026-09-12 00:58:59–00:59:01 UTC.
Two native commands (version plus print) included one model probe; a second ensure operation
reused the same generation-1 cache observation. Native init reported no tools, MCP servers or
plugins, and the terminal sentinel matched the assistant output and selected model/session.
Credentials came from the existing selected local profile, never repository files or task text.

Independent verification reread the retained native output with the final stricter observer,
checked the one-attempt local cache, and found no owned temporary process/directory or session
in the user's history. No second model call was used for this revalidation. Historical readiness
is not extended beyond normal expiry. Billing/API request counts were not measured. Evidence:
`outputs/runtime-convergence/claude-preflight-acceptance.{ts,json,log}` and
`claude-preflight-independent-verification.json` in the coordinating workspace.

Validation: pinned CI Bun 1.3.11 with actual Docker and independent SpecMesh passed
**394/394**, zero skipped/failed, 4,179 assertions, 74.64 seconds. Final policy-directory and
empty-plugin evidence checks are covered by focused Claude/native-event regression **13/13**
(97 assertions) and independent rejudging of the same retained native output; no model trial was repeated.
Typecheck and repository SpecMesh structural check pass (seven references, expected dirty
fact warnings). Published as b0bd743dce2bc550f9bf0198670bacf29010b620, with
[passing exact-SHA CI](https://github.com/muqiao215/ControlMesh/actions/runs/34663896019).

Claude source predecessors are published: CM fb69bddebabde0fcb0b45d2746a8c18cb0f06e50 with
[passing CI](https://github.com/muqiao215/ControlMesh/actions/runs/34663045103), History
61f57ad33ae985b44c050787553bef507575cc5e with
[passing CI](https://github.com/muqiao215/Codex-Claude-History-Viewer/actions/runs/34663036284).
The complete migration remains active and CM-R7 is not activated. Actual Claude native
execution/adoption, grants, retained-turn recovery and normal local/device integration remain
required, followed by other providers and the original transport/store/topology/product scope.

## Previous Claude native reference increment

The full goal remains active; current increment adds **Claude native source identity and
headless History revalidation**. ClaudeSessionStore hashes the complete original JSONL bytes,
binds the canonical local file/device/session/workspace and rejects partial, changed, foreign
or sidechain records. ClaudeHistoryClient independently revalidates the context-only candidate.
Existing one-shot Claude execution remains ephemeral; this source layer does not claim native
execution, preflight or retained-turn recovery. See claude-continuity-design.md for those gates.

Real existing-source inspection agreed with History's independent Python implementation in
197 ms; original bytes/mtime were unchanged and model calls were zero. Private evidence:
`outputs/runtime-convergence/claude-native-reference-readback.json` in the coordinating workspace.
Shared raw-byte fixtures include unknown fields and integers beyond JS precision. Typecheck,
focused native/History regression **39/39** (318 assertions) and History's full **201-test**
Python suite passed. The final change only escapes fixture paths for portability; source logic
and real-readback evidence are unchanged.

Scheduler predecessor `d93c052a94637da2b9d7c48e14de456c7a7ba0e8` is published with
[passing exact-SHA CI](https://github.com/muqiao215/ControlMesh/actions/runs/34662249501).
No installed runtime/default/service changed. Next: finish the actual Claude native execution
and readiness owner, then remaining providers and the original CM-R0–CM-R7 scope.

## Previous persistent scheduler increment

Full goal remains active. This increment implements **persistent device scheduling** through
normal headless startup; CM-R7 is unactivated and installed production remains Python 0.43.0.
Native adoption predecessor `c2f170519fea20286eaa1df5bc735772dbe9c1e7` is published with
[passing exact-SHA CI](https://github.com/muqiao215/ControlMesh/actions/runs/34659708183).

Candidate schema 15 persists explicit assignment generations, scheduler leases and work states.
Paginated discovery, bounded concurrency, elapsed-time ownership fencing, persisted pause,
typed preflight waiting and private readiness/retry controls share the normal worker admission.
Unknown attempts survive restart without model replay. See the package's `DEVICE-RUNTIME.md`
and [device-scheduling-design.md](device-scheduling-design.md).

Actual acceptance **2026-09-12 00:20:38–00:21:59 UTC** ran the normal daemon entrypoint on an
ARM64 coordinator and the x64 desktop worker. Automatic discovery launched two real OpenCode
1.18.29/M3 tasks concurrently, without explicit run commands. Native message exchange completed
in both directions. Losing one observation and reopening both ends did not repeat execution;
original-effect reconciliation used zero native calls. An explicit resumed assignment then
continued the original session and consumed changed current project facts. Pause survived a
worker restart. Three scheduled records completed, each at attempt 1.

Independent native SQLite/local journal readback confirms 11,366 ms of overlapping first turns,
two native sessions, three task turns, marker recall, actual native mailbox tools and five
required SpecMesh reads per turn. Two preflight entries remained generation 1; actual billing/API
request counts were not measured. All 15 recorded container IDs, the local worker process and
the temporary remote directory are absent. Remote terminal outcomes were captured through
verified control responses during the trial; its temporary database was removed during cleanup,
so no retained independent remote SQLite comparison is claimed.

Validation: pinned CI Bun 1.3.11, actual Docker and independent SpecMesh: **378 passed, 0 skipped,
0 failed**, 4,069 assertions, 74.62 seconds. Two later scheduler regressions cover removed-assignment
starvation and rejected competing-start persistence; final focused scheduler/control verification
passed **21/21**, 181 assertions. Source typecheck and Python protocol tests **9/9** passed after
those changes. Protocol outputs, ownership inventory and packaged Web assets are synchronized.
The independent repository SpecMesh check passed with seven references and expected warnings
for uncommitted project facts; it does not constitute reviewed semantic closeout.
Published at d93c052 with passing exact-SHA CI 34662249501; see Current above.

Private evidence in the coordinating workspace: `outputs/runtime-convergence/device-scheduler-acceptance.{ts,json,log}`,
`verify_device_scheduler.py`, and `device-scheduler-independent-verification.json`. No provider
credentials, native stores or private fleet inventory are published with the implementation.

Next: publish this accepted scheduler increment, then continue the remaining provider/transport/
store/topology/product and rollout owners in task_plan.md. This scoped acceptance does not close
all migration phases or activate the installed production writer.

## Previous native adoption and device startup increments

Full goal remains active, CM-R7 unactivated, and installed production remains Python 0.43.0.
Published predecessor `950f8aab5aa259c3edec4868600a5b411c9cafbf`; exact-SHA [CI passed](https://github.com/muqiao215/ControlMesh/actions/runs/34657572203).
The normal private device startup/control increment is committed and pushed.

Current increment: **device-local History search and explicit native adoption**.
The worker retains a native reference bound to the original device, principal, task,
workspace, capability and local profile. The coordinator receives an opaque context-only
handle; current task ingress issues source/grants independently. No Web process is needed.
Native model/directory/revision checks precede preflight, including after the asynchronous
mailbox wait. Completed turns use the existing device-session handle. Recovery retains the
original reference and verifies its appended turn without a model call. Candidate DB schema
14 adds only the local adoption registry.

Actual acceptance **2026-09-11 23:46:46–23:47:36 UTC** used the normal device entrypoint,
independent History CLI and real OpenCode 1.18.29/M3 in the qualified container. A raw native
CLI created the original session before either CM task database existed. History searched
and prepared it with zero provider checks or execution records. The adopted task recalled
a marker present only in the original conversation and read five current SpecMesh files.
An intentionally dropped observation was recovered after both processes reopened, without
another native command. A second task turn continued the same session and read changed
PROJECT facts. This adoption trial uses separate processes on one host; the earlier ARM64/x64
startup/write/communication trial remains separate evidence, not a new multi-host adoption claim.

Independent readback verified the three native user turns (one seed plus two task turns),
marker absence from both follow-up inputs, two sets of five native reads, unchanged original
message/part hashes, two completed worker records and two confirmed coordinator effects.
All nine owned containers and both exact configured runtime processes are absent. The worker
preflight cache is generation 1/ready; one model probe, one seed and two task turns were used.
Billing/API request counts remain unmeasured. No production writer or installation changed.
Private evidence: `outputs/runtime-convergence/device-adoption-acceptance.{ts,json,log}` and
`verify_device_adoption.py` / `device-adoption-independent-verification.json` in the shared
coordinating workspace. Publication and exact-SHA CI must be checked against this increment's commit.

Validation for this increment: pinned CI Bun 1.3.11, actual Docker and independent SpecMesh
configured: **361 passed, 0 skipped, 0 failed**, 3,911 assertions, 72.69 seconds. The initial
non-container run was 339 passed/22 environment skips; all skips are covered by the full
configured run. Typecheck, Python protocol tests (9 passed), regenerated schema/model
outputs, 512-module/57-field ownership inventory and pinned-Bun packaged Web build passed.
The repository SpecMesh structural check passed with seven references; expected dirty-fact
warnings reflect this uncommitted increment, not reviewed semantic closeout.

The coordinator owns task creation, assignment, result/effect inspection, cancellation,
revocation and reconciliation requests. The worker reads explicit local profiles and creates
a separate native Adapter/communication context for each authenticated task. Recovery
reconstructs the retained original job. Read-only startup/status/assignment inspection needs
no native credentials or model probe. Durable command reservations prevent cross-process
duplicate execution and old run IDs from executing a resumed revision. Shared stdio shutdown
interrupts owned execution before closing state. See `packages/controlmesh-runtime-core/DEVICE-RUNTIME.md`.

Actual acceptance **2026-09-11 23:07:49–23:10:22 UTC** used the normal entrypoint on ARM64
Rock 5C and the x64 desktop. Writer A edited the project and sent a native MCP handoff to B;
a deliberately lost observation left canonical files unchanged. Both processes reopened;
explicit original-proposal recovery published the retained modification with zero model
turns. B consumed A's actual message, edited current files and sent a causally linked handoff
back to A. A resumed its original native session and recalled its marker without reinjection.
Across the three turns the counter advanced 1 -> 2 -> 3 -> 4; each turn performed five
required continuity reads, two native edits and one write. Two sessions stayed task-bound.

Independent native SQLite, local journal and file-hash inspection confirms the three
proposals, two actual linked handoffs and current-file inheritance. Eighteen owned containers
and the exact temporary ARM64 process/directory were independently verified absent. The
three structural SpecMesh checks passed; reviewed semantic closeout is not claimed. Preflight
generations were A=2/B=1 (A's earlier readiness expired before its later turn); no expiry was
extended and provider billing/API request counts were not measured.

Local CI-Bun core tests: **330 passed / 17 Docker skips / 0 failed**, 3,735 assertions,
347 cases in 35 files, 34.81 seconds. Actual Docker: **25 passed / 0 failed**, 113 assertions,
37.38 seconds, covering those skips. A final slow-body configuration-revocation regression
was added afterward; its device suite passed **15/15**, including that new case. Typecheck,
protocol generation/drift, unchanged packaged dashboard and 512-module/57-field inventory
checks passed. Final control/device regression passed **22/22**, 135 assertions: the final
listener delegates to the existing coordinator listener and returns its typed configuration
error rather than a generic wrapper response. This does not change native execution; the
real model canary was not repeated for that listener consolidation. Independent repository
SpecMesh check passed with seven references and only expected uncommitted-fact warnings.
Private evidence is `outputs/runtime-convergence/device-startup-*` plus
`verify_device_startup_native.py` in the coordinating workspace.

Historical next-step statement superseded by Current above; both normal startup and native
adoption are now published with passing exact-SHA CI. Full migration remains open.

## Previous device-write increment

Full goal active: CM-R0 through CM-R6 remain in progress, CM-R7 is not activated. Python
v0.43.0 remains released/installed production. Local TaskHub write/recovery baseline
`e56d95b7f632c133ba380fa5ae91f94986bff784` has exact-SHA
[CI success](https://github.com/muqiao215/ControlMesh/actions/runs/34651878404).
Device-local staged writes and original-proposal recovery were pushed as
`80b330cc9cde5ab900650df0f127c06ab28c6b37`. Its
[CI run](https://github.com/muqiao215/ControlMesh/actions/runs/34654692522) passed both
Python suites, runtime/protocol/SDK tests, actual Docker and installed-wheel smoke. The two
product jobs failed their final generated-dashboard synchronization check: new device
protocol validators had not been rebuilt into the wheel's JS asset. The follow-up regenerates
that asset using CI Bun 1.3.11 from the Web package directory; its complete diff matches
the asset generated in CI. Local isolated-wheel smoke passed again, including installed
CLI/HTTP/SDK reads, artifact downloads and mutation rejection. Its repeated build leaves
the same asset bytes. Correction `9fa218c` subsequently passed exact-SHA CI 34655188758.

`OpenCodeDeviceAdapter` accepts trusted relative write roots and optional independent
SpecMesh. Actual native writes stay staged; full manifests/native/session/files remain on
the worker. Bounded wire references bind the write profile and workflow; completion and
reconciliation require a matching published-proposal proof. Before normal publication the
worker serializes a live coordinator renewal with its heartbeat. Before recovered publication
it re-fetches the same current challenge. Each local file operation also checks its monotonic
lease/challenge deadline and original local authority. Cancellation/revocation/partition at
refresh prevents publication. Changes already applied before later cancellation or lost
completion remain explicitly recoverable uncertainty; there is no distributed batch atomicity
or instantaneous remote revocation guarantee.

Real acceptance on **2026-09-11 22:24:41–22:26:21 UTC**: ARM64 Rock 5C coordinator and x64
OpenCode 1.18.29/M3 worker. The first task edited PROJECT/code and wrote a result in its stage;
an intentionally dropped observation left canonical counter 1 unchanged. After both runtime
and coordinator reconstruction, explicit recovery published that original proposal as counter
2, with zero native commands and an idempotent receipt. A second turn in the same native
session recalled the marker without reinjection, read current documents/code and changed
counter 2 -> 3. Every turn made five required continuity reads, two native edits and one write.
Independent native/device/file/Docker readback confirms two applied proposals, two completed
local records, two confirmed coordinator effects, one reconciliation and twelve containers
absent. Independent SSH inspection confirms the temporary ARM64 coordinator and directory gone.
Both post-publication SpecMesh checks passed structurally; semantic closeout is not claimed.

The successful attempt used one model preflight plus two task turns (nine native commands,
three model-run commands). An earlier fixture-layout failure used one additional preflight,
created zero native task records and changed no project files. Its staging location was an
ancestor of the project and correctly rejected. The location check is now also performed
before preflight in both local/device adapters. Its already-expired probe was not extended;
the successful attempt reused only unstarted local state. Both attempts remain recorded.
Provider API/billing request counts are not measured.

Final CI Bun 1.3.11 core regression: **322 passed / 17 Docker cases skipped / 0 failed**,
3,592 assertions, 339 cases in 34 files, 34.26 seconds. Focused layout/local/device tests
passed 18/18. Protocol Python tests passed 9/9; strict TS, generated-model Ruff and ownership
checks passed. The 512-module/57-field inventory changed only the generated protocol-model
hash. Final actual-Docker verification passed **25 tests / 113 assertions / 0 failures**
in 37.85 seconds and covered all 17 skipped cases; all 339 unique cases passed across
the bounded runs. A wire read-count extension
allows actual in-scope reads beyond the old 80-file fixed list; a test verifies 86 reads.
This numeric-bound extension followed the six-file real canary and did not rerun the model.

Private coordinating-workspace evidence:
`outputs/runtime-convergence/device-write-acceptance.{ts,json,log}`,
`device-write-coordinator.{ts,js}`, `verify_device_write_native.py`,
`device-write-independent-verification.json`, the preserved `.initial.{json,log}` attempt,
and `device-write-core-final.log` / `device-write-containers-final.log`.
No production writer/service/installation, real chat delivery, browser account or automation
was changed. Full remaining owners are still required by task_plan.md.

Next: expose device coordinator/worker execution, assignment and recovery through normal
private startup/control. Existing device scripts are synthetic canary entrypoints; a library
canary does not establish the installed multi-device workflow. Continue other provider/tool
profiles, transports, stores, topology, terminal, writer cutover and release/install gates.

## Done

- Independent SpecMesh candidate: descriptor/content/Git capability handshake, bounded
  supervised subprocesses, task-start before native preflight, trusted required-read
  coverage, content/HEAD/profile revocation, explicit handoff and unknown-closeout control
  operations. No implicit permission expansion or completion promotion. Native canary
  artifacts: `outputs/runtime-convergence/specmesh-native-acceptance.{ts,json,log}` and
  `specmesh-native-independent-verification.json` in the private coordinating workspace.

- Transactional TS kernel: task revisions, fenced episodes, immutable dispatch/observation
  evidence, idempotent receipts, cancellation, deadlines, unknown-outcome recovery and mailbox.
  Snapshot import/export preserves all 57 serialized TaskEntry fields and unknown fields;
  the complete Python source inventory tracks 512 modules. This inventory is not a claim
  that those owners have all been ported.
- Process ownership: guarded Linux process groups, independent process anchor, cancellation
  and lease expiry, including frozen-controller and partition tests. This provides lifecycle
  control; hostile-code isolation still needs the actual sandbox/provider launchers.
- Source/grant ports: trusted TaskIngress, immutable provenance and grant narrowing, reply
  identity, provider policy/mapping; 689 live Python/TS differential cases agree. Typed
  native quota/auth/model preflight is durable and bounded. Unknown/denied quota does not
  become repeated model calls or newly authorized human prompts.
- Native OpenCode 1.18.29 read profile: same-session continuation, native-reference v2,
  headless Viewer inspection with independent native revalidation, original file/permission/
  source evidence and explicit local reconciliation. Required current-turn native reads are
  verified; successful model output alone does not complete the task.
- Device coordinator/worker: credential and capability binding, logical workspace maps,
  durable revocation, fenced leases, explicit peer messages, device-local manifests and
  native handles. Actual x64/ARM64 runs cover claim/reclaim/partition and native continuation.
- New device recovery: schema 7 persists a trusted, expiring challenge. The configured
  adapter rereads original device/native/file evidence without any model, CLI or preflight
  invocation. Agent reports and recovery acceptance keep distinct provenance. Missing original
  observation, confirmed result, terminal task and receipt commit together; existing
  observations cannot be replaced. Receipt replay also updates the matching local record.
  Current cancellation, task/assignment/grant/configuration changes, device revocation,
  challenge expiry and invalid evidence prevent acceptance.
- One-shot execution: OpenCode/Claw use their own command builders; unsupported SDK engines
  return a typed error instead of silently running Claude. Grants are applied inside command
  construction after the provider verb. Native errors and missing completion cannot become
  success merely because a CLI exits zero. OpenCode stdin is literal and its trusted stderr
  quota record aborts retries with reset metadata preserved. Original exit/cancel causes hold.
  The TS host port uses actual process supervision and current source/grant/readiness/workspace
  checks; scheduler/native-adoption/container/delivery ownership is not implied.
- Container execution: a pinned image, nonroot process, read-only root, specific writable
  project mounts, explicit network, namespace/capability/resource restrictions and inspected
  identity precede launch. An inner PID 1 watcher expires a boot-bound lease independently of
  the host. Actual tests cover write/network boundaries, quota abort, detached descendants,
  concurrent cancellation, controller SIGKILL/SIGSTOP, lost create acknowledgement and cleanup.
  Versioned, durable intent/identity records prevent replay. Unconfirmed creation with no
  observed immutable ID remains unknown; absence cannot close a still-pending daemon request.
  Cleanup resolves only the original owned container and never starts it. The one-shot caller
  retains source/confirmation/native tool checks while outer isolation enforces network/roots.
- Container OpenCode read driver: narrowly selected persistent native data/cache, read-only
  auth overlay, temporary HOME/config and runtime-bound preflight/dispatch. A real Git project
  passed trusted TaskIngress -> model preflight -> native task -> coordinator/runner reopen ->
  same-session resume -> confirmed result. Headless Viewer independently revalidated the first
  native reference. The second turn recalled a marker without reinjection and read the changed
  PROJECT.md. Both episodes were done and both effects confirmed. The production writer and
  scheduler/transport startup were not switched.

Container native verification: strict TS and CI-version Bun 1.3.11 full core passed **140 tests /
2,019 assertions**, including actual directory/resource mounts and both original and new provider
binding checks. The subsequent worker suite passes **12 tests / 135 assertions**, including
host/container admission separation; strict TS and both Python CI-workflow tests also pass.
Real acceptance on **2026-09-11 13:21:49–13:22:35 UTC** used x64 OpenCode 1.18.29 with the
previously selected M3 provider, a pinned Node/Git image, one model probe and two task turns
(three model invocations total, nine native commands). The cache generation remained 1 after
reopening. All owner-labelled containers were independently absent afterward; the credential
file was unchanged. Private raw evidence, image recipe/digest and canary live outside Git in
the workspace's `outputs/runtime-convergence/container-native-*`. No transcript was copied
into the follow-up prompt, and no provider credentials entered the image or coordinator database.

Container local verification: strict TS and CI-version Bun 1.3.11 passed **132 core tests /
1,987 assertions**, including real Docker execution and the existing **410 live Python/TS
one-shot comparisons**. The container file has two planning/lease unit cases and seven cases
using the actual daemon; the native CLI in its quota case is a controlled fixture. Docker
29.1.3 on x64 Linux used the pinned Node 22 image recorded in findings. All actual containers
created by acceptance are removed. Unknown-create fixtures intentionally retain uncertainty
in their isolated test records and issue no provider call. Reboot protection is a boot-ID
fault/unit check, not a physical machine reboot acceptance. A new required CI container job
will run the actual daemon tests independently of optional local image availability.

Ruff, ownership check and whitespace checks passed. No Python source changed in the container
batch. Previous one-shot Mypy and full Python 3.11/3.12 suites passed at `0b01ea2` in CI.
No new real account/model calls, production scheduler runs, installation or default switch
were performed. Final exact-commit CI is verified after publication.

Initial container commit `6b6b221` passed its actual-container and product/build gates in CI
34600620577. Both Python versions had one failure / 5,732 passes because the workflow test
still required the old exact job set. The test now requires all mandatory gates, including
container execution, while permitting future additional gates. Follow-up `f9337d9` has
exact-SHA green CI 34601215864, freshly verified completed/success.

Container directory follow-up: an explicit native layout preserves original canonical project
paths without mounting their ancestors. The container plan, inspected Docker workdir and PID 1
agree before provider execution. Reserved runtime/control paths cannot be shadowed. Strict TS
passed; CI-version Bun 1.3.11 container suite passed **12 tests / 52 assertions**, including nine
real-daemon cases, in 19.21 seconds. The new cases verify a Unicode/space-containing native cwd,
nested write permissions, adjacent host-file exclusion and rejection of a changed Docker workdir
before launch. No model/auth probe or production runtime switch occurred in this follow-up.

Prior device-recovery verification included Python protocol **9 passed**, generated-model
Ruff and Web build. Canonical schemas and TS/Python/Web generated assets remain synchronized.
Tests cover lost original observation,
already delivered observation, recovery acknowledgement loss, reconstruction, cancellation,
expiry, revoked devices, changed files/native rows/configuration, conflicting evidence,
atomic rollback and additive schema-6-to-7 migration preserving device records.

Actual acceptance on **2026-09-11 11:20:38–11:21:58 UTC**: ARM64 Rock 5C coordinator and x64
OpenCode 1.18.29/M3 worker. After the first native answer was retained locally, the coordinator
stopped before receiving it. Coordinator process and local worker database reopened; lease
expiry left the task unknown. An explicit recovery request accepted the original result in
**130 ms with zero OpenCode commands/model calls**, then replayed the same receipt. The
original observation digest remained unchanged. A following episode resumed the same native
session, recalled the marker without reinjection and read the changed PROJECT.md. Two device
records completed, two coordinator effects confirmed, preflight generation stayed 1 and
source/grant/report/recovery provenance held. No provider credentials or native file paths
were copied to the coordinator. This is not evidence of an ARM64 provider executing natively.

The ephemeral device credential was revoked. Independent SSH inspection confirmed the
canary artifact directory absent and no matching coordinator process. Private evidence and
bundled-source hash are retained outside Git under the workspace's
`outputs/runtime-convergence/device-recovery-*`; the accepted implementation is the final
source used by that canary. History Viewer, SpecMesh and Ops repositories were unchanged.

Device recovery commit `e86604a543216be53424b74e2dfcf48f9881a53c` has exact-SHA green CI
34593893922. Local HEAD and origin/main matched after publication.
Earlier implementation history is in Git; it is not duplicated here.

## Remaining

All original CM-R0–CM-R7 gates remain authoritative: remaining provider/transport/workspace/
artifact owners, native provider write and other image/auth/state profiles, other persisted runtime stores,
writer exclusion and rollback, device-local History adoption, broader Agent/topology integration,
independent SpecMesh current-checkout/lifecycle gates, fleet enrollment/rotation/fairness and
real topology execution, terminal product work, default TS switch, Python retirement and
release/install/running alignment. A qualified native read profile and isolated process tests do not
establish complete production migration.

## Issues

No blocking condition. Never construct legacy TaskRegistry against live migration input:
its constructor performs orphan cleanup. Standalone native clients do not honor CM advisory
locks. Remote authentication attests the reporting device, not its honesty; native/file
verification describes the device snapshot checked before report delivery. The read profile
and task evidence do not automatically promote history into authoritative project truth.

## Local task execution entrypoint — 2026-09-11

Schema 8 adds durable local runs. `LocalTaskRuntime` binds queued work to the task revision
and trusted provider profile, persists claims atomically with execution episodes, shares
configured controller concurrency limits, and retains outcomes across restart. Its
OpenCode adapter uses one durable preflight and the qualified native container driver.
The private stdio entrypoint accepts bounded requests with explicit request IDs; metadata
does not call models and duplicate execution requests never redispatch. Cancellation,
controller stop and uncertain results retain the existing kernel reconciliation rules.
At this entrypoint milestone `tell` persisted a pending message only; the subsequent native
mailbox integration below adds verified delivery and recovery.

The first real adoption attempt passed preflight but was refused with
`native_worktree_changed`. OpenCode rewrites the shared `global` project row when its
no-Git probe runs; empty Git repositories use that same project ID. The worker had used
the probe's `/` as the adopted session's read-permission base. The attempt remains
unknown in its original private coordinator, all six containers were recorded removed,
and no resume/retry was issued against that uncertain task. The fix derives global
session worktrees from their bound directory, retains native worktrees for other projects,
and refuses broken Git discovery. The regression covers a changed/removed probe path,
nested empty-Git workspace, mismatched session directory and broken `.git` pointer.

Corrected real acceptance ran **2026-09-11 14:08:50–14:09:31 UTC** through the actual
stdio executable in separate processes. Headless History discovery/revalidation selected
an existing controlled OpenCode 1.18.29/M3 session. First execution recalled its earlier
marker and read the current project; after controller exit/restart, an explicit resume
recalled the same marker without reinjection and read the changed file. Both task episodes
and local runs completed. Inspection, submission and enqueue/replay made zero model calls;
one probe plus two turns made three model invocations/nine native commands. Preflight
generation remained 1. Replaying the first enqueue after restart added no native calls.
All nine owned containers were independently absent via Docker inspect.

Final local verification: strict TS and the 512-module/57-field ownership drift check
passed. CI Bun 1.3.11 ran **154 tests / 2081 assertions across 21 files, zero failures,
32.18 seconds**, including real Docker and process recovery. The four focused native/
local-entry suites passed **29 tests / 204 assertions**. An intermediate full run exposed
a test-only `/proc` cleanup race: it reread a process after already observing termination
and treated dead/empty state as live. The helper now recognizes terminal states and asserts
the completed poll without extending its deadline. Full verification passed after that fix.

Private logs and scripts remain in `outputs/runtime-convergence/local-runtime-*` in the
workspace, not this repository. Production Python, live tasks, service installation,
default writer and release version are unchanged. The failed attempt is retained separately
as `local-runtime-acceptance-before-worktree-fix.*`; successful acceptance does not erase it.

## Native mailbox delivery — 2026-09-11

Local OpenCode execution now includes an attributed, ordered mailbox prefix in its actual
native input. Schema 9 adds effect-bound message reservations. The worker records receipt
with the original dispatch manifest, then consumes only after independently verifying the
native user input and terminal reply. Consumption, effect confirmation and task completion
share one transaction. Native reconciliation uses the original batch after interruption;
generic acknowledgement cannot bypass it, and TTL expiry cannot cause uncertain delivery
to be replayed. A fitting prefix keeps message bytes/order intact; later and overflow
messages remain pending and their count appears in the result. Stdio has message/status
inspection. Native Agent-originating send/ask/answer and device delivery remain open.

Real acceptance **2026-09-11 14:33:59–14:34:50 UTC** used the actual stdio entrypoint,
headless History revalidation and existing OpenCode 1.18.29/M3 session. A message sent
after enqueue supplied a new token absent from the task prompt. CM verified its presence
in native input, the reply contained it, and the message became consumed. Duplicate send
returned the same ID. After actual controller exit/restart, the next turn recalled the
token from native history without redelivery and read the changed current file. Two runs
completed with one probe/two task turns (three model calls/nine native commands), readiness
generation 1 and zero extra replay calls. All nine containers were independently absent.
This real send used the configured human-request ingress; Agent provenance is covered by
directed tests; the subsequent native Agent-originating acceptance is recorded below.

Verification: strict TS and the unchanged 512-module/57-field ownership baseline passed.
CI Bun 1.3.11 full core passed **161 tests / 2144 assertions / 21 files / 32.97 seconds**,
including real containers, process ownership and schema upgrades. After strengthening the
delivery helper's live-lease and trusted-reconciliation guards, the three affected native/
mailbox/local-control suites passed **29 tests / 246 assertions / 2.32 seconds**. Coverage
includes ordered Agent-origin context, late messages, fitting prefixes, oversized first
message refusal, scope loss, atomic reservation rollback, lost completion/reopen after TTL,
receipt/payload/native-input alteration, idempotent recovery and schema-8 preservation.

Private evidence: workspace `outputs/runtime-convergence/native-mailbox-acceptance.*`.
The existing production service, provider account settings and live task writer were not
changed. The whole migration remains active.

## Native Agent communication — 2026-09-11

The qualified local OpenCode read owner now exposes an optional scoped MCP channel.
Private configuration binds task peers and parent; model arguments cannot supply an actor,
source origin, lease or new peer. A generated Node stdio client connects to one per-episode
Unix socket using a private capability file. Both host and container tests cover paths
longer than Linux's socket-path limit. The task channel is mounted read-only, and its
client/profile identity participates in readiness and dispatch binding. Preflight does
not enable communication tools.

Schema 10 persists logical calls before application and distinguishes unresolved calls
from completed duplicates. Current scopes and execution authority guard both fresh calls
and cached responses. Receive waits outside transactions; reserved messages cannot expire
into replay. The native driver closes admission, then matches actual OpenCode tool names,
arguments and outputs to all recorded calls. Input-batch and tool-received message
consumption precede effect/task completion in one transaction. Recovery checks the same
original records with no model invocation. Tests cover lost terminal commit, fabricated
native output, revoked scope, cancelled task, changed client, duplicate in-flight receive
and schema-9 reservation preservation.

Real acceptance **2026-09-11 15:30:48–15:31:29 UTC** used OpenCode 1.18.29/M3 and the
existing pinned native image. The parent resumed the controlled existing session; the child
was a distinct native Agent. All four tools appeared in five actual native tool records.
Three messages (tell, question, answer) retained `agent_message` origin and causal answer
identity and became consumed. The parent recalled an old marker absent from the new
prompts, while the child's new token reached the parent through actual tools. Both Agents
read the current project file and completed. Controller exit/reopen and replay of the
original enqueue produced no additional model call. Two per-task qualified profiles used
one preflight each and one task turn each: **four native model-run commands, thirteen native commands total**
including a separate model-free native MCP discovery. A native task command can make several
provider requests during its tool loop; these counts are not a provider billing/request audit.
Independent readback matched all
five native tool records and confirmed all thirteen immutable container IDs absent and
all per-episode capability/socket files removed.

Verification: strict TS passes. CI Bun 1.3.11 full core with actual Docker enabled passes
**175 tests / 2,269 assertions / 23 files / 35.12 seconds**, zero failures or skips. After
tightening channel-directory admission and synchronous authorization checks, the affected
broker/worker suites passed again; no extra paid native probe was needed. Raw scripts,
results and independent verification remain in private workspace
`outputs/runtime-convergence/native-agent-*`. An auxiliary Docker-absence check initially
matched a capitalized diagnostic; the real client uses lowercase. Correcting only that
case normalization confirmed removal without rerunning any provider execution.

## Next

Publish and verify the accepted device-write increment, then implement normal private
coordinator/worker startup and task assignment/recovery controls. Continue the remaining
provider/transport/store/topology/product/default/release/install owners; Python remains
production until the full cutover gates pass.

## Device-native communication — 2026-09-12

Implemented scoped native device calls, coordinator peer/parent projection, shared private
IPC with a remote backend, bounded native call receipts, and atomic completion/recovery
consumption using the original coordinator journal. Long receives permit independent
renewals and recheck revoked/stale authority. The device adapter qualifies preflight through
its actual runner. Initial device input-prefix batches and general fleet/provider rollout
remain open; this is not production cutover.

Checks so far: strict TS; 512-module/57-field ownership regeneration/check; Python protocol
9 passed; generated Python Ruff and Web build passed. CI Bun 1.3.11 full runtime with real
Docker passed 181 tests / 2393 assertions / 23 files / 36.38 seconds. A final focused pass
will include the default-preflight runner regression. New device/native tests use real HTTP
and Node stdio IPC with synthetic native records; they cover actual tool-parts matching,
lost completion/reopen, changed tool output, original session continuation, duplicate/lost
send receipts, receive/renewal concurrency, revocation and stale or forged authority.

Development corrections: the schema-writing helper initially had a Python brace typo
(no schema writes occurred); two commands used the wrong working directory and were
corrected. A Bun test assertion was attached before asynchronous revocation could run;
settling the promise into a value allowed the intended concurrent operation, and the test
passed. Generated model hashes required the expected ownership refresh. Real acceptance and its independent verification are recorded below.


Real OpenCode 1.18.29/M3 acceptance ran 2026-09-11 16:15:25–16:17:22 UTC
(2026-09-12 local time): ARM64 Rock 5C coordinator, x64 PC running two native Agents in
the pinned qualified container. The parent warmed an original session, then resumed it
while the child sent a fresh token and question. All four native tools occurred in six
verified calls. Both Agents read the changed project file; the parent recalled its marker
without prompt reinjection. The parent completion request was deliberately interrupted;
coordinator and local DB reopened, and explicit reconciliation consumed original received
messages without a new native command. Three effects and local records completed; all
three Agent-origin messages were consumed with question/answer causation intact.

Two model preflight commands plus three task commands produced fifteen native commands
and five native model-run commands. Each task can contain multiple provider requests;
provider billing/request counts were not measured. Both readiness generations remained 1.
The final statistics query mistakenly selected `provider_checks.status` instead of `state`.
That reporting failure occurred after completion/recovery; the raw failed result is retained.
A separate, model-free verifier reproduced the query error, reread actual native parts,
checked result/manifest hashes, session recall and coordinator outcomes, and passed.
It independently confirmed all fifteen container IDs absent, per-episode channels removed,
and the temporary remote directory/process absent. The explicit revoke step was not reached
because of that reporting error; the ephemeral coordinator, registration database and
endpoint were removed instead. The private script was corrected without rerunning Agents.

Private evidence: `outputs/runtime-convergence/device-agent-acceptance.{ts,json,log}` and
`device-agent-independent-verification.{ts,json}` in the shared task workspace. A final
fixture update initially omitted the report's runtime digest; adding the same explicit
fixture runtime identity corrected it, and focused verification passed. Production Python
0.43.0, live task ownership, services and installation remain unchanged. No release tag
or full-migration completion is claimed.

Final focused device-native verification (including runtime identity and exact completion
receipt replay): 23 passed / 319 assertions / 3.04 seconds. Strict TS, ownership drift and
whitespace checks passed after all source changes. Exact-SHA remote CI remains a separate
publication check.

Publication follow-up: 0645f9d was pushed, but exact-SHA CI 34621617071 failed two timing
checks while protocol/SDK/Web, package/install, Ruff, Mypy and Python 3.12 passed. The MCP
container fixture had a five-second total budget including Docker setup and both Node
processes, unlike the adjacent twenty-second container fixture. CI reported anchor_failed
without detailed outcome fields. Its test budget now matches the adjacent fixture and
failure assertions print the full outcome; runtime lease/enforcement deadlines are unchanged.
Using CI's pinned Node image locally: 16 tests / 69 assertions / 24.47 seconds passed.
The failed Python 3.11 test asserted completion after a fixed 200 ms, but the job was still
running. It now waits for observed completion with a bounded deadline. The adjacent running
restart fixture now waits for observed startup and drains its detached child, eliminating a
closed-event-loop warning. Host-job tests: 10 passed; Ruff and TS passed. New exact-SHA CI
must verify these test corrections; the earlier failed run is not treated as green.
That follow-up subsequently passed at ae9861152eadb4e0fae1b40054df5191ef2ff752,
CI 34622269044, as recorded in Current.

## Device initial input increment

The device reads its bounded ordered mailbox prefix before preflight. The full batch stays
in its local manifest; coordinator references and result proofs carry IDs/digest and the
actual native user-message ID. Dispatch atomically reserves the exact current prefix.
Completion/recovery consumes the initial batch before later MCP deliveries. Rejected
unstarted dispatch can release only through the coordinator's effect-free check and fence
advance; a committed dispatch with a lost response stays unknown. No storage version bump
is needed: existing reservation tables and the device ledger's text phase support this.

Verification: 192 core tests / 2,500 assertions / 37.28 seconds on CI Bun 1.3.11 with the
qualified Docker image. The 34 device tests cover bounded prefixes, later arrivals, combined
initial/MCP delivery, transaction rollback, changed input/proof/content, expiry during
preparation, lost dispatch acknowledgement and model-free recovery. A new test initially
expected an unavailable result for a retry of an uncertain task; the existing admission API
correctly rejects with task_not_admitted, and the test now asserts that contract.

Real acceptance ran 2026-09-11 16:53:49–16:55:12 UTC (September 12 locally), using an ARM64
coordinator and x64 OpenCode 1.18.29/M3 in the qualified container. A marker existed only in
the queued message, outside the task prompts. The first native input and answer verified it.
The completion request was deliberately withheld; coordinator/local database reopen and
explicit recovery consumed the original message without any new native command. A second
turn resumed the same session, recalled the marker, read the changed file and received no
duplicate batch. Both effects/local records completed; readiness stayed at generation 1.
One model preflight plus two task turns used nine native commands and three native model-run
commands; provider API/billing counts were not measured. The device credential was revoked.
Independent readback verified both actual native inputs/answers, prior-record hashes and
final coordinator state, and found all nine container IDs and temporary remote artifacts/
processes absent. No production installation, writer or service was changed.

Private evidence in the shared task workspace: outputs/runtime-convergence/device-mailbox-
acceptance.{ts,json,log} and device-mailbox-independent-verification.{ts,json}. An earlier
preparation-only attempt used the wrong send API shape and made zero native/model calls;
its raw report remains in its unique work directory. The readback script was corrected for
the marker label and for inspecting an earlier turn after a later turn exists; native
execution was not repeated for either readback correction. This closes the qualified device
initial-input acceptance, not the complete runtime migration or production cutover.

## Terminal transport delivery — schema 11

The outbox projects accepted terminal events with task revision/fence and original source
context separate from event origin. Explicit binding pins reply identity and selected adapter;
result text cannot redirect delivery. The bounded queue reserves one attempt before network
effects, retains original acknowledgements before acceptance and assigns a remote receipt once.
Missing acknowledgements and expired sends stay unknown. Retained acknowledgements can be
read back after restart without resending. Credential failure before dispatch requires explicit
retry. Missing adapters never broadcast to another channel. Private configuration/control wires
binding, drain, readback, revocation and separate delivery status without model injection.

The Feishu text port validates HTTP/API success and original app/chat/message/content using
the installed official Lark SDK shapes. Headers distinguish scheduled, heartbeat, Agent and
ordinary tasks. Acceptance uses real loopback HTTP and fixture credentials, including SIGKILL
after server receipt and before client acknowledgement. The child is reaped; repeated drain
after database reopen issues no second POST. A separate acceptance-transaction failure retains
the acknowledgement, then one GET accepts it; repeated reconciliation issues no extra request.
Changed remote identity/content, missing original receipt, stale routes, credential expiry,
queue capacity, four shared dispatch slots and concurrent senders are covered. Shutdown
aborts and drains in-flight HTTP before storage closes. Python's live generic summary fallback
agrees for all three terminal states. No provider/model commands or real chat notifications
were used. Rich-media/thread, token refresh, other transport/startup owners and production
release/install remain required for the full migration.

Upgrade fixtures now construct genuine pre-11 databases before reopening; retaining new tables
while changing user_version initially failed as expected. Core and focused logs are private
outputs/runtime-convergence/delivery-{core-final,focused}.log in the shared task workspace. Production
Python v0.43.0, live services and task writers remain unchanged.


## Selected-app credentials and verified replies

Private startup supports either an external tenant-token file or an explicit self-built app
credential file. The TS credential owner shares refresh within the runtime, validates TTL,
invalidates old credentials on rotation, latches auth rejection and bounds transient retries.
Its responses never enter task text or state. The delivery owner still requires explicit
binding and never replays an uncertain send. Startup-configured reply targets issue the
native thread grant; conflicting task metadata is rejected. Parent GET and reply POST use
the official API model, with parent/root/topic checks retained after restart.

Validation includes 20 concurrent token callers, isolated cancellation, credential rotation,
short/invalid expiry, auth rejection/backoff, existing-topic receipt reconciliation, file
permission/symlink/app mismatch, and the actual stdio child interrupted during HTTP. The
child exits 0, has empty stderr, returns a correlated interrupted command result, and leaves
one unknown delivery. All child handles and HTTP servers are closed. Local evidence:
outputs/runtime-convergence/feishu-auth-replies-core.log, feishu-auth-replies-focused.log,
feishu-stdio-focused.log. Full ingress, rich media, user/marketplace auth and production
transport qualification remain open, alongside the other migration owners.

## 2026-09-12 — Claude device adapter integration in progress

Confirmed published CM e9d73aae0e7d165fcead999a6f1329fd63bd1c90 CI
34676334207 completed successfully, including all required jobs. The current
uncommitted Claude device adapter now passes runtime-core typecheck after
converting the schema-validated network result to the Worker record shape.
Coordinator native evidence guards cover Claude as well as OpenCode. A new
HTTP regression test verifies both providers reject dispatch, observation and
completion without a retained manifest, leaving zero effects and no done task.
Pinned Bun focused device/device-native tests: 63 passed, 0 failed, 681 assertions
in 6.10s (/tmp/cm-claude-device-coordinator-tests.log). Typecheck exit 0
(/tmp/cm-claude-device-types.log). These checks do not qualify the new adapter.

Remaining immediate work: configured Claude worker startup and History catalog
wiring, concrete container adapter execution/recovery tests, then controlled real
device native continuation acceptance. No release, install or default switch.
Full CM-R0–R7 and cross-project delivery scope remains open.

### Device History control port

The worker control accepts provider-independent search/refresh/prepare/stop
methods, rather than an OpenCode-only adoption registry. Added explicit
history_refresh(workspace_id); both search and refresh enforce history:read at
the control boundary. No file path is accepted, query does not refresh, and
stopped controls refuse work. Focused control regression: 12 passed, 0 failed
(/tmp/cm-device-history-control.log); typecheck passed before the final scope
guard addition (/tmp/cm-device-history-types.log). This is control-layer
qualification only; Claude normal startup/catalog wiring remains pending.

### Configured Claude device entry point

Worker startup now accepts exactly one explicit opencode or claude profile.
Claude profile fields match the existing local runtime configuration, require
a container and use registered workspace read/write capabilities. The adapter
factory checks task provider/model and builds ClaudeDeviceAdapter with the
optional SpecMesh port and Claude History adoption registry. History uses its
independent headless catalog, worker-local cache and existing opaque adoption
records; no OpenCode database is instantiated for a Claude worker.

Typecheck passed (/tmp/cm-claude-device-config-types.log); configured control
tests: 13 pass, 0 fail, 124 assertions in 1.87s
(/tmp/cm-claude-device-config-tests.log). New test confirms Claude startup and
assignment inspection without native directories, probes, task rows or execution
records, and rejects ambiguous dual-provider configuration. This qualifies
startup inspection only. Container execution/reconciliation and actual configured
History adoption still require tests. Mixed-provider registration per worker is
not implemented; full migration/provider/topology scope remains open.

### Configured Claude device container continuation

Added test/claude-device.test.ts using the normal coordinator and worker startup,
real loopback HTTP and Docker, and the existing synthetic Claude JSONL/MCP
fixture compiled for image-owned Node. First attempt exposed relative registered
reads being passed to the literal absolute Claude file-grant API. Fixed worker
configuration to resolve read_files and required_reads against its registered
workspace. The completed test publishes once, closes/reopens the worker, resumes
and reassigns the task, reads changed PROJECT.md, and publishes a changed result
using the same original native session UUID. Exactly two task inputs are recorded.

Pinned image test: 1 pass, 0 fail, 13 assertions in 11.97s
(/tmp/cm-claude-device-test.log), handle34774 exit0. Typecheck exit0
(/tmp/cm-claude-device-final-types.log). This proves configured container fixture
continuation, not real-model acceptance, History adoption or interrupted recovery.
All current device edits remain uncommitted pending those additional gates.

### Claude device retained-observation recovery

Expanded the real Docker/HTTP configured test with an observation RPC failure
after the worker retains native completion. It exposed the coordinator
reconciliation request's OpenCode-only provider guard. Extended that guard to
Claude without changing the existing evidence/lease/task binding checks.

Both normal and interrupted cases pass: 2 tests, 0 failures, 34 assertions in
23.39s (/tmp/cm-claude-device-recovery-test.log), handle32986 exited0. The
interrupted task is unknown, canonical output absent, and reopening the worker
then explicitly reconciling publishes the retained result. Identical recovery
returns the same receipt, preserves file inode and native input bytes, and calls
neither Bun.build nor Bun.spawn. Subsequent task continuation retains the
original session UUID and consumes changed current context. Typecheck exit0
(/tmp/cm-claude-device-recovery-types.log). These remain synthetic provider
protocol tests over real Docker, not real-model or History adoption acceptance.

### Configured device History adoption fixture

The configured Docker test now also seeds an unmanaged native Claude JSONL,
uses a deterministic external History CLI to refresh/search/select it through
worker control, prepares an opaque adoption and reopens the worker before
execution. Query does not implicitly refresh; discovery/adoption leave native
bytes unchanged and produce no native task input. The actual container then
resumes exactly the selected UUID, and later continues it with changed context.
Three cases passed: 55 assertions, 35.40s; /tmp/cm-claude-device-adoption-test.log,
handle30083 exit0. Typecheck passed before final lookup signature refinement.

Removed implicit first-workspace selection from Claude source lookup: locating
a UUID only depends on the registered native config directory; adoption still
checks task/workspace/model/profile independently. Full pinned runtime-core gate
started as handle25331, /tmp/cm-claude-device-full-gate.log (pending at entry).
Real-model device qualification, real History service acceptance, communication
and current SpecMesh device profiles remain open. No release or cutover.

Full pinned runtime-core gate completed successfully: 462 pass, 0 fail,
4918 assertions across 47 files in 155.36s; handle25331 exit0. Includes the final
Claude source-lookup refinement and all three configured device container cases.
Evidence: /tmp/cm-claude-device-full-gate.log. Remaining live qualification and
full migration requirements above remain open; no release/default change.

### Real History and first real Claude device attempt

Actual History project CLI (isolated synthetic native data/cache) passed the
configured Docker adoption case: 1 pass, 21 assertions, 12.76s; handle10777
exit0, /tmp/cm-claude-device-real-history.log. Added optional CM_HISTORY_TEST_ROOT
to run that cross-project gate without changing real History files. Typecheck
passes. Production History retains only its three pre-existing untracked paths.

One guarded real MiniMax-M3/Claude2.1.263 device attempt was then run against the
owned original acceptance session, through real History and configured worker.
Handle27060 exited1; accepted=false. Original input marker was not reinjected.
Native tools read the seven current continuity files and proposed the correct
old marker/current fact, but every write omitted expected_sha256 and was refused.
Native result is error_max_turns (limit16), not a successful completion and not
proven quota exhaustion. Worker retained the result, coordinator is unknown,
recovery correctly refused provider_error, and canonical output was not created.
Container exit0/removal does not imply task success. Do not rerun the guarded
script or increase the limit to relabel the attempt.

Evidence remains private under outputs/runtime-convergence/claude-device-native-
acceptance.{ts,json,log}, guarded by claude-device-native-attempt.json. Next
investigate required write-argument representation/feedback and max-turn error
classification, preserve failed evidence, then design any explicit corrective
continuation separately. Full migration and real device qualification stay open.

### Native task-budget classification and write-tool guidance

The actual tool schema already required expected_sha256; missing schema delivery
is not established. Added a complete create-call JSON example to the write_file
description, explicitly requiring null rather than omission and preserving the
existing conditional-write validation. Its effect on real model behavior remains
unverified. No implicit precondition or retry was added.

Claude control now classifies error_max_turns as
claude_native_turn_limit_exceeded with no ProviderFailure, so a task budget does
not newly degrade provider health. Existing persisted degraded state is preserved.
Focused control tests: 12 pass, 69 assertions, 8.43s; handle49143 exit0,
/tmp/cm-claude-turn-budget-test.log; typecheck passed. Offline readback of the
original failed device outcome confirms this classification without native
execution (outputs/runtime-convergence/claude-device-failure-readback.{ts,json}).
Original acceptance stays failed. Broader tests for changed tool guidance and a
separate bounded corrective native continuation remain pending.

### Corrective live attempt and explicit missing-file precondition

Updated-description configured Docker tests passed all three paths with real
History: 55 assertions/35.69s, handle78267 exit0. Original failed native session
passed read-only baseline validation. A separately guarded corrective trial
(claude-device-corrected-native-acceptance.ts) used one input and the same16-turn
limit. Handle7585 exited1: error_max_turns; 15 write calls, zero containing
expected_sha256. Container removed, no canonical output. Error was correctly
classified claude_native_turn_limit_exceeded. Do not rerun either guarded attempt.
Description alone did not solve this real-model failure; null-argument handling
in the model/provider stack remains an inference, not an established cause.

Added an additive explicit expected_sha256 string value missing for write_file.
It means the target must not exist, exactly like existing null; omission still
rejects. Existing-file replacement requires the actual hash. Persisted receipts
retain original arguments, and idempotency identity is unchanged. Tool guidance
now demonstrates the string form. File tests: 12 pass/331 assertions/1.53s,
handle55835 exit0 (/tmp/cm-write-precondition-sentinel.log). Broader native
receipt/container tests and real efficacy of the string form remain pending.

### Missing-file sentinel native evidence compatibility

The container-native protocol fixture now uses expected_sha256:"missing" for
creation and the read hash for replacement. Local and configured device Docker
tests pass with the actual History backend enabled: 7 pass, 94 assertions,
55.45s (/tmp/cm-claude-missing-native-tests.log), handle40217 exit0. Covers
original-session continuation, lost-observation model-free reconciliation,
unmanaged adoption and missing-image fail-closed behavior.

Added receipt proof regression: exact missing arguments verify, but substituting
null only in the native evidence rejects workspace_tool_call_unproven. File
tests 12 pass/333 assertions/1.64s, handle88924 exit0
(/tmp/cm-missing-receipt-tests.log). Typecheck exit0
(/tmp/cm-missing-native-types.log). No real model invocation this turn. Both
prior real attempts remain failed; efficacy with MiniMax is still unverified.

### Sentinel live failure, outbound schema diagnostic and product acceptance gap

Third separately guarded trial (claude-device-sentinel-native-acceptance) exited1
(handle18085): 12 attempted writes still omitted expected_sha256. Native ended
with subtype success while explicitly saying it could not complete. Retained
reconciliation therefore marked the task done with changed_paths=[]; the outer
acceptance failed because device-sentinel-result.txt does not exist. This is NOT
successful real task acceptance. No fourth model attempt was made. All three
guarded reports remain failed and must not be rerun.

An actual Claude CLI diagnostic using a loopback mock Anthropic endpoint and
fake credentials captured outbound /v1/messages tools without contacting a real
model service. It showed the field and required list intact, including the former
[string,null] union. CLI schema deletion is not evidenced; the model's claim of
transport stripping is not authoritative. Changed advertised write precondition
to string with pattern ^(?:[a-f0-9]{64}|missing)$; server retains legacy null
compatibility. Repeated offline capture confirms the plain string schema and
required list reach the outgoing request. Evidence: private
claude-schema-diagnostic.{ts,json,log}. File/MCP tests12pass/334assertions/1.56s,
handle49192 exit0 (/tmp/cm-write-schema-string-tests.log). Live efficacy pending.

Additional required work: structured task/SpecMesh artifact acceptance. No
required output was declared in the existing task protocol; a successful native
conversation is not proof of fulfilling the user's requested artifact. Add
explicit verifiable output requirements rather than prose heuristics; preserve
the observed done-but-no-output discrepancy and outer failed acceptance.

### Plain-string live trial and offline argument round trip

Plain-string schema configured tests passed3/55assertions/35.38s (86838 exit0).
A fourth separately guarded real trial (claude-device-string-schema-native)
exited1, handle89451. Again12 writes omitted the field; native success with
no required output, outer file check failed. Container removed. All four
attempts remain failed; no more prompt/schema-only live trials are justified.

Offline actual CLI diagnostic now returns a synthetic Anthropic SSE tool_use
containing expected_sha256:"missing". The real Claude CLI forwards it intact
to the actual CM MCP client/broker as controlmesh_write_file. Backend records
arguments and deliberately performs no write. Local endpoint/fake credentials,
no real model request. Result: exactly one call with the expected precondition;
exit0, private claude-argument-diagnostic.{ts,json,log}. Together with outgoing
schema capture, this excludes field loss in the tested CM/CLI paths. Actual
model generation versus upstream gateway transformation is not yet isolated.

Documented versioned artifact completion contract requirements and acceptance
cases in claude-continuity-design.md. Implementation remains pending, including
identity binding and original-contract recovery; do not treat the design as a
completed fix or retrofit historical failed results into success.

### Artifact completion contract: initial local enforcement

Added task-completion.schema.json using the repository2020-12 schema dialect;
regenerated TypeScript/Python models and validators with generate:all-protocol.
completion_requirements is a bounded versioned list of relative file paths,
current-turn read/write modes and optional expected SHA256. Strict decode rejects
duplicates/traversal/.git; Claude registration checks file and tool grants before
execution. TaskIngress rejects declared contracts for unqualified providers.
Native task digest conditionally includes the contract, preserving old digest
bytes for undeclared tasks. Claude prompt includes declared conditions, and
normal/recovery evidence verifies current-turn receipts and staged hashes.

Device Claude explicitly rejects declared contracts until its result protocol
and coordinator verification are wired (device_completion_contract_not_qualified).
This temporary fail-closed boundary is incomplete work, not final device support.

Verification: focused file/digest14pass351assertions1.60s; actual Docker local
6pass49assertions35.71s (61051 exit0), including missing artifact and wrong hash
with native success: canonical publication refused, retained recovery also
refused, one native input each. Correct contract permits normal continuation.
Typecheck exit0. Logs /tmp/cm-completion-{focused-tests,container-tests,final-types}.log.
Full protocol/cross-provider/device gate and SpecMesh requirement transport remain
pending. No real model invoked and no old acceptance report altered.

### Device artifact completion contract enforcement

Added device-completion-proof schema and optional native-result completion proof;
regenerated both language models/validators. Device assignment now includes
completion_requirements in its portable execution payload/digest. Claude worker
returns the contract digest and ordered hashes after local receipt/content checks.
No private file paths enter the proof. Coordinator normal completion and retained
reconciliation validate presence, original requirements digest, count and any
expected hashes. Removed temporary device refusal only after wiring these paths.

Configured actual Docker+real History tests now declare completion contracts:
5pass87assertions50.82s (78394 exit0), including normal/original-session resume,
lost-observation recovery, adoption, missing output and wrong hash. Invalid
contracts cannot publish or recover as done and do not replay native input.
Device/OpenCode/proof regression65pass695assertions6.66s (12526 exit0); typecheck
passed. Python protocol suite exit0. Logs /tmp/cm-device-completion-{tests,
regression,final-types,python-protocol}.log. Proof tampering/missing/wrong hash
unit cases reject; requirements remain bound to original execution on recovery.

Full runtime gate, SpecMesh contract transport, other provider qualification and
real-model acceptance remain pending. Historical undeclared tasks and four failed
live reports are not retroactively changed; no model invocation this turn.

### Full candidate validation before publication

The complete pinned runtime gate passed471tests/5000assertions across48files
in185.17s; handle99877 exited0, /tmp/cm-device-completion-full.log. Initial
ownership check correctly detected regenerated protocol Python model changes;
regenerated python-ownership.json (only generated models.py source hash changed),
then reran the full gate. SpecMesh structural check passed against base
e9d73aae0e7d165fcead999a6f1329fd63bd1c90 with only expected dirty-plan warnings
(/tmp/cm-device-completion-specmesh.log). Earlier protocol9tests/typecheck pass.

This source increment implements candidate Claude device execution, History
control/adoption, retained reconciliation and explicit file completion contracts.
It is not a release/default cutover or successful real MiniMax task acceptance.
Four guarded real device attempts remain failed and are retained privately.
The independent SpecMesh acceptance.json currently contains assertions only;
it must not be silently reused as an executable task contract. Independent
requirement transport/review and remaining migration owners stay open.
