# Implementation Checklist Against The Migration Plan

This repository now implements the safe Option B foundation from `controlmesh_typescript_migration_plan(1)..md`.

## Completed In This Change

| Plan item | Status | Files |
|---|---|---|
| Keep Python core authoritative | Done | `docs/typescript-migration/PORTING.md` |
| Migration docs | Done | `PORTING.md`, `MODULE_MAP.md`, `DECISION_LOG.md`, `STATUS.md`, `RUNTIME_CONTRACTS.md`, `PERSISTED_FORMATS.md`, `VERSION_MATRIX.md` |
| JSON Schema protocol source | Done | `schemas/controlmesh/v1/*.schema.json` |
| Task state schema | Done | `schemas/controlmesh/v1/task-state.schema.json` |
| Task/event/provider/artifact/doctor schemas | Done | `schemas/controlmesh/v1/` |
| Transport, ask_parent, memory, topology, config schemas | Done | `schemas/controlmesh/v1/` |
| OpenAPI admin draft | Done | `schemas/controlmesh/openapi/controlmesh-admin.v1.yaml` |
| Generated TypeScript protocol types | Done | `packages/controlmesh-protocol/src/generated/types.ts` |
| Generated Python protocol models | Done | `controlmesh/protocol/generated/models.py` |
| Protocol generators | Done | `packages/controlmesh-protocol/scripts/generate.mjs`, `scripts/generate_protocol.py` |
| npm workspace scaffold | Done | `package.json`, `pnpm-workspace.yaml`, `tsconfig.base.json` |
| SDK scaffold | Done | `packages/controlmesh-sdk/` |
| Runtime facade client scaffold | Done | `packages/controlmesh-runtime-facade/` |
| Plugin API scaffold | Done | `packages/controlmesh-plugin-api/` |
| Feishu card pure helper scaffold | Done | `packages/controlmesh-feishu-ui/` |
| Web dashboard scaffold | Done | `apps/controlmesh-web/` |
| Golden test directory scaffold | Done | `tests/golden/` |
| Protocol tests | Done | `tests/protocol/test_protocol_schema.py` |
| Read-only v1 facade | Done | `controlmesh/api/v1_facade.py`, `controlmesh/api/protocol_adapters.py` |
| Artifact metadata boundary hardening | Done | `controlmesh/api/v1_facade.py`, `controlmesh/api/protocol_adapters.py`, `tests/api/test_admin_catalog.py` |
| Artifact download contract and exposure gate | Done (design only) | `schemas/controlmesh/openapi/controlmesh-admin.v1.yaml`, `ARTIFACT_DOWNLOAD_CONTRACT.md`, `tests/protocol/test_artifact_download_contract.py` |
| Unregistered artifact safe-open primitive | Done (16/22 security cases) | `controlmesh/api/artifact_access.py`, `tests/api/test_artifact_access.py` |
| Authenticated artifact download | Done (22/22 security cases) | `controlmesh/api/v1_facade.py`, `controlmesh/api/server.py`, `tests/api/test_artifact_download_http.py` |
| Artifact download SDK and Web wiring | Done | `packages/controlmesh-sdk/`, `apps/controlmesh-web/` |
| TypeScript runtime response validation | Done | `packages/controlmesh-protocol/src/validation.ts`, `packages/controlmesh-sdk/src/client.ts` |
| Python-projected topology facade | Done | `controlmesh/api/protocol_adapters.py`, `controlmesh/api/v1_facade.py`, `packages/controlmesh-sdk/`, `apps/controlmesh-web/` |
| Provider reference golden fixtures | Done | `tests/golden/fixtures/providers/`, `tests/golden/test_provider_golden.py` |
| Python task-lifecycle parity matrix | Done | `tests/golden/fixtures/tasks/lifecycle.matrix.json`, `tests/golden/test_task_lifecycle_golden.py` |
| TypeScript lifecycle consumer and dual-run rollback gate | Done (internal only) | `packages/controlmesh-runtime-facade/src/lifecycle-parity.ts`, `tests/golden/fixtures/tasks/lifecycle.rollback-gate.json` |
| SDK smoke tests | Done | `packages/controlmesh-sdk/test/client-smoke.test.ts` |
| Web dashboard read-only wiring | Done | `apps/controlmesh-web/src/main.ts`, `apps/controlmesh-web/src/styles.css` |

## Deliberately Not Changed

These items are intentionally not ported because the plan marks them as high-risk runtime behavior:

- `TaskHub`
- provider CLI runners and timeout behavior
- file-backed memory writes and promotion
- artifact writer and workspace path resolver
- transport send/receive adapters
- background restart and recovery loops
- systemd/deployment behavior

## Completed Read-Only Facade Slice

This slice added a read-only API facade:

- Convert existing catalog task rows into `controlmesh.task.v1`.
- Convert indexed runtime events with `payload.task_id` into `controlmesh.task_event.v1`.
- Convert Python-resolved task artifact files into `controlmesh.artifact.v1` metadata.
- Convert provider info into `controlmesh.provider_capability.v1`.
- Expose `/api/v1/tasks`, `/api/v1/tasks/{task_id}`, `/api/v1/tasks/{task_id}/events`, `/api/v1/tasks/{task_id}/artifacts`, and `/api/v1/providers`.
- Keep legacy `/catalog/*` endpoints unchanged.
- Add SDK smoke tests for task list, provider status, task events, artifact metadata, and protocol errors.

## Completed Web Dashboard Slice

The Web dashboard now uses the SDK to render:

- tasks from `listTasks()`
- providers from `getProviderStatus()`
- task events from `getTaskEvents()`
- artifact metadata from `listArtifacts()`

The app uses a Bun build/dev-server script to avoid adding external frontend dependencies while npm registry access is unreliable.

## Next Implementation Slice

The artifact metadata edge-case slice is complete:

- custom per-agent `tasks_dir` is covered through the facade;
- symlink escapes, empty/missing folders, disappearing/unreadable files, and absolute-path non-disclosure are covered;
- `MW-004` and `MW-005` are completed.

All approved read-only migration slices and the internal lifecycle candidate gate are complete. The candidate matches 14/14 Python cases, but Python remains production/rollback owner and public mutation APIs remain blocked pending `MUTATION_API_REVIEW.md` approval.

## Verification Commands

```bash
pnpm check:protocol
pnpm test:golden
pnpm test:sdk
pnpm --filter @controlmesh/web build
uv run python -m pytest tests/api/test_admin_catalog.py tests/protocol tests/tasks/test_models.py tests/test_repository_coordination.py -q
uv run ruff check controlmesh/api controlmesh/protocol tests/api tests/protocol tests/test_repository_coordination.py
```
