# Agent Operating Rules

Every agent taking over this repository must read these files in order:

1. `REQUIREMENTS.md`
2. `IMPLEMENTATION.md`
3. `HANDOFF.md`
4. the relevant line-specific plan or migration status document

## Repository Truth

- Requirements are authoritative in `REQUIREMENTS.md`.
- Architecture and implementation method are authoritative in `IMPLEMENTATION.md`.
- Current state and next work are authoritative in `HANDOFF.md`.
- JSON Schema is authoritative for cross-language payload shape.
- Python is authoritative for runtime behavior.
- Chat history is context, not project truth.

## Before Editing

- Run `git status --short` and preserve existing worktree changes.
- Read the modules and tests that own the requested behavior.
- Resolve requirement IDs affected by the change.
- Confirm whether the change is read-only, mutating, persisted, transport-facing, or provider-facing.
- Do not assume generated files are hand-written.

## Change Rules

- Keep changes scoped to the active requirement and ownership boundary.
- Do not rename persisted fields, task statuses, provider names, transport names, or relative paths without an approved migration.
- Do not move Python runtime ownership into TypeScript without golden parity and rollback gates.
- Do not let Web or SDK code read private ControlMesh files directly.
- Do not expose absolute artifact paths.
- Do not commit secrets, credentials, `.env` files, auth profiles, caches, virtual environments, runtime logs, or dependency directories.
- Collaboration documents, task plans, findings, progress, evidence, and lockfiles are intended to be tracked.

## Required Handoff Discipline

Before ending a work unit, update `HANDOFF.md` with:

- objective and requirement IDs;
- files changed;
- behavior completed;
- exact verification commands and results;
- known risks or unverified areas;
- one concrete next step;
- whether any local server/process is running.

Do not mark work complete based only on code inspection. State clearly when tests could not run.

## Standard Verification

Python facade/protocol work:

```bash
uv run python -m pytest tests/api/test_admin_catalog.py tests/protocol tests/tasks/test_models.py -q
uv run ruff check controlmesh/api controlmesh/protocol tests/api tests/protocol
```

TypeScript protocol/SDK/Web work:

```bash
pnpm install
pnpm check:protocol
pnpm test:golden
pnpm test:sdk
pnpm --filter @controlmesh/web build
```

Use narrower commands while iterating, then run the relevant full gate before handoff.

## Forbidden Shortcuts

- Do not edit generated protocol models directly.
- Do not instantiate mutation-capable registries solely to serve read-only APIs.
- Do not weaken authentication or path containment to make a test pass.
- Do not add a mutating TypeScript endpoint because an SDK method already exists.
- Do not delete unrelated user changes or reset a dirty worktree.
- Do not treat ignored files as the only place for important project state.
