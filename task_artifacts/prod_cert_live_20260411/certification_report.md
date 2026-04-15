# ControlMesh Live Production Certification Evidence

Date: 2026-04-11 UTC
Scope: production certification evidence only. No endpoints, contracts, write-plane behavior, catalog schema, or substrate behavior were expanded.

Formal conclusion: `not-prod-ready`

## Evidence Artifacts

Raw artifacts are in this directory:

- `systemctl_status.log`
- `systemctl_show.log`
- `controlmesh_status.log`
- `controlmesh_service_status.log`
- `controlmesh_service_unit.log`
- `config_summary.log`
- `env_key_presence.log`
- `port_scan.log`
- `internal_health.json`
- `agent_log_tail.log`
- `installed_controlmesh_service_logs.log`
- `repo_controlmesh_service_logs.log`
- `pytest_service_logs_targeted.log`
- `ruff_service_logs_targeted.log`
- `mypy_service_logs_targeted.log`
- `pytest_infra_broad.log`
- `service_logs_fix.diff`
- `live_restart_api_drill.sh`
- `live_drill/drill.log`
- `live_drill/api_enable.log`
- `live_drill/pre_restart_status.log`
- `live_drill/pre_restart_show.log`
- `live_drill/post_restart_status.log`
- `live_drill/post_restart_show.log`
- `live_drill/post_restart_internal_health.json`
- `live_drill/final_restore_status.log`
- `live_drill/final_restore_show.log`

## Four Required Questions

### 1. Can a real supervised controlmesh deployment be brought up stably from zero to running under the intended service/supervisor path?

Partially proven, but not enough for prod certification.

Proven live:

- The real user-systemd service is installed and active: `systemctl_show.log` records `ActiveState=active`, `SubState=running`, `ExecMainPID=503798`, `Restart=always`, `RestartUSec=5s`, `FragmentPath=/root/.config/systemd/user/controlmesh.service`, and `ActiveEnterTimestamp=Sat 2026-04-11 04:40:52 UTC`.
- The intended supervisor environment is present: `Environment=... HOME=/root IS_SANDBOX=1 CONTROLMESH_SUPERVISOR=1`.
- `controlmesh_status.log` reports the live process running with `pid=503798`, provider `codex (gpt-5.4)`, `Errors: 0`, and the real home/config/workspace/log paths under `/root/.controlmesh`.
- `agent_log_tail.log` shows the runtime startup path completing: workspace init, internal agent API, TaskHub, `AgentStack`, Telegram long-polling, provider auth, and bot online.

Not fully proven:

- I did not run a fresh `controlmesh service install` or destructive clean-home reinstall on the live host during this certification pass.
- The original certification pass did not include a service-manager restart drill from inside the child task process because restarting the service would terminate the evidence collector before it could write a verified result.

Follow-up live drill after that first pass:

- A bounded restart drill was later attempted with [`live_restart_api_drill.sh`](./live_restart_api_drill.sh).
- `live_drill/pre_restart_status.log` and `live_drill/pre_restart_show.log` captured the pre-drill running service state.
- `live_drill/post_restart_status.log` and `live_drill/post_restart_show.log` prove one controlled `systemctl --user restart controlmesh` succeeded and the service came back with a new PID (`507548`) in `active/running`.
- The immediate `live_drill/post_restart_internal_health.json` probe still failed with `Connection refused`, so the drill proved restart under systemd but did not yet prove a clean post-restart supervisor-health checkpoint at the exact moment probed.

Answer: the service/supervisor path is live and stable on an already provisioned deployment, and one bounded service-manager restart is now proven. A zero-to-running install drill is still missing, and the restart evidence is still incomplete until the post-restart supervisor-health/API checks are re-run cleanly.

### 2. Can the system continue to work under real transport and provider credentials, with true runtime lifecycle rather than mocks?

Yes for the Telegram + Codex/Claude runtime path tested here.

Evidence:

- `agent_log_tail.log` shows `[main] Bot online: @V_YueBot (id=8515961362)` and `Run polling for bot @V_YueBot id=8515961362`.
- `agent_log_tail.log` shows real provider authentication: `[main] Provider [claude]: authenticated` and `[main] Provider [codex]: authenticated`.
- `agent_log_tail.log` shows real Telegram ingress and provider execution: `Message received text=返回了吗`, `Codex CLI wrapper: cwd=/root/.controlmesh/workspace, model=gpt-5.4`, `Codex subprocess starting`, and `Streaming flow completed`.
- The current certification task itself was submitted through the real task/runtime path: `Task submitted id=c1296fd4 name='ControlMesh Prod Certification and Live Deployment Evidence' parent=main provider=(parent default)`, followed by a Codex subprocess start.
- `internal_health.json` returned `{"agents":{"main":{"status":"running","uptime":"21m","restart_count":0,"last_crash_error":null}}}` from the live internal supervisor API at `127.0.0.1:8799`.

Limit:

- `config_summary.log` shows the public direct API is disabled: `api_enabled=False`; `port_scan.log` shows `port_8741=closed` while `port_8799=open`. Therefore public `/health` and catalog smoke were not proven against this live service.

Answer: true live transport/provider runtime was proven for Telegram plus authenticated Codex/Claude, but public API/catalog live smoke was not.

### 3. Are observability, recovery, rollback, and operator runbook evidence sufficient for production trust?

No.

Proven:

