# Native writes with original-session continuity

Status: in_progress. Normal local candidate TaskHub write/completion/reconciliation is
implemented and accepted with real OpenCode 1.18.29/M3. Device-local writes and recovery
also have actual ARM64-coordinator/x64-worker acceptance; normal device startup and other
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

1. Normal coordinator/worker startup, assignment and recovery control must expose the
   qualified device writer through explicit configuration. The present device script is a
   synthetic canary entrypoint; library acceptance does not close the product workflow.
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


## Accepted device integration

Trusted device options select relative write roots and optional independent SpecMesh. The
shared native runner stages and seals; the device journal retains full evidence. Wire
references carry only a write-profile digest and workflow binding. Completion/reconciliation
must include the matching published-proposal proof; read results cannot silently substitute.

Before normal publication, DeviceWorker drains an in-flight heartbeat and renews the actual
coordinator lease. Before recovered publication it fetches the same current challenge again.
Every local file operation still checks the conservative monotonic deadline, original local
workspace/profile and journal. Network failure, coordinator cancellation/revocation or stale
assignment before confirmation prevents publication. A leased operation can have applied
files before later cancellation/result loss; this remains explicitly recoverable uncertainty,
not an impossible claim of instantaneous remote revocation or distributed batch atomicity.

Tests cover normal writes and native continuation, lost observation before publication,
partial publication, lost completion/recovery acknowledgement, repeated recovery without
another native call, changed registration/files/workflow, cancellation/revocation/partition,
expired challenge/lease, proof omission/substitution and existing read-only behavior. Local
and device invalid-layout tests clear readiness first and verify zero provider commands.
A separate fixture verifies 86 in-scope reads; read_count is an aggregate safe integer, not
the old required-read list limit or a new authority grant.

The actual ARM64 coordinator/x64 native worker canary passed two turns, observation loss,
coordinator/local reconstruction, original-proposal recovery and original-session recall.
Five required continuity reads and two edits/one write were observed per turn. Independent
readback verifies stage lineage 1 -> 2 -> 3 and cleanup; exact counts and initial fixture
failure are recorded in progress.md. General native apply_patch/delete/move are still fixture
coverage, and the device report authenticates the worker rather than proving a compromised
worker honest. SpecMesh remains independent and does not claim reviewed semantic closeout.
