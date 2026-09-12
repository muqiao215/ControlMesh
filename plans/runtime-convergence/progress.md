# Runtime convergence progress

## Current scope and production boundary

Full CM-R0–CM-R7 remains active: complete TS ownership, multi-device coordination,
real native Agent continuity and release/install alignment. Read task_plan.md for the
acceptance matrix. All 512 Python module owners and 57 persisted TaskEntry fields
remain in the inventory; a passing candidate gate does not retire those owners.
Installed CM 0.43.0 remains the production Python writer. No live migration, service
switch, release or installation is performed by the current topology increment.

## Current implementation

All four approved local queue compositions now seal terminal reductions and finish idle
root tasks in the same transaction. Schema 21 stores completion proof; the kernel rechecks
current child run/episode/effect results, assignment generations and the exact checkpoint.
Changed, unresolved or queued work prevents closure. Failure of terminal event insertion
rolls back acceptance and topology progress. Replays after reopen produce one event.

The parent result explicitly identifies an internal topology reduction. No provider episode
or native session is invented. Existing DeliveryOutbox projects the resulting terminal event
once, without a model call. No external message was sent during acceptance.

Required artifact/SpecMesh success gates, nested aggregate bindings and explicit topology
reopen remain pending and are refused rather than bypassed. Director/judge immutable budgets,
controller identities and assignment generations from the previous increment remain active.

## Verification and publication

- Previous main: 52c657c; CI 34686581108 verified successful.
- Focused gate: 30 pass, 0 fail, 197 assertions across 3 files in 2.19s; runtime typecheck passed.
- Full pinned runtime gate: 532 pass, 0 fail, 7610 assertions across 62 files in
  229.07s (exit 0). Evidence: /tmp/cm-parent-completion-full.log.
- Current increment remote CI is pending; a local green gate is not remote acceptance.
- No real provider/model run was launched. Fixtures establish orchestration behavior,
  not real-model/native continuity acceptance.
- Schema 21 is private candidate storage. Upgrade tests preserve older tasks/topologies;
  downgrade requires a pre-upgrade backup, never editing a populated database version.

## Next execution order

1. Required artifact/SpecMesh root completion gates, nested aggregate result binding
   and explicit topology reopen with retained history.
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
