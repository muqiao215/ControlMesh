# `ductor_bot/memory`

Additive memory-v2 primitives inspired by OpenClaw's mature split between:

- durable authority memory (`MEMORY.md`)
- per-day memory notes (`memory/YYYY-MM-DD.md`)
- dream diary output (`DREAMS.md`)
- machine-managed dreaming state (`memory/.dreams/`)

This cut does **not** replace Ductor's existing `memory_system/MAINMEMORY.md`.
It creates a parallel, explicit, file-backed substrate that future search and
dreaming work can build on.

## What Exists in Cut 1

### File layout

- `workspace/MEMORY.md`
  - human-readable durable authority for promoted items
  - grouped into fixed sections: `Fact`, `Preference`, `Decision`, `Project`, `Person`
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

### Deterministic promotion flow

Promotion candidates come from explicit markdown markers inside a daily note:

```md
## Promotion Candidates
- [decision] Keep canonical authority file-backed and human-readable.
- [preference score=0.90] Prefer OpenClaw-style split memory, adapted for Ductor.
```

No agent prompt is used to classify or promote these lines. The parser is
purely rule-based:

- only lines inside `## Promotion Candidates` are considered
- category must be one of the fixed durable-memory sections
- `score=` is optional and numeric
- candidate IDs are deterministic hashes of normalized category + content

Preview/apply helpers live in `ductor_bot.memory.commands`:

- `preview_daily_note_promotions(...)`
- `apply_daily_note_promotions(...)`

Both helpers are internal utilities for now. They are not wired into the
runtime command surface yet.

### Dreaming machine state

`ductor_bot.memory.dreaming` stores only concrete operational state:

- sweep status
- last processed day
- promoted candidate keys
- daily note checkpoints
- exclusive sweep lock ownership + expiry

There is no autonomous scheduler or background dreaming job in this cut.

## What Is Deliberately Deferred

- semantic search / vector store
- automated cross-note ranking or clustering
- cron wiring or service startup integration
- replacing `/memory` or `MAINMEMORY.md`
- historical migration
- OpenClaw runtime assumptions that depend on its own command surface

## Why This Shape

OpenClaw's docs show a solid architecture around explicit memory files,
daily memory, search, and dreaming. Ductor needs the same split, but with
its own constraints:

- file-backed authority stays canonical
- operations must be reviewable and deterministic
- no cloud dependency is introduced
- future search can be added behind this file/state boundary instead of
  becoming the source of truth
