# ControlMesh Requirements

This file is the repository-level requirements source of truth. It describes what the project must provide, how completion is judged, and which requirements are intentionally deferred.

Detailed line-specific plans may live under `plans/` or `docs/`, but they must not silently redefine this file.

## Product Goal

ControlMesh is a local-first, chat-native task runtime that connects official coding CLIs to persistent workspaces, background tasks, multi-agent coordination, messaging transports, and operational tooling.

The current TypeScript program adds a protocol, SDK, facade, and Web product layer around the authoritative Python runtime. It does not replace core runtime behavior.

## Status Vocabulary

| Status | Meaning |
|---|---|
| `existing` | Implemented before the current migration work |
| `completed` | Implemented and verified in the current program |
| `partial` | Some acceptance criteria are met |
| `planned` | Approved but not implemented |
| `blocked` | Must not proceed until the named gate is satisfied |

## Functional Requirements

### Runtime And Entry Points

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| RT-001 | Provide an interactive `controlmesh` terminal entry point. | `controlmesh` enters the enhanced terminal and provider-native mode remains reachable. | existing |
| RT-002 | Preserve the legacy bot runtime. | `controlmesh bot` remains available. | existing |
| RT-003 | Keep Python as the authoritative runtime during the TypeScript program. | No TypeScript component owns task state, provider processes, recovery, memory writes, or workspace mutation. | completed |
| RT-004 | Keep runtime behavior backward compatible while product layers are added. | Existing Python tests pass and legacy `/catalog/*` endpoints retain their response shapes. | completed |

### Provider Execution

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| PR-001 | Execute supported official coding CLIs through Python adapters. | Claude, Codex, Gemini, and configured providers remain discoverable and runnable through existing Python paths. | existing |
| PR-002 | Preserve provider timeout, streaming, liveness, and process semantics. | No TypeScript code infers or changes provider execution outcomes. | completed |
| PR-003 | Expose provider availability to product clients. | `GET /api/v1/providers` returns `controlmesh.provider_capability.v1` objects. | completed |
| PR-004 | Add golden provider behavior fixtures before any provider runner port. | success, timeout, error, and event ordering fixtures pass against Python reference behavior. | completed |

### Tasks And Background Work

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| TK-001 | Create and persist background tasks. | A task receives a stable string ID, task folder, binding, status, and timestamps. | existing |
| TK-002 | Support create, tell, ask_parent, resume, cancel, and result delivery semantics. | Existing TaskHub tests cover the lifecycle and state transitions. | existing |
| TK-003 | Preserve current task status values. | Protocol includes `running`, `done`, `failed`, `cancelled`, `waiting`, `detached`, `recovering`, `stale`, and `timeout`. | completed |
| TK-004 | Expose a read-only task list and detail facade. | `/api/v1/tasks` and `/api/v1/tasks/{task_id}` return `controlmesh.task.v1`. | completed |
| TK-005 | Expose task lifecycle events. | `/api/v1/tasks/{task_id}/events` returns only events whose payload matches the requested task ID. | completed |
| TK-006 | Do not add mutating TypeScript task APIs until parity gates pass. | SDK mutation methods are not treated as supported product behavior until create/tell/resume/cancel golden tests exist. | blocked |

### Multi-Agent Coordination

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| MA-001 | Support main/sub-agent supervision and shared task coordination. | Existing AgentSupervisor, InterAgentBus, and internal API tests pass. | existing |
| MA-002 | Preserve approved topology semantics. | `pipeline`, `fanout_merge`, `director_worker`, and `debate_judge` retain Python-owned behavior. | existing |
| MA-003 | Expose topology data only through protocol adapters. | UI does not decide ownership, routing, judging, or escalation. | completed |

### Messaging Transports

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| MS-001 | Preserve Feishu as the native/runtime-first transport. | Existing Feishu auth, message, card, and native tool tests pass. | existing |
| MS-002 | Preserve Telegram, WeChat, Matrix, and QQBot compatibility paths. | Existing transport tests remain green. | existing |
| MS-003 | Define a cross-language transport message contract before porting presentation logic. | `transport-message.schema.json` exists and generated models remain synchronized. | completed |
| MS-004 | Keep real transport send/receive adapters in Python. | TypeScript may render or display normalized data but does not send platform messages. | blocked |

