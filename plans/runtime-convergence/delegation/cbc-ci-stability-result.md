# CBC result: bounded CI stability adjustment

Bounded task: CI workflow/helpers and this report only. No runtime source, no other
workers' tests/docs, no dependency or release changes, no pushes.

## Answer to the user's question

The 12 recent main runs do not show over-strict settings. 11/12 succeeded; the one real
failure (`d5734e1`, TS literal-type) was a genuine defect fixed by `8651820`, and the
first-attempt failure of run 34750299686 (SHA `93fb734`) was a transient Docker engine
condition: `docker info` preflight returned `container_engine_unavailable` after the
production 10s supervisor timeout at `packages/controlmesh-runtime-core/src/containers/process.ts:92`,
while the following container tests in the same job passed. No assertion was loosened, no
gate was skipped, and no test retry was added. The change below reduces duplicate/stale
runs and turns an unavailable engine into an explicit, diagnosable failure instead of an
ambiguous test error.

## Changed files

| File | Change |
| --- | --- |
| `.github/workflows/ci.yml` | added scoped `concurrency`, wired read-only Docker readiness + failure diagnostics into `container-execution`, added reviewed `timeout-minutes` per job |
| `.github/scripts/docker-readiness.sh` | new bounded read-only Docker readiness probe (`--diagnose` snapshot mode) |
| `tests/ci/test_docker_readiness.py`, `tests/ci/__init__.py` | new hermetic helper test (fail-closed behavior) |
| `plans/runtime-convergence/delegation/cbc-ci-stability-result.md` | this report |

`git diff --stat .github/workflows/ci.yml` → 22 insertions, 0 deletions (all additive).
Job names, required-check names, gate commands, and pinned images/actions are unchanged.

## 1. Concurrency (narrow, semantics preserved)

Primary acceptance correction: manual invocations now include `github.run_id` in their
group. GitHub's default concurrency queue replaces an older pending invocation even
when `cancel-in-progress` is false. The worker proposal below is retained as review
history only; `.github/workflows/ci.yml` is authoritative. The final aggregate also uses
`always() && !cancelled()` and explicitly requires every dependency result to equal
`success`, so a failed prerequisite produces a failing aggregate rather than a skipped
echo step. Required job names and gate coverage are unchanged.
Reference: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && format('pr-{0}', github.event.pull_request.number) || github.event_name == 'workflow_dispatch' && format('dispatch-{0}', github.ref) || github.ref }}
  cancel-in-progress: ${{ github.event_name != 'workflow_dispatch' }}
```

- Pull requests group by PR number, pushes by ref → PR and push runs stay independent.
- Final `workflow_dispatch` grouping includes each run ID and does not cancel previous
  manual invocations. The initial proposal incorrectly assumed a lossless pending queue.
- Cancelled superseded runs are `cancelled`, not `failure`, so `notify-failure`
  (`contains(needs.*.result, 'failure')`) does not emit stale failure noise.

Local simulation of the group expression (GitHub precedence `&&` before `||`),
`.venv/bin/python` inline fixture:

```
pull_request      -> ('CI-pr-42', True)
push              -> ('CI-refs/heads/main', True)
workflow_dispatch -> ('CI-dispatch-refs/heads/main', False)
```

## 2. Docker readiness (read-only, bounded, fail-closed)

New step order in `container-execution`: install deps → **Confirm Docker engine readiness
(read-only, bounded)** → pinned image pull → real container tests → **Collect read-only
Docker diagnostics** (`if: failure()`).

`bash .github/scripts/docker-readiness.sh`:

- probes `docker --host unix://<socket> info --format '{{.ID}} {{.OSType}}'` — the same
  read-only operation the supervisor performs as its preflight;
- socket resolution mirrors the tests (`/var/run/docker.sock`, else `/run/docker.sock`);
- bounds: default 5 attempts, 20s per attempt, 90s total wall-clock budget, 2s pause; the
  per-attempt timeout is clamped to the remaining budget; `timeout --kill-after=2` keeps a
  probe that ignores SIGTERM inside its bound;
- **only these readiness reads retry.** No test, native execution, provider execution, or
  production timeout is retried or widened (`containers/process.ts` 10s unchanged);
- fail-closed: exit 1 with `docker-readiness: engine unavailable` plus socket stat,
  `docker version`, last `info` output (truncated to 2000 bytes) and
  `systemctl is-active docker`;
- `--diagnose` prints one snapshot and always exits 0, so the failure-diagnostics step can
  never mask the real failure.

