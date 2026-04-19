# ControlMesh Release Notes — 2026-04-13

Release status: prod-ready

Release anchor:
- intended local release tag: `controlmesh-prod-ready-2026-04-13`
- release commit: the commit that lands this note, the canonical program-state promotion, and this evidence directory together

Canonical references:
- checkpoint: `task_artifacts/prod_cert_live_20260413_foreground/CHECKPOINT.md`
- program progress file: `plans/_program/<progress-file>`
- program findings file: `plans/_program/<findings-file>`
- program plan file: `plans/_program/<plan-file>`

Evidence bundle:
- `task_artifacts/prod_cert_live_20260413_foreground/deployment_consistency.log`
- `task_artifacts/prod_cert_live_20260413_foreground/post_restart_internal_health.json`
- `task_artifacts/prod_cert_live_20260413_foreground/api_health.status`
- `task_artifacts/prod_cert_live_20260413_foreground/catalog_sessions.status`
- `task_artifacts/prod_cert_live_20260413_foreground/catalog_tasks.status`
- `task_artifacts/prod_cert_live_20260413_foreground/catalog_teams.status`
- `task_artifacts/prod_cert_live_20260413_foreground/post_restore_internal_health_settled.json`

Local-only captures intentionally omitted from the release-tracked subset:
- raw config snapshot with secrets: `task_artifacts/prod_cert_live_20260413_foreground/config.before.json`
- raw catalog response bodies with live identifiers: `task_artifacts/prod_cert_live_20260413_foreground/catalog_*.body`

Operational reference:
- runbook: `task_artifacts/prod_hardening_runbook.md`

Release facts:
- External takeover from meiren over the established reverse-SSH path succeeded.
- The live controlmesh binary loads the current repository code directly.
- Controlled restart drill succeeded and supervisor health recovered on `127.0.0.1:8799/interagent/health`.
- Temporary API enable succeeded; `/health`, `/catalog/sessions`, `/catalog/tasks`, and `/catalog/teams` all returned `200`.
- Rollback restored `api.enabled=false`, closed `8741` again, and left supervisor health healthy on `8799`.

Scope freeze:
- This release closes the certification line.
- Post-release deployment observation, rollback rehearsal, monitoring, and change management must move to a separate `ControlMesh Release Operations` scope.
- New features, contracts, or architecture changes are out of scope for this release anchor.
