# Decisions

## 2026-09-06 — Require terminal interaction acceptance for product readiness

Decision: Treat the current terminal as a basic shell and prioritize Terminal Product v1.
User-facing readiness requires discoverable commands, editable input, visible execution,
interruption/recovery, and real-terminal visual and interaction acceptance.

Why: The user explicitly rejected the current terminal experience. Runtime test counts,
read-only Alpha packaging, and TypeScript parity cannot establish terminal usability.

Rejected: Calling the terminal complete based only on backend gates or cosmetic changes.
Python retains runtime ownership; no public mutation API is admitted by this UX work.

Revisit when: The acceptance scenarios in `plans/terminal-product-v1/task_plan.md` pass
on the documented terminal environments. UI framework selection remains a prototype task.

## 2026-09-05 — Require a trusted source context before unattended provider execution

Decision:

Carry one ControlMesh-issued execution context from each ingress to both provider-launch
boundaries. Group messages, bot handoffs, API, cron, webhook, and heartbeat execution
require a confirmed sandbox; setup or recovery failure is fail-closed. Local foreground
and direct-message compatibility may remain host-compatible. The context is additive on
task/background persistence and legacy records receive an explicit compatibility scope.

Why:

The previous global Docker fallback let an unattended or group request become a host
provider process when isolation was unavailable. A policy check only at routing time could
also be bypassed by one-shot, resume, recovery, or alternate transport paths.

Rejected:

Inferring trust from prompt text, filenames, provider names, process labels, or a generic
`task_id`; allowing Docker setup failure to fall back for all sources; and adding a second
identity model parallel to the existing runtime evidence identity.

Revisit when:

The runtime has an equivalent authenticated isolation capability with durable, auditable
source policy and recovery semantics.

## 2026-08-29 — Keep real Feishu bot coordination transport-owned and opt-in

Decision:

For allowlisted groups that explicitly enable `multi_bot_mode`, let the Python Feishu
transport choose one of respond, passive-observe, or drop before orchestration. Ordinary
human messages activate one configured coordinator, exact bot @ activates only that
identity, `/all` activates every configured identity, and bot-authored messages require a
configured sender plus explicit local target and bounded loop budget.

Why:

Changing every bot to accept all unmentioned group messages cannot distinguish an ordinary
message from one targeting a different bot and creates duplicate replies. Transport events
contain sender and mention identity, so arbitration belongs at ingress, before commands,
provider execution, or result writeback. Keeping the mode per-group and disabled by default
preserves existing deployments and makes the Raspberry Pi coordinator a reversible canary.

Rejected:

Global `require_mention=false`, global `group_reply_all=true`, prompt-only coordination,
unknown bot-to-bot traffic, and autonomous bot conversation.

Revisit when:

Cross-server diagnostics or distributed loop budgets need durable shared state, or Feishu
exposes a stronger native group arbitration primitive.

## 2026-08-08 — Ship the read-only Alpha as one Python install

Decision:

Bundle the deterministic Web build in the Python wheel, serve it same-origin from
`controlmesh api serve`, restrict that standalone server to `127.0.0.1`, and expose only
supported read operations in the Alpha TypeScript SDK.

Why:

A PyPI Alpha that requires a source checkout for its dashboard is not independently
installable. Same-origin serving also avoids a new CORS/security contract, while the
localhost/read-only limits preserve Python ownership and the approved product boundary.

Rejected:

Source-only Web evaluation, a separate remote dashboard deployment, enabling CORS broadly,
and leaving unsupported mutation-shaped SDK methods as apparent public capabilities.

Revisit when:

Remote authentication/origin policy or task-mutation parity is explicitly approved.

## 2026-08-07 — Use progressive project memory

Decision:

Use `AGENTS.md` as the startup protocol, `PROJECT.md` for intent/current direction,
`docs/ARCHITECTURE.md` for the system map, `docs/DECISIONS.md` for durable rationale, and
`plans/<task>/` for substantial active work.

Why:

New sessions should recover context gradually without reading overlapping requirements,
implementation, handoff, and plan documents.

Rejected:

Keeping `REQUIREMENTS.md`, `IMPLEMENTATION.md`, and `HANDOFF.md` as parallel mandatory
sources of truth.

Revisit when:

A concrete compliance or release need requires a separate formal specification.

## 2026-08-07 — Keep one user-level skill source

Decision:

Keep the upstream `planning-with-files` Git checkout under
`~/.local/share/planning-with-files`, expose it at `~/.agents/skills/planning-with-files`,
and link Claude's compatibility path to the same skill.

Why:

Codex, OpenCode, and Claude should use one updateable source rather than drifting copies.

Rejected:

Project-local copies and separate per-agent installations.

Revisit when:

An agent host cannot follow the shared path or a project requires a pinned skill version.

## 2026-07-22 — Keep Python runtime authoritative

Decision:

Python continues to own task state, recovery, provider processes, transports, memory
writes, workspace mutation, and operational behavior. TypeScript may define/validate
protocols and provide SDK/Web product layers.

Why:

The Python behavior is mature, persisted, and broadly tested. Replacing it without parity
would risk user data and runtime compatibility.

Rejected:

A broad TypeScript rewrite based on type similarity or SDK method availability.

Revisit when:

Canonical fixtures cover critical lifecycle, provider, path, workspace, delivery, and
recovery behavior with shadow-mode and rollback gates.

## 2026-07-22 — Use JSON Schema for public cross-language shapes

Decision:

Versioned JSON Schema is the public payload source; Python and TypeScript models are
generated from it.

Why:

Neither language should silently redefine the shared wire contract. Deterministic
generation makes drift testable.

Rejected:

Hand-maintained duplicate Python and TypeScript public models.

Revisit when:

A replacement offers equal cross-language generation, validation, compatibility, and
determinism.

## 2026-07-22 — Expose artifacts through Python-safe relative paths

Decision:

Artifact APIs accept `task_id` plus an exact metadata `relative_path`. Python resolves the
persisted task folder and performs allowlisted descriptor-relative no-follow opening.

Why:

Artifact IDs do not exist in the authoritative model, and absolute/browser-constructed
paths would violate containment.

Rejected:

Absolute paths, browser filesystem derivation, and pathname re-open after validation.

Revisit when:

A versioned artifact identity is added through an explicit persisted-data migration.

## 2026-07-22 — Keep the Web dashboard local and read-only

Decision:

The current dashboard binds to `127.0.0.1`, consumes only the authenticated Python facade,
and does not mutate runtime state.

Why:

It delivers visibility without expanding the remote attack surface or crossing incomplete
task parity gates.

Rejected:

Remote exposure by default and private-file access from Web/SDK code.

Revisit when:

Authentication scopes, browser credential storage, origin/CSRF controls, audit behavior,
and task mutation parity are explicitly approved.

## 2026-08-29 — Gate result writeback and promotion on the current typed episode

Decision:

Use the existing four-field runtime evidence identity as the writeback idempotency and
freshness boundary. Only the persisted plan owner may record the latest episode's terminal
result; identical retries reuse the prior event and conflicting retries fail closed.
Controller promotion requires one current completed result and rechecks execution, review,
and summary snapshots immediately before canonical writes.

Why:

Summary identity alone cannot prove that a result is owned, successful, current after
recovery, or unchanged between eligibility and write time.

Rejected:

Task-ID-only matching, filename/text correlation, worker-direct promotion, and treating a
committed golden fixture or successful delivery as promotion authority.

Revisit when:

Execution evidence moves to a transactional store with equivalent identity, idempotency,
freshness, and rollback guarantees.

## 2026-08-08 — Admit a private TypeScript lifecycle candidate without transferring ownership

Decision:

Allow the private runtime-facade package to execute the canonical lifecycle matrix in
memory, require a live Python/TypeScript dual-run with structured diffs and a digest-bound
rollback gate, and keep public OpenAPI/SDK/Web mutation surfaces absent.

Why:

This proves a cross-language consumer can reproduce observable semantics while avoiding
production file writes, premature API commitments, or a runtime ownership transfer.

Rejected:

Echoing matrix expectations, switching production ownership after fixture parity, and
adding public mutation methods before authorization/idempotency/audit review.

