# ControlMesh Agent Handoff

Last updated: 2026-08-07

## Objective

Close out and commit every approved non-blocked migration-plan item while preserving
Python runtime ownership.

Completed requirements in this work unit: `MW-006`, `PW-006`, `MA-003`, and `PR-004`.

## Current State

Completed:

- JSON Schema source under `schemas/controlmesh/v1/`.
- Generated TypeScript protocol models under `packages/controlmesh-protocol/`.
- Generated Python protocol models under `controlmesh/protocol/generated/`.
- Bearer-protected read-only facade:
  - `GET /api/v1/tasks`
  - `GET /api/v1/tasks/{task_id}`
  - `GET /api/v1/tasks/{task_id}/events`
  - `GET /api/v1/tasks/{task_id}/artifacts`
  - `GET /api/v1/tasks/{task_id}/artifacts/content`
  - `GET /api/v1/providers`
  - `GET /api/v1/topologies`
- TypeScript SDK smoke coverage for tasks, providers, events, artifacts, and protocol errors.
- Read-only Web dashboard for tasks, providers, events, and artifact metadata.
- Bun-native Web build/dev server; no external Vite dependency.
- Repository-level requirements, implementation, agent rules, and handoff documents.
- Repository coordination contract tests that protect these canonical files and their tracking policy.
- Artifact metadata boundary coverage for custom per-agent task directories, symlink escapes, empty/missing folders, disappearing/unreadable files, and absolute-path non-disclosure.
- Planned artifact download OpenAPI contract, 22-case security matrix, and an automated gate proving the route remains unregistered.
- Descriptor-relative artifact safe-open primitive covering strict paths, custom task directories, metadata allowlisting, symlink/TOCTOU containment, missing/unreadable files, and MIME.
- Authenticated artifact content route, corrected SDK download method, and Web download action.
- Ajv-backed runtime validation for every public SDK JSON response and error envelope.
- Python-projected topology endpoint with SDK/Web read-only consumption.
- Python-reference provider success, timeout, error, and ordering golden fixtures.

Python runtime behavior was not moved or rewritten.

## 2026-08-07 Closeout

- Reconciled migration status with the implemented artifact download slice.
- Marked the orchestration topology plan complete based on the landed shared execution
  spine, both deferred topology runtimes, presentation support, and regression coverage.
- Audited tracked and untracked migration files for credentials and generated/runtime
  debris. No real credentials were found; `.omo/` is local session state and is ignored.
- Installed workspace links with `pnpm install`; dependency directories remain ignored.
- Prepared the migration work as reviewable documentation, protocol, Python facade,
  TypeScript product-layer, and verification commits.

## Files Changed In This Work Unit

- `schemas/controlmesh/openapi/controlmesh-admin.v1.yaml`
- `docs/typescript-migration/ARTIFACT_DOWNLOAD_CONTRACT.md`
- `docs/typescript-migration/DECISION_LOG.md`
- `tests/protocol/test_artifact_download_contract.py`
- `controlmesh/api/artifact_access.py`
- `tests/api/test_artifact_access.py`
- `tests/api/test_artifact_download_http.py`
- `controlmesh/api/server.py`
- `controlmesh/api/v1_facade.py`
- `packages/controlmesh-sdk/src/client.ts`
- `packages/controlmesh-sdk/test/client-smoke.test.ts`
- `apps/controlmesh-web/src/main.ts`
- `apps/controlmesh-web/src/styles.css`
- `packages/controlmesh-protocol/src/validation.ts`
- `packages/controlmesh-protocol/package.json`
- `schemas/controlmesh/v1/topology.schema.json`
- `tests/golden/fixtures/providers/`
- `tests/golden/test_provider_golden.py`
- `tests/golden/__init__.py`
- `tests/golden/runners/__init__.py`
- `pnpm-lock.yaml`
- `REQUIREMENTS.md`
- `IMPLEMENTATION.md`
- `docs/typescript-migration/STATUS.md`
- `docs/typescript-migration/IMPLEMENTATION_CHECKLIST.md`
- `HANDOFF.md`

