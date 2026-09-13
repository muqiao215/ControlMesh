# Runtime convergence progress

## Current

Gemini native stream/text-turn verification now joins process and retained-session evidence.
Stream deltas concatenate verbatim; init identity, one user input, matched tool results and
one final success event are required. Truncated/late/error streams are refused. A text turn
requires exited/0, matching session/model/prompt, unchanged native baseline and exact new
persisted user/assistant content. Tool-bearing turns require a future scoped receipt owner.
The one-shot observer routes explicit native init/delta streams to this verifier while
preserving legacy JSON/array behavior; two differential failures exposed those legacy
formats and were corrected without weakening the new persistent turn verifier.
Validation: 12 tests, 483 assertions (2.76s), including the live Python/TS one-shot matrix,
installed Gemini recording/formatting services and forged/missing result refusal.
Typecheck/diff-check passed. Evidence: /tmp/cm-gemini-turn-final.log.
The installed service test does not launch the Gemini CLI/model. Registered preflight,
process/grant enforcement, native model smoke and task/recovery integration remain work,
alongside all incomplete CM-R0–R7 rollout and release requirements.

Gemini CLI 0.59.0 is installed. Its bundled ChatRecordingService uses JSONL metadata,
message-ID replacements, $set metadata/full-message updates and $rewindTo records, rather
than treating every line as a new message. A strict GeminiSessionStore now replays those
records against the registered workspace hash, checks canonical bounded stable reads and
retains a byte/content baseline. Appended continuation refuses old-message rewrites,
rewinds/full replacement and changed original prefix, including edit-then-restore.
Validation: 3 tests, 18 assertions (659ms), including the actual installed recording
service producing message/token updates, continuation and rewind without any model call.
Typecheck/diff-check passed. Evidence: /tmp/cm-gemini-session-final.log.
This is an internal session owner, not a registered Provider or completed Gemini turn
verifier. Preflight, process supervision, native completion/recovery, History integration
and full CM-R0–R7 migration/release/default-switch gates remain open.
Previous b61c5ce and 279181a pushes succeeded after the earlier network resets.

Normal TopologyScheduler director_worker and debate_judge execution now has installed
Codex qualification. Three distinct native sessions run the two peer workers and controller.
The director dispatches registered roles and resumes its original session to complete;
the judge selects a registered winner. Frozen context supplies the exact round/role
contract, both workers exchange MCP messages, and two running tasks are observed.
Completed schedules drain again without new model requests.
Validation: 2 native modes, 113 assertions (85.49s), actual CLI + Viewer with synthetic
loopback model endpoint. Typecheck and diff-check passed. Evidence:
/tmp/cm-codex-control-native.log. These are local happy paths; repair/error branches,
physical devices and real-account coverage remain distinct, as do all open CM-R0–R7 gates.
GitHub API currently also fails with connection reset; previous 279181a remains locally
committed with its push unconfirmed. Native tests and this qualification are local progress.
Gemini executable is present at /home/muqiao/.local/bin/gemini, but no persistent Gemini
provider module was found under runtime-core/src/providers; registration remains work.

Installed Codex concurrent fanout is now qualified on the loopback model fixture.
Three distinct sessions represent alpha, beta and merger. Alpha/beta overlap (two running
local tasks observed) and exchange a native MCP question/answer. Alpha's lost observation
blocks whole-batch collection and does not start the merger. After reopen with auth removed,
retained reconciliation completes without new requests/messages; restoring fixture auth
allows the third session to consume both accepted summaries and finish the parent.
Final exchange + fanout matrix: 2 tests, 88 assertions (45.41s). Typecheck/diff-check passed.
Evidence: /tmp/cm-codex-peer-fanout-final.log. This is native CLI with synthetic loopback
Responses, not physical-device or real-account qualification. Rock 5C SSH again ended with
connection timeout/exit 255 to 100.103.100.10:22; no remote canary was started.
28a1f11 CI 34727900799 succeeded; 6a25b39 CI 34728114519 was in progress when observed.
Director/judge qualification, physical-device input/output, full TS parity and final
release/default-switch remain incomplete; the complete CM-R0–R7 objective stays active.

Codex topology participation now validates the frozen native assignment instead of
blanket rejection. An empty ordinary inbox no longer skips required topology input:
NativeMailboxDelivery prepares the coordinator schedule context and native receipts
consume it. Parent artifact acceptance verifies the Codex task_completion format.
Validation: installed Codex + Viewer + loopback model worker/write -> reviewer/read
pipeline 1 test, 50 assertions (18.12s). Reviewer adopts the updated same native session;
both schedule messages are consumed. After service reopen the parent verifies the actual
file receipt and completes without another model request or history change. This is
local sequential continuity, not two concurrent providers or physical-device topology.
Topology/artifacts/Codex regression: 85 pass, 2 environment skips, 786 assertions (13.41s).
Then artifact tests with real standalone SpecMesh: 18 pass, 68 assertions (5.98s), including
Codex missing-proof refusal. Typecheck/diff-check passed after correcting a test-only
optional-string assertion. Logs: /tmp/cm-codex-topology-native.log,
/tmp/cm-codex-topology-regression.log, /tmp/cm-codex-topology-artifacts-final.log.
Earlier commits 592f37e, 49dbf8b and de5accd CI succeeded; 28a1f11 CI 34727900799 was
in progress when observed. Other native topology modes, device/real-account qualification
and full migration/release/default switch remain open.

Codex now uses the independent SpecMesh lifecycle through normal local registration.
The start gate runs before provider readiness and requires all referenced continuity
files to be registered required reads. The workflow binding participates in the retained
configuration digest. Publication transitions to publication authority, checks the fresh
plugin snapshot before completion and retains status=pass/closeout_verified=false.
Recovery reserves retained work and runs the same configured check without native execution.
Validation: installed CLI + real Viewer + standalone SpecMesh + loopback model normal and
lost-observation publication 2 tests, 59 assertions (36.41s); blocked-publication recovery
and missing-start-document 2 tests, 46 assertions (22.70s). Startup rejection makes no
provider request; the publication rejection is an injected blocked result after a real
plugin check, and reopen recovery uses the real plugin. Shared SpecMesh/Codex regressions
24 tests, 151 assertions (18.78s); typecheck/diff-check passed.
Evidence: /tmp/cm-codex-specmesh-native.log, /tmp/cm-codex-specmesh-gates.log,
/tmp/cm-codex-specmesh-regression.log. Tests use fresh isolated native sessions and a
synthetic model endpoint. Reviewed closeout, topology, physical device/real-account
qualification and full CM-R0–R7 migration/release/default-switch gates remain incomplete.

