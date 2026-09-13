# CBC: bounded CI stability adjustment

User asks whether repeated CI failures indicate overly strict settings and authorizes
adjusting CI. Primary continues bridge acceptance and AGY owns TS cron; do this independent
CI task using a fresh native CBC context and configured model.

## Evidence already gathered

- Latest 12 main CI runs: 11 now success, 1 genuine TS test literal-type failure at
  d5734e1 (fixed by 8651820). Do not remove typechecking to hide it.
- Run 34750299686, SHA 93fb734, first attempt failed exactly one container test at
  containers/process.ts:92: Docker `info` preflight returned
  `container_engine_unavailable` after ~10 seconds. Subsequent container tests passed.
  Primary reran failed jobs once, with no source change: now success. Raw first-attempt
  log `/tmp/cm-ci-34750299686-failed.log`. This supports transient environment failure,
  not a proven application defect. Do not retry arbitrary test assertions.
- .github/workflows/ci.yml has no concurrency cancellation and runs all heavy jobs for
  every main push. Some historical same-SHA runs duplicate work; inspect triggers before
  assuming push/PR deduplication is currently guaranteed.

## Implement within these files only

`.github/workflows/ci.yml`, a small `.github/scripts/` CI helper if justified, and
`plans/runtime-convergence/delegation/cbc-ci-stability-result.md`. You may add one focused
helper test if it proves a real failure-mode requirement. No runtime source or other
workers' tests/docs; do not change dependencies or release workflows.

Add narrowly scoped CI concurrency so superseded runs for the same event/ref do not
keep expensive checks running or send stale failure noise; preserve separate PR/push and
intentional workflow_dispatch semantics. Keep all required correctness, security,
typecheck, migration, packaging and actual container execution gates. Do not add blanket
continue-on-error, unconditional skips or automatic whole-suite retries.

Add a bounded read-only Docker readiness step and useful failure diagnostics before
container execution if supported by code/log evidence. Only Docker readiness reads may
retry (small attempt cap and wall-time bound); fail when the engine remains unavailable.
Never retry native/provider executions or expand their production timeouts. Do not edit
Telegram delivery or manually send notifications. Avoid speculative node/action upgrades.

Review job-level timeout bounds and aggregate `CI success` behavior; make only warranted
adjustments and keep stable required-check names. Validate YAML (watch YAML 1.1 `on`
coercion), expression/concurrency behavior, shell syntax and failed-engine handling with
small local fixtures. No full test suite, Docker restarts, production config or pushes.
Write changed files, exact checks/log paths/exit codes and remaining limits to the report.
Do not spawn more workers. Stop on auth/quota failure without loops.
