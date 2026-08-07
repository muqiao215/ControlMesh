# Task: TypeScript Lifecycle Consumer Parity and Rollback Gate

## Goal

Implement an internal-only TypeScript candidate runtime that consumes the canonical Python
task-lifecycle matrix, independently produces normalized observations for every case, and
is admitted only through a dual-run diff plus rollback gate. Public HTTP, SDK, and Web
surfaces must remain read-only. After parity is proven, record a separate review of
authorization, idempotency, and audit requirements for future mutation APIs.

## Requirements

- Parse and validate the committed lifecycle matrix without copying its expected results
  into runtime code.
- Execute all 14 cases across the eight required domains through a candidate TypeScript
  lifecycle implementation and return the same normalized observation shape.
- Run the Python oracle and TypeScript candidate together, produce deterministic structured
  diffs, and fail closed on missing, extra, or mismatched cases.
- Persist a machine-readable rollback-gate result proving candidate status, matrix digest,
  coverage, diff count, and the retained Python owner.
- Expose mutation capability only through an internal in-process facade; do not add HTTP
  routes, public SDK methods, Web mutations, or private-file access from product layers.
- Document the later API review boundary for create/tell/resume/cancel authorization,
  idempotency, audit events, and rollback.
- Integrate the gate into standard CI, run complete verification, push, and verify final CI.

## Non-goals

- Do not transfer production ownership from Python.
- Do not expose mutation APIs over HTTP or the public SDK.
- Do not satisfy parity by echoing `case.expected` from the matrix.
- Do not weaken artifact containment, authentication, or persisted field invariants.

## Plan

- [x] Audit TypeScript runtime/package boundaries and matrix contract.
- [x] Implement internal candidate state machine and all case runners.
- [x] Implement dual-run structured diff and rollback gate artifact.
- [x] Add internal facade and prove public surfaces remain read-only.
- [x] Record mutation API authorization/idempotency/audit review.
- [x] Integrate tests/CI and run complete local gates.
- [ ] Update durable memory, commit, push, and verify final GitHub Actions.

## Success

Every committed Python case has an independently computed matching TypeScript observation;
the dual-run gate is deterministic and green, intentional drift is proven to fail closed,
Python remains the declared production owner, no public mutation surface exists, and the
final local and remote gates are green.

## Status

Current phase: commit, push, and remote CI verification.

## Next Step

Commit and push, then monitor GitHub Actions for the exact final HEAD.

## Decisions Made

| Decision | Rationale |
|---|---|
| Keep the candidate inside the private runtime-facade package | This proves parity without expanding the public HTTP/SDK/Web product surface. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Bun 1.3.14 has no `BunFile.textSync()` | 1 | Use Node-compatible `readFileSync`; retain async Bun writes for the CLI path. |
| Combined Schema/test/docs patch missed a formatted test context line | 1 | Split the change by file and patch against the current formatted source. |
| `pnpm exec tsc` was unavailable because the workspace had no TypeScript compiler dependency | 1 | Add an explicit workspace TypeScript/Bun typecheck toolchain and make candidate typechecking a gate. |
| Internal candidate was included in the Web bundle through the runtime-facade barrel export | 1 | Remove the barrel export; keep imports on the private module path and verify the built dashboard is unchanged. |
