# Recovery Execution Boundary

## Purpose

This document defines where the recovery protocol stops and where a future
recovery execution layer may begin.

The current runtime foundation already has typed contracts for review, task
packets, runtime events, worker lifecycle state, persisted records, recovery
policy, and summary compression. Phase 7 does not add an engine. It only fixes
the boundary a future engine must obey.

The guiding rule is:

Policy decides whether recovery is allowed. The execution layer prepares and
runs bounded recovery actions. Human gates approve actions that must not be
crossed automatically.

## Responsibilities

The recovery execution layer may:

- Convert a `RecoveryDecision` into a bounded execution plan.
- Execute only generic recovery actions through runtime substrate interfaces.
- Emit typed runtime events for attempted, completed, failed, or gated actions.
- Persist execution results through the state store when store wiring exists.
- Stop when policy, terminal state, or human-gate boundaries require it.

The recovery execution layer must not:

- Decide recovery policy by reading prose, logs, or plan files directly.
- Mutate canonical plan files as a side effect of recovery execution.
- Reach into product transport implementations.
- Call CLI entrypoints as its primary runtime API.
- Encode Feishu, Weixin, provider, MCP, or plugin-specific recovery behavior in the core engine.
- Invent new scope, defer, or stopline semantics outside the existing review and recovery contracts.

## Inputs

A future recovery engine may consume only typed runtime objects and substrate
interfaces. It should not scrape logs or infer behavior from human prose.

Allowed typed inputs:

- `RecoveryContext`
- `RecoveryPolicy`
- `RecoveryDecision`
- Current `TaskPacket`
- Recent `RuntimeEvent` records
- Current `WorkerState`
- Persisted `ReviewRecord` values
- Persisted or in-memory `SummaryRecord` values

Allowed substrate inputs:

- State-store reads for known runtime objects
- Event-stream reads for recent typed events
- Optional summary reads for bounded handoff context
- Runtime configuration that is already represented as typed policy

Forbidden inputs:

- Raw transport payloads
- CLI stdout or stderr scraping
- Feishu, Weixin, Telegram, browser, or webhook-specific objects
- Shell command strings as recovery facts
- Plan-file prose as direct engine input

## Outputs

The execution layer should produce explicit execution objects before and after
actions run. These names are design targets, not Phase 7 Python classes.

`RecoveryExecutionPlan` should describe:

- Source `RecoveryDecision`
- Ordered generic actions
- Required human gates
- Expected state transitions
- Events that should be emitted
- Store records that may be written after execution
- Stop conditions

`RecoveryExecutionResult` should describe:

- Whether execution was skipped, gated, completed, partially completed, or failed
- Which generic actions ran
- Which action failed first, if any
- Whether escalation is now required
- Events emitted
- Store records written
- Notes needed for a future summary capsule

The engine output is not a product reply and not a transport response. Rendering
or user notification belongs above the runtime substrate.

## Allowed Dependencies

A future engine may depend on narrow runtime abstractions:

- Worker controller interface
- State store interface
- Event publisher interface
- Review gate or human gate interface
- Optional summary reader interface

These dependencies must be protocols or adapters owned by the runtime layer.
The engine should depend on their abstract behavior, not on specific process,
chat, CLI, webhook, or provider implementations.

## Forbidden Dependencies

A future engine must not depend directly on:

- Business transport implementations
- CLI command handlers
- Feishu, Weixin, Telegram, browser, or webhook provider modules
- Production service configuration
- Random shell command composition
- Plan-file mutation helpers
- Model-provider clients
- ControlMesh-specific adapter internals

Adapter-specific behavior can be attached later through extension points, but it
must not become part of the core recovery action taxonomy.

## Generic Recovery Actions

The core action taxonomy should stay generic and runtime-owned.

Core generic actions:

- `retry_same_worker`
- `restart_worker`
- `recreate_worker`
- `mark_reauth_required`
- `clear_runtime_state`
- `emit_human_gate`
- `split_scope`
- `defer_line`
- `stopline`

Adapter-specific actions must stay outside the core taxonomy unless they can be
expressed as generic runtime actions.

Examples of adapter-specific actions:

- `refresh_feishu_context_token`
- `restart_weixin_ilink_session`
- `rotate_telegram_webhook`
- `reopen_browser_tab`
- `refresh_mcp_plugin_connection`

Adapter-specific actions may later be represented as extension actions behind a
typed adapter boundary, but Phase 7 does not define that extension system.

## Human Gate Boundaries

The future engine must stop at a human gate when recovery would cross safety,
identity, production, or canonical-contract boundaries.

Mandatory human-gate cases:

- Operator-safety concerns
- Production destructive actions
- Actions that change canonical runtime or plan contracts
- Scope split, defer-line, or stopline decisions
- Identity, authentication, or external credential changes
- Any action whose effect cannot be represented by existing typed contracts

Human gate emission is a runtime event and decision boundary. It is not a
license for the engine to continue by asking a transport-specific UI directly.

## Relationship To Existing Contracts

`RecoveryPolicy` remains the authority for allowed recovery decisions.

`RecoveryDecision` remains the bridge from policy to execution planning.

`WorkerState` remains the authority for legal worker lifecycle transitions.

`RuntimeEvent` remains the event surface for recovery observations.

`RuntimeStore` remains a persistence substrate, not a recovery decision maker.

`SummaryRecord` may carry compressed context for handoff, but summaries do not
override typed task, worker, event, review, or recovery records.

## Deferred Items

Phase 7 deliberately defers:

- Python `RecoveryExecutionPlan` and `RecoveryExecutionResult` classes
- Recovery engine implementation
- Controller wiring
- Store write-side integration for recovery attempts
- Event publisher implementation
- Worker restart or recreation implementation
- Transport-specific recovery actions
- Auth refresh execution
- Adapter extension systems
- CLI or operator UI

## Acceptance Boundary

Phase 7 is complete when this boundary is explicit enough that a later engine
can be reviewed for violations before it is implemented.

A valid future implementation must be able to answer:

- Which typed inputs produced this execution plan?
- Which policy decision authorized it?
- Which generic action is being executed?
- Which runtime abstraction is being called?
- Which event and store facts will be emitted?
- Which human gate would stop the engine?

If the answer requires transport logs, product-specific provider state, or
direct plan-file mutation, the implementation is outside this boundary.