Revisit when:

The deferred operation-specific admission choices in
`docs/typescript-migration/MUTATION_API_REVIEW.md` are explicitly approved.

## 2026-08-08 — Use an executable Python lifecycle oracle

Decision:

Generate one versioned task-lifecycle parity matrix by executing production Python
ownership paths, normalize only unstable identity/time/root/process values, and require
Schema validation plus a no-drift CI check.

Why:

Scattered unit tests and hand-written snapshots cannot prove cross-language mutation
parity across persistence, events, recovery, workspace isolation, and artifact containment.

Rejected:

SDK-only smoke evidence, prose-only matrices, raw temporary snapshots, and treating the
matrix as permission to expose mutation APIs.

Revisit when:

The fixture envelope cannot express a required observable behavior without unstable or
implementation-private data.

## 2026-06-03 — Keep topology selection explicit

Decision:

Support `pipeline`, `fanout_merge`, `director_worker`, and `debate_judge` through typed,
bounded Python runtimes, but require explicit topology selection.

Why:

Automatic inference would hide control-flow choices and make interruption, budgeting, and
parent boundaries less predictable.

Rejected:

Free-text orchestration decisions, automatic topology routing, and silent final-round tie
breaking.

Revisit when:

An explainable selection policy has independent requirements and regression evidence.

## 2026-05-09 — Force risky routing to the foreground

Decision:

Repository writes, publish/release actions, and other approval-requiring side effects stay
foreground unless a trusted worker explicitly satisfies capability, sandbox, permission,
and output-policy requirements.

Why:

Provider identity or activation keywords do not prove that a background worker is safe to
perform side effects.

Rejected:

Text-first automatic release routing and provider-name-based trust.

Revisit when:

Trusted worker contracts and user approval semantics cover the exact side effect.


## 2026-09-11 — Adopt native sessions through the local TaskHub ingress

Decision: use Viewer for read-only candidate discovery, validate identity in OpenCode's
native store, and execute explicit native resume through the existing TaskHub. Persist
source identity/revision separately from project memory and execution provenance.

Why: copying history into a new prompt cannot establish native continuity. Reusing TaskHub
preserves supervision and recovery without adding a second scheduler or emitting scheduled
prompts under a user's identity. A model catalog or successful CLI exit alone is insufficient:
adoption first requires a supervised, bounded PONG response from the selected model.

Rejected: Viewer writing CM private files, automatic latest-session selection, inferred
permissions from historical text, and silently switching to a fresh session on failure.

Revisit remote/browser adoption only after authenticated mutation admission and source-aware
policy are implemented. The current CM lease does not exclude independent native clients.

## 2026-09-11 — Integrate against existing repository authority

Reuse the existing storage/parsers and keep SpecMesh independently callable. Do not install a second TaskHub from a proposal or equate historical handoff with live completion. The human overview and headless retrieval have separate entry points. See [scope and remaining limits](CODEKIT-INTEGRATION.md). Status: implemented for v0.43.0; broader roadmap gates remain planned.

## 2026-09-11 — Migrate actual runtime owners, with transactional episodes

The user explicitly authorized full TS runtime migration, multi-device coordination and
native Agent continuity, and chose original local repositories with verified direct main
pushes. The former read-only-first policy is a rollout gate, not a permanent language ban.
Keep Python active until replacement owners pass parity and rollback checks. Start with
a real private coordinator kernel, not the fixture-specific facade: separate stable tasks,
execution episodes and monotonic fencing; commit transitions, events and receipts together.
Persist uncertain external effects and reconcile before another execution. Use SQLite on
one coordinator host, never as a shared network file. Native clients outside CM still need
revision reinspection and cannot be made safe by an advisory CM-only lease. This decision
does not claim production cutover or complete provider parity.

## 2026-09-11 — Separate worker execution authority from human ingress and device clocks

Use an authenticated private worker port and a coordinator-local database. A device token
maps to a configured owner/device/capability/workspace set; worker events use agent origin.
Operator assignment and revocation are local authority and revocation is durable. Keep
absolute workspaces, native databases and provider credentials on the device. Bind an
assignment digest before claim so an old inspected input cannot execute after reassignment.

