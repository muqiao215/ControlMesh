# Runtime convergence progress

## Current scope and production boundary

Full CM-R0–CM-R7 remains active: complete TS ownership, multi-device coordination,
real native Agent continuity and release/install alignment. Read task_plan.md for the
acceptance matrix. All 512 Python module owners and 57 persisted TaskEntry fields
remain in the inventory; a passing candidate gate does not retire those owners.
Installed CM 0.43.0 remains the production Python writer. No live migration, service
switch, release or installation is performed by the current topology increment.

## Current implementation

RuntimeControlTopology now connects director/judge decisions to actual local task runs,
accepted effect output and persisted checkpoint/round identity. Schema 20 freezes the
controller task/role, parallel limit and budgets. Worker collection, state transitions
and next-task enqueue/resume commit atomically; same-role tasks retain their native
identity through assignment generations. Judge repair/interruption caps survive restart.
Generic topology mutation cannot bypass a managed controller. Malformed decisions remain
unaccepted; there is no automatic fresh session fallback or model replay.

The preceding pipeline and fanout queue compositions are already on main. The new
controller composition completes explicit local steps for all four approved topologies;
a terminal checkpoint still does not finalize the parent TaskHub task.

## Verification and publication

- Previous main: 6146dab; CI 34685935121 verified successful.
- Current focused gate before final admission checks: 24 pass, 0 fail, 141 assertions,
  3 files in 1.56s; runtime typecheck passed.
- Full pinned runtime gate after final admission checks: 523 pass, 0 fail, 7548 assertions
  across 62 files in 223.39s (exit 0). Log: /tmp/cm-control-queue-full.log.
- Current increment remote CI is pending; a local green gate is not remote acceptance.
- No real provider/model run was launched. Fixture native session IDs establish only
  orchestration behavior, not real-model/native continuity acceptance.
- Schema 20 is private candidate storage. Upgrade tests preserve older tasks/topologies;
  downgrade requires a pre-upgrade backup, never editing a populated database version.

## Next execution order

1. Parent task lifecycle finalization from an accepted terminal topology transition.
2. Bounded automatic service scheduling and explicit malformed-output recovery.
3. Device topology queues with the same assignment/revision/authority boundaries.
4. Real native topology/source-revision profiles, remaining provider/transport/store
   owners and the full ownership/parity matrix.
5. Release/install/default rollout only after all full-goal gates are proven.

Keep canceled tasks 77f04609/7738c5eb canceled. Do not replay failed native acceptance
attempts or launch browser-account/cron/bot canaries as a convenience test. Observation
timeout is not evidence that an existing execution ended.

## Retained evidence

Detailed preceding execution, native acceptance failures/recoveries, exact commits and
logs are retained in [progress-through-6146dab.md](progress-through-6146dab.md). Search
that archive for the relevant owner; it is historical evidence, not the current next-step
list. Current durable behavior is in docs/ARCHITECTURE.md; concrete findings and links
are in findings.md and the relevant native acceptance design files in this directory.