Codex normal local configuration now registers staged writes through workspace.write_roots
and codex.node_executable. Write/edit MCP calls use the current lease transaction; native
shell remains read-only. The manifest binds stage/tool scope, observation precedes promotion,
and publication holds the native session lock. Recovery persists its reservation before
filesystem work and verifies/reuses the retained proposal with no new model call.
Read-only prompt composition is preserved for existing retained dispatches.
Validation: installed Codex + real Viewer + loopback model write/observation-loss/
postpublication-confirmation-loss/source-conflict matrix 4 tests, 92 assertions (62.67s).
The observation-loss injection occurs after native completion and proposal seal, before
recordEffectObservation; it is not a pre-native-dispatch failure. Conflict leaves concurrent
user bytes intact and refuses recovery. Codex local/workspace/communication/process/ingress
regression 24 tests, 172 assertions (5.56s); final typecheck and diff-check passed.
Evidence: /tmp/cm-codex-native-write-final.log, /tmp/cm-codex-write-regression.log.
No real account or existing session was used. SpecMesh lifecycle, native topology, physical
peer/real-account qualification and full CM-R0–R7 release/default-switch gates remain open.

Codex staged workspace verification now reuses NativeWorkspaceFiles and WorkspaceStage.
Controller-owned staged profiles can select read/write/edit MCP tools; default profiles
remain read-only. A focused test writes a private staged PROJECT.md, verifies the native
receipt/required write hash, promotes through WorkspaceStage, reopens and verifies the
same evidence without another write. Missing stage and unregistered tool scope are refused.
Validation: Codex workspace/communication 5 tests, 32 assertions; shared workspace files/
staging regression 32 tests, 432 assertions (2.77s). Typecheck and diff-check passed.
Evidence: /tmp/cm-codex-stage-foundation.log. This is the write-owner integration foundation,
not normal Codex task publication: adapter transaction/reconciliation, registered write
profile, installed native write fixture and SpecMesh closeout still need integration.

Codex controlled current-file reads are now qualified through a separately scoped MCP
server and the existing NativeWorkspaceFiles receipt owner. Native output must match
retained receipts, required current reads and read-only task completion contracts.
The channel requires the matching dispatched manifest; recovery verifies retained evidence
without a new model request. Unconfigured communication/workspace receipts are refused.
Validation: installed CLI + real Viewer + synthetic loopback read/recovery 2 tests,
43 assertions (27.41s); final combined file-read/communication test 1 test, 24 assertions
(13.93s); targeted workspace/communication/ingress/local configuration regression 27 tests,
451 assertions (4.76s). Final typecheck and diff-check passed.
Evidence: /tmp/cm-native-workspace-read-v2.log, /tmp/cm-native-workspace-scope-final.log,
/tmp/cm-codex-files-final.log. These isolated fixtures do not qualify real-account behavior.
Rock 5C SSH timed out; physical-device qualification remains unavailable. Codex writes,
publication, SpecMesh lifecycle, full provider/store/transport parity and release/default
switch are still open. Production remains Python CM 0.43.0; full CM-R0–R7 is incomplete.

Local dual-native Codex exchange is qualified against a loopback model fixture. Two
separately seeded native sessions run concurrently, ask/receive/answer through MCP and
consume the attributed messages. Alpha's lost observation reconciles after reopen with
no new model call/message. Exactly one shared provider probe is asserted. A startup race
was fixed: concurrent callers now wait boundedly for an existing in-flight preflight,
without acquiring another permit; cancellation/expiry do not cancel its owner.
Validation: complete native tool exchange/recovery 2 tests, 57 assertions (27.14s);
final dual-native test 1 test, 28 assertions (13.37s); shared preflight/three providers/
local Codex regression 37 tests, 243 assertions (3.70s). Typecheck and diff-check passed.
Logs: /tmp/cm-native-exchange.log, /tmp/cm-native-peer-final.log,
/tmp/cm-preflight-concurrency-regression.log. Physical device, live-account, file/workflow,
provider/store/transport parity and release/default-switch gates remain open.


Codex active communication now registers the existing broker and fixed peer scope through
normal local configuration. Native MCP receipts are matched to the durable call journal;
completion and retained-result recovery share journal verification/consumption. Installed
CLI + real Viewer + synthetic loopback Responses send/recovery: 2 tests, 41 assertions,
33.49s, exactly one attributed peer message and no recovery request. Broker/journal/Codex
regression: 24 tests, 190 assertions, 6.06s; final receipt refusal additions: 2 tests,
14 assertions. Typecheck/diff-check passed. Native ask/receive/answer exchange and device
qualification remain pending, along with the full migration and release gates.
Evidence logs: /tmp/cm-native-mcp-final.log and /tmp/cm-codex-active-regression.log.
Previous 9c99092 CI 34725610771 succeeded; 5d0dcae CI was running when checked.


Codex initial mailbox delivery is implemented with the existing reservation/consumption
and recovery transactions. Native user-message ID plus exact composed input establishes
delivery; changed mailbox content blocks recovery without consumption. Actual CLI +
Viewer Agent-origin delivery/recovery: 2 tests, 39 assertions, 25.16s. Targeted runtime,
mailbox and native regressions: 24 tests, 161 assertions, 5.32s; final added corruption
case: 4 tests, 37 assertions, 2.81s. Typecheck passed. No real model/account or old native
session was used. Active Codex messaging tools, topology/file contracts, physical device
acceptance and full migration/release remain pending.


Installed Codex phased commentary/final output now verifies without making a successful
turn stale. Exec JSON lacks phase, so every ordered message is compared to the persisted
turn before selecting its final answer. A native apply_patch attempt in the configured
read-only temporary workspace was rejected and created no file. This does not qualify
shell/network permissions or enable file completion profiles.
Validation: 18 targeted tests / 126 assertions (5.45s); installed CLI + real Viewer +
loopback Responses matrix 5 tests / 74 assertions (63.94s), including preflight quota,
ordinary continuation, result reconciliation, readonly patch and commentary across reopen.
Typecheck and diff-check passed. Evidence: /tmp/cm-native-turn-profiles.log. All fixtures
are isolated; no real account or existing session was used. Full CM-R0–R7 remains open.


Installed-native recovery qualification now also injects failure at CM's
recordEffectObservation after the real Codex result has been retained. On reopen,
reconciliation succeeds with the isolated auth file absent; repeating the same recovery
request leaves the native file byte-identical and produces zero additional HTTP requests.
A subsequent explicit resume retains the original context. Both normal/lost-observation
paths passed: 2 tests, 33 assertions, 24.64s; typecheck passed. This is a real CLI + real
Viewer with a synthetic loopback model service, not a mid-process kill or real-account
canary. Previous registration commit 4bb3e78 CI 34724757370 succeeded; structured-turn
commit 2c8cc1d CI 34725232567 was still running at this observation.


