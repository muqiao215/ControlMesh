# CBC: TypeScript cron recurrence owner

Implement the next independent owner in runtime-convergence. AGY owns cron-store,
cron-migration, database.ts and their tests; do not touch those files or src/index.ts.
Primary owns acceptance, dispatch and commits. Use configured CBC model, no subagents.

Read repository instructions and actual Python controlmesh/cron/observer.py schedule
calculation plus resolve_user_timezone and relevant existing tests. Design proposal
delegation/cron-port-spec.md is secondary: comments are not proof of DST behavior.

## Scope and ownership

- New `packages/controlmesh-runtime-core/src/cron-schedule.ts` (additional small helper
  only if needed), corresponding new focused tests and a Python-generated recurrence
  fixture/generator under existing test/script conventions.
- Runtime-core package.json and pnpm-lock.yaml only if a justified parser dependency is
  necessary; verify official package API/licensing/version, preserve frozen installation.
  Prefer a sound maintained parser over implementing a partial cron grammar silently.
- `plans/runtime-convergence/delegation/cbc-cron-recurrence-result.md` (under 120 lines).

## Requirements

1. TS runtime recurrence must not launch Python. Python/cronsim is allowed as a test
   oracle only. Support the existing accepted five-field CronSim grammar, including
   ranges/steps/names and its special day expressions. Inventory actual supported grammar
   and reject unsupported forms explicitly rather than giving plausible wrong times.
2. Pure deterministic API with explicit reference instant and timezone inputs. Preserve
   job timezone -> configured user timezone -> supplied host timezone -> UTC resolution.
   Separate wall-clock recurrence from monotonic waiting/leases; scheduled epoch time
   identifies an occurrence and must not depend on coordinator incarnation.
3. Characterize actual Python `_schedule_job` behavior for naive CronSim, fold=0,
   aware-datetime subtraction and gap/fold transitions. Do not repeat the source comment
   that gaps always yield negative delay without testing it. If Python behavior has a
   scheduling bug, identify exact observed difference and implement an explicit tested
   policy (no silent drift or claim of full differential equality). Avoid duplicate
   firing during repeated local time and return a strictly future instant.
4. Deterministic due-slot/reschedule planning can be included, but no timer loop,
   database mutation, native/provider launch, network message, production cron state or
   automatic retry. Integration with CronStore/TaskIngress is a later owner boundary.
5. Include UTC/Asia-Shanghai/New-York/London plus a non-hour DST transition zone;
   end-of-month, leap years, named weekdays, Sunday aliases, day-field combination,
   invalid/impossible schedules, seconds/milliseconds reference boundaries, backward/
   forward clock change, restart/replan identity and finite work bounds. Do not use a
   minute-by-minute multi-year scan that blocks the event loop.

## Evidence

Generate compact oracle fixtures from actual installed Python cronsim/zoneinfo in a
temporary test environment. Compare matching ordinary cases and explicitly assert any
intentional DST corrections. Run focused recurrence tests, runtime-core typecheck and
frozen-lock consistency only. No full suite. Logs /tmp/cm-cbc-cron-recurrence-*.log.
PATH prefix: /home/muqiao/Documents/Codex/2026-09-06/new-chat/outputs/runtime-convergence/ci-bun-bin.
Use .venv Python for the oracle. Report exact changes/check exits, test counts, grammar
coverage, known limits and native session ID if available. Keep final stdout under 8
lines. Do not commit/push, install globally, restart services or touch accounts/browsers.
Stop on auth/quota errors without loops.
