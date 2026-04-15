#!/usr/bin/env bash
set -euo pipefail

ROOT="/root/.controlmesh/analysis/controlmesh-src"
ART="$ROOT/task_artifacts/prod_cert_live_20260411/live_drill"
CFG="$HOME/.controlmesh/config/config.json"
BACKUP="$ART/config.before.json"
STATE="$ART/state.env"

mkdir -p "$ART"

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$ART/drill.log"
}

wait_active() {
  local tries="${1:-60}"
  local ok=0
  for _ in $(seq 1 "$tries"); do
    if systemctl --user is-active --quiet controlmesh; then
      ok=1
      break
    fi
    sleep 1
  done
  if [[ "$ok" -ne 1 ]]; then
    log "service failed to become active"
    return 1
  fi
}

wait_port_state() {
  local port="$1"
  local expect="$2"
  local tries="${3:-60}"
  python3 - "$port" "$expect" "$tries" <<'PY'
import socket
import sys
import time

port = int(sys.argv[1])
expect = sys.argv[2]
tries = int(sys.argv[3])

for _ in range(tries):
    s = socket.socket()
    s.settimeout(1)
    open_now = False
    try:
        s.connect(("127.0.0.1", port))
        open_now = True
    except OSError:
        open_now = False
    finally:
        s.close()
    if (expect == "open" and open_now) or (expect == "closed" and not open_now):
        sys.exit(0)
    time.sleep(1)
sys.exit(1)
PY
}

restore_config() {
  if [[ -f "$BACKUP" ]]; then
    cp -fp "$BACKUP" "$CFG"
    log "restored prior config snapshot"
    systemctl --user restart controlmesh
    wait_active 90
    systemctl --user status controlmesh --no-pager > "$ART/final_restore_status.log" 2>&1 || true
    systemctl --user show controlmesh \
      -p ActiveState -p SubState -p ExecMainPID -p NRestarts -p Result -p ActiveEnterTimestamp \
      --no-pager > "$ART/final_restore_show.log" 2>&1 || true
  fi
}

trap 'rc=$?; if [[ $rc -ne 0 ]]; then log "drill exiting with rc=$rc"; restore_config; echo "DRILL_STATUS=failed" > "$STATE"; echo "DRILL_RC=$rc" >> "$STATE"; fi' EXIT

log "drill start"
cp -fp "$CFG" "$BACKUP"

python3 - <<'PY' > "$ART/config_before_summary.log" 2>&1
import json
from pathlib import Path

cfg = Path.home() / ".controlmesh/config/config.json"
data = json.loads(cfg.read_text())
api = data.get("api", {})
print(f"api_enabled={api.get('enabled')}")
print(f"api_port={api.get('port')}")
print(f"api_token_present={bool(api.get('token'))}")
print(f"transport={data.get('transport')}")
print(f"transports={data.get('transports')}")
PY

systemctl --user status controlmesh --no-pager > "$ART/pre_restart_status.log" 2>&1 || true
systemctl --user show controlmesh \
  -p ActiveState -p SubState -p ExecMainPID -p NRestarts -p Result -p ActiveEnterTimestamp \
  --no-pager > "$ART/pre_restart_show.log" 2>&1 || true

log "restarting live controlmesh service"
systemctl --user restart controlmesh
wait_active 90
sleep 3
systemctl --user status controlmesh --no-pager > "$ART/post_restart_status.log" 2>&1 || true
systemctl --user show controlmesh \
  -p ActiveState -p SubState -p ExecMainPID -p NRestarts -p Result -p ActiveEnterTimestamp \
  --no-pager > "$ART/post_restart_show.log" 2>&1 || true
curl -sS http://127.0.0.1:8799/interagent/health > "$ART/post_restart_internal_health.json" 2>&1 || true

log "enabling live API"
controlmesh api enable > "$ART/api_enable.log" 2>&1
log "restarting after API enable"
systemctl --user restart controlmesh
wait_active 90
wait_port_state 8741 open 90

systemctl --user status controlmesh --no-pager > "$ART/post_api_enable_status.log" 2>&1 || true
systemctl --user show controlmesh \
  -p ActiveState -p SubState -p ExecMainPID -p NRestarts -p Result -p ActiveEnterTimestamp \
  --no-pager > "$ART/post_api_enable_show.log" 2>&1 || true
curl -sS http://127.0.0.1:8799/interagent/health > "$ART/post_api_enable_internal_health.json" 2>&1 || true

TOKEN="$(python3 - <<'PY'
import json
from pathlib import Path
cfg = Path.home() / ".controlmesh/config/config.json"
print(json.loads(cfg.read_text())["api"]["token"])
PY
)"

python3 - <<'PY' > "$ART/api_token_summary.log" 2>&1
import json
from pathlib import Path
cfg = Path.home() / ".controlmesh/config/config.json"
token = json.loads(cfg.read_text())["api"]["token"]
print(f"api_token_len={len(token)}")
PY

curl -sS -o "$ART/api_health.body" -w "%{http_code}\n" http://127.0.0.1:8741/health > "$ART/api_health.status"
curl -sS -H "Authorization: Bearer $TOKEN" -o "$ART/catalog_sessions.body" -w "%{http_code}\n" \
  "http://127.0.0.1:8741/catalog/sessions?limit=1" > "$ART/catalog_sessions.status"
curl -sS -H "Authorization: Bearer $TOKEN" -o "$ART/catalog_tasks.body" -w "%{http_code}\n" \
  "http://127.0.0.1:8741/catalog/tasks" > "$ART/catalog_tasks.status"
curl -sS -H "Authorization: Bearer $TOKEN" -o "$ART/catalog_teams.body" -w "%{http_code}\n" \
  "http://127.0.0.1:8741/catalog/teams" > "$ART/catalog_teams.status"

log "restoring prior config state"
restore_config
wait_port_state 8741 closed 90
curl -sS http://127.0.0.1:8799/interagent/health > "$ART/post_restore_internal_health.json" 2>&1 || true

echo "DRILL_STATUS=completed" > "$STATE"
echo "DRILL_RC=0" >> "$STATE"
log "drill complete"