### Memory, Workspace, And Artifacts

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| MW-001 | Preserve file-backed memory as authoritative user data. | TypeScript has no memory write path; Python promotion/search/store semantics remain unchanged. | completed |
| MW-002 | Preserve workspace and task-folder layouts. | TypeScript never constructs workspace or artifact filesystem paths. | completed |
| MW-003 | Expose read-only artifact metadata. | `/api/v1/tasks/{task_id}/artifacts` returns relative paths, MIME, size, and timestamps through `controlmesh.artifact.v1`. | completed |
| MW-004 | Block artifact symlink escapes. | Resolved artifact files outside the Python-resolved task folder are omitted. | completed |
| MW-005 | Support custom per-agent task directories. | Artifact facade locates folders using persisted `tasks_dir` without instantiating or mutating `TaskRegistry`. | completed |
| MW-006 | Add authenticated artifact download only after path tests. | Contract uses `task_id` plus metadata `relative_path`; traversal, symlink, missing-file, token, MIME, header, and allowlist tests pass before endpoint exposure. | completed |

### Protocol, SDK, And Web

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| PW-001 | Use JSON Schema as the cross-language shape source of truth. | Schemas live under `schemas/controlmesh/v1/`; Python and TypeScript generated outputs are clean. | completed |
| PW-002 | Preserve Python field names and unknown fields at protocol boundaries. | Generated object models allow additive fields and use snake_case payload fields. | completed |
| PW-003 | Provide a TypeScript SDK for the read-only facade. | Task list/detail, events, providers, artifact metadata, and protocol errors have smoke tests. | completed |
| PW-004 | Provide a local read-only Web dashboard. | User can configure API/token and inspect tasks, providers, events, and artifact metadata. | completed |
| PW-005 | Keep the dashboard local-first. | Dev server binds to `127.0.0.1`; remote exposure is not enabled by default. | completed |
| PW-006 | Add runtime validation to TypeScript consumers. | Public SDK responses are validated against generated protocol validators. | completed |

### Operations And Security

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| OS-001 | Keep service, doctor, restart, and deployment behavior Python-owned. | Existing CLI/service tests remain green. | existing |
| OS-002 | Protect `/api/v1` data with Bearer authentication. | Missing or wrong tokens receive `controlmesh.error.v1` with HTTP 401. | completed |
| OS-003 | Never expose secrets through tracked collaboration files. | `.env*`, auth profiles, tokens, runtime credentials, and private state remain ignored. | completed |
| OS-004 | Keep generated caches and build products out of repository truth. | `node_modules`, caches, virtual environments, runtime logs, and `dist` remain ignored. | completed |

### Repository Collaboration

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| RC-001 | Maintain one repository-level requirements file. | `REQUIREMENTS.md` lists IDs, acceptance criteria, and status. | completed |
| RC-002 | Maintain one implementation guide. | `IMPLEMENTATION.md` defines architecture, boundaries, workflow, and verification. | completed |
| RC-003 | Maintain a current agent handoff. | `HANDOFF.md` records current state, pending work, risks, and exact commands. | completed |
| RC-004 | Maintain stable agent operating rules. | `AGENTS.md` tells every agent what to read, edit, test, and update. | completed |
| RC-005 | Track collaboration artifacts. | Requirements, implementation notes, handoffs, plans, findings, progress, evidence, and lockfiles are not globally ignored. | completed |

## Non-Functional Requirements

| ID | Requirement | Acceptance criteria |
|---|---|---|
| NFR-001 | Backward compatibility | Existing Python behavior and persisted values remain authoritative. |
| NFR-002 | Security | No arbitrary file read, shell endpoint, browser credential storage beyond explicit local token entry, or remote bind by default. |
| NFR-003 | Determinism | Generated protocol files and golden fixtures are reproducible. |
| NFR-004 | Testability | Every cross-language boundary has protocol tests and every behavior port has golden parity tests. |
| NFR-005 | Reversibility | TypeScript product layers can be disabled without changing Python runtime data. |
| NFR-006 | Observability | User-visible task, provider, event, artifact, and error states are explicit. |
| NFR-007 | Maintainability | Requirements use stable IDs and implementation changes update handoff/status documents in the same work unit. |

## Release Gates

A TypeScript slice is complete only when:

1. Its requirement IDs and acceptance criteria are updated here.
2. JSON Schema and generated Python/TypeScript models are synchronized when payloads change.
3. Python facade tests pass.
4. SDK smoke tests pass when SDK behavior changes.
5. Web build passes when Web behavior changes.
6. `HANDOFF.md` and the relevant status document reflect the result and next step.

Runtime replacement remains blocked until critical create/resume/tell/ask_parent, provider, artifact path, workspace, and recovery parity is demonstrated.
