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

Execution evidence is keyed by the shared `packet_id + task_id + line + plan_id` identity.
The runtime store admits a terminal result only from the persisted plan owner and only for
the latest task episode. An identical retry returns the original event; a conflicting retry
or packet identity drift is rejected before JSONL append. Summary promotion loads that
single current terminal result, admits only `completed`, and rechecks execution, persisted
review, and summary snapshots in the writer's immediate pre-write hook.

### Provider Execution

Responsibilities:

- discover and authenticate official provider CLIs;
- preserve provider-native process, liveness, timeout, streaming, and session behavior;
- normalize runtime events without letting product clients infer outcomes.

Key location: `controlmesh/cli/`.

Every provider-launch path carries one Python-issued `ExecutionContext` containing a
trace id, existing `Origin`, bounded `SourceScope`, transport, and a hashed source
reference.  The context is propagated through the orchestrator, MessageBus injection,
TaskHub/background persistence, cron/webhook one-shot execution, and recovery/resume.
`CLIService._make_cli()` and `infra.task_runner.run_oneshot_task()` are the two final
admission boundaries; both call the same source-aware policy evaluator before provider
construction or command building.

Group messages, bot handoffs, API requests, cron, webhook, and heartbeat work require a
confirmed Docker container.  If setup, recovery, image build, daemon access, or container
start fails, these sources fail closed and never fall back to a host provider process.
Explicit local foreground and direct-message compatibility remains host-compatible.  The
policy decision records normalized sandbox, tool, network, writable-root, and confirmation
posture without storing prompt text, credentials, absolute paths, or raw message IDs.

### Native Session Adoption

The enhanced terminal registers its own foreground CLI service with TaskHub and routes
background results/questions into its file-backed inbox, without a transport bot.

The local terminal `/tasks sessions <query>` reads the Linux/OpenCode source from History
Viewer on loopback port 8787. Candidate identities are cross-checked against the local
OpenCode SQLite store opened read-only. `/tasks inspect <id>` also works without Viewer.
`/tasks adopt` requires an explicit session ID, revision, native directory, target repository,
and provider/model. Only a runtime-issued local-foreground context may enter this path.

TaskHub persists a versioned `native_session` reference alongside its ordinary task identity,
execution context and tool grant. It checks identity/revision before admission and dispatch,
performs a supervised PONG model preflight, and passes the explicit session plus native cwd
to OpenCode. `AgentRequest.working_dir` changes execution cwd; `CLIConfig.runtime_home`
keeps CM environment/state ownership at the original runtime home. Host OpenCode commands
pass `--dir` explicitly so native event subscriptions bind to the execution directory.

Existing cancel/resume paths retain the native session and checkpoint after CM's own turn.
`/tasks recover --task <id> --revision <revision> -- <instruction>` handles stale tasks after
an owner crash: it requires a freshly inspected revision, checks both task and preflight
process leases, retains the original execution grant, and resumes the same TaskHub task.
Active-task checks and an advisory OS lease exclude concurrent CM runs. Other native clients
do not honor this lease: users must stop those clients before adoption. Revision checks detect
intervening changes but do not guarantee exclusion against an unrelated OpenCode process.

Viewer history is discovery evidence, native OpenCode owns conversation continuation,
SpecMesh owns project facts, and CM owns task lifecycle. Historical instructions do not
issue execution grants. The public HTTP/SDK surface stays read-only; container directory
mapping, remote adoption and other native providers are not supported by this first adapter.

### Messaging and Delivery

Responsibilities:

- authenticate and receive transport messages;
- map chats, topics, and users to sessions;
- arbitrate opt-in Feishu multi-bot groups before orchestration so coordinator, exact @,
  broadcast, passive observation, and bot-loop rules have one Python-owned decision seam;
- deliver foreground and background results through `MessageBus` envelopes;
- keep user-visible background output summarized and transport-aware.

Key locations:

- `controlmesh/messenger/`
- `controlmesh/bus/`
- `controlmesh/session/`

The domestic Feishu long connection runs one lifecycle per attempt generation: each
attempt owns its thread, event loop, SDK client, and ping timer, and startup timeout or
stop aborts exactly that attempt by cancelling its connect/ping tasks and joining its
thread. Event dispatch is generation-gated at both the SDK handler and the owner loop, so
a superseded or cancelled connection can never deliver to the owner loop, and a
superseded attempt's cleanup can never disconnect the attempt that replaced it.

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
- Source-aware execution policy is evaluated immediately before provider admission;
  provider/model fallback cannot weaken a required sandbox boundary.
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
  recovery; SDK smoke tests alone do not establish parity. The executable Python oracle at
  `tests/golden/runners/task_lifecycle.py` generates the versioned lifecycle matrix and CI
  checks it for drift. Its JSON Schema is the cross-language fixture-shape authority. The
  private `@controlmesh/runtime-facade` candidate consumes matrix inputs in memory; the
  dual-run gate compares every normalized observation, records JSON-path differences, and
  keeps Python as both production and rollback owner. It is not transport-facing.
- Result writeback and promotion safety is frozen by
  `tests/golden/runners/result_writeback_promotion.py`. Its ten normalized cases exercise
  production Python store/controller paths, and its committed Schema-validated fixture is
  checked for exact inventory and field drift by `pnpm test:golden`.
- Source-aware provider admission is frozen by
  `tests/golden/runners/execution_provenance_sandbox.py`. Its ten normalized cases cover
  trusted compatibility, every unattended/untrusted required scope, sandbox readiness,
  and denial before command construction. The fixture deliberately replaces generated
  trace/source identifiers with placeholders and contains no paths or sensitive input.
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

### OpenCode quota failures

OpenCode enables native error logs on its own stderr. An opt-in one-shot executor observer classifies explicit quota exhaustion and terminates that process tree before native retry loops become generic timeouts. Quota metadata propagates through CLI, stream and agent results while existing task failure/delivery ownership remains unchanged. Provider-reported reset text is not assigned an invented timezone or used to schedule automatic account/model switching. Shared historical log files and assistant/tool output are not quota evidence.

## Runtime migration (in progress)

Full runtime migration is now active in `plans/runtime-convergence/`. The private
`packages/controlmesh-runtime-core/` uses one coordinator-local SQLite transaction domain
for tasks, execution episodes, fencing leases, events, external-effect records, durable
mailboxes and command receipts. It imports strict offline TaskHub snapshots without
constructing the legacy registry or touching task folders. This kernel currently has no
production startup route; provider/transport ownership and `controlmesh_runtime` review/
promotion storage still belong to Python. Its database must not be shared over a network
filesystem. See the package README for implemented behavior and activation gates.

## Codekit integration (v0.43.0)

See [CODEKIT-INTEGRATION](CODEKIT-INTEGRATION.md) for the new module boundary, public invocation and limits. This local implementation does not establish deployment acceptance.
