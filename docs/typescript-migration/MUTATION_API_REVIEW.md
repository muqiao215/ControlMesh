# Mutation API Admission Review

## Status

Deferred. The internal TypeScript candidate matches the Python lifecycle matrix, but no
public mutation API is approved or exposed. Python remains both production and rollback
owner.

## Evidence Available

- Canonical Python matrix: `tests/golden/fixtures/tasks/lifecycle.matrix.json`
- TypeScript dual-run consumer: `packages/controlmesh-runtime-facade/scripts/check-lifecycle-parity.ts`
- Machine rollback gate: `tests/golden/fixtures/tasks/lifecycle.rollback-gate.json`
- Negative exposure checks: OpenAPI contains only GET operations and the public SDK has no
  create/tell/resume/cancel methods.
- Python result-writeback/promotion matrix:
  `tests/golden/fixtures/runtime/result-writeback-promotion.matrix.json`; this hardens
  internal ownership and canonical promotion but grants no transport-facing permission.

Parity is necessary but not sufficient for API admission. A later proposal must satisfy
the following review before changing OpenAPI, SDK, or Web surfaces.

## Shared Admission Requirements

### Authorization

- Define explicit scopes per operation; one broad `tasks:write` scope is insufficient for
  cancel or resume.
- Bind callers to the task's parent agent, chat/topic, and operator identity.
- Re-authorize every request; never trust a browser-stored task object.
- Deny cross-agent and cross-workspace mutation without an explicit delegated capability.

### Idempotency and concurrency

- Require an idempotency key for create and every retryable mutation.
- Persist the key, canonical request digest, result task ID, and expiry under Python
  ownership.
- Same key plus same digest returns the prior result; same key plus a different digest is a
  conflict.
- Define optimistic state preconditions for resume, cancel, and tell so concurrent callers
  cannot silently reorder lifecycle transitions.

### Audit

- Emit append-only audit events for accepted and rejected mutations with operation, caller
  identity, task ID, parent/chat/topic binding, idempotency key, precondition,
  previous/new state, and outcome.
- Never record prompts, parent messages, credentials, absolute paths, or artifact contents
  in the audit envelope.
- Correlate API audit events with task-local and runtime lifecycle events.

### Rollback

- Keep the Python path callable and authoritative throughout any shadow or canary period.
- Fail closed to Python when the matrix digest, candidate gate, or runtime health does not
  match the approved release.
- Rollback must not require persisted-field renames or TypeScript-only reconstruction.

## Operation Review

| Operation | Required authorization | Idempotency/precondition | Required audit evidence |
|---|---|---|---|
| create | Agent/chat/topic plus workspace-create capability | Mandatory idempotency key and request digest | Resolved provider/model, task ID, workspace class; no absolute path |
| tell | Parent/delegate of a currently in-flight task | Expected next sequence or task revision | Assigned sequence, sender identity, outcome; no message body |
| resume | Parent/delegate and provider-session resume capability | Expected terminal/waiting state and session revision | Prior/new state, retained provider/model/session fingerprint |
| cancel | Parent/operator cancel capability, separately scoped | Expected running/detached state; repeated cancel semantics | Prior/new state, process/host-job class, cancellation outcome |

## Decision Required Later

The next API proposal must choose authentication scopes, idempotency retention, task
revision semantics, audit retention/access, canary percentage, and rollback thresholds.
Until explicitly approved, OpenAPI, SDK, and Web remain read-only even though the internal
candidate gate is green.
