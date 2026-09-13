# AGY batch 1 review 2 — repair persistence correctness

Continue native conversation def64a8d-18c9-49eb-abd4-82488284d15f. Your actual worker
exit was 0/SUCCESS. Primary read the 9-test/98-assertion, migration 24-test/117-assertion
and successful typecheck logs. Acceptance is withheld: source contradicts several
reported guarantees. Same TS cron files/tests ownership, no other workers or full suite.

1. `createAttempt` accepts any fence >= current epoch (future invented fences pass),
   omits uncertain attempts from duplicate suppression, and permits new attempts on a
   completed occurrence. This permits duplicate scheduled side effects. Require issued
   current authority, block uncertain/terminal replay, and test each bypass. Do not let
   `getCoordinatorEpoch` silently create authority for arbitrary identities. Keep the
   existing single-coordinator boundary; a per-ID counter is not global leader fencing.
2. `markAttemptUncertain`, `updateOccurrenceState`, dependency reconciliation/release
   bypass attempt/current-owner fencing or rewrite terminal state. Make these transitions
   owner-bound and terminal-safe. Unknown completion retains ownership. A passed boolean
   without attempt identity/current authority cannot reconcile whichever owner currently
   holds the dependency. Add stale-controller and late-completion tests, including
   coordinator identity changes. Use existing DB clock/transaction conventions.
3. Raw field retention is not lossless: input coercion turns null into the string 'null',
   omits explicit empty timezone, and Number/JSON.parse can round Python integer IDs.
   Match actual CronJob.from_dict/to_dict and preserve original/unknown JSON separately
   from normalized execution fields. Do not invent default coercion that Python does not
   perform. Reuse existing lossless JSON/identity helpers where applicable. Reject values
   that cannot be faithfully represented, rather than silently rounding. Python parity
   must include missing/null/empty/zero and >2^53 IDs (including unknown-field values), not
   only the existing two happy-path fixtures.
4. `putJob({...hydratedJob})` persists internal `raw`/`version`/`spec_digest` fields back
   into raw metadata. Repeated status/enabled updates can recursively nest prior raw
   strings and alter definition hashes. Keep storage metadata separate; preserve
   user-supplied fields of the same names without leaking internal bookkeeping. Test
   repeated status-only updates, stable spec digest/revision and bounded payload growth.
5. Export's temp-file rename overwrites an existing destination despite the assignment's
   exclusive-output requirement. Use actual exclusive destination publication, refuse
   existing targets/symlinks, and clean scratch files on failures. Export must read one
   consistent DB snapshot; corrupt stored metadata must reject, not disappear into {}.
   Import file reading must avoid lstat/read replacement and growth races. A source
   string/object should have explicit semantics and complete validated snapshot handling.
6. Offline CLI opens/migrates DB before validating action, and export can create a new
   empty DB or mutate an older DB before writing. Validate arguments first; export must
   use a read-only existing supported DB and preserve it (see legacy-export.ts pattern).
   Do not modify production files to test. Reimport should have explicit idempotency and
   snapshot identity; don't retain obsolete top-level metadata when importing an empty
   metadata snapshot or claim a merge is a complete replacement.
7. Correct result claims: actual methods/error names differ from report (e.g.
   registerOccurrence/createAttempt, occurrence_definition_conflict), no directory fsync
   is currently present, '27 fields' list is inconsistent, and listed existing test
   files/counts do not match git diff. Report exact inspected state and test scope.

Use focused adversarial tests and typecheck, raw logs /tmp/cm-agy-cron-batch1-r2-*.log.
Do not run a full suite or mark the whole cron owner complete. CBC owns Python bridge,
primary owns global plans and CI is separately committed. Do not commit/push, act on
accounts, touch live state, restart services or launch providers. Keep the report concise.