Installed Codex 0.154.0 + the real History Viewer now pass the isolated configured
adoption/reopen test: seed a native session, adopt through ordinary CM configuration,
continue, close/reopen CM, continue again with the same UUID and the original marker
present in both provider requests. The loopback Responses fixture supplies model output;
this proves native persistence/request continuity, not live-account or tool permission
acceptance. One native test / 15 assertions passed in 12.17s. The previous blocker was
structured `item_completed` UserMessage/AgentMessage records being ignored by the legacy
turn reader. Both formats are now supported with exact turn/content/end-event checks;
duplicate/mixed messages, foreign turns and non-text message parts refuse.
17 targeted regression tests / 118 assertions, typecheck and diff-check passed.
Full migration/release/default-switch and physical multi-device acceptance remain open.


Ordinary controlmesh.local_runtime.v1 configuration now registers Codex through
CodexRegistration, LocalCodexHistory, CodexTaskPreflight and CodexTaskAdapter. The
existing control commands can prepare adoption, submit, enqueue, inspect, resume and
reconcile. Source lookup is limited to the registered sessions tree (512 directories,
20,000 entries), requires an exact UUID and rejects duplicate matches; symlinks are
not candidates. Construction/status/adoption do not probe a model. Recovery uses
retained evidence and succeeds with the auth file removed, without another probe.
31 local/CLI tests / 249 assertions and typecheck passed
(/tmp/cm-codex-registration-final.log). Four configured-flow tests also passed with
the actual Viewer headless CLI (29 assertions, /tmp/cm-codex-registration-viewer.log).
Codex model execution used supervised synthetic executables; real-account continuation
and native sandbox qualification remain unproven by this increment.
The registered profile currently supports adopted read-only sessions. Fresh sessions,
file receipts, required reads, SpecMesh completion contracts, mailbox/topology and
write profiles still require implementation; unsupported configured contracts refuse
before preflight rather than silently dropping requirements. Full migration/release
and production default switch remain incomplete. Prior bb9bacb CI 34724233626 passed.

Codex History adoption now reuses DeviceNativeAdoptions and the existing opaque-handle
schema/table. LocalCodexHistory connects registered source lookup, the shared bounded
JSONL catalog and CodexHistoryClient; CM independently validates Viewer candidates and
requires a completed native baseline before retaining an adoption. Handles remain bound
to principal/device/task/workspace/model/profile and survive DB reopen. Resolve retains
the original reference for recovery; execution separately rejects a changed revision.
27 tests / 213 assertions and typecheck passed (/tmp/cm-codex-adoption-final.log), including
an actual headless Viewer subprocess with synthetic Codex records and unchanged source
bytes. Claude/OpenCode adoption regressions passed. No native model was invoked.
The ordinary configuration and bounded source lookup are now connected as described
above; full native continuation and remaining capability profiles are still open.
Previous commits a253cfe and History 9ea53f1 have successful CI runs 34723955246 and
34723955816 respectively. This increment does not change production defaults or releases.

Permissions restored: the prepared provider-alignment patch is now applied to the
main checkout. Codex probe and resume share codexProviderArguments; OPENAI_BASE_URL
selects the same explicit native provider parameters before any process dispatch.
17 affected tests / 122 assertions and runtime typecheck passed in the authoritative
checkout (/tmp/cm-restored-endpoint.log). The earlier supervised handshake failures
no longer reproduce after permission restoration. Installed Codex 0.154.0 with the
loopback synthetic Responses service passed ready/quota cases, seven assertions
(/tmp/cm-restored-native.log). No real account/model acceptance is inferred.
Viewer's new Codex native-reference matches the current TS reader; ordinary CM Codex
registration/adoption and full CM-R0–R7 remain pending. Production has not switched.

CodexPreflight now uses the installed 0.154.0 native interface with isolated state,
explicit authentication snapshots, ephemeral sessions, selected model and a bounded
request. ProviderPreflightService.ensureCodex shares durable permits/cache/retry budget.
CodexTaskPreflight binds credentials and executable identity, rechecks readiness at
admission and captures an execution-specific generation for later failure revocation.
CodexTaskAdapter retains process output before revoking the matching cached readiness;
recovery remains model-free. Queue tests now use this owner instead of fabricated ready
responses and prove one probe across two turns and a database reopen.

ProcessSupervisor accepts stdout-line abort detection as well as stderr; container
forwarding, one-shot Codex and exact resume use it. Native quota/error records stop the
owned CLI before a later internal retry. Arbitrary prose and tool text do not qualify.
47 focused tests / 689 assertions / 6.47s passed; typecheck/diff-check passed
(/tmp/cm-codex-preflight-final.log). Two real Docker one-shot tests passed, six assertions
(/tmp/cm-codex-preflight-container.log). Installed native Codex against a synthetic
loopback Responses endpoint passed ready + quota cases, one request each (seven assertions,
/tmp/cm-codex-preflight-native-test.log); this is real CLI protocol evidence, not a real
model/account quota or native memory acceptance. The opt-in test is committed.

Native built-ins remain advertised; tool_count is null because CLI JSONL does not attest
the advertised count. No claim of a zero-tool native profile or general sandbox
qualification. The npm launcher requires a Node path absent in the restricted environment;
registration must resolve/qualify the installed native binary. OPENAI_BASE_URL is mapped
into an explicit native provider; the initial env-only experiment failed authentication
without reaching loopback. No user's authentication was used in these protocol tests.
Normal configuration/History registration, effective task/probe profile equivalence and
real-account readiness/native sandbox qualification remain pending. Production stays
Python CM 0.43.0; no release, live migration or default switch occurred.

Codex typed error parsing now preserves quota/auth/model/rate-limit outcomes in the
normal one-shot process status, including nonzero CLI exit. Only native error and
turn.failed records supply these facts; assistant/tool prose cannot. Quota reset
authority requires an explicitly zoned timestamp. 16 targeted tests / 507 assertions
and runtime typecheck passed (/tmp/cm-codex-failure-test.log), including the existing
410-case Python parity fixture and supervised synthetic Codex processes. No real
model probe ran. Actual Codex preflight driver/cache wiring and normal task-entry
registration remain next; this change alone does not implement quota retry policy.

Full CM-R0–CM-R7 remains in progress. Installed CM 0.43.0 is still the production Python
writer. No release, installation, live migration or default/service switch has occurred.
The 512-module/57-field ledger is an inventory, not completed parity.

