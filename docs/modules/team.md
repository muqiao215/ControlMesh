# Team Module

The additive `ductor_bot/team/` package is the first state-led slice of the OMX migration.

It now includes a narrow leader-session live bridge, but it still does **not** start workers, manage tmux, or replace Ductor's existing task/session stack.

## Included in This Cut

- contracts and validated models for:
  - team manifest
  - nested leader session identity via `TeamSessionRef`
  - nested leader/worker runtime ownership via `TeamRuntimeContext`
  - task claims
  - dispatch requests
  - mailbox messages
  - events
  - phase state
- separate persisted worker runtime state for live execution facts:
  - strict lifecycle: `created`, `starting`, `ready`, `busy`, `unhealthy`, `stopped`, `lost`
  - explicit runtime execution facts: `execution_id`, `lease_id`, `lease_expires_at`, `heartbeat_at`, `health_reason`
  - deterministic reconcile from persisted lease facts without starting or probing processes
- file-backed state primitives under a dedicated team state root
  - canonical runtime/CLI root: `DuctorPaths.team_state_dir` -> `workspace/team-state`
- team JSON envelope API:
  - `read-manifest`
  - `list-tasks`
  - `get-summary`
  - `read-events`
  - internal write-gated: `record-dispatch-result`
- limited live delivery bridge:
  - dispatch requests can inject a coordination prompt into a worker routable session when one is persisted, with deterministic leader-session fallback via `MessageBus`
  - delivered dispatch requests can later accept an explicit worker-reported result writeback via the existing team state layer
  - mailbox messages can emit leader-visible unicast notifications
- phase transition machine:
  - `plan`
  - `approve`
  - `execute`
  - `verify`
  - `repair`
  - terminal: `complete`, `failed`, `cancelled`

## Not Included Yet

- worker process lifecycle
- real worker process start/stop/attachment
- tmux/team runtime management
- gateway dispatch wiring
- write-capable external API operations
- true worker-session delivery or per-worker runtime execution
- end-to-end delivery acknowledgements beyond successful bus submission
- worker runtime/process execution control

## Live Bridge

The current live path is intentionally narrow:

- dispatch requests first check `TeamManifest.worker_runtime_ref(...).routable_session`
- when a worker runtime already owns a routable session, the existing `MessageBus` injects directly into that worker session
- when a worker is not directly routable, dispatch requests deterministically fall back to `TeamManifest.leader.session`
- mailbox messages still use a leader-visible unicast notification without injection
- worker targets remain team-state semantics, not independently managed live runtimes

This keeps the cut additive to Ductor's existing bus/session stack and avoids inventing a second delivery mechanism before worker runtime management exists.

Direct worker routing in this cut is intentionally limited to dispatch requests:

- the team layer already has persisted worker runtime ownership for dispatch targeting
- mailbox state is still leader-visible coordination state, not a proven per-worker inbox transport
- mailbox delivery therefore stays honest: leader-visible only, with no fake worker-delivered acknowledgement path

## Identity Model

`SessionKey` remains Ductor's chat/session identity. The team layer composes with it instead of redefining it:

- `TeamLeader.session` stores a `TeamSessionRef`
- `TeamLeader.session_key` materializes the existing `SessionKey`
- `TeamLeader.runtime.cwd` owns the leader workspace/runtime cwd
- `TeamWorker.runtime.provider_session_id` stores provider-local runtime session ids
- `TeamWorker.runtime.session_name` stores the Ductor-side runtime/session handle when one exists
- `TeamWorker.runtime.routable_session` stores an optional future-routable `TeamSessionRef` without replacing `SessionKey`
- `TeamWorker.runtime_ref` flattens worker ownership into a narrow runtime/session reference for orchestration code

## Worker Runtime Ownership

Worker runtime ownership is still manifest-backed and additive:

- team-local ownership remains `TeamWorker.name`
- provider/runtime-local ownership is captured in `runtime.provider_session_id`
- optional Ductor runtime handle is captured in `runtime.session_name`
- optional future live route is captured in `runtime.routable_session`

The read-only summary now exposes both:

- `workers`: the persisted manifest entries
- `worker_runtimes`: explicit flattened ownership records derived from those workers
- `worker_runtime_states`: persisted dynamic runtime truth for currently known worker runtime units
- `worker_runtime_counts`: lifecycle counts across persisted dynamic runtime records

## Worker Runtime State

Dynamic runtime truth now lives outside the manifest in `worker-runtimes.json`.

This split is intentional:

- manifest entries still define static worker identity and any pre-known routing handles
- runtime state records define live execution facts that can expire or be recovered independently
- recovery can classify state from persisted timestamps without inventing process supervision

Each runtime record is keyed by worker name and carries only live facts:

- `status`
- `execution_id`
- `lease_id`
- `lease_expires_at`
- `heartbeat_at`
- `health_reason`
- `started_at` / `stopped_at`

The first cut does not start or attach a real process. It does establish the runtime contract the next cut can bind to a real worker unit:

- create a runtime record
- transition it through strict lifecycle boundaries
- renew heartbeat/lease metadata
- reconcile it to `lost` when persisted lease ownership expires

Dispatch envelopes now also record the effective live route in envelope metadata and emitted events:

- `live_route`: `worker_session` or `leader_session`
- `live_target_session`: the serialized `SessionKey` storage key for the actual bus target

This makes direct-worker vs. leader-fallback behavior inspectable without adding a second transport or widening the external API.

## Result Writeback

Execution/result writeback is now intentionally narrow and explicit:

- `TeamDispatchRequest.status` still only tracks transport-side lifecycle:
  - `pending`
  - `notified`
  - `delivered`
  - `failed`
  - `cancelled`
- a separate `TeamDispatchResult` record can be attached only after a dispatch is `delivered`
- the latest persisted result records:
  - `outcome`: `completed`, `failed`, or `needs_repair`
  - optional `summary` / `details`
  - `reported_by`
  - `reported_at`
  - optional linked `task_status`
- route provenance is now persisted on the dispatch request itself:
  - `live_route`
  - `live_target_session`

This keeps three facts separate:

- the bus delivered a dispatch to a live route
- a worker later reported an execution/result outcome
- the linked task status optionally changed because of that outcome

`TeamLiveDispatcher.record_dispatch_result(...)` is the narrow writeback entry point for future runtime/orchestration code. It records the latest result, emits a `dispatch_result_recorded` event, and emits `task_status_changed` when the linked task status changes.

Runtime/CLI callers now also have a minimal honest call path without inventing a new transport:

- internal localhost endpoint: `POST /teams/operate`
- request shape:
  - `operation`: one of the team API operations
  - `request`: JSON object passed through to `ductor_bot.team.api.execute_team_api_operation(...)`
- exposed operations through this endpoint:
  - `read-manifest`
  - `list-tasks`
  - `get-summary`
  - `read-events`
  - `record-dispatch-result`

The write surface remains intentionally narrow. `record-dispatch-result` is the only internal write-capable operation in this cut, and it still routes through the existing team API envelope rather than exposing a broad mutable CRUD control plane.

This still does **not** mean Ductor owns worker execution. The team layer only persists worker-reported outcomes after dispatch delivery; it does not start, supervise, or verify worker runtime/process execution.

The manifest now persists nested `session` and `runtime` records, but still accepts the earlier flattened fields on input:

- leader `session_transport` / `session_chat_id` / `session_topic_id`
- manifest-level `cwd`
- worker `session_id`
- worker `session_name`

## Files

- implementation: `ductor_bot/team/`
- tests: `tests/team/`
