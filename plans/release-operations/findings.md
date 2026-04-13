# Confirmed Facts
- ControlMesh canonical program state is `prod-ready`.
- The release anchor commit is `d4df495b85e39d88ea2459ff8eb7fa7e4e177de6`.
- The pushed release tag is `controlmesh-prod-ready-2026-04-13`.
- The canonical live certification evidence bundle lives under `task_artifacts/prod_cert_live_20260413_foreground/`.
- The certification line is closed and should not absorb post-release operating work.

# Blockers
- None at line open.

# Risks
- Post-release observations may accidentally drift back into feature or hardening scope if the line is not kept narrow.
- Rollback or monitoring discipline may drift away from the released runbook if it is not periodically checked against the actual live state.
- Operator-facing issues may be discovered after release without a clear reopen threshold unless they are recorded explicitly.

# Deferred
- new features
- contract expansion
- architecture reshaping
- broader deployment-platform redesign
- non-operational backlog items that belong to later product lines

# Decision Records
- 2026-04-13: Open `ControlMesh Release Operations` as a separate post-release line after the `prod-ready` certification anchor.
- 2026-04-13: Keep the release-operations line bounded to deployment observation, monitoring, rollback discipline, and change control for the released state.
