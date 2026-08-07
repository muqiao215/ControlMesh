# ControlMesh Implementation Guide

This file explains how the repository is implemented and how approved work should be added. Requirements live in `REQUIREMENTS.md`; current execution state lives in `HANDOFF.md`.

## Architecture

```text
Chat / Terminal / Web
        |
        v
Python entry points and transport adapters
        |
        v
Orchestrator / TaskHub / AgentSupervisor
        |
        +--> provider CLI runners
        +--> runtime events and history index
        +--> workspace, memory, task folders, artifacts
        |
        v
read-only Python /api/v1 facade
        |
        v
TypeScript protocol -> SDK -> Web dashboard
```

### Ownership Boundaries

| Layer | Authoritative implementation | May mutate runtime state? |
|---|---|---:|
| Task lifecycle and recovery | Python `controlmesh/tasks/` | yes |
| Provider process execution | Python `controlmesh/cli/` | yes |
| Transport adapters | Python `controlmesh/messenger/` | yes |
| Memory and workspace writes | Python `controlmesh/memory/`, `controlmesh/workspace/` | yes |
| Runtime/history read model | Python `controlmesh/runtime/`, `controlmesh/history/` | derived/read-only where used by facade |
| Public protocol shapes | JSON Schema `schemas/controlmesh/v1/` | no |
| Protocol adapters | Python `controlmesh/api/protocol_adapters.py` | no |
| Read-only facade | Python `controlmesh/api/v1_facade.py` | no |
| SDK and Web | TypeScript `packages/`, `apps/` | no, until separate approval gates pass |

## Repository Map

```text
REQUIREMENTS.md                 product and engineering requirements
IMPLEMENTATION.md               architecture and implementation method
HANDOFF.md                      current agent-to-agent state
AGENTS.md                       stable operating instructions

controlmesh/                    Python application and runtime
controlmesh_runtime/            independent runtime contracts/engine
schemas/controlmesh/v1/         cross-language schema source
packages/controlmesh-protocol/  generated TypeScript protocol
packages/controlmesh-sdk/       TypeScript client
packages/controlmesh-runtime-facade/ HTTP/SSE helpers
apps/controlmesh-web/           local read-only dashboard
tests/protocol/                 schema/generation checks
tests/golden/                   parity fixtures and runners
docs/typescript-migration/      migration-specific decisions and status
plans/                          program/line/task execution records
```

## Protocol Workflow

Cross-language payload changes follow this sequence:

1. Update `schemas/controlmesh/v1/*.schema.json`.
2. Run both generators:

   ```bash
   pnpm generate:all-protocol
   ```

3. Add or update the Python adapter in `controlmesh/api/protocol_adapters.py`.
4. Add facade tests that validate schema version, required fields, unknown-field policy, auth, and failure envelopes.
5. Update SDK behavior and smoke tests.
6. Update Web only through SDK calls.
7. Run `pnpm check:protocol` to prove generated files are synchronized.

Rules:

- Protocol payloads keep snake_case Python field names.
- Additive fields are preferred; public/persisted fields are not silently renamed or removed.
- IDs stay strings at the public boundary unless existing transport contracts permit string/integer references.
- Relative paths remain relative.
- TypeScript never derives task or artifact filesystem paths.
- Unknown fields remain allowed at forwarding boundaries.

## Read-Only Facade

Current endpoints:

| Endpoint | Source | Protocol |
|---|---|---|
| `GET /api/v1/tasks` | derived task catalog | `controlmesh.task.v1` list |
| `GET /api/v1/tasks/{task_id}` | derived task catalog | `controlmesh.task.v1` |
| `GET /api/v1/tasks/{task_id}/events` | indexed runtime events filtered by `payload.task_id` | `controlmesh.task_event.v1` list |
| `GET /api/v1/tasks/{task_id}/artifacts` | Python-resolved persisted task folder | `controlmesh.artifact.v1` list |
| `GET /api/v1/tasks/{task_id}/artifacts/content` | descriptor-safe Python artifact opener | binary content |
| `GET /api/v1/providers` | Python provider info | `controlmesh.provider_capability.v1` list |
| `GET /api/v1/topologies` | Python-projected indexed team state | `controlmesh.topology.v1` list |

