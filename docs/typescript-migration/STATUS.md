# TypeScript Migration Status

## Phase 0: Audit And Freeze

- Status: completed.
- Python runtime remains authoritative.
- Protocol schema directory and generated model workflows are active.
- TypeScript protocol package and runtime validators are active.

## Phase B: Protocol And Facade

- Status: read-only v1 facade, artifact metadata hardening, SDK smoke, and Web dashboard read-only slice completed.
- Runtime facade, SDK, plugin API, Feishu UI, and web dashboard scaffolds are present.
- The TypeScript packages are alpha scaffolds and only talk to public/facade APIs.
- No Python runtime behavior has been changed.

### Completed Read-Only Facade Slice

Added read-only `/api/v1` facade endpoints backed by existing Python read models:

- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/events`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/providers`

These endpoints serialize through `controlmesh.protocol.generated` models and do not call or mutate `TaskHub`.

Added SDK smoke tests for:

- `listTasks()`
- `getProviderStatus()`
- `getTaskEvents()`
- `listArtifacts()`
- protocol error envelope mapping.

### Completed Artifact Metadata Hardening

The artifact metadata facade now has fixture-backed coverage proving that:

- persisted custom per-agent `tasks_dir` values locate task folders without constructing `TaskRegistry`;
- symlinks resolving outside the task folder are omitted;
- empty and missing task folders return an empty metadata list;
- files that disappear or cannot be read during metadata inspection are omitted without failing the request;
- responses contain relative artifact paths and do not expose absolute task or artifact paths.

This completes `MW-004`; `MW-005` remains completed. Artifact download was implemented
in the subsequent authenticated download slice described below.

### Completed Artifact Download Contract Slice

The planned `MW-006` boundary is now defined without exposing a route:

- OpenAPI uses `GET /api/v1/tasks/{task_id}/artifacts/content?relative_path=...` and marks it `x-controlmesh-status: planned`.
- `ARTIFACT_DOWNLOAD_CONTRACT.md` defines authentication order, task-folder-only allowlisting, relative-path rules, safe-open requirements, error behavior, MIME, and response headers.
- 22 stable security case IDs cover auth, traversal, custom `tasks_dir`, allowlist, symlink/TOCTOU, missing/unreadable files, MIME, and header injection.
- Protocol tests keep the OpenAPI gate and Markdown matrix synchronized and prove the production route is not registered.
- The alpha SDK artifact-ID download shape is explicitly unsupported because `controlmesh.artifact.v1` has no `artifact_id`.

The unregistered Python safe-open primitive is also complete for 16 of the 22 matrix cases. It validates lexical relative paths, uses persisted custom `tasks_dir`, requires an exact metadata allowlist match, performs descriptor-relative no-follow opens, blocks symlink/TOCTOU replacement, handles missing/unreadable files, and carries Python MIME metadata.

`MW-006` is completed. All 22 security cases pass, the Python route streams only an already validated descriptor, the SDK uses `task_id` plus metadata `relative_path`, and the Web dashboard exposes artifact downloads.

### Completed Validation, Topology, And Provider Golden Slices

- `PW-006`: `@controlmesh/protocol` compiles generated JSON Schemas with Ajv 2020; every public SDK JSON response, list item, SSE event, and error envelope is validated at runtime.
- `MA-003`: Python projects indexed team manifest, worker runtime, task owner, and dependency facts into `controlmesh.topology.v1`; SDK and Web only consume that graph.
- `PR-004`: fake provider success, timeout, error, and event ordering fixtures pass against `ProviderRunSupervisor` as the Python reference.

### Completed Web Dashboard Slice

Completed Web dashboard read-only wiring:

- task list backed by `listTasks()`
- provider status backed by `getProviderStatus()`
- task events backed by `getTaskEvents()`
- artifact metadata backed by `listArtifacts()`
- Bun-based build/dev server with no extra npm registry dependency

### Current Next Step

Review the deferred mutation API admission choices in `MUTATION_API_REVIEW.md`. Do not add
public mutation methods merely because the internal candidate parity gate is green.

## Blocked Runtime Ports

The private TypeScript candidate now consumes the Python task-lifecycle matrix and passes
the digest-bound rollback gate. These production ownership ports remain blocked until an
explicit migration and API-admission decision:

- TaskHub and task state transitions.
- Provider process execution and timeout behavior (provider reference goldens exist; port gates remain).
- Memory writes and promotion.
- Workspace path mutation.
- Transport adapters and message delivery semantics.

## Approved full runtime migration direction (2026-09-11)

The user has approved planning the complete TS runtime port and multi-device coordination. Current Python ownership stays in force until per-area gates pass. [Runtime convergence](../../plans/runtime-convergence/task_plan.md) is the active forward plan; this historical phase ledger does not by itself authorize dual writers or mark pending ports complete.