The worker derives a conservative deadline from request-send time plus coordinator
remaining duration. It does not compare device wall clocks. Linux uptime accounts for
suspend, and the process anchor receives the same authority deadline so controller stalls
cannot extend work through a fixed heartbeat grace period. A lost/expired authority never
revives from a delayed response. Repeated external dispatch remains denied and uncertain
completion requires reconciliation. These controls fence coordinator writes and supervise
cooperating process groups; they do not make an uncooperative external service transactional.

## 2026-09-11 — Recover native results from before/after evidence, without repeating execution

Persist the native dispatch manifest and retain the original observation separately from
the accepted result. A later native reference alone cannot establish the original task,
permissions, file state or session baseline. An explicit trusted verifier must independently
check those bindings before the kernel atomically clears an unknown outcome. Missing evidence
stays unknown. Never turn an unsuccessful acceptance check into an automatic model rerun.

Required current-file reads are both an Agent instruction and an acceptance condition.
OpenCode's custom Agent prompt replaces its model's default prompt; a generic instruction
was insufficient in a real resumed turn, which reused old file contents. The worker now
issues and inspects an explicit list of required fresh reads. Guidance does not replace
verification: a terminal answer without the current native read remains unaccepted.

## 2026-09-11 — Preserve provenance at issuance and separate mapping from execution admission

Port current Python policy and grant semantics with a live differential oracle. Keep the
historical mapping result for an otherwise empty controller-required grant for parity,
but never interpret it as approval to execute. Real admission checks source and confirmation
independently. Unknown new sources must be rejected rather than becoming host-compatible;
malformed persisted context requires explicit reviewed reissue, not invented trace fields.

Use a configured trusted `TaskIngress` to issue source/grant/reply identity and atomically
persist them with the task and event. Task bodies and Agent messages cannot choose this
authority. Stable retry identity excludes the random newly generated trace; retries return
the original issued trace. Worker command origin remains distinct from task provenance.
Do not relabel remote worker traffic as human requests to reuse the local native profile.
This port does not itself implement the remaining sandbox or transport owners.

## 2026-09-11 — Share native execution while retaining full evidence on its device

Extract one native driver instead of maintaining separate local and network verification
implementations. A prepared device adapter persists its full manifest before coordinator
dispatch and its original observation before network delivery. The coordinator atomically
starts/dispatches and stores a bounded evidence reference; completion binds that reference,
original observation and native handle. Do not transport native databases, credentials or
private workspace paths as a continuity mechanism.

Resolve opaque continuation handles through the original device's verified result ledger,
bound to task and workspace. Reopening a worker must not lose the original provider session
or repeat a completed native call after a lost acknowledgement. Preserve worker command
origin separately from original human task provenance. Preparation that has not dispatched
an effect may release its lease; an unknown external result must remain unknown until an
explicit evidence-based recovery decision. Remote attestation/reconciliation remains a
separate required owner, not an implied feature of the local journal.

## 2026-09-11 — Give each TS execution its own container and expiring inner lease

Use one container per execution rather than porting the Python shared-sidecar `docker exec`
wrapper unchanged. Stopping an exec client does not establish that its inner descendants
stopped, and stopping the shared sidecar would interrupt peer tasks. A per-execution PID
namespace provides an attributable cleanup boundary; an inner PID 1 lease watcher also stops
work when the host controller or Docker client disappears. Bind monotonic deadlines to a boot
ID so a reboot cannot make an old lease current again.

Provision from an explicit, available image digest with narrow workspace mounts and verified
engine configuration. Preserve the original grant; discharge network and host writable-root
restrictions through the outer container while retaining native tool/confirmation checks.
An isolated network blocks the model client too; required provider connectivity needs an
explicit compatible profile, not a silent grant change. Native auth/state mounts, directory
identity, compatibility layout and actual provider image qualification remain migration gates.
Keep the released Python owner until those gates and writer cutover are verified.

Record creation intent before the daemon call. A lost create response may arrive after a
negative inspect, so retain uncertainty until the originally labelled immutable ID has been
observed and removed. Never retry that execution or manufacture completion from absence.
