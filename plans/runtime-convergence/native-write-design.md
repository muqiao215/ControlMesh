# Native writes with original-session continuity

Status: implementing. The prior independent SpecMesh increment is published at 3073c7f;
exact-SHA CI 34643193079 passed. Python remains production. An explicit isolated native-write
profile is accepted; normal TaskHub write admission and result reconciliation remain pending.

## Concrete gap

OpenCodeReadContainerRunner always supplies empty writable_roots. OpenCodeExecution pins
read-file identities for the whole turn; native completion and reconciliation assume those
files did not change. Task preparation and result verification have no owned write handoff.
Grant mapping alone cannot establish filesystem enforcement.

OpenCode 1.18.29 edit/write/apply_patch share the edit permission. Its apply_patch source
checks source paths for edit permission and separately processes move destinations. A
literal permission string is therefore insufficient to confine all writes. Preserve actual
container mount enforcement and verify both source/destination observations. Disable native
automatic snapshots, formatting and LSP in the issued profile so repository-defined tools
cannot acquire a new implicit execution path.

## Implementation boundary

1. Capture selected write roots into a private stage, including a consistent before snapshot.
   Keep original repository directory and Git identity. Native container projection overlays
   only staged write roots at their original absolute paths; Git metadata remains read-only.
   Existing source files and required continuity reads retain current-source evidence.
2. Invoke the real native edit/write tools under verified deny-by-default permissions and
   the issued read/write roots. Preserve native session/store/device identity across turns.
   Native file tool results are evidence of activity, not semantic acceptance.
3. Seal a bounded content-addressed proposal after native work stops. Canonical files must
   still match the before snapshot. Agent processes never receive canonical writable mounts.
4. Promote through the current controller's lease with a durable write-ahead journal. Check
   current authority before each canonical change; atomic replacement and fsync protect each
   file. Track partial multi-file application explicitly. Never describe a multi-file change
   as atomic. Recovery compares before/after bytes and resumes only the existing proposal,
   without running the Agent again. Conflicts preserve external edits and remain unresolved.
5. Wire owned local/device lifecycle and current SpecMesh context. Do not promote new file
   assertions to permissions or independently verified closeout. Preserve cancellation and
   unknown outcomes; qualified read behavior and existing persisted manifests stay compatible.

## Acceptance

- Real native create/edit/delete plus second-turn current-file read in the original session.
- Container writes land only in the stage; canonical project and Git metadata stay unchanged
  until controller promotion. Outside-root, symlink and move targets cannot widen grants.
- Capture rejects changed/missing/replaced entries and bounds bytes/entries; dirty baselines
  remain supported. Proposal and stage identity changes revoke promotion.
- Concurrent canonical edits cause conflict before publication; no overwrite of later work.
- Crash before first replace, after a replace but before receipt, and during a multi-file
  change recover from the same journal without another native/model invocation.
- Cancel, stale fence, expired device lease or revoked profile prevents canonical promotion.
- Native failure retains a diagnosable staged result without silently accepting or replaying it.
- Existing read/continuation/device/container/SpecMesh regressions and exact-SHA CI stay green.

The staging/promotion primitives are necessary owners, not completion of the native-write
path. General provider/tool execution, production cutover and installed workflow gates remain
part of the full runtime-convergence goal.

## Verified increment and next integration

The actual OpenCode canary completed two turns in the original directory and native session,
reading all five continuity files each turn and using native edit/write. Independent SQLite
readback confirms the second turn read the first turn's canonical result and recalled the
marker without prompt reinjection. Both staged proposals were applied through kernel leases;
all nine containers are absent. It used a private explicit composition, not the normal
OpenCodeExecution/TaskHub write route. Native deletion is still untested; controller-side
create/edit/delete and recovery are covered by stage tests.

Prepared stage files and directory entries are fsynced before returning a reference; the
immutable basis binds both canonical and prepared snapshots. A fresh staged runner checks
the prepared tree once before attachment. Active native edits are checked against current
canonical source authority, not rejected for changing their own staged output. Constructor
attachment cannot silently resume a partially edited stage as fresh input.

Next extend trusted admission with explicit write roots, retain a versioned write manifest
and bind the sealed proposal before publication. Complete write-aware local completion and
reconciliation first, then device ownership. Existing read manifests remain compatible.
Do not use wildcard native read patterns over existing aliases until the issued read-root
policy denies aliases that resolve outside its scope. Writable projections protect canonical
files; they do not independently enforce the native read permission boundary.