| Delivery area | Verified state | Remaining acceptance |
|---|---|---|
| Published CI baseline | 7c4fedd; CI 34717999450 success | Codex preflight/queue integration pending publication/CI |
| TS runtime | Kernel, local/device execution, mailbox, topology and retained recovery; reconnectable local service/CLI with full local regression | Final CI; remaining provider/transport/store/terminal ownership and parity |
| Native continuation | Simple direct and streamed exact recall passed; earlier topology first runs and current artifacts passed | Full worker/merger continuation and complex-context acceptance still fail |
| Multi-device | Configured initial input HTTP transfer, topology source capture and pre-dispatch receiver; artifact transport/publication | Physical transfer and full native profiles |
| SpecMesh/History | Independent integration and scoped continuity evidence exist | Reviewed closeout and remaining full integration acceptance |
| Release/local alignment | Production still Python 0.43.0 | Full-goal acceptance, release/install, staged default switch |

Latest real attempt structured-topology-resume-native-acceptance-20260912 finished with
accepted=false after its first worker, zero successful required reads and no continuation.
Native read calls sent expected_sha256="missing" for existing files. The retained evidence
shows invalid read arguments, not a proven concurrent file change. The attempt and session
05a0e591-a529-4401-b28a-932b3e948f95 are guarded against replay. No new native model canary
was launched during this correction.

CodexTaskAdapter now implements LocalTaskExecution for explicitly trusted adopted sessions.
It reuses kernel start/dispatch/observation/confirm/finish and execution_manifests rather
than introducing a parallel task store. The manifest binds task/configuration digests and
native baseline; environment values are not persisted in it. Private output records use
exclusive creation, fsync and directory identity, and survive a missing database observation.
Recovery acquires the native advisory lease, revalidates retained evidence and reconciles
through the existing kernel without readiness probing or another native process. Repeated
recovery uses the original command receipt. A later explicit resume takes the newly
confirmed session reference from the kernel's result.

18 queue/process/session tests passed, 100 assertions, 2.97s
(/tmp/cm-codex-task-final.log); typecheck and diff-check passed. Tests use a supervised
synthetic native executable and real private files/database; no model call occurred.
TaskIngress correctly refused authority supplied in a task body, so fixture registration
uses trusted kernel issuance; public ingress was not weakened. Normal configuration and
History authorization are not yet wired. Pending mailbox, topology assignments and file
completion contracts refuse in this partial adapter rather than silently dropping input
or asserting receipt-less success. Fresh-session and interrupted-lineage support, actual
provider readiness and native sandbox qualification remain required.

7338c3c CI 34717037974 and 7c96b76 CI 34716653749 passed. Earlier documentation-only
2ff693e CI 34716372099 failed its container job with container_engine_unavailable;
subsequent complete gates passed. This does not establish physical device availability.

Codex exact-session process owner now reuses ProcessSupervisor and NativeSessionLease.
It validates native source, current readiness/authority and execution policy before task
input; host-ineligible origins and unsupported grants refuse. The pinned 0.154.0 version
is checked without a model request. Parent exec carries sandbox/config flags; resume uses
an exact UUID and stdin, never --last. Input/baseline retention must finish synchronously
before dispatch; all owned outcomes are retained before semantic verification. Executable,
workspace and store identity changes stop admission. verifyRetainedCodexResume rechecks
original dispatch/output/transcript without a process or model call.

8 process/session tests passed (48 assertions, /tmp/cm-codex-resume-final.log), typecheck
and diff-check passed. The actual installed CLI accepted the parent-sandbox/resume help
combination; this is argument compatibility, not live sandbox enforcement or native memory
acceptance. The supervised subprocess/transcript used isolated synthetic fixtures. Normal
local runtime registration, durable task-journal wiring, preflight ownership, fresh-session
creation, effective native sandbox qualification and History candidates remain pending.
No provider was added to the normal entrypoint by these private process primitives.

Codex native continuity owner is in progress. Local CLI help reports 0.154.0 and explicit
UUID resume support; inspected local rollout structure includes session_meta, task_started,
turn_context, user_message, final agent_message and task_complete. No native/model command
was dispatched. A new private CodexSessionStore reads bounded descriptor-checked rollout
bytes, binds identity/content revisions and verifies one exact appended completed turn.
It rejects rewritten prefix, inode/device/workspace changes, repeated turn IDs, partial
output and mismatched prompt/model/result. It is not yet a registered task adapter or
History candidate port. Interrupted/compacted history qualification remains pending;
unsupported lineage currently refuses rather than implying safe execution.

Session regression: 10 tests / 57 assertions / 92ms including existing Claude checks
(/tmp/cm-codex-session-final.log), typecheck passed. Synthetic Codex fixtures do not prove
live continuation. The earlier topology source commit a54007d passed CI 34716213071.

Physical acceptance readiness was checked after a54007d. The previously qualified ARM64
peer is offline in the local VPN inventory and bounded SSH exited 255 with connection
timeout. No remote files/processes were created, no previous task/session was resumed,
and no model request was made. Physical delivery remains unaccepted pending device
availability. Continue the remaining provider/runtime ownership migration locally;
this external dependency does not block all CM-R0–CM-R7 work.

Current topology checkpoint adds source_files to frozen device routes. Enqueue captures
source bytes and issues the assignment in one transaction; retry/restart keeps the original
reference. Missing source and forced assignment failure block without queued work or
retained snapshot rows. Changed route policy is refused on restart.

Final topology/control/worker regression: 88 tests / 808 assertions / 14.35s
(/tmp/cm-topology-seed-final.log), typecheck and diff-check passed. Real Docker integration
with a synthetic Claude process/transcript passed both artifact modes: 2 tests / 106
assertions / 46.39s (/tmp/cm-topology-seed-container.log). In publish_received mode, only
the coordinator initially has PROJECT.md; source_files/bootstrap_files deliver it before
container execution, followed by result publication and original-session fixture resume.
This does not prove physical-host delivery or real-model context continuation.

Current work connects initial inputs to configured device execution. Local
prepare_workspace_seed returns a durable reference scoped to the task's source workspace;
assign freezes that reference. Worker bootstrap_files grants are separate from native
write grants. Leased HTTP chunk reads feed a durable receiver before any execution dispatch.
A controlled link interruption retained 32768 bytes, executed nothing, then resumed at
that offset and executed once after verified publication. Existing local conflicts and
ungranted input paths block without dispatch. No real model/device canary was launched.

