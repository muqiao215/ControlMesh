# Findings

## Requirements

- Required domains: create, tell, ask_parent, resume, cancel, recovery, workspace,
  artifact.
- The output must be a language-neutral executable parity baseline, not another prose-only
  requirements document.
- Python runtime behavior and persisted state are authoritative; JSON fixtures must be
  deterministic enough for CI drift checks.

## Research Findings

- The read-only Alpha deliberately omits mutation endpoints and SDK methods. This matrix is
  the next gate before those boundaries can be reconsidered.
- `TaskHub` owns submit/run/resume/question/cancel/shutdown; `TaskRegistry` owns persisted
  entries, seeded task folders, cleanup, and deletion. Running-task `tell` is an append-only
  task-folder inbox, while resume is allowed only from terminal/waiting states with a
  stored provider and session.
- The architecture requires parity evidence across state transitions, provider processes,
  delivery, recovery, workspace, and artifacts; SDK smoke tests are explicitly insufficient.
- Existing provider goldens establish a precedent under `tests/golden/fixtures/`, but the
  lifecycle matrix does not yet exist. Migration status still lists TaskHub/state,
  workspace mutation, artifacts, and recovery among blocked runtime ports.
- Required lifecycle evidence must include topic/parent routing, stable task identity and
  folder reuse, persisted provider/model/session fields, state/error transitions, update
  inbox behavior, recovery classification, and relative/contained artifact paths.
- `tests/golden/fixtures/tasks/create.basic.json` is currently an unexecuted placeholder:
  it asserts only `status=running` and has no generator/test. The golden README lists
  create/resume/tell/ask_parent plus workspace/artifact fixtures as required but absent.
- `TaskRegistry.create` generates an 8-hex task ID, persists the complete `TaskEntry`, seeds
  `TASKMEMORY.md`, three provider rule files, `WORKUNIT.json`, evidence/result templates,
  and a `task.folder.seeded` JSONL event. Per-agent `tasks_dir` is persisted and controls
  later folder resolution.
- On registry reload, persisted `running` or `recovering` entries become `stale` with a
  stable restart error; orphan entry/folder cleanup then reconciles registry and disk.

## Technical Decisions

| Decision | Rationale |
|---|---|
| Use one versioned matrix instead of unrelated per-operation snapshots | Cross-domain state, recovery, workspace, and artifact observations remain reviewable as one mutation gate. |
| Generate by executing production Python ownership paths | Hand-written expectations could silently diverge from the runtime that the project defines as authoritative. |
| Normalize only task IDs, clocks, temporary roots, and process IDs | Stable public errors, state, routing, file names, and relative paths must remain drift-sensitive. |
| Validate the language-neutral envelope with JSON Schema | Future TypeScript or other runtime consumers need an implementation-independent fixture contract. |

## Issues Encountered

| Issue | Resolution |
|---|---|
| Initial broad source read exceeded output limits | Switched to symbol-targeted small reads. |
| First oracle read the event key as `type` | Corrected it to the production `event_type` envelope and regenerated. |
