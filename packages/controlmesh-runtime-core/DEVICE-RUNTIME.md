# Private device runtime

`scripts/device-runtime.ts` starts the candidate coordinator or native worker from one
private configuration file. It uses the same bounded JSON-lines stdin/stdout transport as
the local TaskHub. It is a headless control entrypoint, independent of the human Web UI.
It does not activate the installed production writer or replace the terminal product.

```sh
bun packages/controlmesh-runtime-core/scripts/device-runtime.ts /absolute/private-profile.json
# Unattended service: survives stdin EOF, exits on SIGINT/SIGTERM.
bun packages/controlmesh-runtime-core/scripts/device-runtime.ts /absolute/private-profile.json --daemon
```

Configuration is owned by the current user, mode 0600, at a canonical absolute path. The
state directory must already exist, be owned by that user and mode 0700. Put the profile
outside the state directory; legacy `tasks.json`, `config.json` or `controlmesh_state`
inside it cause startup refusal. Each role has its own SQLite file. Existing unbound
candidate tasks/evidence require explicit migration; opening this entrypoint does not
silently adopt them. Role/principal/device identity persists across restarts.

## Configuration contract

Common fields: `schema_version: "controlmesh.device_runtime.v1"`, `mode: "candidate"`,
`role`, `state_root`, `principal_id`, `device_id`. Unknown top-level fields are rejected.

Coordinator fields:

| Field | Meaning |
|---|---|
| `role` | `coordinator` |
| `listen_port` | Optional loopback port, 0 for an ephemeral port |
| `devices` | 1–128 registrations; each has `device_id`, matching `principal_id`, `token_sha256`, unique `capabilities` and logical `workspace_ids` |

The coordinator stores the device token's SHA256 digest, not provider credentials. The
worker port starts after an explicit `start` operation or `--daemon`. Daemon mode also
recovers expired coordinator episodes every two seconds without invoking a provider.
It binds to 127.0.0.1;
cross-device deployment carries it through a host-verified SSH tunnel or an authenticated
HTTPS deployment. The public Web/SDK facade remains separate. Configuration replacement
invalidates active admission, including requests already reading their body.

Worker fields:

| Field | Meaning |
|---|---|
| `role` | `worker` |
| `coordinator` | `endpoint` and device-local `token`; HTTPS or loopback HTTP only |
| `opencode` | Qualified `model`, `cli_version: "1.18.29"`, absolute `executable`, `native_configuration`, explicit `environment`, pinned `container` and optional `timeout_ms` (1000–300000) |
| `workspaces` | Logical ID -> canonical `directory`, relative `read_files`, `required_reads`, optional relative `write_roots` and optional independent `specmesh` profile |
| `capabilities` | Capability ID -> registered `workspace_ids` and explicit `writable` boolean |
| `communication` | Optional `node_executable` used by native Agent MCP; required for assignments with peers/parent |
| `history` | Optional independent History backend: absolute `python`, repository `directory`, and optional explicit `environment`; no Web server required |
| `max_parallel` | 1–8 active control executions per process; default 4 |
| `scheduler` | Optional limits: `parallelism` (1–8, defaults to and cannot exceed `max_parallel`), `max_pending` (1–1024, default 128), `poll_ms` (100–60000, default 2000), `lease_ms` (2000–30000, default 10000), `max_backoff_ms` (`poll_ms`–300000, default 60000) |

`opencode.environment` supplies device-local `XDG_DATA_HOME` and `XDG_CACHE_HOME`. Container
settings use the existing qualified OpenCode profile; the runtime sets its own control
directory. Credentials, full native manifests, provider session databases, exact paths and
workspace proposals remain on the worker. The coordinator sends logical workspace and
capability identities; it cannot supply executable paths, shell strings or native credentials.

The worker constructs a task-specific Adapter after reading its authenticated assignment.
Its native communication directory is bound to that task's peers/parent. Original-proposal
recovery reconstructs the Adapter from the integrity-checked retained job. Current workspace,
configuration, credential, grant, native session and SpecMesh bindings still apply. SpecMesh
is optional and independent; its presence is never treated as semantic closeout approval.

## Control operations

Each line is one object with a stable `id` and `op`. Replies contain `id`, `ok`, and either
`result` or a bounded error code. Principals, source contexts and grants are issued by the
configured runtime; requests cannot supply them. The protocol rejects unexpected fields.

Coordinator operations:

- `status`, `start`.
- `submit` with `task`; origin is this explicit local control ingress. The task cannot
  contain `execution_context` or `tool_grant`.
  Native context accepts only a device adoption or completed-device-session handle;
  a raw provider session reference is rejected before task creation.
- `inspect_task` with `task_id`: current task, latest result and up to 32 effect identities.
- `assign` with `task_id`, `expected_revision`, `workspace_id`, `capability`, `device_ids`,
  optional `peer_tasks` and `parent_task`.
- `cancel` with `task_id`, `expected_revision`; `resume` additionally takes `prompt`.
- `revoke` with `device_id`; revocation persists after restart.
- `recover_expired`: fences expired episodes without executing a provider.
- `request_reconciliation` with `task_id`, `expected_revision`, `device_id`, `effect_id`.

