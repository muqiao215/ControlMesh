#!/usr/bin/env bash
# Bounded read-only Docker readiness probe for CI container execution.
#
# Why: run 34750299686 (SHA 93fb734) failed one container test because a
# `docker info` preflight returned `container_engine_unavailable` after the
# production 10s supervisor timeout at containers/process.ts:92, while the
# following container tests passed. That is a transient engine/daemon
# condition, so this step confirms the engine answers read-only probes before
# the container gates start and prints state when it does not.
#
# Scope: only these read-only readiness reads may retry, with a small attempt
# cap and a wall-time budget. A still-unavailable engine is a hard CI failure.
# Nothing here widens a production/native/provider execution timeout, mutates
# daemon state, or restarts Docker.
#
# Usage:
#   docker-readiness.sh              readiness probe; exit 0 ready, 1 not ready
#   docker-readiness.sh --diagnose   one read-only snapshot; always exit 0
#
# Environment overrides (hermetic local tests):
#   CM_CI_DOCKER_BIN      docker executable      (default /usr/bin/docker)
#   CM_CI_DOCKER_SOCKET   daemon socket          (default /var/run/docker.sock, else /run/docker.sock)
#   CM_CI_READY_ATTEMPTS  attempt cap            (default 5)
#   CM_CI_READY_TIMEOUT   per-attempt seconds    (default 20)
#   CM_CI_READY_BUDGET    total wall-clock secs  (default 90)
#   CM_CI_READY_SLEEP     pause between attempts (default 2)

set -uo pipefail

mode="ready"
case "${1-}" in
  --diagnose) mode="diagnose" ;;
  "") ;;
  *)
    echo "usage: $(basename "$0") [--diagnose]" >&2
    exit 2
    ;;
esac

docker_bin="${CM_CI_DOCKER_BIN:-/usr/bin/docker}"
socket="${CM_CI_DOCKER_SOCKET:-}"
attempts="${CM_CI_READY_ATTEMPTS:-5}"
attempt_timeout="${CM_CI_READY_TIMEOUT:-20}"
budget="${CM_CI_READY_BUDGET:-90}"
pause="${CM_CI_READY_SLEEP:-2}"

if [ -z "$socket" ]; then
  if [ -e /var/run/docker.sock ]; then
    socket="/var/run/docker.sock"
  else
    socket="/run/docker.sock"
  fi
fi

last_output=""

dump_diagnostics() {
  echo "  docker_bin: ${docker_bin}"
  echo "  socket: ${socket}"
  if [ -e "$socket" ]; then
    echo "  socket_stat: $(ls -l "$socket" 2>&1)"
  else
    echo "  socket_stat: <missing>"
  fi
  if command -v "$docker_bin" >/dev/null 2>&1 || [ -x "$docker_bin" ]; then
    echo "  docker_present: yes"
    echo "  version: $(timeout --kill-after=2 5 "$docker_bin" version --format '{{.Server.Version}}' 2>&1 | head -c 500)"
  else
    echo "  docker_present: no (${docker_bin} not executable)"
  fi
  if [ -n "$last_output" ]; then
    echo "  last_info_output:"
    printf '%s\n' "$last_output" | head -c 2000 | sed 's/^/    /'
  fi
  if command -v systemctl >/dev/null 2>&1; then
    echo "  systemctl_docker: $(systemctl is-active docker 2>&1 | head -c 200)"
  fi
}

info_probe() {
  # Read-only: the same operation the container supervisor performs as a preflight.
  # --kill-after keeps a probe that ignores SIGTERM inside its wall-time bound.
  timeout --kill-after=2 "$1" "$docker_bin" --host "unix://${socket}" info --format '{{.ID}} {{.OSType}}' 2>&1
}

if [ "$mode" = "diagnose" ]; then
  echo "docker-readiness: diagnose snapshot"
  last_output="$(info_probe 10)"
  echo "  info_exit: $?"
  dump_diagnostics
  exit 0
fi

started="$(date +%s)"
deadline=$((started + budget))

attempt=1
while [ "$attempt" -le "$attempts" ]; do
  remaining=$((deadline - $(date +%s)))
  if [ "$remaining" -le 0 ]; then
    break
  fi
  slice="$attempt_timeout"
  if [ "$remaining" -lt "$slice" ]; then
    slice="$remaining"
  fi
  last_output="$(info_probe "$slice")"
  status=$?
  if [ "$status" -eq 0 ] && [ -n "${last_output//[[:space:]]/}" ]; then
    echo "docker-readiness: ready attempt=${attempt}/${attempts} elapsed=$(( $(date +%s) - started ))s engine='${last_output}'"
    exit 0
  fi
  echo "docker-readiness: attempt ${attempt}/${attempts} not ready (exit=${status}, timeout=${slice}s)"
  attempt=$((attempt + 1))
  if [ "$attempt" -le "$attempts" ] && [ "$pause" -gt 0 ]; then
    sleep "$pause"
  fi
done

echo "docker-readiness: engine unavailable"
dump_diagnostics
echo "docker-readiness: engine remained unavailable after ${attempts} attempt(s) within ${budget}s budget"
exit 1
