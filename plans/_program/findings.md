# Confirmed Facts
- ControlMesh should be treated as a file-driven project state machine, not a chat workflow.
- Canonical project truth belongs in `task_plan.md`, `findings.md`, and `progress.md`.
- Background workers are bounded execution lanes and should not mutate canonical state directly.
- Frontstage history must contain only user-visible interaction.
- Runtime/task lifecycle events belong in a separate event surface.
- The `plans/` control-plane skeleton and harness doctrine docs already exist in the repository.
- The history line transcript substrate and minimal frontstage write path already landed.
- Task `9e1e4062` produced candidate code changes for history cut 2 but did not close its evidence lane.
- Task `0e137494` also failed to close its evidence lane and was cancelled after repeated timeout-without-progress.
- The controller independently verified the current history cut 2 candidate with focused tests.
- The scorecard now defines explicit pass thresholds and automatic outcome mapping.
- The task templates and task docs now define a pure automatic worker contract.
- The protocol no longer uses human-gate or human-review outcomes; the evaluator/controller is the final adjudicator.
- The history line is sealed at a stopline with a bounded visible read surface checkpoint.
- Runtime cut 1 red contract is now accepted and checkpointed.
- Runtime cut 1 green substrate is now accepted and checkpointed.
- Runtime cut 2 red contract is now accepted and checkpointed.
- Runtime cut 2 green is now independently verified and accepted; TaskHub writes the bounded lifecycle sequence into the dedicated runtime event substrate without touching transcript storage.
- The current autonomous round now has no active ready queue across canonical product lines.

# Blockers
- None in the current autonomous round.

# Risks
- Transcript and runtime concerns may get re-coupled if the read surface is placed too low.
- Running worker changes in command/history surfaces must be reviewed before promotion.
- A worker can appear productive in the worktree while still failing the evidence contract.
- Repeated evidence-lane failure can stall a product line even when code-level verification looks good.
- If runtime events are added ad hoc, they may leak back into frontstage history or command surfaces.
- Worker result/evidence files can still drift from canonical outcome or schema conventions; controller verification remains the final promotion gate.

# Deferred
- broader UI/history browser work
- richer event analytics
- wider command/control-plane expansion
- broader runtime producers beyond the current TaskHub lifecycle slice

# Decision Records
- 2026-04-09: Adopt `plans/` as the harness control-plane skeleton.
- 2026-04-09: Default to automatic adjudication and exception-triggered pullback.
- 2026-04-09: Preserve single-writer truth promotion.
- 2026-04-09: Start with the history line before opening broader product-line work.
- 2026-04-09: Recycle a running task if it leaves code changes behind without result/evidence closure.
- 2026-04-09: Harden the harness with a pure automatic worker contract plus explicit score thresholds and automatic outcome mapping.
- 2026-04-09: Remove human-gate fallback entirely; the evaluator/controller now performs final adjudication without human intervention.
- 2026-04-09: After sealing history cut 2, move to a separate runtime line rather than broadening history scope.
- 2026-04-09: Accept runtime cut 1 red contract as `pass_with_notes` and advance immediately to the bounded green cut.
- 2026-04-09: Accept runtime cut 1 green substrate as `pass_with_notes` and advance immediately to a bounded TaskHub lifecycle write seam.
- 2026-04-09: Accept runtime cut 2 red contract as `pass_with_notes` and advance immediately to the bounded TaskHub lifecycle green cut.
- 2026-04-09: Accept runtime cut 2 green as `pass_with_notes`; focused controller verification passed, with only task-local outcome/schema drift left as a note.
- 2026-04-09: Close the current autonomous round at `stopline` because history is sealed, runtime is sealed, and the remaining lines are explicitly deferred.