Final corrected regression: 113 tests passed / 1156 assertions, with one external SpecMesh
gate initially skipped (/tmp/cm-seed-final-regression.log). That exact gate was then run
with the independent project configured and passed 1 test / 10 assertions
(/tmp/cm-seed-specmesh-final.log). Typecheck, Web build, 9 Python protocol tests and
diff-check passed. Two concurrent 1 MiB transfers use one-second leases, prove actual
renewals and complete after sharing the device request budget.

The full runtime process completed 832 pass / 1 fail / 10511 assertions in 382.56s
(/tmp/cm-runtime-seed-wire-full.log). It loaded the earlier worker implementation and
reproduced the start/renew race subsequently fixed and covered by the final regression.
Do not call that initial full run green. Exact committed 984b873 CI 34715947420 completed
success and establishes the complete post-fix gate.

The published f1832aa checkpoint adds a persistent local service and normal `pnpm runtime` command entry.
It reuses LocalTaskRuntime, task/event read authority and the existing native queue; clients
reconnect over a private Unix socket. OS-held listener locking precedes profile startup.
Client timeout never retries/cancels execution; another connection can cancel in-flight work.
CLI SIGKILL/restart, original task/cancellation retention and normal shutdown passed (four
CLI tests / 39 assertions / 5.85s). Socket cases passed for pages, concurrency, lock/path
protection, frame bounds and Chinese input. A configured Docker case passed one test /
161 assertions / 16.37s: automatic execution after client disconnect, service restart and
same-native-session continuation with changed current files. Claude is synthetic in that
case; it is not new model or physical-device acceptance. Typecheck passed. Full regression
passed 803 tests / 10317 assertions / 75 files / 447.07s, exit 0, at
/tmp/cm-runtime-service-full.log. Normal `pnpm runtime --help` also passed. Commit f1832aa
passed CI 34711514218. This changes no database or public protocol schema. Service usage and
limits: [local-control-service.md](local-control-service.md). No production service was changed.

The published e2b16e3 checkpoint connects accepted inbox bytes to optional canonical publication.
Database 28 and a sparse WorkspaceStage capture write-file baselines before child dispatch,
preserve unrelated local edits, reject conflicting changes and recover per-file progress.
All writes check scheduler authority. Independent SpecMesh checks bracket publication.
Focused tests passed: 19 stage tests / 82 assertions and 21 expanded HTTP/native-fixture
integration tests / 264 assertions / 57.43s. Configured Docker, restart, pause and independent
SpecMesh cases passed; typecheck passed. Log: /tmp/cm-canonical-configured.log.
Full regression: 789 passed / one test-double timeout / 790 cases / 10075 assertions /
73 files / 364.85s, exit 1 (/tmp/cm-canonical-full.log). The old preparation double omitted
the new step method; its correction and early-exit reporting passed the full scheduler file:
62 tests / 669 assertions / 25.88s (/tmp/cm-canonical-scheduler.log). Typecheck passed after
the correction. Production code was unchanged; final exact-commit CI 34709699732 passed.
The separate local runs were not represented as one green full run. No model input launched.

The preceding checkpoint implements opt-in native completion-file upload over the authenticated
worker port. Database 27 stores bounded chunks; terminal acceptance independently verifies
full bytes against the original completion evidence. Normal worker execution and explicit
retained-result recovery use the same receipts. Local read_artifact provides current accepted
bytes by task/effect/path. It does not overwrite canonical project files or copy native stores.

Focused checks passed: 94 tests / 975 assertions / four files; additional authority/budget/
upgrade checks: 8 tests / 31 assertions. Typecheck and nine Python protocol tests passed;
generated protocol models and bundled Web assets were rebuilt. Full runtime regression passed:
774 tests / 9918 assertions / 73 files / 323.71s, exit 0 (/tmp/cm-device-artifacts-full.log). Initial setup failures were an old-schema fixture
retaining the new table and the generated Python ownership hash needing regeneration.
Neither required weakening runtime checks. Controlled HTTP/native fixtures are not new
physical-host or model acceptance. No new model input was launched this turn.

Previously published native retry/read-guidance fixes passed 760 tests and exact-commit CI.

Remote release metadata and the installed Python environment were checked: CM v0.43.0
and local 0.43.0; History Viewer latest release v1.1.0, checkout 8070b9c (four later
commits); SpecMesh latest release v1.2.1, checkout d393c54 (two later commits). These
other checkouts were not modified; their latest source is not wholly in those releases.

Earlier complex-context diagnostics proved the old marker was present in actual upstream
continuation requests but did not establish successful model recall. Their observer errors
and the latest invalid read request must not be conflated with missing native history.
Detailed evidence and guarded attempts are in findings.md; no failed result was relabeled.

## Done

- Real retained reviewer recovery: failed, no reconciliation needed, seven missing reads,
  original session and native/project bytes preserved, context consumed. Duplicate acceptance
  emitted no events. Zero model/broker/build calls; one local flock helper. The original
  topology canary remains failed and no native prompt was replayed.

- Local/device topology dispatch supports four root kinds and sixteen nested pairs, frozen
  plans/routes, bounded recovery, source-bound results and persisted global admission caps.
- New dispatch snapshots include role, stage, round, prior results and the shared output
  schema. Real Agents do not need coordinator SQLite access to learn their assignment.
- Assigned leases obtain only their own context. Missing/altered context rejects claim;
  device native dispatch cannot omit its delivery. Oversize input blocks before another
  role executes. The existing mailbox order, bounds and consumption proof remain intact.
- Focused input tests: 74 pass / 618 assertions, 3 files, 7.55s; subsequent claim/queue
  negatives: 33 pass / 319 assertions, 1 file, 3.94s. Logs:
  /tmp/cm-topology-input-focused.log and /tmp/cm-topology-input-admission.log.
- Full input gate including expired-message refusal: 688 pass / 8937 assertions, 68 files,
  220.41s, exit 0. Final missing-context visibility change: 33 device tests / 322 assertions,
  4.84s and typecheck passed. Remote CI will cover the published final source together.
- Real Claude/MiniMax-M3 worker consumed its topology input, read all seven required
  current documents and produced accepted structured output. A reviewer then received
  prior worker output but made zero file tool calls and failed required-read verification.
  One preflight and two task inputs occurred; the planned reopen/resume never ran.
- Prior cd4a47f full gate: 680 pass / 8884 assertions, 68 files, 218.98s, exit 0.
  Log: /tmp/cm-device-topology-full.log. Prior f45c1ab CI 34692640944 also succeeded.

## Remaining

1. Publish registered-context CLI changes and check exact-commit CI; connect the interactive terminal frontend to this owner.
2. Complete initial workspace distribution and physical transfer/publication acceptance. Finish real
   topology/current-source acceptance and reviewed SpecMesh closeout; guard failed attempts.
