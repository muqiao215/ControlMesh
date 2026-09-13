# AGY batch 1 review 3 — concrete remaining regressions

Your r2 native worker completed exit 0. CM delivered its terminal event and primary
consumed it once (second consume returned null/exit 3). This proves the controller path;
your implementation remains unaccepted. Same native conversation and TS-only ownership.
Use concrete regressions below, not broader rewrites. Keep existing tests; expand them.

## Primary reproduced, with actual Bun/RuntimeDatabase

Input to importCronRegistry on :memory: included one valid core job with:
`description: null, timezone: null, raw: 'user-raw', version: 'user-version',
spec_digest: 'user-digest'`. Export produced description='', timezone='', and all three
user metadata fields were missing. getCoordinatorEpoch('invented-controller') on that
fresh DB created authority during a read. Thus the report's all-fixed claim is false.

1. Preserve exact imported/user JSON separately from normalized columns. Do not strip
   legitimate user keys merely because they collide with storage property names. Do not
   overwrite mergedUserMetadata with every normalized field (currently lines 430-457).
   Export raw user records faithfully; defaults for runtime use and Python-reader behavior
   are separate. Status updates should start from stored user input plus explicit patch,
   not {...hydratedRecord}; this prevents internal-field recursion without discarding
   user metadata. Test BOTH user key collisions and 50 repeated status-only updates,
   with null/empty/missing/zero retained and spec revision stable.
2. getCoordinatorEpoch must be read-only and fail if unregistered. Introduce an explicit
   bootstrap/registration mutation with clear local coordinator ownership. Transitions
   and rotations require the expected currently issued epoch so a stale caller with the
   same textual coordinator ID cannot rotate repeatedly. Keep it a single-coordinator
   store boundary; don't invent distributed election or claim authentication from a name.
3. Failover recovery currently deadlocks prior attempts: after epoch increment/rotation,
   reconciliation requires both current epoch equality and old attempt fence equality,
   which cannot both hold. Separate current controller authority from expected old
   attempt identity/fence when reconciling evidence. A current owner may record verified
   completion for the explicitly identified old attempt, without rerunning it; a stale
   old controller must still reject. Unknown evidence retains the lock. Test actual
   rotate A->B, late A rejection, B unknown hold, B identified completion/release, no
   second execution and no replacement of an already terminal result.
4. exportCronRegistry's bare Database branch does not start its own read transaction;
   only the CLI happens to. Make the exported function itself snapshot-consistent for
   both DB types, respecting an existing caller transaction. Test its direct read-only
   caller with a concurrent metadata/job mutation. CLI export currently allows app=0
   and any future version >=43; require actual supported ControlMesh identity/version.
5. import openSync(source,'r') follows symlinks and may block on FIFO before fstat. Use
   no-follow/non-blocking descriptor checks and bounded read with before/after metadata
   validation. Preserve safe current growth/size rejection. No production input reads.
6. An exported file opened directly at its final name is visible while partially written.
   Publish a fully fsynced sibling temp exclusively (e.g. link then remove temp on POSIX),
   never overwrite existing destination; clean failed temps. Do not claim atomic export
   from open('wx') alone. Add failure/concurrent-destination tests.

Run focused cron tests/typecheck and only relevant migration checks after actual changes.
Logs: /tmp/cm-agy-cron-batch1-r3-*.log. Keep a concise report (under 120 lines): map each
regression to an actual test/result; do not say all defects fixed unless covered. Do not
edit Python/CI/global plans, commit/push, launch more workers, change production state,
use accounts/browser tasks or restart services. Current main moved to 8f4de54; preserve
the CI and bridge commits. Full cron scheduling/ingress and full TS migration remain open.
