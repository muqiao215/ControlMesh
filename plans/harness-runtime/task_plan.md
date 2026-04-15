# Current Goal
Preserve the sealed harness-runtime foundation as the completion-pack input line: phases 1-23 are accepted as boundary and substrate history, and further work should continue through the new `Harness Runtime Completion Pack` blocks rather than new micro-phases here.

# Current Status
sealed_foundation_ready

# Frozen Boundaries
- do not modify business transport behavior
- do not prioritize CLI command-surface changes
- do not change production configuration or service wiring
- do not perform a Rust rewrite
- do not copy `claw-code` implementation surfaces
- do not widen this cut into full worker runtime ownership or task execution routing

# Ready Queue
1. No further micro-phase dispatch remains in this line
2. Continue through `plans/_program/` under `Harness Runtime Completion Pack v1`
3. Use the six completion-pack block lines as the only active continuation path

# Non-goals
- transport migration
- new CLI commands
- review UI or dashboard
- background worker orchestration changes
- production task/taskhub rewiring
- full plan-to-runtime migration in this sealed foundation line

# Completion Condition
- `plans/harness-runtime/task_plan.md`, `findings.md`, and `progress.md` exist
- `controlmesh_runtime/` exists as a minimal typed package
- the package exports `ReviewInput`, `ReviewOutcome`, and `review`
- the package exports `TaskPacket` and `RuntimeEvent`
- the package exports `WorkerState`, `WorkerStatus`, and transition helpers
- the package exports `ReviewRecord`, `RuntimeStore`, and decode errors
- the package exports typed recovery context, policy, intent, reason, escalation, and decision objects
- the package exports a pure recovery-policy mapping function
- the package exports typed summary input, summary records, compression decisions, and compression policy
- the package exports a pure summary-compression policy mapping function
- `controlmesh_runtime/recovery_execution_boundary.md` defines recovery execution responsibilities, inputs, outputs, allowed dependencies, forbidden dependencies, generic actions, human-gate boundaries, and deferred execution work
- the package exports `RecoveryExecutionAction`, `RecoveryExecutionStep`, `RecoveryExecutionPlan`, `RecoveryExecutionStatus`, and `RecoveryExecutionResult`
- `controlmesh_runtime/execution_wiring_boundary.md` defines how execution contracts should later connect to typed store and event surfaces and what a future orchestrator may and may not own
- `controlmesh_runtime/execution_event_shape.md` defines the chosen execution event-shape strategy, the fine-grained execution event set, typed payload families, coarse `EventKind` mapping, and review/state flow boundary
- `controlmesh_runtime/orchestrator_boundary.md` defines the orchestrator's sole responsibility, forbidden powers, place in the typed chain, allowed/forbidden dependencies, and first-engine stop boundary
- `controlmesh_runtime/first_engine_boundary.md` defines the first-engine minimum execution unit, capability ceiling, hard stop conditions, and the point where results must be handed back to review/state input surfaces
- `controlmesh_runtime/first_engine_contract_surface.md` defines the first-engine minimum input, linear engine states, minimal outputs, stop-reason truth, and engine-local invariants
- `controlmesh_runtime/first_engine_test_matrix.md` defines the first-engine happy path, stop-boundary cases, state-discipline cases, event-discipline cases, and output-discipline cases
- `controlmesh_runtime/first_engine_trace_examples.md` defines the minimum straight-line examples for success, human-gate stop, and adapter-specific stop
- the package exports engine-local `EngineRequest`, `EngineState`, `EngineStopReason`, `EngineTraceEvent`, `EngineExecution`, `ExecutionEventType`, `can_transition_engine_state`, `run_first_engine(...)`, and `execute_first_engine_plan(...)`
- `controlmesh_runtime/execution_payload_seam.md` chooses typed execution payload classes as the first post-hardening seam and defers typed persistence landing zones
- the package exports `ExecutionPlanPayload`, `ExecutionStepPayload`, `ExecutionResultPayload`, `ExecutionEventPayload`, `ExecutionPayloadEventType`, and a pure `build_execution_payload(...)` conversion helper
- the package exports a pure `build_runtime_event_from_execution_payload(...)` wrapper that turns typed execution payload evidence into the shared `RuntimeEvent` shell without publisher, store, or orchestrator behavior
- `RuntimeStore` provides a separate `execution_evidence` namespace and append/load methods for execution runtime event evidence only
- `controlmesh_runtime/file_backed_primary_boundary.md` explains why file-backed primary remains correct now, what hard trigger conditions justify a later SQLite boundary, and why execution evidence would be the first SQLite landing zone
- `controlmesh_runtime/summary_trigger_landing_boundary.md` defines the allowed summary trigger classes, first summary landing zone, first subject scope, and latest-snapshot summary revision posture
- `controlmesh_runtime/execution_evidence_replay_query_boundary.md` defines replay/query as possible future capabilities over archived execution evidence only, without changing evidence shape, store layout, SQLite boundary, or promotion behavior
- `controlmesh_runtime/review_query_read_surface_boundary.md` defines when review/query-oriented read surfaces become justified, the first allowed packet/task read views, and why those views must remain evidence consumers rather than truth owners
- the line is explicitly sealed as the accepted design/runtime foundation for `Harness Runtime Completion Pack v1`
- focused tests cover first-engine whitelist execution, human-gate stop, unsupported-intent stop, worker-id validation, backdoor rejection, forbidden-integration stop, linear engine-state transitions, trace terminality, result/event invariants, and token-set guardrails
- focused tests cover typed execution payload token-set guardrails, stable trace-to-payload conversion, and explicit failure for invalid or incomplete trace evidence
- focused tests cover payload-to-`RuntimeEvent` wrapping, coarse `EventKind` routing, failure-class propagation, unsupported payload rejection, and non-mutation of typed payloads
- focused tests cover execution evidence append/load, separate namespace layout, corrupt-file decode errors, schema-version presence, and rejection of non-execution runtime events
- focused tests cover all required outcomes:
  - `PASS`
  - `PASS_WITH_NOTES`
  - `RETURN_FOR_HARDENING`
  - `BLOCKED_BY_ENVIRONMENT`
  - `BLOCKED_BY_OPERATOR_SAFETY`
  - `STOPLINE`
  - `SPLIT_INTO_NEW_SCOPE`
  - `DEFERRED_WITH_REASON`
- focused tests cover task-packet validation and event-schema validation
- focused tests cover worker lifecycle validation and legal/illegal state transitions
- focused tests cover persisted round-trip, JSONL append order, bad-file decode errors, atomic writes, and schema-version presence
- focused tests cover recovery contract validity and known recovery-policy mappings
- focused tests cover recovery execution step/plan/result validity and stable core action taxonomy
- focused tests cover summary contract validity and known compression-policy mappings
- no transport, CLI-surface, or production-config files are changed
