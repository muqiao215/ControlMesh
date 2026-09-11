# Private device runtime

`scripts/device-runtime.ts` starts the candidate coordinator or native worker from one
private configuration file. It uses the same bounded JSON-lines stdin/stdout transport as
the local TaskHub. It is a headless control entrypoint, independent of the human Web UI.
It does not activate the installed production writer or replace the terminal product.

```sh
bun packages/controlmesh-runtime-core/scripts/device-runtime.ts /absolute/private-profile.json
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
worker port starts only after an explicit `start` operation. It binds to 127.0.0.1;
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

Multiple explicit run requests may overlap within the configured bound. Work is not
automatically scanned or retried on startup. EOF drains submitted requests; SIGINT/SIGTERM
interrupt owned execution before closing its database. Uncertain external outcomes remain
visible. No polling task is injected into a human conversation and no cron is created.

Full rollout still needs the remaining provider/transport/store/topology owners, persistent
device scheduling, reviewed SpecMesh closeout, user terminal workflow, package/default switch
and installation gates in `plans/runtime-convergence/task_plan.md`.