The facade:

- requires Bearer authentication;
- returns `controlmesh.error.v1` envelopes;
- uses `asyncio.to_thread` for file/index reads;
- does not instantiate `TaskRegistry` for read operations;
- does not call TaskHub or provider execution paths;
- does not expose absolute paths.

## Artifact Implementation

Artifact metadata is resolved as follows:

1. Read the requested task from the derived catalog.
2. Read persisted `tasks_dir` from `tasks.json` through `AdminHistoryCatalogReader.task_folder()`.
3. Walk files under that task folder in Python.
4. Resolve both task folder and candidate path.
5. Omit any candidate that is not a regular file or resolves outside the task folder.
6. Return only task ID, relative path, name, MIME, size, and timestamp.

Authenticated artifact download is exposed only through `GET /api/v1/tasks/{task_id}/artifacts/content?relative_path=...`. Its tests cover traversal, symlink escapes, missing files, token failures, custom task directories, allowlisting, MIME, and safe response headers.

The contract and required security cases live in `docs/typescript-migration/ARTIFACT_DOWNLOAD_CONTRACT.md`; the OpenAPI operation is marked active. The accepted identifier is `task_id` plus the exact metadata `relative_path`; absolute paths and artifact IDs are not part of the contract.

`controlmesh/api/artifact_access.py` owns the unregistered safe-open primitive. It validates the public relative path, requires an exact metadata allowlist match, resolves persisted custom task directories through the read-only catalog, and opens each path component relative to a directory descriptor with symlink following disabled. Callers receive an already opened binary stream; they must not reopen its pathname.

## TypeScript Workspace

The workspace uses `pnpm` for local package linking and Bun for TypeScript tests/builds.

```text
@controlmesh/protocol
        ^
        |
@controlmesh/runtime-facade <- @controlmesh/sdk <- @controlmesh/web
```

Common commands:

```bash
pnpm install
pnpm check:protocol
pnpm test:sdk
pnpm --filter @controlmesh/web build
pnpm --filter @controlmesh/web dev
```

The Web server binds to `127.0.0.1:5173` by default. The user supplies the Python API URL and token locally.

## Testing Strategy

### Required For Python Facade Changes

```bash
uv run python -m pytest tests/api/test_admin_catalog.py tests/protocol -q
uv run ruff check \
  controlmesh/api/protocol_adapters.py \
  controlmesh/api/v1_facade.py \
  controlmesh/api/admin_read.py \
  controlmesh/api/server.py \
  tests/api/test_admin_catalog.py \
  tests/protocol
```

### Required For Protocol/SDK/Web Changes

```bash
pnpm check:protocol
pnpm test:golden
pnpm test:sdk
pnpm --filter @controlmesh/web build
```

### Runtime Port Gate

No module is behavior-equivalent until Python reference output and TypeScript output match shared canonical fixtures after documented normalization. Happy-path SDK tests do not authorize a runtime port.

## Work Method

Every meaningful change should follow:

```text
requirement -> design boundary -> test/fixture -> implementation -> verification -> handoff
```

During implementation:

- update requirement status only when acceptance criteria actually pass;
- keep one active next step in `HANDOFF.md`;
- record decisions that affect compatibility in `docs/typescript-migration/DECISION_LOG.md`;
- keep task-local evidence under `plans/tasks/<task-id>/` when work is delegated;
- do not mix unrelated refactors into migration changes.

## Rollback Model

The TypeScript product layer is optional. If it fails:

- stop the Web server;
- stop consuming `/api/v1` endpoints;
- keep Python terminal, bot, TaskHub, providers, memory, and workspaces unchanged;
- regenerate protocol files from schemas if generated outputs drift;
- do not repair Python runtime data from TypeScript.
