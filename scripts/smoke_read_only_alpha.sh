#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

for command_name in uv pnpm bun curl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "missing required command: $command_name" >&2
    exit 1
  }
done

release_version="$(
  awk -F '"' '/^version = "/ { print $2; exit }' pyproject.toml
)"
tmp_dir="$(mktemp -d)"
runtime_pid=""
cli_pid=""

cleanup() {
  if [[ -n "$cli_pid" ]]; then
    kill "$cli_pid" >/dev/null 2>&1 || true
    wait "$cli_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$runtime_pid" ]]; then
    kill "$runtime_pid" >/dev/null 2>&1 || true
    wait "$runtime_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

pnpm --filter @controlmesh/web build
uv build --out-dir "$tmp_dir/dist"
wheel="$tmp_dir/dist/controlmesh-${release_version}-py3-none-any.whl"
[[ -f "$wheel" ]] || {
  echo "missing expected wheel: $wheel" >&2
  exit 1
}
uv venv --python 3.12 "$tmp_dir/venv"
uv pip install --python "$tmp_dir/venv/bin/python" "${wheel}[api]"

(
  cd "$tmp_dir"
  PYTHONPATH="" "$tmp_dir/venv/bin/python" - "$release_version" "$repo_root" <<'PY'
import importlib.metadata
import pathlib
import sys

import controlmesh

expected, forbidden_root = sys.argv[1:]
module_path = pathlib.Path(controlmesh.__file__).resolve()
if controlmesh.__version__ != expected:
    raise SystemExit(f"version mismatch: {controlmesh.__version__} != {expected}")
if importlib.metadata.version("controlmesh") != expected:
    raise SystemExit("installed distribution metadata mismatch")
if module_path.is_relative_to(pathlib.Path(forbidden_root).resolve()):
    raise SystemExit(f"import resolved to source tree: {module_path}")
print(f"installed wheel OK: controlmesh=={expected} from {module_path}")
PY
)

CONTROLMESH_HOME="$tmp_dir/cli-home" PYTHONPATH="" PYTHONUNBUFFERED=1 \
  "$tmp_dir/venv/bin/controlmesh" api serve --port 0 --token cli-smoke-token \
  >"$tmp_dir/cli.log" 2>&1 &
cli_pid="$!"
for _attempt in $(seq 1 100); do
  grep -q 'Read-only API:' "$tmp_dir/cli.log" && break
  kill -0 "$cli_pid" >/dev/null 2>&1 || {
    cat "$tmp_dir/cli.log" >&2
    exit 1
  }
  sleep 0.1
done
cli_base_url="$(sed -n 's|.*Read-only API: \(http://127\.0\.0\.1:[0-9]*\)/api/v1.*|\1|p' "$tmp_dir/cli.log" | tail -1)"
[[ -n "$cli_base_url" ]] || {
  cat "$tmp_dir/cli.log" >&2
  exit 1
}
curl --fail --silent --show-error "$cli_base_url/dashboard/" >/dev/null
curl --fail --silent --show-error \
  -H 'Authorization: Bearer cli-smoke-token' \
  "$cli_base_url/api/v1/tasks" >"$tmp_dir/cli-tasks.json"
cli_upload_status="$(
  curl --silent --output /dev/null --write-out '%{http_code}' \
    -X POST "$cli_base_url/upload"
)"
[[ "$cli_upload_status" == "404" ]] || {
  echo "installed CLI exposed legacy upload: $cli_upload_status" >&2
  exit 1
}
kill "$cli_pid"
wait "$cli_pid"
cli_pid=""

ready_file="$tmp_dir/runtime-ready.json"
(
  cd "$tmp_dir"
  PYTHONPATH="" "$tmp_dir/venv/bin/python" \
    "$repo_root/scripts/read_only_alpha_runtime.py" \
    --state-dir "$tmp_dir/state" \
    --ready-file "$ready_file"
) >"$tmp_dir/runtime.log" 2>&1 &
runtime_pid="$!"

for _attempt in $(seq 1 100); do
  [[ -s "$ready_file" ]] && break
  kill -0 "$runtime_pid" >/dev/null 2>&1 || {
    cat "$tmp_dir/runtime.log" >&2
    exit 1
  }
  sleep 0.1
done
[[ -s "$ready_file" ]] || {
  echo "runtime did not become ready" >&2
  cat "$tmp_dir/runtime.log" >&2
  exit 1
}

readarray -t runtime_values < <(
  "$tmp_dir/venv/bin/python" - "$ready_file" <<'PY'
import json
import pathlib
import sys

data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in ("base_url", "token", "task_id", "artifact_path"):
    print(data[key])
PY
)
base_url="${runtime_values[0]}"
token="${runtime_values[1]}"
task_id="${runtime_values[2]}"
artifact_path="${runtime_values[3]}"

curl --fail --silent --show-error "$base_url/health" >"$tmp_dir/health.json"
unauthorized_status="$(
  curl --silent --output /dev/null --write-out '%{http_code}' "$base_url/api/v1/tasks"
)"
[[ "$unauthorized_status" == "401" ]] || {
  echo "expected unauthenticated facade status 401, got $unauthorized_status" >&2
  exit 1
}

bun run scripts/read_only_alpha_sdk_smoke.ts \
  "$base_url" "$token" "$task_id" "$artifact_path" "$tmp_dir/state" \
  | tee "$tmp_dir/sdk-smoke.json"

curl --fail --silent --show-error "$base_url/dashboard/" >"$tmp_dir/index.html"
grep -q '<title>ControlMesh</title>' "$tmp_dir/index.html"
curl --fail --silent --show-error \
  "$base_url/dashboard/assets/main.js" >"$tmp_dir/main.js"
grep -q '/api/v1/tasks' "$tmp_dir/main.js"

echo "read-only alpha smoke passed: version=$release_version api=$base_url web=$base_url/dashboard/"