Worker operations:

- `status`, `assignments`, `inspect_task` with `task_id`. These never construct native
  Adapters or spend preflight/model calls.
- `run` with `task_id`, `expected_revision`, `assignment_digest` copied from inspection.
- `inspect_operation` with `operation_id`: `absent`, `running`, `unknown`, or `settled`.
- `reconcile` with the coordinator-issued `challenge_id`.
- `scheduler_status`, `start_scheduler`, `pause_scheduler`.
- `inspect_scheduled` with `work_id`; `retry_scheduled` additionally takes `expected_attempt`.
- `inspect_provider` with `task_id`; `retry_provider` additionally takes `expected_generation`.
  These inspect/reset the local readiness cache without running a model or changing a task.
  Explicit reset requires the private operator's `device:schedule` authority; it is not an
  Agent mailbox or native MCP operation.
- `history_search` with `workspace_id`, `query`: up to 20 device-local suggestions,
  filtered to the registered project. Requires the optional `history` profile.
- `prepare_adoption` with `task_id`, `workspace_id`, `capability`, `session_id`: verifies
  the selected native session is idle, has the configured model and current content
  revision, and belongs to that exact project. Returns `authorization: "context_only"`
  and a `controlmesh.device_native_adoption.v1` handle. Neither operation probes a model.

Use `submit -> assign -> inspect_task -> run` for new work. Resume only a proven terminal
task, assign its new revision and use a new run ID. A repeat run ID returns its original
receipt even after the task resumes. A conflicting body rejects. A process loss after the
durable reservation leaves an `unknown` operation and cannot automatically reissue native
execution. Inspect the coordinator's current task/effects and reconcile the original effect.
Reconciliation can replay the same challenge after a lost acknowledgement; it does not
create a fresh model turn. Original run receipts remain historical observations.

To continue a session created outside CM, search and prepare it **on its original worker**,
then submit a task with the selected task ID and the returned handle as `native_session`.
Assign it to that worker/workspace/capability and run the inspected revision. The coordinator
issues current execution authority independently; History candidates contain no grants.
Native session IDs, store paths and the complete immutable reference remain local in
`device_native_adoptions` (additive candidate schema 14). The coordinator receives only the
device, adoption ID and content digest. Copying the handle to another task/device or changing
the configured profile fails closed. There is no fallback to a new conversation.

Execution revalidates native content before preflight and again before native dispatch.
Completion returns the ordinary completed-device-session handle for subsequent resume.
After interruption, recovery loads the original adoption reference and verifies its retained
appended turn; it neither asks History for a replacement reference nor invokes a model.
A repeated prepare ID replays historical context, not a readiness guarantee. Inspection
requires fresh native validation if another client has changed the session. Native clients
outside CM do not honor its locks, so this does not claim universal cross-client exclusion.

History calls have a separate bound of four concurrent processes, each with a 10-second
deadline and 256-KiB output limit; shutdown drains them. They inherit only the explicitly
configured History environment, not the provider credential environment. This invokes
`python -m history_core`; the human Web frontend is not started.

## Persistent scheduling

`--daemon` starts automatic worker discovery unless a previous `pause_scheduler` is persisted.
Without the flag, opening a profile or inspecting status starts neither scheduling nor a model;
use `start_scheduler` explicitly. `pause_scheduler` stops admission and drains active work.
SIGINT/SIGTERM interrupts owned work and drains it before closing the database. Interactive
EOF drains submitted requests; daemon EOF leaves the service available.

Candidate schema 15 adds assignment generations, a scheduler lease and durable scheduled work.
A record identifies the task's explicit assignment and execution projection, not its changing
revision. Repeating an assignment command preserves its receipt; a new explicit assignment ID
creates a new identity. Legacy assignments retain their original digest. Discovery uses the
authenticated `queue_page` operation: at most 32 returned jobs and 1024 scanned candidates per
page, with an advancing cursor even when the scanned work belongs to another device.

Only one scheduler owns the local principal/device lease. Linux boot identity and elapsed
time fence a superseded process at existing native/file/message admission boundaries. New
manual `run` calls reject while that lease is current; historical run receipts remain readable.
Worker reservations and scheduler concurrency bounds apply together. Old production writers
must still be drained before any eventual production activation.

Interrupted runs become `unknown` and never automatically execute again. Inspect the original
effect and reconcile its retained result; a later discovery pass updates local bookkeeping.
Explicit `retry_scheduled` requires the same assignment, expected attempt and a current waiting
task with no active episode or pending reconciliation. It cannot bypass an uncertain effect.

Confirmed pre-execution quota failures with an evidenced future reset become timed `waiting`.
Quota without reset, authentication failures and exhausted probe budgets remain `blocked`.
After resolving the cause, inspect/reset readiness at its expected generation, then explicitly
retry the scheduled work. Provider-cache probe limits remain authoritative; transport failures
use bounded backoff. No polling task is injected into a human conversation and no cron is created.

Full rollout still needs the remaining provider/transport/store/topology owners,
reviewed SpecMesh closeout, user terminal workflow, package/default switch
and installation gates in `plans/runtime-convergence/task_plan.md`.
