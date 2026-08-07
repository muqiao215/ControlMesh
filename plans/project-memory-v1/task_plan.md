# Task: Adopt Project Memory and Development Standard v1.0

## Goal

Replace the repository's overlapping coordination documents with a concise,
progressively loaded project-memory system, verify it, and then begin the highest-priority
development task.

## Context

The repository recently added requirements, implementation, handoff, migration, and plan
documents. They contain useful truth but make a new session load too much context and
duplicate current state. The user approved a smaller memory model centered on `PROJECT.md`,
`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and task-local planning files.

## Requirements

- Install `planning-with-files` once under `~/.local/share` and expose it through
  `~/.agents/skills` and a Claude-compatible symlink.
- Make `AGENTS.md` the stable startup protocol and add a minimal `CLAUDE.md` shim.
- Add concise `PROJECT.md`, `docs/ARCHITECTURE.md`, and `docs/DECISIONS.md` indexes.
- Preserve durable requirements, architecture boundaries, decisions, current state, and
  verification knowledge while removing duplicate authority.
- Keep complex-task memory under `plans/<task>/task_plan.md`, `findings.md`, and
  `progress.md`.
- Verify documentation links, repository coordination rules, and the relevant code gates.
- Begin the current highest-priority development task only after the documentation system
  is coherent.

## Non-goals

- Do not introduce agent roles, harness configuration, evidence bureaucracy, or empty plan
  structures.
- Do not change Python runtime ownership or expose TypeScript mutation APIs.
- Do not rewrite historical plan documents merely for stylistic consistency.

## Plan

- [x] Install and inspect the global `planning-with-files` skill.
- [x] Inventory durable knowledge and duplicated authority in current documentation.
- [x] Create the new progressive memory files and update documentation links.
- [x] Retire superseded repository-truth documents without losing durable knowledge.
- [x] Update repository coordination tests for the new standard.
- [x] Verify documentation and migration gates.
- [ ] Commit and push the documentation migration.
- [ ] Create the next task plan and begin the XDG-hermetic test fix.

## Success

- A new agent can start with `AGENTS.md`, understand intent from `PROJECT.md`, and load
  architecture, decisions, or active task files only when needed.
- There is one clear authority for intent, architecture, decisions, and current work.
- Repository tests enforce the new structure.
- The first development task is active with its own three planning files.

## Status

Current phase: delivery.

## Next Step

Commit and push the verified project-memory migration.

## Decisions Made

| Decision | Rationale |
|---|---|
| Store task files in `plans/<task>/` | The user-defined repository convention overrides the skill's generic default location. |
| Keep the skill checkout outside the repository | One user-level source of truth serves Codex, OpenCode, and Claude without project copies. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Initial GitHub page read returned no rendered content | 1 | Installed from the user-approved upstream and read the checked-out `SKILL.md` directly. |
