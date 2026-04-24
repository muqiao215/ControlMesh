# `controlmesh/memory`

Additive memory-v2 primitives inspired by OpenClaw's mature split between:

- durable authority memory (`MEMORY.md`)
- per-day memory notes (`memory/YYYY-MM-DD.md`)
- dream diary output (`DREAMS.md`)
- machine-managed dreaming state (`memory/.dreams/`)

`MEMORY.md` is now the primary durable memory surface.
`memory_system/MAINMEMORY.md` remains only as a lazy compatibility layer that
is created when legacy consumers still need it.

## What Exists in Cut 2

### File layout

- `workspace/MEMORY.md`
  - human-readable durable authority for promoted items
  - grouped into fixed sections: `Fact`, `Preference`, `Decision`, `Project`, `Person`
- `workspace/memory_system/MAINMEMORY.md`
  - legacy compatibility mirror
  - no longer seeded at workspace init; created lazily by compat sync
- `workspace/memory/YYYY-MM-DD.md`
  - daily note skeleton with explicit `## Promotion Candidates`
- `workspace/DREAMS.md`
  - append-only dream diary for cross-day synthesis output
- `workspace/memory/.dreams/sweep_state.json`
  - last dreaming sweep status / timestamps / promoted keys
- `workspace/memory/.dreams/checkpoints.json`
  - per-daily-note checkpoint metadata
- `workspace/memory/.dreams/dreaming.lock.json`
  - exclusive sweep lock ownership with expiry
- `workspace/memory/.dreams/promotion_log.json`
  - deterministic de-duplication ledger for already promoted items
- `workspace/memory/.dreams/search.sqlite3`
  - workspace-local SQLite FTS5 index for memory-v2 artifacts
- `workspace/memory/.dreams/sweep_log.jsonl`
  - append-only run log for preview/apply dreaming sweeps

### Deterministic promotion flow

Promotion candidates come from explicit markdown markers inside a daily note:

```md
## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
- [preference score=0.90] Prefer OpenClaw-style split memory, adapted for ControlMesh.
```

No agent prompt is used to classify or promote these lines. The parser is
purely rule-based:

- only lines inside `## Promotion Candidates` are considered
- category must be one of the fixed durable-memory sections
- `score=` is optional and numeric
- candidate IDs are deterministic hashes of normalized category + content

Preview/apply helpers live in `controlmesh.memory.commands`:

- `preview_daily_note_promotions(...)`
- `apply_daily_note_promotions(...)`

These helpers now feed the runtime-facing authority memory path and legacy
compatibility mirror.

### Local FTS5 search

`controlmesh.memory.search` adds a workspace-local search backend using
SQLite FTS5 only.

Indexed sources:

- `MEMORY.md`
- `DREAMS.md`
- `memory/YYYY-MM-DD.md`

The index stays deterministic:

- the canonical authority remains the markdown files, not SQLite
- each indexed document stores a SHA-256 content hash
- sync updates rows only when the content hash changes
- deleted source files are removed from the index
- queries return source path, kind, optional note date, snippet, and rank

Primary helpers:

- `sync_memory_index(...)`
- `search_memory_index(...)`

Thin wrappers also exist in `controlmesh.memory.commands`:

- `sync_memory_search(...)`
- `search_memory(...)`

### Dreaming machine state and sweep runner

`controlmesh.memory.dreaming` stores only concrete operational state:

- sweep status
- last run mode
- last processed day
- last changed/selected/applied counters
- promoted candidate keys
- daily note checkpoints
- exclusive sweep lock ownership + expiry
- append-only sweep run log

The first dreaming sweep runner is intentionally narrow and deterministic:

- it scans daily notes in date order
- it hashes each note and skips unchanged notes with matching checkpoints
- it reuses the cut1 explicit promotion parser and apply helpers
- `preview` mode reports what would be promoted without touching checkpoints
- `apply` mode updates `MEMORY.md`, checkpoints, promotion log, sweep state, and
  appends a reviewable entry to `DREAMS.md`

Primary helpers:

- `preview_dreaming_sweep(...)`
- `apply_dreaming_sweep(...)`

There is still no autonomous scheduler or background dreaming job in this cut.

## What Is Deliberately Deferred

- embeddings / vector search
- automated cross-note ranking or clustering
- cron wiring or service startup integration
- replacing the remaining legacy compatibility read surfaces entirely
- historical migration
- OpenClaw runtime assumptions that depend on its own command surface

## Why This Shape

OpenClaw's docs show a solid architecture around explicit memory files,
daily memory, search, and dreaming. ControlMesh needs the same split, but with
its own constraints:

- file-backed authority stays canonical
- legacy compatibility is allowed, but only as a mirror of the authority
- local SQLite is an index, never the authority
- operations must be reviewable and deterministic
- no cloud dependency is introduced
- future search can be added behind this file/state boundary instead of
  becoming the source of truth
