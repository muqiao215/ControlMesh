# v0.43.0 — Transactional cron state and independent SpecMesh checks

Cron execution status could overwrite a concurrent pause or edit because several writers saved stale registry snapshots. This change makes Manager and bundled cron tools cooperate on locked, fresh field mutations, preserves metadata and rejects conflicting edits. The observer retains task ownership across rescheduling and rechecks current job state before dispatch.

Adds an explicit independent SpecMesh CLI adapter with packaged schemas and runtime validation. Records the approved full TypeScript/multi-device roadmap without changing current Python runtime authority or claiming distributed leases.

Validation: 5,722 full Python regressions; Ruff; real CM CLI -> independent SpecMesh fixture with stale-HEAD rejection; offline wheel resource/dependency checks. Cross-device, Windows locking and future lifecycle hooks remain separately planned.

## Use the independent checker

```sh
controlmesh specmesh check --repo /absolute/project --expected-head FULL_GIT_SHA --specmesh-root /absolute/trusted/SpecMesh
```

The optional tool is provided by SpecMesh distribution v1.2.0, using the draft machine-port contract. The caller chooses trusted code; this is not a general untrusted plugin sandbox.

## Forward plans

See [runtime convergence](plans/runtime-convergence/task_plan.md) for full TS ownership transfer, multi-device coordination and renewed native continuation acceptance. Existing native OpenCode adoption remains available; future cross-device gates remain planned.

## Rollback

Coordinate all cron registry writers before downgrade: older writers can overwrite concurrent pause/status changes. This release performs no persisted-format migration and creates no new schedules. Do not use downgrade as a way to rerun unresolved external operations.
