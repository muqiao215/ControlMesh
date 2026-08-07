# Decisions

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