The route streams from the validated descriptor and never accepts absolute paths. The old alpha SDK artifact-ID shape was replaced with the accepted `task_id` plus `relative_path` contract.

## Worktree Context

The migration closeout is organized into reviewable commits. Local dependency links,
build output, caches, and `.omo/` session state are ignored and are not repository truth.

## Last Verified Gates

The migration gates were rerun on 2026-08-07:

```bash
uv run python -m pytest tests/api/test_admin_catalog.py tests/api/test_artifact_access.py tests/api/test_artifact_download_http.py tests/protocol tests/tasks/test_models.py tests/test_repository_coordination.py tests/golden/test_provider_golden.py -q
uv run ruff check controlmesh/api controlmesh/protocol tests/api tests/protocol tests/test_repository_coordination.py
pnpm install
pnpm check:protocol
pnpm test:golden
pnpm test:sdk
pnpm --filter @controlmesh/web build
```

Observed results:

- Python selected suite: 98 passed.
- Ruff: passed.
- `pnpm install`: lockfile already up to date.
- protocol synchronization: passed.
- protocol/golden tests: 12 passed.
- SDK smoke tests: 11 passed.
- Web build: passed.

Additional closeout verification:

```bash
uv run python -m pytest tests/team tests/routing tests/orchestrator/test_task_selector.py tests/orchestrator/test_commands.py tests/bus/test_adapters.py tests/bus/test_bus.py -q
uv run python -m pytest -q
env -u XDG_DATA_HOME -u XDG_CONFIG_HOME uv run python -m pytest tests/cli/test_auth.py::test_check_opencode_auth_config_file_top_level_env_anthropic_auth_token tests/cli/test_auth.py::test_check_opencode_auth_runtime_provider_with_auth_json -q
```

Observed results:

- Topology/routing selection: 433 passed.
- Full Python suite: 5534 passed, 2 failed, 1 warning.
- Both failures were OpenCode auth tests reading the operator's configured
  `XDG_DATA_HOME` instead of the test's mocked home. With `XDG_DATA_HOME` and
  `XDG_CONFIG_HOME` removed, the exact two tests passed (2 passed).
- The warning was the existing unawaited `AsyncMock` warning in
  `tests/cli/test_codex_provider.py::TestSendStreaming::test_streaming_timeout`.

Run the gates again after any code or schema change.

## Known Risks

- Descriptor-relative `O_NOFOLLOW` opening intentionally fails closed on platforms that do not expose the required `dir_fd` capability; artifact download is unavailable there until a comparably safe implementation exists.
- SDK contains mutation-shaped methods, but Python mutating `/api/v1` endpoints are not implemented or approved.
- Golden fixture coverage is still a scaffold; critical create/resume/tell/ask_parent/provider/recovery parity is not complete.
- The Web dashboard stores the locally entered API URL and token in browser local storage; it is local-only but needs a security decision before remote use.
- The two OpenCode auth tests are sensitive to an operator-defined `XDG_DATA_HOME`;
  the implementation gates pass, but the full suite is not environment-hermetic until
  those tests isolate XDG paths.

## Next Work

Make the two OpenCode auth tests hermetic with respect to `XDG_DATA_HOME` and
`XDG_CONFIG_HOME`, without changing production auth discovery behavior. Keep the
completed facade/protocol/SDK/Web gates green. Do not implement blocked mutating task
or transport ownership in TypeScript without a separately approved requirement change
and parity evidence.

Suggested next change title:

```text
Maintain completed migration gates without crossing blocked runtime ownership
```

## Local Processes

A Web dev server was not started in this work unit. `ss -ltn 'sport = :5173'` confirmed that no process is listening on port 5173.

All workspace `node_modules` directories created or reused by verification were removed after the TypeScript gates. `pnpm-lock.yaml` was retained.

Verify current state with:

```bash
curl -I http://127.0.0.1:5173/
```

To restart it:

```bash
pnpm install
pnpm --filter @controlmesh/web dev
```