3. Complete remaining provider, transport, store and terminal owners and the parity ledger.
4. Full-goal acceptance, release, installed-version alignment and staged default switch.

## Issues

No replay of guarded native failures or browser-account/cron/bot canaries. Keep tasks
77f04609/7738c5eb canceled. Observation timeout does not prove execution has stopped.
Add topology-input-native-acceptance-20260912 to the guarded attempts. Its reviewer is
now confirmed failed after retained-evidence recovery; do not invoke the original script
again or send another prompt to its sessions. The original script and full test process both reached terminal states.
The canary is not accepted; its report records actual native calls and do_not_replay=true.
Retained operator workspace: outputs/runtime-convergence/topology-input-native-acceptance-20260912.{json,log,ts}.
Also guarded: device-artifact[-configured]-native-acceptance-20260912 reports/scripts in
the same operator directory. The configured attempt ended at structured-result collection;
do not replay its worker session or relabel it as an artifact/continuation success.
Schema 28 rollback requires a pre-upgrade backup. Legacy pending assignments without a
frozen input block. Automatic publication is opt-in, with a baseline captured before initial
dispatch; earlier in-flight schedules cannot acquire that baseline retroactively. Interrupted
multi-file publication can leave partial progress; inspect and explicitly recover its journal.

## Next

Publish registered-context CLI changes and check exact-commit CI. Connect the terminal
frontend to the same owner and qualify initial workspace delivery/two-device publication. Continue the other
runtime owners and full rollout gates. Do not return to repeated similar model probes.

## Retained evidence

[topology-scheduling.md](topology-scheduling.md) covers local/device configuration, controls,
input delivery, recovery and limits. Earlier guarded attempts remain in
[progress-through-6146dab.md](progress-through-6146dab.md); use targeted searches.
Durable boundaries are in [ARCHITECTURE.md](../../docs/ARCHITECTURE.md).

## 2026-09-13 — terminal integration checkpoint

Exact baseline `3571ca33f0bca442e0bc77150f281657c975d589` CI run 34711851901 completed success. Added TS interactive socket-client prototype; evidence and limitations in `../terminal-product-v1/progress.md`. Production remains Python; full migration, physical multi-device acceptance and real Agent continuation remain open.

## 2026-09-13 — OpenCode local native adoption owner

Replaced the Claude-only History wiring with explicit registered-provider dispatch.
OpenCode reuses HistoryClient, NativeSessionStore and DeviceNativeAdoptions; database path
comes from the registered XDG data home. Adoption binds current configuration/workspace,
provider/model, device and native content; no installed-binary/history-based readiness
inference. A profile can now enable History with OpenCode and no Claude configuration.
OpenCode searches the native SQLite source directly; explicit refresh is unsupported.

A real independent History Viewer checkout was exercised through its headless CLI using
an isolated synthetic SQLite source: search, prepare, restart, submit, duplicate receipt
and model mismatch; source bytes unchanged and no provider checks/effects created by
discovery/preparation. Command: CM_HISTORY_TEST_ROOT=/home/muqiao/桌面/Codex-Claude-History-Viewer
bun test packages/controlmesh-runtime-core/test/local-native-history.test.ts --test-name-pattern
OpenCode-only. Result: 1 passed, 14 assertions, 803ms; log `/tmp/cm-local-opencode-real-history.log`.
The minimal revision fixture initially lacked catalog columns (including parent_id); added
the fields required by the actual Viewer query to the test database, without altering
production readers. This is cross-project protocol evidence, not a live-model resume canary.

Final focused local History/control/terminal gate: 26 passed, 182 assertions, 5.05s (`/tmp/cm-opencode-history-focused.log`); typecheck and diff-check passed. Prior commits `0b521ef` and `0535bc9` CI runs 34713012235 and 34713186266 both completed success.

## 2026-09-13 — headless Agent continuity CLI

Added ordinary CLI commands for native History search/refresh/adoption preparation and
SpecMesh handoff/closeout checks. New-task submission accepts a prepared adoption handle
and new prompt; explicit enqueue remains separate. Stable request IDs remain intact,
raw native references are rejected by the adoption flag, and server-side scope/profile
validation remains authoritative. SpecMesh gate failure now produces process exit 1
even when transport succeeded.

Validation includes actual CLI child processes over Unix socket against the local native
adoption registry: prepare, create, identical retry, zero model probes and unchanged
isolated native source. A separate process test distinguishes failed/successful gate
results. Real Agent recall, reviewed semantic closeout and complete migration/cutover
remain pending.

Final gate with actual History checkout selected via CM_HISTORY_TEST_ROOT: 13 passed, 131 assertions, 11.68s (`/tmp/cm-headless-continuity-final.log`). Typecheck and diff-check passed. Web remains read-only.

## 2026-09-13 — reconnectable coordinator/worker service

Added private Unix-socket management to the existing device runtime entrypoint, preserving
stdio mode and explicit daemon selection. Reuses shared lock/framing/bounds before opening
the runtime. Existing device owner schedules work; service health checks only read status
and listener identity. Configuration revocation terminates the owned service.

Focused device-control/service gate: 18 passed, 178 assertions, 4.79s (`/tmp/cm-device-service.log`).
Independent coordinator child processes verify management disconnect, duplicate startup
refusal, persisted task after restart and configuration-revocation exit. Configured worker
socket/daemon verifies reconnect and zero provider checks/execution/native files for an
empty queue. Existing stdio/EOF/scheduler/control tests remain passing. This is local
process evidence, not a new physical two-device/native canary. Initial workspace transfer,
remaining provider/store/transport migration and CM-R7 cutover remain open.

## 2026-09-13 — initial workspace receiver primitive

Implemented exact-manifest validation and initial-input staging. Preparation leaves target
workspace untouched; identical files are preserved, conflicts refused, and original
WorkspaceStage provides recovery/promotion/concurrent-write checks. The runtime must
issue expected digest/allowlist/authority; there is no public operation or automatic seed
application yet. Network transfer, assignment binding and execution admission are next
and remain required for initial-distribution completion.

Seed + existing stage tests: 22 passed, 97 assertions, 1.407s (`/tmp/cm-workspace-seed.log`).
Covers retained-stage reopen/publication, exact bytes, unrelated-file preservation,
conflicting existing content, bad bytes/path, symlink and concurrent destination creation.
Typecheck and diff-check passed. No production/native files or devices were modified.
Prior `d0dab04` CI run 34713715880 completed success; `8422a1d` run 34713930764 was still
running at the latest read.

