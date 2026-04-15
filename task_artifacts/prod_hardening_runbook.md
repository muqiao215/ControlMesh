# ControlMesh Deployment / Prod-Hardening Runbook

Scope: shipped read-only catalog/history/snapshot line only. This runbook does not add endpoints, write-plane behavior, or admin/detail expansion.

## Install And Bootstrap

Fresh machine requirement:

```bash
python --version  # must be >= 3.11
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[api,test]"
```

Validated with CPython 3.12.13 in `task_artifacts/prod_hardening/install_editable_api_test_py312.log`.
The same install attempt with Python 3.10.12 correctly failed because `pyproject.toml` requires `>=3.11`; see `task_artifacts/prod_hardening/install_editable_api_test.log`.

Bootstrap config/workspace before enabling API:

```bash
export CONTROLMESH_HOME=/path/to/controlmesh-home
python - <<'PY'
from controlmesh.__main__ import load_config
load_config()
PY
controlmesh api enable
```

Validated in:

- `task_artifacts/prod_hardening/config_bootstrap_clean.log`
- `task_artifacts/prod_hardening/api_enable_clean.log`

## Startup Path

The read-only HTTP catalog is hosted inside the normal runtime path:

1. `controlmesh` or `python -m controlmesh` starts the bot process.
2. `load_config()` resolves `CONTROLMESH_HOME`, creates/merges `config/config.json`, and initializes the workspace.
3. `create_orchestrator()` resolves `ControlMeshPaths`, injects runtime environment, starts observers, and starts the direct API when `api.enabled=true`.
4. `start_api_server()` wires `AdminHistoryCatalogReader(paths)` into `ApiServer`.
5. `/catalog/sessions`, `/catalog/tasks`, and `/catalog/teams` read from derived catalog state built from canonical files.

Background service path:

```bash
controlmesh service install
controlmesh service status
controlmesh service logs
```

Platform behavior:

- Linux: systemd user service, logs through `journalctl --user -u controlmesh -f --no-hostname`.
- macOS: launchd Launch Agent, recent logs from `~/.controlmesh/logs/agent.log`.
- Windows: Task Scheduler task, recent logs from `~/.controlmesh/logs/agent.log`.

## Health And Catalog Checks

Health:

```bash
curl -s http://127.0.0.1:8741/health
```

Expected:

```json
{"status":"ok","connections":0}
```

Read-only catalog:

```bash
TOKEN="$(python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("~/.controlmesh/config/config.json").expanduser().read_text())["api"]["token"])
PY
)"
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8741/catalog/sessions?limit=5"
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8741/catalog/tasks"
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8741/catalog/teams"
```

Validated live against the shipped `ApiServer` in `task_artifacts/prod_hardening/api_server_smoke.log`:

- `/health`: `200`, `{"status":"ok","connections":0}`
- unauthorized catalog request: `401`
- authorized sessions/tasks/teams: `200`
- invalid `limit=-1`: `400`
- six concurrent `/catalog/sessions` reads: all `200`

## Logs And Errors

Foreground/runtime logging writes to:

```text
$CONTROLMESH_HOME/logs/agent.log
```

Validated in `task_artifacts/prod_hardening/logging_smoke.log`: `setup_logging(log_dir=paths.logs_dir)` created `agent.log` and wrote an error line.

For installed services:

```bash
controlmesh service logs
```

Expected backend:

- Linux: follows `journalctl --user -u controlmesh -f --no-hostname`.
- macOS/Windows: prints recent lines from `~/.controlmesh/logs/agent.log`, falling back to newest `*.log`.

## Recovery And Rollback

The catalog/history/snapshot artifacts are derived, not authoritative.

Disable the API and restart:

```bash
controlmesh api disable
controlmesh restart
```

If the service is installed:

```bash
controlmesh service stop
controlmesh service start
```

Recover a missing/corrupt derived history index:

```bash
rm ~/.controlmesh/workspace/.history/index.sqlite3
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8741/catalog/sessions"
```

The next catalog read recreates the SQLite index from canonical transcript/runtime/task/team-state files. This was validated in `task_artifacts/prod_hardening/recovery_smoke.log`.

Recover a missing/stale team control snapshot:

```bash
python - <<'PY'
from controlmesh.team.api import execute_team_api_operation
print(execute_team_api_operation(
    "read-snapshot",
    {"team_name": "alpha-team", "refresh": True, "max_age_seconds": 60},
))
PY
```

Validated in `task_artifacts/prod_hardening/recovery_smoke.log`: missing snapshot returned structured `not_found`; refresh rebuilt the derived snapshot from canonical team state and returned `ok=true`.

## Known Non-Production Evidence Gaps

- Full `controlmesh` supervised startup with live Telegram/Matrix/Feishu credentials and at least one authenticated provider CLI was not executed in this repo-only cut.
- `controlmesh service install/start/logs` was not exercised on an installed service; behavior is documented from code paths only.
- Concurrent read-only access was tested; concurrent reads during active canonical-file writes were not stress-tested.
- Health is intentionally minimal and does not report catalog index freshness or snapshot freshness.
