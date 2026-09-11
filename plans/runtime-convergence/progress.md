# Progress

## Current

Full goal active. A private transactional TS kernel and durable mailbox are implemented in the primary local workspace. CM-R0/R1/R2/R5 remain in progress because runtime integration and their full exit gates are not complete.

## Done

Confirmed current main bd165c1, clean CM worktree, existing Python TaskHub/registry/multiagent owners, and TS candidate's in-memory-only semantics. Restored all roadmap requirements without narrowing the objective.

Implemented `packages/controlmesh-runtime-core` with versioned SQLite transactions, request receipts, task revisions, per-episode device leases/fencing, cancellation, uncertain-result recovery, external-effect dispatch/confirmation and bounded durable mailboxes. Versioned lease/message schemas generate Python and TS definitions through existing tooling. Added an explicit snapshot preview/import CLI and source/serializer drift gate; CI runs `pnpm test:runtime-core`.

Checks: 23 kernel/mailbox/process tests passed, including final atomic-event/reopen regressions (96 assertions). Strict TS typecheck and repository Ruff passed. Existing lifecycle/writeback/grant/provenance goldens passed, including 14/14 facade observations and 22 Python protocol/golden tests; 12 SDK smokes passed; Web bundle rebuilt for the additive generated schemas. Protocol/release-contract tests separately passed 11/11. Source baseline: 512 Python modules and 57 serialized TaskEntry fields. Read-only preview of actual local tasks: one done, two cancelled, no active tasks; no writer switch or task-folder changes.

## Remaining

CM-R0 through CM-R7; coupled History/SpecMesh gates and actual multi-device/native provider acceptance. No full-migration completion is claimed.

## Issues

No blocking condition. Legacy TaskRegistry performs destructive orphan cleanup at construction; import/migration must never construct it against live source data. The old JSON helper treats corrupt inputs as absent, so migration must use strict decoding and preserve all unknown fields.

## Next

Complete the final checks and push this verified source checkpoint to main. Continue with real process supervision and provider/source/grant admission, explicit reconciliation, other persisted stores, device transport, native continuation and SpecMesh hooks. Full production cutover remains pending; do not relabel this kernel checkpoint as full TS migration.
