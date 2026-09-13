# Cron persistence and offline migration acceptance

Status: accepted for source integration of persistence and offline migration only.
Runtime cron admission/execution and production cutover remain pending.

AGY delivered partial code through its original native conversation, but its final CLI
returned SUCCESS/exit zero alongside stderr declaring timeout with turn still in progress.
That is not provider completion evidence. Primary reviewed code and finished acceptance.

Implemented: schema 43 stores definitions, archived lineage, occurrences, attempts,
dependency locks and coordinator epochs. Controller generations and target attempt fences
are separate; uncertain attempts prevent replay. Import/export retains raw JSON and large
integers, separates internal metadata, supports exact replacement and transaction rollback.
Archive/restore retains historical attempts and forces a new definition revision. Snapshot
export is transactionally consistent and uses exclusive sibling-temp publication.

Evidence:

- Combined cron tests: 234 pass, 1069 assertions; typecheck passes.
- Primary's five recovery tests cover seven colliding raw keys, 50 status updates,
  exact replacement, rollback after later validation failure, archived active attempts,
  overlapping WAL reader/writer snapshots and a real publication EEXIST race with cleanup.
- Full runtime package: 1368 pass, 70 skip, two legacy-export failures in 191.55s.
  Cause: its schema upper bound remained 42. Updated to 43 and added unknown-version
  refusal without mutation. Targeted follow-up: 20 pass, 174 assertions. Do not report
  the initial full run as green. Remote CI must verify the submitted tree.

Logs: /tmp/cm-primary-cron-combined.log,
/tmp/cm-primary-runtime-cron-migration-full.log,
/tmp/cm-primary-cron-legacy-followup.log,
/tmp/cm-primary-persistence-recovery-typecheck.log.

No live registry migration, Python/TS dual write, provider run, account/browser action,
service restart or production default switch. Remaining scheduler integration must enforce
source provenance, sandbox/grant authority, quota circuits, dependency/quiet policy,
multi-device fencing, cancellation and delivery. Generic CLI exit zero cannot certify
native success; CBC 429 and AGY partial timeout are direct contrary evidence.
