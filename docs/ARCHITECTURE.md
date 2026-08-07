# Architecture

## Overview

ControlMesh is a Python-owned local task runtime. Terminal and messaging entry points feed
an orchestrator and persistent TaskHub, which execute official provider CLIs and store
runtime state, memory, workspaces, events, and artifacts. A versioned read-only API exposes
safe projections to TypeScript protocol, SDK, and Web layers.

```text
Terminal / Feishu / Telegram / WeChat / Matrix / API
                         |
                         v
                Python orchestrator
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
       TaskHub      Provider CLIs   MessageBus
          |              |              |
          +------- runtime/events -------+
                         |
        workspace / memory / task folders / artifacts
                         |
                         v
              read-only Python /api/v1
                         |
                         v
              TS protocol -> SDK -> Web
```

## Repository Map

- `controlmesh/` → Python application and authoritative runtime.
- `controlmesh_runtime/` → independent runtime contracts and recovery/summary primitives.
- `controlmesh/tasks/` → persistent task lifecycle and background execution.
- `controlmesh/cli/` → official provider CLI adapters, auth, streaming, and processes.
- `controlmesh/orchestrator/` → commands, foreground flows, selectors, and lifecycle.
- `controlmesh/messenger/` → Feishu, Telegram, WeChat, Matrix, QQBot, and transport
  abstractions.
- `controlmesh/multiagent/`, `controlmesh/team/`, `controlmesh/bus/` → supervision,
  topology execution, coordination, and delivery.
- `controlmesh/memory/`, `controlmesh/workspace/` → file-backed memory and path/layout
  ownership.
- `controlmesh/api/` → WebSocket/direct API and authenticated read-only v1 facade.
- `schemas/controlmesh/v1/` → cross-language JSON Schema source.
- `packages/` → TypeScript protocol, SDK, facade helpers, and presentation packages.
- `apps/controlmesh-web/` → dashboard source and deterministic Bun build.
- `controlmesh/web_static/` → generated dashboard assets bundled in the Python wheel.
- `tests/` → Python, protocol, golden, SDK-facing, security, and integration coverage.
- `docs/` → architecture index, decisions, operational guides, and module detail.
- `plans/` → historical plans and active task memory.

## Entry Points

- `controlmesh` → enhanced terminal and provider-native switching.
- `controlmesh bot` → legacy messaging runtime.
- `controlmesh/__main__.py` → CLI dispatch and configuration startup.
- `controlmesh/orchestrator/lifecycle.py` → orchestrator construction and shutdown.
- `controlmesh/multiagent/supervisor.py` → main/sub-agent stacks and shared services.
- `controlmesh/api/server.py` → WebSocket, file, catalog, and `/api/v1` routes.
- `controlmesh api serve` → standalone localhost-only read-only facade and bundled
  dashboard, without starting a transport runtime.
- `apps/controlmesh-web/` → dashboard source/build; packaged use enters at `/dashboard/`.

## Components

### Runtime and Task Lifecycle

Responsibilities:

- persist task identity, status, binding, timestamps, questions, results, and recovery state;
- implement create, tell, ask_parent, resume, cancel, timeout, and result delivery;
- run approved topology behavior on the shared TaskHub execution seam.

Key locations:

- `controlmesh/tasks/`
- `controlmesh/runtime/`
- `controlmesh/team/`
- `controlmesh/multiagent/`

Python owns all mutation and recovery decisions.

### Provider Execution

Responsibilities:

- discover and authenticate official provider CLIs;
- preserve provider-native process, liveness, timeout, streaming, and session behavior;
- normalize runtime events without letting product clients infer outcomes.

Key location: `controlmesh/cli/`.

### Messaging and Delivery

Responsibilities:

- authenticate and receive transport messages;
- map chats, topics, and users to sessions;
- deliver foreground and background results through `MessageBus` envelopes;
- keep user-visible background output summarized and transport-aware.

Key locations:

- `controlmesh/messenger/`
- `controlmesh/bus/`
- `controlmesh/session/`

### Memory, Workspace, and Artifacts

Responsibilities:

- own local path construction and persisted workspace layout;
- maintain file-backed user memory;
- resolve task folders and artifacts in Python;
- prevent traversal and symlink escape during artifact reads/downloads.

