# Task: Python Task-lifecycle Golden Parity Matrix

## Goal

Establish an authoritative, deterministic Python golden parity matrix for task lifecycle
behavior covering create, tell, ask_parent, resume, cancel, recovery, workspace, and
artifact semantics, so any future mutation API or TypeScript runtime can prove behavioral
parity before it is allowed to own mutations.

## Context

The read-only Alpha is published and mutation remains intentionally blocked. Existing
Python tests are broad, but future implementations need canonical cross-language fixtures
that capture state transitions, persisted representations, emitted events, path ownership,
and error outcomes rather than relying on scattered unit assertions.

## Requirements

- Derive the matrix from authoritative Python TaskHub/registry/recovery/workspace/artifact
  behavior and existing tests, without changing established lifecycle semantics.
- Cover create, tell, ask_parent, resume, cancel, recovery, workspace, and artifact as
  explicit named cases with stable IDs.
- Capture deterministic inputs, observable outputs, persisted state, emitted events, and
  errors while normalizing timestamps, process IDs, temporary roots, and random IDs.
- Store language-neutral, reviewable golden fixtures and provide one deterministic
  generator/check command that fails on drift.
- Validate schema/fixture shape and prove every required operation has meaningful cases,
  including negative and recovery/path-security behavior where applicable.
- Integrate the parity check into standard pnpm/CI gates and document how future mutation
  implementations consume it.
- Run focused and complete local gates, push, and verify final remote CI.

## Non-goals

- Do not add mutation HTTP endpoints or restore mutation methods to the Alpha SDK.
- Do not move lifecycle ownership out of Python.
- Do not invent behavior that the current Python runtime does not implement.
- Do not snapshot unstable implementation details that are not observable contracts.

## Plan

- [x] Audit Python lifecycle ownership, existing fixtures/tests, and migration requirements.
- [x] Specify the language-neutral matrix schema, normalization rules, and case inventory.
- [x] Implement deterministic Python fixture generation/checking for all eight domains.
- [x] Add contract tests, documentation, package scripts, and required CI integration.
- [x] Execute focused and complete local verification; resolve drift or missing coverage.
- [x] Update durable project memory and task evidence.
- [ ] Commit, push, and verify GitHub Actions on final HEAD.

## Success

- All eight named domains have explicit, meaningful canonical cases.
- Regeneration is deterministic and `check` proves committed fixtures match Python behavior.
- Fixtures expose enough state/event/path/error evidence to judge a future mutation
  implementation, not merely whether a method returned successfully.
- Standard CI requires the parity check.
- Full local and final remote verification are green; worktree matches `origin/main`.

## Status

Current phase: full local verification.

## Next Step

Run full Python and product-layer gates, inspect the final diff, then update handoff evidence.

## Decisions Made

| Decision | Rationale |
|---|---|
| Treat Python execution as the fixture oracle | Project architecture already defines Python as authoritative for mutation and persistence. |
| Store normalized observable behavior, not raw internal files wholesale | Future implementations need a stable parity contract; timestamps, roots, and incidental serialization would create false drift. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Large source/test read was truncated | 1 | Read by exact symbol and small line ranges from now on. |
| First generator run used `type` instead of production event key `event_type` | 1 | Corrected the oracle to read the actual task event envelope. |
| Focused Ruff check found two unused exception imports | 1 | Removed them; the oracle records exception types dynamically. |
