# Native writes with original-session continuity

Status: in_progress. Normal local candidate TaskHub write/completion/reconciliation is
implemented and accepted with real OpenCode 1.18.29/M3. Device write ownership and other
profiles remain pending. Python v0.43.0 remains production; see progress.md for publication.

## Owner and implementation

- `local-runtime-config.ts` accepts optional trusted `workspace.write_roots` and composes
  `OpenCodeStagedContainerRunner` with `OpenCodeTaskAdapter`/`OpenCodeWorker`. Empty/absent
  roots retain the read profile. Task bodies cannot issue roots, grants or workflow bindings.
- `native-workspace.ts` normalizes bounded canonical roots, requires representable native
  grants and constructs explicit root read/edit patterns. Git metadata and existing aliases
  are denied. OpenCode edit/write/apply_patch share native edit permission; a narrower portable
  grant is rejected. Patch observations must account for source and move destination.
- `WorkspaceStage` snapshots selected roots into private storage and overlays them at the
  original paths inside Docker. Canonical files are not native writable mounts. Prepared
  files/directories are fsynced and bound to the first runner attachment. Native snapshots,
  formatters and LSP are disabled in the issued profile.
- `OpenCodeExecution` persists a version-2 dispatch manifest with roots, stage basis,
  permission evidence and optional independent workflow binding. After the native process
  stops, it seals a content-addressed proposal and verifies actual completed native file
  tools against every changed path before retaining the original observation. Native tool
  activity proves execution evidence, not semantic correctness.
- Execution-time snapshot checks and publication-time authority are separate. Only the
  current controller publisher may rename canonical files. The journal records per-file
  intent, replacement and fsync; a batch can be partially applied and is never claimed atomic.
  Changed canonical files conflict instead of overwriting unrelated edits.
- `SpecMeshPort.bind` rechecks the independent current-checkout snapshot after owned changes,
  allowing the Agent to update continuity documents within its issued roots. Required read
  registration must still cover the returned references. Structural pass does not establish
  independent reviewed closeout; results explicitly retain `closeout_verified: false`.

## Recovery and command identity

The private local control exposes `inspect_reconciliation` and `reconcile_task` using the
original task revision and exact episode/effect/manifest/observation digests. Inspection
requires no native credentials or model probe. Acceptance revalidates current configured
source, grant, runner, native session and retained proposal; it holds the native lease
through publication and asynchronous workflow checks. Dropping or replacing the original
workflow binding rejects. No prompt or substitute workspace is accepted from the request.

Schema 13 persists command reservations before any recovery publication or asynchronous
check. The original operation/body/principal/origin/device identity cannot be reused for
another operation while acceptance is pending, including after restart. Successful completion
consumes the reservation and stores the final receipt in one SQLite transaction. Replay
returns the original receipt and repairs queue bookkeeping without repeating native work.

`NativeResultVerification` validates the exact sealed receipt and actual native read/edit/
write/apply_patch paths. `NativeReconciler.acceptWorkspace` resumes only the retained proposal.
A crash after rename but before journal acknowledgement compares before/after state and
acknowledges the already applied file without rewriting it. Cancellation, changed revisions,
revoked grants, changed files/native history or missing evidence retain an unknown outcome.
Read manifests and synchronous read recovery remain compatible.

## Verified acceptance

Real normal-local TaskHub acceptance completed two turns in one native session. Each turn
read five required continuity files, edited code and PROJECT, and wrote a result; the counter
advanced 1 -> 2 -> 3 with marker recall and no prompt reinjection. A deliberately failed
completion after publication recovered after runtime reopen with unchanged inode and no new
native message. Independent readback confirms two completed runs/effects, one reconciliation
and nine absent containers. Both current SpecMesh structural checks passed.

The native run used schema 12; current schema-13 code then upgraded that exact isolated state
and replayed its original receipt without new events, containers or native messages. Focused
tests cover request reservation/conflict/restart, partial publication, concurrent canonical
edits, cancellation, missing tool evidence, denied aliases, workflow failure and schema
migration. The real native model exercised edit/write; apply_patch/delete/move remain fixture
coverage until a suitable real-provider acceptance runs. See progress.md for current totals.

## Remaining scope and limits

1. Device-local publication must be bound to current coordinator assignment/fence, with
   disconnect/restart recovery and a real two-device write acceptance. The existing device
   adapter is qualified for reads; local success does not authorize remote writes.
2. Staging is bounded to 64 MiB total, 4 MiB/file, 2,048 entries, 64 roots and a 2 MiB private
   record. Large-project/dependency/cache exclusion and general workspace cleanup are not
   qualified. Scoped roots are supported; do not silently increase limits or copy secrets.
3. Failure before an immutable sealed receipt exists is diagnosable but not automatically
   acceptable. Abandonment/recovery ownership is still required; never retry uncertain Agent
   execution merely because no final task receipt exists.
4. General provider/tool/shell/source/approval profiles, reviewed semantic closeout,
   transport/store/topology/product owners and production release/install cutover remain
   required by the full runtime-convergence plan. Native clients outside CM do not honor
   its advisory session locks.
