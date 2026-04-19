# ControlMesh Live Certification Checkpoint — 2026-04-13

Conclusion: prod-ready

Facts:
- External takeover completed from meiren over the existing reverse SSH path using the dedicated meiren-to-moonrise key.
- Live controlmesh binary loads the current repo code directly:
  - controlmesh: <home>/.controlmesh/analysis/controlmesh-src/controlmesh/__init__.py
  - cli.service: <home>/.controlmesh/analysis/controlmesh-src/controlmesh/cli/service.py
  - service_logs: <home>/.controlmesh/analysis/controlmesh-src/controlmesh/infra/service_logs.py
  - service_linux: <home>/.controlmesh/analysis/controlmesh-src/controlmesh/infra/service_linux.py
- Controlled restart drill succeeded:
  - pre-restart ExecMainPID=545767
  - post-restart ExecMainPID=546069
  - post-restart supervisor health succeeded on 127.0.0.1:8799/interagent/health
  - service remained ActiveState=active, SubState=running, Result=success
- Temporary API enable / smoke / rollback closed successfully:
  - API enabled and restarted successfully with ExecMainPID=546126
  - GET /health => 200
  - GET /catalog/sessions => 200
  - GET /catalog/tasks => 200
  - GET /catalog/teams => 200
  - rollback restored prior config state with api.enabled=false
  - after rollback, 8741 closed again and 8799 supervisor health returned main=running

Key evidence:
- precheck_live_binary_repo.txt
- deployment_consistency.log
- pre_restart_show.log
- post_restart_show.log
- post_restart_internal_health.json
- post_api_enable_show.log
- api_health.status
- catalog_sessions.status
- catalog_tasks.status
- catalog_teams.status
- config_after_restore_summary.log
- post_restore_listeners.log
- post_restore_internal_health_settled.json
- drill.log