Key locations:

- `controlmesh/memory/`
- `controlmesh/workspace/`
- `controlmesh/api/artifact_access.py`

### Public Protocol and Product Layer

Responsibilities:

- define additive public payload shapes in JSON Schema;
- generate Python and TypeScript models deterministically;
- project Python state through authenticated read-only adapters;
- validate all public SDK JSON responses at runtime;
- render local read-only task, provider, topology, event, and artifact views.
- serve the compiled dashboard from the same local origin as `/api/v1`.

Dependency direction:

```text
JSON Schema
  -> generated Python models -> Python adapters/facade
  -> generated TypeScript models/validators -> SDK -> Web
  -> deterministic Web build -> Python wheel -> localhost /dashboard/
```

TypeScript never constructs private task or artifact filesystem paths.

## Data Flow

### Foreground Turn

```text
message or terminal input
  -> session lookup
  -> orchestrator flow
  -> provider CLI process
  -> normalized events/result
  -> session update and transport response
```

### Background Task

```text
task submission
  -> TaskHub persistence
  -> route/capability and safety gates
  -> provider-backed worker or topology runtime
  -> events/checkpoints/artifacts
  -> ask_parent + resume when needed
  -> summarized result delivery
```

### Read-only Product View

```text
Python history/task/provider read models
  -> protocol adapters
  -> authenticated /api/v1
  -> runtime-validating SDK
  -> local Web dashboard
```

## Important Invariants

- Python is authoritative for runtime behavior and persisted state.
- JSON Schema is authoritative for cross-language public shapes.
- Generated protocol files are never edited directly.
- Legacy `/catalog/*` response shapes remain backward compatible.
- Task statuses, persisted fields, provider/transport names, and relative paths remain
  stable without an approved migration.
- Read-only APIs do not instantiate mutation-capable registries merely to read data.
- Task events are filtered by authoritative task identity.
- Artifact paths stay relative; safe open uses Python-resolved persisted task directories,
  metadata allowlisting, descriptor-relative traversal, and no-follow semantics.
- Web/SDK code cannot read private ControlMesh files or own provider/transport execution.
- Standalone Alpha serving binds to `127.0.0.1`, registers no legacy upload/WebSocket
  mutation routes, and keeps the SDK surface read-only.
- High-risk routing and release/publish behavior stays foreground unless an explicitly
  trusted and approved worker contract allows it.
- `director_worker` and `debate_judge` use typed control decisions, bounded rounds, and
  explicit parent-input boundaries rather than transcript parsing.

## External Dependencies

- Official provider CLIs such as Claude, Codex, Gemini, and OpenCode.
- Messaging APIs for configured transports.
- Python/uv for runtime and tests.
- pnpm, Node, and Bun for protocol generation, SDK tests, and Web build/dev.
- Local files and OS process/service facilities for persistence and operation.

## Fragile Areas

- Provider auth discovery intentionally honors operator environment variables and XDG
  paths; tests that mock user homes must isolate ambient XDG configuration.
- Provider streaming, timeout, liveness, and recovery semantics require golden fixtures
  before any port.
- Task lifecycle mutations span persisted state, events, provider processes, delivery, and
  recovery; SDK smoke tests alone do not establish parity.
- Artifact download security depends on platform support for descriptor-relative no-follow
  opening and fails closed when unavailable.
- The dashboard stores a locally entered token in browser storage and must remain
  local-only until a separate remote-use security decision.
- Transport topic/thread mapping and retry semantics are platform-specific despite shared
  message envelopes.

## Read Next

- Runtime mental model → `docs/system_overview.md`
- Task lifecycle → `docs/modules/tasks.md`
- Orchestration → `docs/modules/orchestrator.md`
- Provider adapters → `docs/modules/cli.md`
- Messaging → `docs/modules/messenger.md`, `docs/modules/bus.md`
- Multi-agent and topologies → `docs/modules/multiagent.md`, `docs/modules/team.md`
- Workspace and memory → `docs/modules/workspace.md`, `docs/modules/memory_v2.md`
- API and protocol migration → `docs/modules/api.md`, `docs/typescript-migration/`
- Configuration and operations → `docs/config.md`, `docs/modules/service_management.md`
- Why these boundaries exist → `docs/DECISIONS.md`
