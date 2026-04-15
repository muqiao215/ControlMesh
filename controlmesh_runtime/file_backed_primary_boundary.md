# File-Backed Primary Boundary

## Decision

Phase 20 keeps file-backed state as the primary persistence model for the
current harness-runtime line.

SQLite remains a later boundary, not the next implementation target.

This is a design-only decision. Phase 20 does not add:

- SQLite code
- migration code
- dual-write logic
- replay logic
- query surfaces
- store backend abstraction

## Why File-Backed Primary Still Fits

The current runtime line is still stabilizing object boundaries:

- engine-local trace
- typed execution payloads
- wrapped execution runtime events
- execution evidence persistence landing zone

That means the most valuable property right now is inspectability, not query
power.

File-backed primary remains the right default because:

- persisted objects are still being shaped in narrow phases
- file layout keeps every checkpoint easy to inspect and audit by hand
- append-only JSONL matches the current evidence model well
- the line still follows plan-with-files and single-writer truth discipline
- there is no demonstrated cross-packet or cross-task query pressure yet
- there is no demonstrated multi-consumer consistency problem yet

At this stage, a database would add backend weight before the runtime has shown
enough stable read patterns to justify it.

## What Must Stay File-Backed For Now

Phase 20 keeps these facts explicit:

- tasks stay file-backed
- workers stay file-backed
- reviews stay file-backed
- runtime events stay file-backed
- execution evidence stays file-backed

This is not a claim that files are forever the best backend.

It is a claim that the current runtime still benefits more from transparent
artifacts than from a query engine.

## SQLite Boundary Triggers

SQLite should not begin because it feels cleaner.

It should begin only when one or more hard trigger conditions are true.

### Trigger 1: Cross-Entity Query Pressure

Start the SQLite boundary if runtime work needs stable queries across many
packets, tasks, workers, or execution-evidence files, such as:

- cross-packet execution evidence lookup
- task-to-review-to-execution joins
- worker-centric historical failure queries

If those queries become a first-class runtime need, files stop being a good
primary query surface.

### Trigger 2: Evidence Volume Starts Hurting Maintenance

Start the SQLite boundary if execution evidence volume makes the file-backed
layout operationally awkward to inspect or manage.

Examples:

- too many JSONL files to reason about manually
- archive size or scan cost becomes a routine burden
- append/load behavior remains correct but operator use becomes clumsy

### Trigger 3: Consistent Multi-Reader Runtime Views

Start the SQLite boundary if multiple runtime readers need a shared,
transaction-like view of current evidence rather than independent file reads.

Examples:

- controller-like readers
- summary consumers
- review consumers
- dashboard or operator surfaces

If multiple surfaces need a synchronized read model, SQLite becomes a better
candidate.

### Trigger 4: Cross-File Join Becomes Structural

Start the SQLite boundary if replay, summary compression, or review submission
cannot stay narrow without joining many file-backed records repeatedly.

The hard signal is not "joins exist."

The hard signal is "cross-file joins become structural runtime behavior rather
than occasional tooling."

## Triggers That Do Not Count

These are not enough by themselves:

- "SQLite would be cleaner"
- "A database seems more serious"
- "We may want dashboards later"
- "It might help queries someday"
- "There are several JSONL files now"

Phase 20 rejects speculative migration.

The boundary should move only when real runtime pressure is visible.

## First SQLite Landing Zone Priority

If the SQLite boundary is triggered later, the first landing zone should be:

1. execution evidence
2. review/query-oriented read surfaces
3. only then broader runtime state

This ordering is deliberate.

Execution evidence is the first SQLite candidate because it is the most likely
source of:

- append-heavy growth
- cross-packet inspection pressure
- cross-file join pressure
- future replay/query temptation

What should not happen first:

- moving all tasks, workers, reviews, summaries, and recovery state at once
- introducing a general backend abstraction before the first real pressure point
- letting SQLite become an excuse for broad runtime rewiring

The first SQLite cut, if it happens, should be narrow and evidence-led.

## Migration Boundary

When the SQLite boundary eventually opens, it should still respect the current
runtime layering:

- trace remains source
- payload remains expression
- `RuntimeEvent` remains the shared shell
- persistence remains the landing zone

SQLite must not reverse that order.

If future persistence design tries to redefine event or payload shape around the
database schema, the boundary has slipped.

## Acceptance Boundary

Phase 20 is complete when the runtime line can answer:

- why file-backed primary still fits the current phase
- which hard conditions would justify a SQLite boundary
- which conditions do not justify it
- what the first SQLite landing zone would be
- what SQLite work is explicitly still deferred

If the answer includes new store implementation code, dual-write, replay,
query APIs, or migration steps, it is outside the Phase 20 boundary.
