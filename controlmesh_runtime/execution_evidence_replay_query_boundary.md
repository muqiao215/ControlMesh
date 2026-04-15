# Execution Evidence Replay and Query Boundary

## Decision

Phase 22 stays design-only.

It defines the legal future shape of replay and query semantics for execution
evidence.

It does not add:

- replay code
- query APIs
- store changes
- SQLite changes
- publisher or event bus behavior
- orchestrator behavior
- canonical promotion

## Purpose

Execution evidence now has a typed chain:

- engine trace is the source
- execution payload is the expression
- `RuntimeEvent` is the shared shell
- `execution_evidence` is the file-backed archive

Phase 22 fixes one more boundary before any future implementation:

replay and query may use archived execution evidence later, but they must not
reshape the evidence chain backwards.

## Replay Boundary

Replay is potentially valuable, but it is not an implementation target in this
phase.

If replay is introduced later, its only legal source should be archived
execution evidence:

- `RuntimeEvent` records from `controlmesh_state/execution_evidence/`

Replay must not use:

- naked engine trace as a persisted source
- ad hoc payload JSON outside the `RuntimeEvent` shell
- recovery plan/result files as an alternate replay truth
- transport logs
- CLI output
- plan prose

The replay level is therefore:

- execution evidence level

Not:

- trace level
- transport level
- controller level
- canonical state level

## Replay Minimum Input

A future replay attempt should require at least:

- packet id
- ordered execution-evidence runtime events
- typed execution payloads inside those runtime events

It may later also need:

- expected event-token set
- expected coarse `EventKind` mapping
- expected terminal result event

Phase 22 does not define the replay algorithm.

It only defines the legal input layer.

## Replay Output Boundary

Future replay output should be evidence about evidence, not promotion.

Allowed future replay outputs:

- replay validation result
- missing-event report
- ordering anomaly report
- payload integrity report

Forbidden future replay outputs:

- direct `WorkerState` promotion
- direct `ReviewOutcome` decision
- direct canonical file mutation
- automatic retry or recovery action
- event publication

Replay may inform review/state layers later, but replay must not become a
state-promotion engine.

## Query Boundary

Query may also be valuable later, but the first query surface must stay narrow.

The first legal query grain should be:

- by `packet_id`, for one execution episode
- limited task-level aggregation by `task_id`

Phase 22 rejects first-cut query surfaces such as:

- global cross-task search
- cross-line search
- full worker history search
- arbitrary metadata search
- dashboard-oriented query language
- SQL-like user-facing query APIs

The first query surface, if implemented later, should answer only bounded
questions about execution evidence.

## Query Minimum Inputs

Future query semantics may depend on:

- packet id
- task id
- event token
- coarse `EventKind`
- failure class
- worker id

It should not depend on:

- transport provider identity
- CLI command names
- UI route names
- untyped payload metadata
- canonical plan-file text

Query must remain typed evidence lookup, not text search over runtime prose.

## Relationship To File-Backed Primary

Replay and query must build on the existing execution evidence landing zone.

They must not force immediate changes to:

- store layout
- payload shape
- `RuntimeEvent` shape
- SQLite boundary
- event publisher design
- orchestrator design

If future replay/query pressure becomes strong enough to justify SQLite, that
decision must go through the Phase 20 boundary criteria first.

Replay/query need cannot silently bypass the file-backed primary decision.

## Relationship To SQLite

SQLite is not part of Phase 22.

Future replay/query needs may become evidence that SQLite is warranted, but
only if they trigger one of the already-defined hard criteria:

- cross-entity query pressure
- evidence volume burden
- consistent multi-reader runtime views
- structural cross-file joins

Until then, file-backed execution evidence remains the primary archive.

## Forbidden Reverse Pressure

Phase 22 explicitly forbids these shortcuts:

- changing execution evidence shape to make replay easier
- changing payload shape to make queries easier
- adding SQLite because query might be useful later
- introducing event bus or publisher behavior for replay
- letting replay trigger orchestrator actions
- letting query become canonical truth
- using replay/query as a reason to persist naked trace

The direction remains:

trace -> payload -> `RuntimeEvent` -> persistence -> future replay/query

Never the reverse.

## Acceptance Boundary

Phase 22 is complete when the runtime line can answer:

- whether replay may become a valid future capability
- what replay's legal source layer is
- what replay must not output
- whether query may become a valid future capability
- what the first query grain may be
- how replay/query relate to file-backed primary and SQLite boundary criteria

If the answer includes replay code, query APIs, store changes, SQLite work,
publisher/event bus wiring, orchestrator behavior, or canonical promotion, it
is outside the Phase 22 boundary.
