# Cron recurrence: scoped implementation review

Status: independent recurrence candidate accepted for source integration; full cron
runtime and registry migration are NOT accepted. CBC's original process disappeared;
explicit original-session recovery returned quota 429 despite process exit zero.
Primary finished the empty test file and corrected the uncovered implementation bugs.

## Implemented and verified

- Pure TypeScript five-field recurrence and explicit timezone precedence, no Python
  runtime call, provider execution, timer, or database mutation.
- Python CronSim 2.7 grammar and zoneinfo matrix, retaining original Python announced
  and actual timer instants separately from proposed TS occurrence policy.
- Corrected wildcard/range steps: `*/15` previously ran each minute.
- Repeated civil slots bind to fold 0; restart during the second repeated hour cannot
  re-admit the fixed daily slot. Gap shifting uses the pre-transition offset.
- Bounded occurrence count and scan; fractional counts and invalid dates rejected.
- CronSim source attribution and complete installed license in runtime-core notices.

Validation: Bun 1.3.11, 217 tests pass, 917 assertions; log
`/tmp/cm-primary-cron-recurrence-review.log`. Golden generator --check and changed-file
Ruff pass. Full working-tree typecheck remains red only for AGY's unfinished archival
DTO in cron-store.ts; recurrence/type-test diagnostics were corrected. Remote CI must
validate the committed tree independently.

## Remaining requirements and limitations

Six-field CronSim input is explicitly rejected, so arbitrary legacy registry parity is
not claimed. Resolve this difference before accepting complete migration. DST expected
values implement the documented TS policy, not unchanged Python timer behavior. The
matrix and isolated restart case are evidence for covered cases only.

No scheduler admission, occurrence persistence, coordinator fencing, quiet/dependency
policy, quota circuit, grant/sandbox admission, native execution, cancellation or output
delivery is wired by this module. The existing CronStore must own durable occurrence
identity when integrated; helper strings alone do not establish transactional deduplication.
Full CM-R0–R7 and CM-A01–A10 gates remain open as recorded in the parent plan.