## 2026-09-13 — durable initial-input inbox

Added private database 29 transfer/file tables and a bounded, runtime-authorized receiving
owner. Retains exact manifest, byte progress and prepared publication across DB reopen;
identical chunks are idempotent, corrupt final chunks do not advance progress, incomplete
inputs cannot prepare, and revoked authority cannot publish. Restored stages reject
a different target/state root. Network/assignment/scheduler integration remains open.

Initial seed tests: 5 passed, 34 assertions. After destination-restoration check, final
inbox tests: 2 passed, 20 assertions (`/tmp/cm-seed-inbox-final.log`). Full runtime suite
started with pinned Bun and configured container/SpecMesh fixtures, output
`/tmp/cm-runtime-seed29.log`; follow the original process handle before claiming its result.
Existing upgrade tests retain their scenario and now assert current private version 29.
Previous `8422a1d` and `9eb1ae6` CI runs 34713930764 and 34714128067 passed.

Expanded verification found old-version fixtures retaining the new tables while resetting
user_version, causing `workspace_seed_transfers already exists`. Fixed fixture downgrades
to remove both version-29 tables; production migration remains strict. All 19 upgrade
cases passed (83 assertions, `/tmp/cm-seed29-upgrades.log`). Final inbox tests now include
empty-file receipt and declared-capacity limits: 3 passed, 24 assertions.

Full runtime process completed: 815 passed / 7 failed, 10405 assertions, 350.54s. All seven
failures were the old-version fixture downgrade omission described above; corrected
upgrade subset passed all 19 cases. Do not report this initial full run as green. Final
inbox subset and typecheck passed after changes. Exact committed CI remains the complete
post-fix gate. Full output: `/tmp/cm-runtime-seed29.log`.

## 2026-09-13 — frozen initial-input sender

Added authorized source capture into durable content storage and validated bounded reads.
Only explicit files are captured; symlinks/traversal/revoked authority refuse. Source
identity/content is rechecked around capture. Changed-source retries cannot change the
original transfer binding. Two separate DBs exercise chunk delivery with repeated receiver
reopen and original-byte publication after source edits, without copying unselected files.

Source/inbox/seed tests: 8 passed, 56 assertions, 632ms (`/tmp/cm-seed-source.log`). Typecheck
and diff-check passed. No real native session, production workspace or remote device was
modified. Network/assignment/lease admission integration, metadata fidelity and physical
acceptance remain open; the internal sender does not establish full distribution.

## 2026-09-13 — initial-input executable permissions

New source manifests bind ordinary file mode; capture verifies descriptor identity and
rejects special bits. Receiver validates original/staged mode and refuses conflicts, while
WorkspaceStage's optional selected mode preserves permissions on new files. Existing
callers without selected mode retain behavior. Tests include executable-bit survival across
sender/receiver DBs, mode conflicts and special-bit refusal.

Stage/seed/source/inbox: 28 passed, 143 assertions (1.58s, `/tmp/cm-seed-modes.log`). Final
original-mode check: 4 passed, 19 assertions (`/tmp/cm-seed-modes-final.log`). Typecheck and
diff-check passed. Exact schema-29 commit b697357 CI run 34714662479 completed success;
this is the complete post-fixture-fix gate referenced in the earlier entry. Network/device
assignment and live delivery acceptance remain pending.

## 2026-09-13 — Gemini typed failure and retry interruption

Native Gemini terminal envelopes now classify quota, rate limit, authentication and model
errors; known native types take precedence over message fallback. Stream parsing and
one-shot process supervision share the classifier. Assistant/tool content and warnings
do not trigger the abort callback. Relative retry delays remain relative, without an
invented reset timestamp.

Validation: 12 tests passed, 484 assertions, 2.29s in gemini-failure, gemini-stream and
oneshot tests (`/tmp/cm-gemini-failure-final.log`); runtime-core typecheck passed. The
process fixture verifies interruption before a retry marker; it does not run a real
Gemini model/account. Full Gemini admission/grant/preflight and native execution remain
open. Production remains Python; no runtime cutover or release is claimed.

## 2026-09-13 — installed Gemini policy precedence qualification

Added optional installed-code regression using the real policy loader and engine. It
verifies controller admin denial for read/write/unknown tools, then demonstrates user
allow precedence after system TOML presence disables the admin path. Isolated temporary
policy directories are removed and patched Storage accessors restored. No production
configuration or sessions changed. Test: 1 passed, 4 assertions, 704ms
(`/tmp/cm-gemini-policy-native.log`); typecheck passed. This identifies an execution
admission requirement; Gemini native grant parity remains incomplete.

## 2026-09-13 — Gemini explicit resume and policy material

Added internal gemini-profile owner: full UUID resume, explicit model, stream-json,
default approval, controller admin-policy path and byte-preserving stdin; no CLI extras.
Policy rendering uses exact validated tool names, deterministic deduplication and a
deny fallback. Installed Gemini policy loader/engine verifies allowed read versus denied
write/similar/unknown names. 3 tests passed, 28 assertions, 642ms
(`/tmp/cm-gemini-profile.log`); typecheck and diff-check passed. This is configuration
material, not an execution admission token. Effective policy, configuration immutability,
session ownership and actual supervised resume integration remain pending; restrictive
Gemini grant refusal stays in place.

## 2026-09-13 — broad regression exposes intermittent device completion uncertainty

Full runtime-core gate at 6df3ee4: 889 passed, 30 skipped, 1 failed, 10876 assertions,
354.52s (`/tmp/cm-runtime-core-post-gemini.log`). Failure: configured container topology
with publish_received=true returned unknown for reviewer instead of done. Exact isolated
reproduction passed (52 assertions, 22.59s); paired false/true sequence passed (106
assertions, 44.69s). Root cause remains unresolved; these reruns do not turn the full gate
green. Added contextual synthetic-fixture failure diagnostics. DeviceWorker now preserves
its existing classified reason on unknown outcomes rather than dropping it; completion,
reconciliation and retry behavior stay unchanged. Related device/control tests: 44 passed,
307 assertions, 7.44s; typecheck/diff-check passed.

Remote CI for 6df3ee4 (34729703343) and ee64368 (34729596207) completed success; this does
not negate the local optional Docker failure. Physical ARM64 peer SSH still timed out;
no remote run started. Production cutover remains blocked on the complete acceptance
matrix, not just CI.

## 2026-09-13 — diagnostic full-suite rerun

