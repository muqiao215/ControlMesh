# ControlMesh Project Context

## Why

Official coding CLIs are powerful but usually tied to one foreground terminal session.
ControlMesh turns them into a local-first, persistent task runtime that can be reached from
a terminal or chat, continue work in the background, coordinate multiple agents, ask for
missing information, recover after interruption, and deliver results back to the original
conversation.

## User Intent

The product should let a user move naturally between local terminal work and long-running
chat-native work without losing context or handing control of private project state to a
remote platform.

The important user outcomes are:

- official Claude, Codex, Gemini, OpenCode, and configured provider CLIs remain the actual
  execution engines;
- tasks have stable identities, persistent state, artifacts, interruption, resume, and
  result-delivery behavior;
- Feishu is the native/runtime-first transport, with Telegram and WeChat as important
  supported paths;
- multi-agent work is explicit, bounded, inspectable, and coordinated through shared
  runtime primitives;
- project and task knowledge survives a new terminal, a new agent, or a long gap without
  requiring the user to explain everything again;
- the user spends attention on intent and judgment, while agents handle exploration,
  implementation, tests, review, and memory maintenance.

## Non-goals

- Do not replace official provider CLIs with a proprietary model runtime.
- Do not move Python runtime ownership into TypeScript merely to unify languages.
- Do not let the Web UI or SDK read or write private ControlMesh files directly.
- Do not expose a remote-first dashboard, arbitrary shell endpoint, or arbitrary file read.
- Do not infer orchestration topology from prose; topology selection remains explicit.
- Do not add process documents, agent roles, evidence systems, or empty structures without
  a real need.
- Do not make conversation history the source of project truth.

## Success

ControlMesh succeeds when a user can start or resume real provider-backed work from the
terminal or a supported chat, let it run persistently, answer task questions, inspect
status and artifacts, recover from interruption, and receive a trustworthy result without
breaking existing workspaces or transport behavior.

The project-memory system succeeds when a new agent can read `AGENTS.md`, this file, the
relevant architecture/decision links, and one active task directory, then continue work
without loading the whole repository or asking the user to repeat established context.

## Constraints

- Python is authoritative for task lifecycle, recovery, provider processes, transports,
  memory writes, workspace mutation, and persisted runtime behavior.
- JSON Schema under `schemas/controlmesh/v1/` is authoritative for cross-language payload
  shape; generated Python and TypeScript models are not edited directly.
- Public protocol fields use stable snake_case names, allow additive unknown fields where
  forwarding requires it, and never expose absolute artifact paths.
- Persisted fields, task statuses, provider/transport names, and workspace layouts require
  explicit migrations.
- TypeScript runtime ownership stays blocked until canonical Python fixtures demonstrate
  create, tell, ask_parent, resume, cancel, provider, recovery, workspace, and artifact
  parity with rollback gates.
- The Web product remains local-first and binds to `127.0.0.1` by default.
- Secrets, credentials, auth profiles, runtime state, caches, dependency directories, and
  build output must remain untracked.

## Current State

The Python runtime is mature and remains the production core. It provides the enhanced
terminal, legacy bot runtime, provider adapters, persistent TaskHub, message transports,
memory/workspace behavior, multi-agent supervision, four approved topologies, recovery,
and operational tooling.

The approved TypeScript foundation is complete:

- versioned JSON Schemas and synchronized generated Python/TypeScript models;
- Bearer-protected, read-only Python `/api/v1` facade for tasks, events, providers,
  topologies, artifact metadata, and descriptor-safe artifact downloads;
- runtime-validated TypeScript SDK;
- local read-only Web dashboard;
- protocol, provider golden, SDK, facade, artifact-security, and Web build gates.
- GitHub CI runs the frozen protocol/golden/SDK/Web gate as a required product-layer job
  and exposes one aggregate `CI success` check for the complete workflow.

The `0.42.0a1` read-only release candidate is installable as one Python artifact: the
deterministic dashboard build ships in the wheel, `controlmesh api serve` exposes the
authenticated facade and dashboard only on `127.0.0.1`, and the public Alpha SDK surface
contains only supported read operations. CI includes a required isolated-wheel smoke that
exercises the installed CLI, real HTTP/SDK reads, artifact containment, mutation rejection,
and wheel-bundled dashboard assets.

Mutation-shaped SDK ideas are not supported product behavior. Real task mutation and all
transport/provider execution remain Python-owned.

Provider authentication tests isolate operator XDG paths while retaining explicit XDG
override coverage. The Codex streaming timeout test uses a complete stderr stream double,
so the full Python suite passes with runtime warnings promoted to errors.

## Current Priority

1. Publish and post-verify the `0.42.0a1` read-only facade/dashboard prerelease.
2. Build the Python task-lifecycle golden parity matrix before considering mutation APIs.
3. Decide browser credential storage and operator scope before any non-local Web use.

## Knowledge Map

- System structure and ownership → `docs/ARCHITECTURE.md`
- Important choices and rejected alternatives → `docs/DECISIONS.md`
- Full documentation catalog → `docs/README.md`
- TypeScript migration contracts and status → `docs/typescript-migration/`
- Historical and active work → `plans/`
- Current active work → `plans/project-memory-v1/`
