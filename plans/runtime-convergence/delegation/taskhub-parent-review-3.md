# CBC review 3 — remaining attempt integrity defects

Continue the same native CBC session. Primary received CM job cbc-parent-bridge-r2's
actual completed event and exit 0. Its 14 focused tests passed, but acceptance is refused
for the following concrete gaps. Own the same Python bridge/CLI/tests and your result
documents only. Another CBC owns CI; AGY owns TS cron. No cross-owner edits or full suite.

## P1: missing/corrupt intent permits rebinding and another delivery

Primary reproduced on scratch state using actual run_attempt and consume:
1. run job `binding-check`, parent `owner`, command `true` to completed.
2. overwrite that scratch job's DISPATCH.json with `{broken`.
3. run same ID, parent `other-owner`, command `false`.
Result: `unexpected_rebinding=true`, old state `completed`, second parent can consume.

Cause: load_json intentionally maps missing/corrupt/unreadable to None. run_attempt's
no-intent branch then writes a new arbitrary binding and silently adopts any existing
job. Refuse adoption here. Existing job/artifact history without a valid binding needs
explicit migration/review, never implicit claim. Distinguish missing from corrupt,
validate intent schema/ID/required field types, and fail closed without changing evidence.
Bind plan_id/source_task_id and execution definition provenance as well as command/cwd.
Validate job/step identifiers wherever this public API uses them in filesystem paths.
Add concrete corruption/deletion/pre-existing-unbound and changed-provenance tests.

## P1: missing wrapper does not prove children stopped

_finalize_vanished_worker still sets terminal failed with no uncertainty metadata.
The wrapper may be gone while its spawned CLI/children survive. The report's blanket
claim of no resource release is not supported by this projection. Keep explicit
review_required and unknown execution quiescence; do not authorize replay, mark all
resources released, clear the review flag merely because wrapper state is terminal,
or present it as confirmed execution failure. Test a real wrapper/child separation in a
temporary fixture and clean up only the fixture processes after the assertion.

Also avoid `wait --wait-timeout 0` hanging forever on confirmed review-required state
(EPERM, missing PID beyond startup, lost dispatcher before worker starts). Surface a
structured needs-review rejection/status to the waiting parent without synthesizing
successful completion, consuming a future terminal receipt or launching again. Preserve
the ability to reconcile later genuine completion evidence. At-most-once consume is
acceptable for this local CLI scope, and is not full durable-message protocol completion.

## Other exactness

- Inspect runner.start's asynchronous spawn boundary: an intent marked dispatched while
  HOST_JOB remains pending after dispatcher death must become reviewable, never hang
  silently or restart automatically.
- Do not claim exactly-once dispatch under crashes; one execution when uncontended or
  cooperating concurrent callers, no automatic replay under uncertainty is the guarantee.
- Keep implementation bounded and use existing owners. Do not create a desktop callback,
  scheduler or native adoption protocol. Record any local-only lock limitations honestly.

Run only focused bridge tests + Ruff and relevant small regression tests. Save exact
logs `/tmp/cm-parent-bridge-r3-*.log`, update your result with actual code and native
session ID. Do not touch wrapping CM state (primary owns it), production state, accounts,
services, canceled tasks, global config, git commits or remote pushes. Report concise
results; no repeated scans of history/docs. Stop on auth/quota error without retries.