At d5fa32b, the complete runtime-core gate with the pinned Docker image and real
SpecMesh root passed: 890 passed, 30 skipped, 0 failed, 10905 assertions across
920 tests / 96 files, 354.81s (`/tmp/cm-runtime-core-diagnostic.log`), command exit 0.
Ownership drift check and typecheck were part of that command. Both artifact publishing
modes passed within the original broad execution order (22.35s / 22.63s). The previous
intermittent unknown outcome did not reproduce; root cause remains unconfirmed.

Static review found existing heartbeat serialization before publication refresh and
terminal completion; no evidence justified weakening leases or changing retry behavior.
The 30 skips include optional installed native/account-dependent profiles and therefore
this successful suite does not close provider parity, real account, physical peer or
production cutover gates. Preserve the earlier failure and new reason diagnostics for
recurrence; continue outstanding CM-R3/R4/R6 work.

## 2026-09-13 — backstage runtime event store, schema 30

Added runtime-session-key and runtime-events TS owners. Numeric session references use
validated decimal strings/BigInt normalization rather than Number, preserving large
terminal IDs; typed string refs remain distinct. Supported canonical/legacy keys were
compared directly with the current Python SessionKey implementation. Malformed percent
encoding is deliberately refused, not silently replaced. Schema 30 adds a separate
principal-scoped backstage_events table; task kernel events remain untouched.

Appending the same event ID/payload is idempotent; conflicting reuse is rejected.
readRecent preserves insertion order, legacy alias lookup, principal isolation and
Python limit<=0 meaning all events. Unsafe numeric chat/topic values are refused, not
rounded. JSONL import must preserve such integers before decoding; not implemented yet.
Tests cover schema-29 upgrade, reopen, conflict rollback and unchanged task-event table.
Historical downgrade fixtures now also remove the new table. Targeted 18-file migration
regression: 322 passed, 2937 assertions, 63.61s (`/tmp/cm-events-all-migrations.log`);
typecheck and diff-check passed. Python producers/JSONL import and public API integration
remain open. No production writer changed. Old TS binaries reject schema 30; do not
open an upgraded candidate database with an older runtime.

## 2026-09-13 — transactional legacy backstage JSONL import/export

RuntimeEventStore now imports an explicitly selected session's JSONL batch atomically
and exports compatible JSONL. Integer source tokens beyond JS safe range are parsed
from Bun's native JSON reviver source context into bigint and serialized back as JSON
numbers. Nested payload integers and numeric chat/topic references retain their values.
The dedicated event codec is required; ordinary JSON.stringify cannot encode this
internal representation. Previously rounded Number inputs and unsafe exponent-form
values are refused rather than guessed. No public protocol payload type changed.

Tests compare exported records directly with Python json.loads, including uint64 chat
IDs and nested negative integers; verify replay counts, conflicting-batch rollback,
malformed-line refusal, session/principal isolation and numeric/depth limits. 4 tests
passed, 32 assertions, 466ms (`/tmp/cm-event-import-final.log`); typecheck and diff-check
passed. Import accepts bounded caller-supplied content; filesystem discovery, migration
command/dry-run reporting and production producer wiring remain open. No local operator
JSONL files were imported or modified.

## 2026-09-13 — explicit event-file migration command

Added scripts/migrate-runtime-events.ts with default dry-run and explicit source, target
database, principal and session. Apply requires the SHA-256 returned by preview. Source
reading is bounded to 16 MiB, canonical regular/no-follow, descriptor/path stable across
read and strict UTF-8. Entire batch is validated in memory before opening the target.
Apply consumes the verified snapshot, so later source changes cannot alter imported
bytes. Preview creates no target database; source files are never modified.

Real CLI subprocess tests plus event codec/import tests: 5 passed, 42 assertions, 604ms
(`/tmp/cm-event-command.log`); typecheck and diff-check passed. Tests cover missing/stale
digest refusal before target creation, successful apply/replay, unchanged source and
symlink refusal. No operator history was migrated. Producer wiring and full cutover
remain pending; this command only imports explicitly supplied backstage events.

## 2026-09-13 — lifecycle producer and local session history surface

Kernel task.* lifecycle events now append a bounded backstage summary in the same
transaction when the task has a valid issued execution context. Summaries contain task
ID/status/revision/fence, not raw model output, task prompt or credentials. Legacy partial
contexts still produce original task events but cannot establish session attribution.
Per-database persisted source UUID plus kernel sequence creates stable distinct event IDs.
Local session_events control/CLI reads only the configured principal, caps reads at 100
and returns lossless JSONL. No write/identity override is exposed on that surface.

Normal submit/replay/cancel/reopen tests verify automatic production, bounded contents,
identity-override refusal and transaction rollback on invalid topic. Kernel/device/control
regressions: 61 passed, 351 assertions, 7.70s (`/tmp/cm-session-events-final.log`);
event/CLI: 13 passed, 101 assertions, 8.02s (`/tmp/cm-session-events-cli.log`); typecheck
and diff-check passed. This wires TS lifecycle production and reads; Python frontstage
events, route-candidate/inbox producers and operational default switch remain pending.

## 2026-09-13 — bounded session history pages

Session control/CLI now accepts exclusive before cursor and returns has_more/next_before.
Pages cap records at 100 and JSONL bytes at 2 MiB, using sequential database iteration
instead of loading up to 100 MiB before truncating. Each page remains chronological;
cursor traversal walks older events and is stable when newer events arrive. Dedicated
prepared statements are explicitly finalized: early termination of a cached Bun SQLite
query iterator reproduced API-misuse on its next use, fixed by private statement lifetime.

Event/CLI/local-control tests: 29 passed, 217 assertions, 10.74s
(`/tmp/cm-session-page-final.log`); typecheck and diff-check passed. Large escaped payloads
verify both raw page and 8 MiB outer response bounds, repeated pages, new inserts,
principal isolation and cursor refusal. Full legacy export retains its explicit whole-
stream semantics; the interactive control path is now bounded.

## 2026-09-13 — native TS host-job model and terminal merge

Added host-job-model with Python-compatible serialized fields/defaults for valid input,
command SHA-256 binding, explicit imported timestamps, unique bounded step IDs and sticky
terminal task/step merge. Current Python _merge_job was run directly against 85 task/step
state pairs and matched TS. Additional refusals prevent changing a step's command/cwd/
kind/approval-required/side-effect definition, deleting terminal steps or accepting a
mismatched digest. These tighten unsafe legacy merge cases; they are not silently
rewritten during import. Approval metadata is preserved data, never execution authority.

2 tests passed, 8 assertions (including the 85-pair structural comparison), 336ms
(`/tmp/cm-host-job-model.log`); typecheck and diff-check passed. Persistent host-job store,
legacy file precedence/import, approved process dispatch, reconciliation and execution
control remain open. No host command or old host job was started.