## 3. Job timeout review

Every job now has an explicit bound (previously only `container-execution` had one, 10
minutes; all others inherited the 360-minute default). This is required by the concurrency
change: a hung unbounded job would otherwise block its group forever.
`ruff` 15, `mypy` 20, `test` 45, `build` 20, `product-layer` 45, `alpha-smoke` 30,
`container-execution` 10 (unchanged — observed job wall time in run 34750299686 was ~75s
from `09:48:15` to `09:49:28`, with a 90s worst-case readiness budget), `ci-success` 5,
`failure-smoke` 5, `notify-failure` 10.

## Exact checks run and results

| Check | Command | Result |
| --- | --- | --- |
| Shell syntax | `bash -n .github/scripts/docker-readiness.sh` | exit 0 |
| Helper tests | `.venv/bin/python -m pytest tests/ci/test_docker_readiness.py -q` | 5 passed in 8.41s |
| CI workflow contract tests | `.venv/bin/python -m pytest tests/webhook/test_ci_workflow_webhook.py tests/test_read_only_alpha_release.py -q` | 4 passed |
| Combined | `.venv/bin/python -m pytest tests/ci/... tests/webhook/... tests/test_read_only_alpha_release.py -q` | 9 passed in 8.35s |
| Lint | `.venv/bin/python -m ruff check tests/ci .github` | All checks passed |
| YAML parse / structure | PyYAML `safe_load` on `.github/workflows/ci.yml` | parsed; `on` key is coerced to boolean `True` by YAML 1.1 (pre-existing, unchanged) |
| Real read-only probe | `bash .github/scripts/docker-readiness.sh` (local docker 29.1.3) | `docker-readiness: ready attempt=1/5 elapsed=0s engine='50a6f23c-... linux'` exit 0 |
| Diagnose mode | `bash .github/scripts/docker-readiness.sh --diagnose` | snapshot printed, exit 0 |
| Usage guard | `bash .github/scripts/docker-readiness.sh --bogus` | exit 2 |
| Fail-closed fixture | fake docker exiting 1, attempts=2/timeout=1s/budget=3s | exit 1, `engine remained unavailable after 2 attempt(s) within 3s budget` |
| Hung-engine fixture | fake docker `exec sleep 30`, attempts=1/timeout=1s | exit 1 within ~1s (probe) + bounded diagnostics |

Structural assertions verified from the parsed workflow: `ci-success.needs` still includes
all seven gates including `container-execution`; `product-layer` still runs
`pnpm check:protocol`, `pnpm test:golden`, `pnpm test:runtime-core`, `pnpm test:sdk`,
`pnpm --filter @controlmesh/web build`, `git diff --exit-code controlmesh/web_static`;
`container-execution` still runs the same three `bun test` files; `alpha-smoke` still runs
`bash scripts/smoke_read_only_alpha.sh`; notify-failure env/run body untouched.

Not run (out of scope): full `uv run pytest`, `pnpm` gates, real container tests, any push
or workflow run. The changed workflow has not executed in GitHub yet.

Primary verification after the manual-group/aggregate correction: actual extracted
aggregate Python code returned exit 0 for all-success dependencies and exit 1 for each
of failure/cancelled/skipped/timed_out container results. Parsed YAML still names all
seven required gates. Existing workflow/Alpha contract tests: 4 passed in 0.13s.
`git diff --check` passed. These are local checks; remote CI remains to be observed.

## Remaining limits / follow-ups for the primary

1. **Container failures are still not notified.** `notify-failure.needs` omits
   `container-execution`, and the message body has no container line. Editing that is
   Telegram delivery content, which this bounded task was told not to touch. That is why
   run 34750299686's first-attempt container failure produced no notification.
2. **PR/push events remain independent.** The actual push filter is `main` only, so a
   same-repo feature branch push alone does not trigger this workflow. A merge push and
   a PR run remain separate evidence; this change does not suppress either event type.
3. **Readiness reduces but cannot remove transient daemon failures.** If the daemon is
   reachable at readiness time and stalls later inside a container execution, the test
   still fails; that remains a real signal, and the diagnostics step now records engine
   state for triage.
4. **No daemon remediation.** The helper never restarts Docker or mutates daemon state; the
   runner image owns engine availability.
5. Job timeout values are conservative first bounds chosen from the one available log
   (container job). If other jobs' real durations differ substantially, adjust from CI
   timings rather than guessing.
