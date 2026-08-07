# Project Instructions

## Start Here

First read:

1. `PROJECT.md`

Then read only what the task requires:

- Architecture and ownership boundaries → `docs/ARCHITECTURE.md`
- Historical decisions and rejected directions → `docs/DECISIONS.md`
- Active substantial work → the relevant `plans/<task>/` directory

Do not load unrelated documentation by default. `docs/README.md` is a catalog, not a
required reading list.

## Project Memory

Conversation history is context, not project memory.

Update `PROJECT.md` only when confirmed user intent, priorities, constraints, non-goals,
or project stage changes.

Update `docs/ARCHITECTURE.md` when durable knowledge about how the system works or who owns
behavior changes.

Update `docs/DECISIONS.md` when an important choice is made that a future agent may
otherwise revisit.

For substantial work that spans multiple files, requires investigation, or may cross
sessions, maintain:

- `plans/<task>/task_plan.md`
- `plans/<task>/findings.md`
- `plans/<task>/progress.md`

Use the globally installed `planning-with-files` skill for this workflow. Keep transient
discoveries in task findings; promote only durable knowledge into project documents.

## Before Editing

- Run `git status --short` and preserve existing changes.
- Read the modules and tests that own the requested behavior.
- Determine whether the change is read-only, mutating, persisted, transport-facing, or
  provider-facing.
- Do not assume generated files are hand-written.

## Development

- Use existing development, testing, review, and validation mechanisms.
- Keep changes inside the active ownership boundary.
- Do not silently reinterpret or weaken user requirements.
- Do not rename persisted fields, task statuses, provider names, transport names, or
  relative paths without an explicit migration.
- Python owns runtime behavior. JSON Schema owns cross-language payload shape. TypeScript
  product layers do not write private runtime files.
- Do not expose absolute artifact paths or weaken authentication/path containment.
- Do not commit secrets, credentials, `.env` files, auth profiles, caches, virtual
  environments, runtime logs, dependency directories, or local agent session state.
- Before reporting completion, run verification proportional to the change and record the
  exact result in the task progress file.

## Documentation

Keep documentation concise and linked rather than duplicated.

- Code explains implementation.
- `PROJECT.md` explains intent and current direction.
- `docs/ARCHITECTURE.md` explains the durable system map and invariants.
- `docs/DECISIONS.md` explains why important choices were made.
- Task files explain the current work only.

Do not introduce new process or infrastructure unless a real task requires it.
