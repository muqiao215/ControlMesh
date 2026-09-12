# Codekit integration in v0.43.0

## Ownership and implemented boundaries
CM remains the task execution authority. This batch does not install the kit's second SQLite TaskHub or replace the Python runtime with its TypeScript prototype.

`controlmesh/cron/guarded_store.py` provides atomic JSON transactions under a shared sidecar lock. Manager CRUD, scheduled/manual status updates, and bundled cron tools now cooperate on this store. Tool snapshots use field-level three-way comparison: unrelated pause/status changes survive; concurrent edits to the same field fail explicitly. Unknown metadata survives. Corrupt registries are rejected rather than overwritten. All writers must participate; external legacy scripts that overwrite JSON remain a deployment concern. Folder changes and registry commits are not one filesystem transaction.

`controlmesh/cron/observer.py` retains the active task handle during rescheduling, verifies ownership and freshly loaded enabled state at wakeup, prevents duplicate execution within this observer, and schedules the successor using current configuration. This is not a distributed lease: multiple running CM processes can still dispatch the same job. No production schedule was changed.

## Independent SpecMesh adapter
From an environment with CM dependencies installed:

```sh
python -m controlmesh specmesh check --repo /absolute/project --expected-head FULL_GIT_SHA --specmesh-root /absolute/trusted/SpecMesh
```

`--task plans/task-name` additionally requires that task's continuity files. Other operations: inspect, prepare_handoff, verify_closeout. The adapter calls the independent `specmesh_port` subprocess with bounded timeout and validates request/result schemas. Error findings, stale HEAD, malformed output, or unknown closeout cannot be promoted to success. Schemas are bundled for installed packages and mirrored in `schemas/controlmesh/specmesh/`.

This explicit command does not initialize TaskHub, automatically gate task submission, run arbitrary untrusted plugins, or resume an Agent. The caller selects a trusted code root. Byte output checks happen after capture and are not a hostile-plugin resource sandbox. Cross-device coordination, provider quota lifecycle and general plugin admission remain separate work.

## Validation and continuation
Affected cron, adapter and main CLI regressions are recorded in the workspace implementation report. Linux locking is exercised; the Windows locking branch needs platform acceptance. Next: review the local diff and reconcile any newer source HEAD before integration. Add dispatch hooks only with explicit gate semantics and tests through real TaskHub submission paths.

## Candidate TS local submission: explicit requirement adoption

With trusted `specmesh.requirements_path` configured, private local `submit` accepts
`specmesh_requirements_sha256` alongside `task`. The caller supplies the source hash
it has selected. The control reads a fresh standalone snapshot, rejects a stale hash
or conflicting task completion requirements, then synchronously revalidates before
normal ingress submission. It persists `completion_requirements` and an
`asserted_candidate` source record (`specmesh_completion_source`, path/hash/snapshot).
Caller-supplied source records are rejected by this control entrypoint. This record
is provenance metadata, never a grant or a completed-task claim. Native task digests
and artifact checks bind the adopted completion requirements through existing paths.

Omitting the adoption field preserves ordinary submission. Unsupported completion
providers still fail at ingress (currently only Claude is qualified). Submission does
not enqueue, probe a model, create artifacts, or enlarge permissions. Identical retries
are idempotent while the source snapshot remains current; changed source fails rather
than silently replacing the accepted contract. This is a candidate runtime interface,
not a Python production or public Web API change.

### Device coordinator adoption

The candidate coordinator accepts optional trusted configuration
`specmesh: { workspace, configuration }`, where `workspace` is the coordinator's
canonical project checkout and `configuration` is the independent port profile
(including `requirements_path`). Its private `submit` accepts the same
`specmesh_requirements_sha256` as local control. Both use one adoption implementation.
The coordinator persists the exact contract before assignment; the existing portable
execution projection carries it to workers without the coordinator's absolute path
or source metadata. Workers retain their independently configured workspace mapping
and permissions. Source requirements are frozen at submission; this does not claim
that coordinator and worker Git revisions/content are identical. Full code-revision
coordination remains a separate acceptance gate.

The optional port is owned by coordinator shutdown. Without this trusted profile,
explicit adoption fails; ordinary submissions retain their existing behavior. Tests
cover reopen/idempotency, stale hashes and actual loopback queue projection, with no
provider input or output file creation.
