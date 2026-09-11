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
