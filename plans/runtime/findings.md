# Confirmed Facts
- Frontstage history and runtime events must remain separate surfaces.
- History cut 2 is sealed and should not be widened to absorb runtime event work.
- Runtime cut 1 red tests now lock a dedicated `runtime-events` root separate from transcripts.
- Runtime cut 1 red tests now lock a distinct `RuntimeEvent` model/store seam.
- Focused red-slice verification is stable: bounded `ruff` passes and bounded `pytest` fails in four expected contract locations.
- Runtime cut 1 green now exposes `ControlMeshPaths.runtime_events_dir`.
- Runtime cut 1 green now provides a real `RuntimeEvent` schema and `RuntimeEventStore` append/read behavior under `~/.controlmesh/runtime-events/...`.
- Focused green verification passes for the accepted runtime cut 1 slice.
- Runtime cut 2 red tests now lock a minimal TaskHub producer seam: Telegram-scoped `task.lifecycle.created`, `task.lifecycle.started`, and `task.lifecycle.terminal`.
- Runtime cut 2 red tests confirm transcript storage stays empty for the same session while runtime lifecycle writes are missing.
- Runtime cut 2 green now writes the bounded TaskHub lifecycle sequence into `RuntimeEventStore` via `SessionKey.telegram(chat_id, thread_id)`.
- Independent evaluator verification passed for runtime cut 2 green: bounded `ruff` passes and focused `pytest` passes at `2 passed`.
- Transcript storage remained untouched during runtime cut 2 green verification.

# Blockers
- None within the current frozen runtime scope.

# Risks
- Reusing transcript paths or models for runtime events would blur the product boundary.
- Event writes placed too high in the stack may accidentally capture frontstage-visible results instead of runtime facts.
- Task lifecycle write seams could accidentally duplicate or over-log events if hooked at the wrong layer.
- Worker evidence lanes can still drift from the canonical schema even when the bounded code/result slice is valid.

# Deferred
- runtime UI/panel
- analytics
- replay tooling
- non-Telegram producer seams
- richer runtime diagnostics/read surfaces

# Decision Records
- 2026-04-09: runtime line opened as a separate scope after the history stopline.
- 2026-04-09: runtime cut 1 red contract accepted as `pass_with_notes` after closure hardening and independent evaluator verification.
- 2026-04-09: runtime cut 1 green accepted as `pass_with_notes`; the next bounded cut is a real TaskHub lifecycle write seam.
- 2026-04-09: runtime cut 2 red contract accepted as `pass_with_notes`; the next bounded cut is the matching TaskHub lifecycle write implementation.
- 2026-04-09: runtime cut 2 green accepted as `pass_with_notes`; controller verification passed, while task-local evidence used a non-canonical outcome token and omitted part of the preferred findings shape.
- 2026-04-09: runtime line reached its current bounded completion condition and is sealed at `stopline`; further runtime expansion must open a new scope instead of extending this line in place.
