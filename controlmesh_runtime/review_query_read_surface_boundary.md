# Review and Query Read Surface Boundary

## Decision

Phase 23 stays design-only.

It defines when review/query-oriented read surfaces become justified and what
their first legal shape may be.

It does not add:

- query APIs
- read-surface implementation
- SQLite changes
- replay tools
- store-layout changes
- publisher or event bus behavior
- orchestrator behavior
- canonical promotion

## Purpose

Execution evidence is now a typed archive, and Phase 22 defined replay/query as
possible future evidence-inspection capabilities over that archive.

Phase 23 adds one more boundary before any read surface exists:

read surfaces may help review and handoff later, but they must remain evidence
consumers. They must not become truth owners, store drivers, or database
products.

## When A Read Surface Is Worth Adding

A review/query-oriented read surface is justified only when there is durable
pressure that file review alone no longer handles well.

Valid trigger conditions are:

- execution evidence volume makes manual file review painful
- stable `packet_id` lookup demand appears for single execution episodes
- stable `task_id` lookup demand appears for bounded task-level review
- review or handoff needs a fixed read view rather than repeated manual
  `source_refs` assembly
- Phase 20 SQLite boundary criteria are approaching or already met

These are structural pressures, not convenience preferences.

## When A Read Surface Is Not Worth Adding

Phase 23 rejects read-surface work for weak or transient demand.

Invalid trigger conditions are:

- one-off debugging convenience
- no stable `packet_id` or `task_id` access pattern
- evidence volume remains easy to inspect by file
- review still works through ordinary checkpoint and file review
- a developer wants a generic query layer before bounded review demand exists
- a future SQLite migration is merely anticipated, not justified by hard
  criteria

The rule is:

no read surface without a stable reader and a stable question.

## First Allowed Read Views

If a read surface is implemented later, the first legal view set is narrow.

Allowed first views:

- by `packet_id`, returning one execution episode
- by `task_id`, returning limited execution-evidence aggregation for review or
  handoff

The first view should answer bounded questions such as:

- what happened in this execution episode
- whether the episode reached a terminal result
- which execution payload event tokens were observed
- whether a failure class or stop boundary is present
- which worker id and packet id the evidence belongs to

The first view should not answer broad product or analytics questions.

## Rejected First-Cut Read Views

Phase 23 explicitly rejects first-cut read surfaces for:

- cross-line search
- cross-worker history
- cross-summary lookup
- cross-review lookup
- global text search
- fuzzy search
- arbitrary metadata filters
- SQL-like user-facing query
- dashboard-oriented aggregation
- transport/provider-specific lookup

Those may become separate future decisions, but they are not the first
review/query read surface.

## Evidence Consumer Boundary

A read surface is an evidence consumer.

It may:

- read archived execution evidence
- project a bounded review-oriented view
- preserve typed payload and `RuntimeEvent` identity
- report missing, malformed, or incomplete evidence
- provide input to later review or handoff work

It must not:

- mutate execution evidence
- rewrite payloads
- rewrite `RuntimeEvent` records
- promote `WorkerState`
- decide `ReviewOutcome`
- update canonical plan files
- create recovery plans
- emit runtime events
- publish to an event bus
- trigger orchestrator behavior

Read surfaces may make evidence easier to consume. They do not own truth.

## Relationship To Replay

Replay and read surfaces are related but separate.

Replay asks:

- can this archived execution evidence be validated as a coherent sequence

Read surfaces ask:

- can a bounded reader inspect this archived evidence without assembling files
  by hand

A future read surface must not imply replay implementation.

A future replay validator must not imply a broad read/query API.

Both remain evidence-inspection capabilities and both must use archived
execution `RuntimeEvent` evidence as their source.

## Relationship To File-Backed Primary

Read surfaces must build on the current file-backed execution evidence landing
zone.

They must not force immediate changes to:

- evidence file layout
- payload shape
- `RuntimeEvent` shape
- summary landing shape
- store backend
- SQLite boundary

If file-backed reads become painful, that pain may count as evidence for the
Phase 20 SQLite criteria. It does not bypass those criteria.

The direction remains:

archived execution evidence -> future bounded read surface

Never:

desired query shape -> rewritten evidence archive

## Relationship To SQLite

SQLite is not part of Phase 23.

Future read-surface pressure may help justify SQLite only if it matches the
hard triggers already defined by Phase 20:

- cross-entity query pressure
- evidence-volume maintenance burden
- consistent multi-reader runtime views
- structural cross-file joins

Even then, the first SQLite landing zone remains execution evidence.

Phase 23 does not authorize broad migration of tasks, workers, summaries,
recovery state, or canonical files into SQLite.

## Relationship To Review And Handoff

The first read surface should serve review and handoff, not general runtime
exploration.

Allowed future consumers:

- review preparation
- handoff preparation
- packet-level execution evidence inspection
- task-level bounded aggregation

Forbidden future ownership:

- final review adjudication
- canonical state promotion
- summary replacement
- progress-file replacement
- dashboard truth source

Review and handoff may consume read-surface output later, but they must still
own their own promotion and decision boundaries.

## Forbidden Shortcuts

Phase 23 forbids these shortcuts:

- adding a read API because replay may be useful
- adding SQLite because read surfaces may be useful
- adding global search before packet/task views are proven insufficient
- using read output as canonical truth
- mutating evidence to make a view easier
- broadening query grain to line/worker/summary/review by default
- treating typed evidence lookup as text search over prose
- letting read surfaces emit events or invoke orchestration

## Acceptance Boundary

Phase 23 is complete when the runtime line can answer:

- when a review/query-oriented read surface is justified
- when it is not justified
- which first read views are allowed
- which first read views are forbidden
- why the read surface is an evidence consumer rather than a truth owner
- how the read surface relates to replay
- how the read surface relates to file-backed primary and SQLite criteria

If the answer includes query APIs, read implementation, SQLite code, replay
tools, store-layout changes, publisher/event bus wiring, orchestrator behavior,
or canonical promotion, it is outside the Phase 23 boundary.
