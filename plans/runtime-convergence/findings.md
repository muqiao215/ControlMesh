# Findings

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