- File logs are available at `/root/.controlmesh/logs/agent.log`; `agent_log_tail.log` contains startup, transport, provider, task, and failure-localization evidence.
- `systemctl status` exposes recent service logs and live process tree; see `systemctl_status.log` and `controlmesh_service_status.log`.
- The internal supervisor health endpoint responds; see `internal_health.json`.

Observed blocker:

- The deployed `controlmesh service logs` command is not sufficient on this host. `installed_controlmesh_service_logs.log` shows only:
  - `Showing logs (Ctrl+C to stop)...`
  - `No journal files were found.`
- This is an operator-trust blocker because the documented Linux log path is `journalctl --user`, but the host does not expose user journal files for this service.

Minimal fix made in repo:

- `controlmesh/infra/service_logs.py` now falls back to recent file logs when the user journal is unavailable or `journalctl` is missing.
- `controlmesh/infra/service_linux.py` passes the resolved `logs_dir` into that fallback path.
- `tests/infra/test_service_linux.py` and `tests/infra/test_service_logs.py` cover the fallback.
- `repo_controlmesh_service_logs.log` proves the repo version now prints `No user journal available; showing recent file logs instead.` and then shows `agent.log` lines.

Still insufficient:

- The fix has not been deployed into the currently running `/root/.local/bin/controlmesh` service binary.
- A live rollback drill was not executed.
- Public direct API health/catalog smoke was not executed because `api.enabled=false` and enabling it requires a service restart.
- After the follow-up drill, a rollback path is now partially evidenced: `live_drill/drill.log` shows the attempt exited with `rc=127`, restored the prior config snapshot, and `live_drill/final_restore_show.log` plus `live_drill/final_restore_status.log` show the service came back running on the restored config.
- That same follow-up drill still did not complete the API smoke because `live_drill/api_enable.log` shows `controlmesh: command not found` inside the drill shell before the temporary API enable/restart/health/catalog sequence could finish.

Answer: observability improved in the repo, but the deployed runtime and recovery/rollback evidence are still insufficient for production trust.

### 4. Does the conclusion advance from alpha-ready to prod-ready, or if not, what exact evidence layer is still missing?

No. The conclusion does not advance to prod-ready.

Current status: `not-prod-ready`

What advanced:

- Real user-systemd service presence and stable running state were proven.
- Real Telegram transport was proven.
- Real authenticated provider runtime was proven for Codex and Claude.
- A live operator observability blocker was found and fixed in the repo with tests.
- One bounded live `systemctl --user restart controlmesh` drill now shows the service can come back under the user-systemd supervisor path.

Exact missing evidence layer:

- Deploy the service-log fallback fix to the live service binary, then re-run `controlmesh service logs` against the deployed command, not only `uv run controlmesh service logs` from the repo.
- Re-run the controlled lifecycle drill with a clean operator shell/PATH so the temporary API enable step actually executes:
  - `systemctl --user restart controlmesh`
  - wait for service active/running
  - confirm internal supervisor health returns running after restart
  - confirm Telegram/provider readiness in post-restart logs
- If public API/catalog is in prod scope, run the explicit API drill:
  - enable API in live config
  - restart service because `api` is restart-required
  - `curl http://127.0.0.1:8741/health`
  - authorized `/catalog/sessions`, `/catalog/tasks`, `/catalog/teams`
  - disable/revert API if it is not intended to stay enabled
  - restart service and verify port rollback
- Finish one rollback/recovery drill that includes both the failed-change path and the verified restored-health path after the revert, not only the config restore itself.
- Re-run a broad regression slice after unrelated Docker test failures are either fixed or explicitly baselined. `pytest_infra_broad.log` currently shows `301 passed, 11 failed`, with failures isolated to Docker setup/mount tests reporting `Docker binary not found, falling back to host execution`.

## Verification Commands And Results

Passed:

```bash
uv run pytest tests/infra/test_service_linux.py tests/infra/test_service_logs.py
```

Result: `19 passed in 0.82s`.

```bash
uv run ruff check controlmesh/infra/service_logs.py controlmesh/infra/service_linux.py tests/infra/test_service_linux.py tests/infra/test_service_logs.py
```

Result: `All checks passed!`.

```bash
uv run mypy controlmesh/infra/service_logs.py controlmesh/infra/service_linux.py
```

Result: `Success: no issues found in 2 source files`.

Live smoke of the repo-fixed service log command:

```bash
timeout 3 uv run controlmesh service logs
```

Result: fallback succeeded and displayed recent `agent.log` lines; see `repo_controlmesh_service_logs.log`.

Failed or insufficient:

```bash
timeout 3 controlmesh service logs
```

Result: the currently deployed command showed `No journal files were found.`; see `installed_controlmesh_service_logs.log`.

```bash
uv run pytest tests/infra
```

Result: `301 passed, 11 failed`. The failures are Docker-manager tests, not service-log tests; see `pytest_infra_broad.log`.

```bash
python3 ... port scan for 8741 and 8799
```

Result: `port_8741=closed`, `port_8799=open`; see `port_scan.log`.

## Code Changes

Minimal certification-blocker fix only:

- `controlmesh/infra/service_logs.py`
- `controlmesh/infra/service_linux.py`
- `tests/infra/test_service_linux.py`
- `tests/infra/test_service_logs.py`

No endpoint, contract, write-plane, schema, or substrate changes were made.
