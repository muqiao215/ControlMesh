# Persistent device scheduling

Implement the normal headless coordinator/worker service, not a cron prompt loop. This is
part of the full CM-R1/R2/R4/R5 migration. Production Python remains the factual released
owner until all cutover gates pass.

The coordinator remains the authoritative task writer. Add a generation to explicit device
assignment identity (legacy assignments retain their old digest) and a paginated discovery
operation. Each bounded page advances past jobs assigned to other devices and blocked work;
32 returned jobs and 1024 scanned candidates are transport bounds, not an invisible global
queue cap. A new explicit assignment has a new identity even if its specification is equal.

The worker persists one record per assignment/execution projection before starting it. Queue
states distinguish queued, running, timed waiting, blocked, unknown, completed and superseded.
Restart never reissues an unknown run. Current coordinator task inspection can settle local
bookkeeping after explicit reconciliation; it cannot invent a successful native result.
Only a confirmed pre-execution provider reset/backoff can automatically schedule another
preflight. Quota without reset, authentication and unresolved probe outcomes wait for explicit
operator action. Native effects that started remain subject to the existing retained-result
reconciliation path. No scheduled task is relabeled as a new human request.

A device-local scheduler lease uses Linux boot identity and elapsed time, with a monotonically
increasing local generation. Its ownership is checked inside the existing worker admission
and native process/file/message guards. Two scheduler processes cannot each claim a separate
concurrency budget. Process takeover invalidates old admissions; crash-owned runs become
unknown. Shutdown cancels owned work and closes control/state only after it drains. Explicit
pause stops new admission, drains current work and persists across daemon restart.

Normal CLI daemon mode starts the configured coordinator listener/recovery maintenance or
worker scheduler, survives stdin EOF, and exits on SIGINT/SIGTERM. Existing interactive stdio
behavior is preserved. Control exposes scheduler status, start/pause and explicit bounded
retry; no system service, cron, browser or chat transport is installed by these changes.

Acceptance: pagination/starvation and explicit-assignment identity; persisted discovery and
restart; parallelism and competing scheduler processes; quota/backoff timing with zero extra
probes; lost response/process/lease ownership and no duplicated native execution; cancellation,
configuration revocation and orderly daemon shutdown; actual normal-entrypoint native tasks
with mailbox exchange/continuation. Continue remaining provider, transport, store, topology,
terminal, release/install and cutover owners after this scheduler is verified.
