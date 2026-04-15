# Team Module

The additive `controlmesh/team/` package is the first state-led slice of the OMX migration.

It now includes a narrow real worker runtime path backed by ControlMesh named sessions:

- attach to an existing named session when one is already resumable
- start a worker by bootstrapping the exact named session declared in the manifest
- stop that named session and persist `stopped` runtime truth

It still does **not** add a supervisor daemon, tmux fleet management, or a second transport.

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
  - explicit runtime execution facts: attachment identity, `execution_id`, `lease_id`, `lease_expires_at`, `heartbeat_at`, `health_reason`
  - deterministic reconcile from persisted lease facts plus current named-session owner identity without starting or probing processes
- file-backed state primitives under a dedicated team state root
  - canonical runtime/CLI root: `ControlMeshPaths.team_state_dir` -> `workspace/team-state`
- team JSON envelope API:
  - `read-manifest`
  - `list-tasks`
  - `get-summary`
  - `read-events`
  - internal write-gated: `record-dispatch-result`
- limited live delivery bridge:
  - dispatch requests can attach a worker to a real named-session runtime unit
  - verified attached workers can inject a coordination prompt into a worker routable session, with deterministic leader-session fallback via `MessageBus`
  - attached workers are claimed for a single active execution transaction at a time
  - delivered dispatch requests can later accept an explicit worker-reported result writeback via the existing team state layer
  - mailbox messages can emit leader-visible unicast notifications
- narrow runtime lifecycle automation:
  - `start-worker-runtime`
  - `stop-worker-runtime`
  - `heartbeat-worker-runtime`
  - both run through the internal localhost `/teams/operate` endpoint
  - all three reuse the existing named-session contract instead of introducing tmux or a new worker transport
- phase transition machine:
  - `plan`
  - `approve`
  - `execute`
  - `verify`
  - `repair`
  - terminal: `complete`, `failed`, `cancelled`

## Not Included Yet

- worker process lifecycle
- tmux/team runtime management
- gateway dispatch wiring
- write-capable external API operations
- generalized worker pool management or multi-worker scheduling
- end-to-end delivery acknowledgements beyond successful bus submission
- force-stop or execution-aware interruption while a worker is `busy`

## Live Bridge

The current live path is intentionally narrow:

- dispatch requests first verify whether the target worker is attached to a real runtime unit
- the first real runtime unit is a persisted ControlMesh named session:
  - source of truth: `ControlMeshPaths.named_sessions_path`
  - required facts: session exists, is not ended, and has a resumable `session_id`
- runtime start automation now creates that exact named session with a real bootstrap turn and persists the returned `session_id`
- runtime stop automation ends that exact named session through the existing orchestrator/process label path
- runtime owner validation now rejects `ready` / `busy` state when the current named-session `session_id` no longer matches the persisted attachment owner
- runtime heartbeat renewal now accepts lease refresh only from the current live named-session owner and extends `heartbeat_at` / `lease_expires_at` together
- the minimum non-daemon heartbeat driver now lives in the runtime lifecycle controller:
  - `start-worker-runtime` and runtime reattach arm a bounded in-process keepalive loop for that worker
  - the loop renews the same owner-validated heartbeat/lease while runtime state remains live
  - the loop exits on `stopped`, `lost`, or owner-validation failure
  - leader startup now scans canonical team state and recovers still-live runtimes:
    - valid persisted live runtimes are renewed immediately and have keepalive re-armed automatically
    - stale persisted live runtimes converge to `lost` instead of being trusted after restart
    - repeated recovery runs are idempotent and do not arm duplicate keepalive tasks
- when a verified attached worker also owns a routable session, the existing `MessageBus` injects directly into that worker session
- when a worker is not directly routable, dispatch requests deterministically fall back to `TeamManifest.leader.session`
- when a manifest advertises worker routing metadata but no real attachment can be verified, the team layer falls back to the leader route instead of trusting stale metadata
- mailbox messages still use a leader-visible unicast notification without injection
- worker targets remain team-state semantics, not independently managed live runtimes

This keeps the cut additive to ControlMesh's existing bus/session stack and avoids inventing a second delivery mechanism before worker runtime management exists.

Direct worker routing in this cut is intentionally limited to dispatch requests:

- the team layer already has persisted worker runtime ownership for dispatch targeting
- mailbox state is still leader-visible coordination state, not a proven per-worker inbox transport
- mailbox delivery therefore stays honest: leader-visible only, with no fake worker-delivered acknowledgement path

## Identity Model

`SessionKey` remains ControlMesh's chat/session identity. The team layer composes with it instead of redefining it:

- `TeamLeader.session` stores a `TeamSessionRef`
- `TeamLeader.session_key` materializes the existing `SessionKey`
- `TeamLeader.runtime.cwd` owns the leader workspace/runtime cwd
- `TeamWorker.runtime.provider_session_id` stores provider-local runtime session ids
- `TeamWorker.runtime.session_name` stores the ControlMesh-side runtime/session handle when one exists
- `TeamWorker.runtime.routable_session` stores an optional future-routable `TeamSessionRef` without replacing `SessionKey`
- `TeamWorker.runtime_ref` flattens worker ownership into a narrow runtime/session reference for orchestration code

## Worker Runtime Ownership

Worker runtime ownership is still manifest-backed and additive:

- team-local ownership remains `TeamWorker.name`
- provider/runtime-local ownership is captured in `runtime.provider_session_id`
- optional ControlMesh runtime handle is captured in `runtime.session_name`
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

- `attachment_type`
- `attachment_name`
- `attachment_transport`
- `attachment_chat_id`
- `attachment_session_id`
- `attached_at`
- `status`
- `execution_id`
- `dispatch_request_id`
- `lease_id`
- `lease_expires_at`
- `heartbeat_at`
- `health_reason`
- `started_at` / `stopped_at`

This cut now binds that contract to one narrow real runtime unit: a ControlMesh named session with a real bootstrap/stop path.

The team layer can now:

- create or re-establish a runtime record when a real named session is verified
- start that named session through a real bootstrap turn and persist the returned attachment facts
- stop that named session and persist `stopped`
- transition `created -> starting -> ready -> busy`
- claim a single active execution on `ready`
- persist the execution claim onto both the runtime record and the dispatch request
- release `busy -> ready` on explicit result writeback
- reconcile stale lease ownership to `lost`
- refuse to trust stale busy ownership after lease expiry by clearing `dispatch_request_id` during reconcile
- refuse to trust `ready` / `busy` ownership when the owning named session is missing or its `session_id` changed
- refresh `heartbeat_at` and extend `lease_expires_at` only when the live named-session owner proves the current `session_id`

The start/stop path is intentionally narrow:

- start uses the manifest's `worker.runtime.session_name`
- start runs one real bootstrap turn to create a resumable named session
- stop refuses to kill a `busy` runtime in this cut
- owner reconcile now checks the live named-session owner identity against persisted attachment facts
- heartbeat renewal now requires the caller to present the current owner `session_id`
- heartbeat renewal only refreshes persisted lease facts; it does not supervise a daemon or create its own loop
- the current driver is a controller-owned bounded task, not a separate process:
  - it is armed when the runtime is explicitly started or reattached
  - it keeps renewing through both `ready` and `busy`
  - it is cancelled on `stop-worker-runtime`
  - leader startup now re-arms it automatically for persisted runtimes that still validate against the live named-session owner
  - it still is not a separate daemon and does not supervise worker processes beyond that bounded recovery

If a named session is still missing, ended, or lacks a resumable `session_id`, dispatch falls back to the leader route and no fake worker execution claim is created.

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
- attached execution provenance is also persisted on the dispatch request when a real worker runtime was claimed:
  - `execution_id`
  - `runtime_lease_id`
  - `runtime_lease_expires_at`
  - `runtime_attachment_type`
  - `runtime_attachment_name`

This keeps three facts separate:

- the bus delivered a dispatch to a live route
- a worker later reported an execution/result outcome
- the linked task status optionally changed because of that outcome

`TeamLiveDispatcher.record_dispatch_result(...)` is the narrow writeback entry point for future runtime/orchestration code. It records the latest result, emits a `dispatch_result_recorded` event, and emits `task_status_changed` when the linked task status changes.

Runtime/CLI callers now also have a minimal honest call path without inventing a new transport:

- internal localhost endpoint: `POST /teams/operate`
- request shape:
  - `operation`: one of the team API operations
  - `request`: JSON object passed through to `controlmesh.team.api.execute_team_api_operation(...)`
- exposed operations through this endpoint:
  - `read-manifest`
  - `list-tasks`
  - `get-summary`
  - `read-events`
  - `record-dispatch-result`
  - `start-worker-runtime`
  - `stop-worker-runtime`
  - `heartbeat-worker-runtime`

The write surface remains intentionally narrow. The lifecycle additions are only enough to start, stop, or renew the lease/heartbeat for the named-session-backed runtime unit. The control plane is still not a broad mutable CRUD API.

This still does **not** mean ControlMesh owns full worker execution. The team layer can now start/stop the named-session-backed worker unit, bind runtime validity to the current named-session owner identity, renew heartbeat/lease facts when that owner proves its identity, recover that responsibility after leader restart for still-valid persisted runtimes, and keep those renewals alive through a bounded controller-owned task, but it does not supervise a daemon, does not run a separate always-on manager, and does not add a new transport.

The manifest now persists nested `session` and `runtime` records, but still accepts the earlier flattened fields on input:

- leader `session_transport` / `session_chat_id` / `session_topic_id`
- manifest-level `cwd`
- worker `session_id`
- worker `session_name`

## Files

- implementation: `controlmesh/team/`
- tests: `tests/team/`
