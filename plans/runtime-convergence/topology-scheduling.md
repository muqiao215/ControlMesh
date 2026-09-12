# Local topology scheduling

Status: implemented in the private TypeScript candidate; production Python remains the
writer. This is a local coordinator service. Device topology dispatch and real native
provider/topology qualification remain separate runtime-convergence gates.

## Startup and ownership

Use the existing private `controlmesh.local_runtime.v1` candidate configuration. Opt in:

```json
{"topology_scheduler":{"auto_start":true,"keep_alive":true,"interval_ms":250,"lease_ms":30000,"max_steps":16,"artifact_files":["result.md"]}}
```

`artifact_files` is an exact workspace-relative allowlist; omit it if no topology has a file
completion contract. A required file contract without a configured artifact gate blocks.
The existing SpecMesh configuration supplies the independent current-source check.
This does not turn an unknown project closeout result into a pass.

From the repository root:

```sh
bun packages/controlmesh-runtime-core/scripts/local-runtime.ts /absolute/private-config.json
```

The existing JSON-lines protocol remains on stdin/stdout. With `keep_alive:true`, EOF does
not stop the scheduler; SIGTERM/SIGINT follows the normal owned runtime shutdown path.
No HTTP listener, production service installation, cron entry or browser session is added.
Without this explicit configuration, topology scheduler operations reject as unconfigured.
`auto_start:false` permits registration/inspection before `start_scheduler` is requested.

## Register and activate

First submit every root, worker and controller through the existing authorized `submit`
operation. Initial task prompts must describe the task and required result contract.
Registration never rewrites that initial input or manufactures tasks, grants or sessions.
The following example assumes `root`, `worker` and `reviewer` already exist:

```json
{"id":"register-flow","op":"register_schedule","plan":{"schema_version":"controlmesh.topology_schedule.v1","root_task_id":"root","nodes":[{"task_id":"root","topology":"pipeline","worker_roles":["worker"],"controller_role":"reviewer","max_repair_cycles":1,"max_parent_interruptions":1,"roles":[{"role":"worker","task_id":"worker","resume_prompt":"Continue the assigned implementation and return its structured result."},{"role":"reviewer","task_id":"reviewer","resume_prompt":"Review the current result and return a structured decision."}]}]}}
{"id":"activate-flow","op":"activate_schedule","root_task_id":"root","expected_revision":1}
```

Registration is paused and immutable. Activation authorizes the service to execute the
registered graph with its frozen roles and limits. Supported kinds are `pipeline`,
`fanout_merge`, `director_worker` and `debate_judge`. Pipeline has one worker; judge has
exactly two; the configured local parallelism also bounds batches. Director dispatch may
select only registered roles. Its `director_limits` fields are those of `DirectorPolicy`.
`round_limit`, repair and interruption caps are finite. Unknown fields reject.

An aggregate role uses `aggregate:true` and names another declared node's task ID. Every
non-root node has exactly one parent, and the entire graph must be reachable and acyclic.
An aggregate starts only after the parent's actual dispatch reserves it. Registration
limits are 32 nodes, 16 roles per node, 128 total task IDs and 60,000 encoded input bytes.
Each task belongs to one registered schedule; overlapping registrations reject.

## Observe and recover

`inspect_schedule` returns the root mode/revision, blocking reason, node stages and current
child task revisions/run outcomes. It does not execute tasks or accept model output.
`pause_schedule` uses the current schedule revision and prevents new topology transitions.
Already admitted native work retains the existing runtime lifecycle; pause is not a claim
that a running provider process stopped. Use the existing `cancel` operation on the root
for cancellation authority, or normal runtime shutdown to stop owned native processes.

The private control operations are:

| Operation | Input beyond `id` and `op` | Meaning |
|---|---|---|
| `register_schedule` | `plan` | Persist a paused immutable plan |
| `inspect_schedule` | `root_task_id` | Current progress and actionable child identities |
| `activate_schedule` / `pause_schedule` | `root_task_id`, `expected_revision` | Compare-and-set admission state |
| `reopen_schedule` | `root_task_id`, `expected_revision`, `task_revision`, `topology_revision`, `prompt` | Explicitly continue a verified completed/failed project under the same identities |
| `inspect_schedule_run` | `root_task_id`, `execution_id` | Read the preserved root execution archive |
| `start_scheduler` / `scheduler_status` | none | Start or inspect the local service loop |
| `drain_schedules` | none | Bounded foreground advance for controlled execution |
| `answer_schedule` | `root_task_id`, `expected_revision`, `node_id`, `parent_revision`, `topology_revision`, `input` | Answer the actual waiting-parent checkpoint |
| `retry_schedule_child` | those root/node revisions plus `child_id`, `child_revision`, optional `prompt` | Explicit native recovery under the original assignment |

A blocked schedule remains blocked across restart. Re-activation only re-evaluates current
state; it does not retry a blocked native run. Malformed output requires explicit retry,
which retains rejected evidence and original task/session identity and has a durable two
retry ceiling per child/parent execution. Completed/failed native work requires a prompt;
unstarted quota-blocked work must omit it and keeps its original input. Known reset times
prevent early retry. Uncertain or cancelled work cannot be replayed through this control.

Accepted semantic repair follows the frozen workflow cap and is distinct from malformed
output recovery. Automatic resume prompts combine the registered continuation instruction
with factual checkpoint context. They do not expand execution permissions. Their kernel
events have `origin:schedule`, rather than appearing as new human requests. Explicit user
answers/retries retain their control-request origin.

For a completed or failed project, read `inspect_schedule` and use the root node's
`task_revision`, `topology_revision` and `execution_id`, plus the schedule's `revision`.
Submit `reopen_schedule` with those three current revisions and the new project instruction.
The kernel verifies and archives the terminal result, and the scheduler becomes active in
the same transaction. Its next ordinary tick dispatches the original registered roles.
Task IDs, native session references, grants, device routes and frozen policy limits are
preserved; every new child execution must still pass its normal preflight/admission checks.
Unused roles stay unused until actually selected. Existing child work must be settled.

This operation rejects active, paused, blocked and cancelled schedules; malformed-output
recovery uses `retry_schedule_child` with its existing budget. A repeated request ID with
identical input returns the original receipt, including after restart or completion of the
new run, without creating another run. Changed input under that ID rejects. Root reopen
events retain the operator's request origin; later automatic dispatch remains attributed
to the schedule. `inspect_schedule_run` reads the old archive using the previous execution
ID; it returns null for a run that has not been archived. The archive remains contextual
history and does not replace the next run's current file or SpecMesh acceptance.

## Persistence and verification boundaries

Candidate database schema 24 adds `topology_schedules` and `topology_schedule_members`.
Principal/device/origin, plan digest, revision, state and fenced lease persist together.
Each transition rechecks task/checkpoint versions and actual child results in a transaction.
Async artifact preparation must still hold the schedule lease at commit; a pause, expired
lease or replacement owner cannot publish its stale result. Task/provider lease checks
remain authoritative independently of the scheduling lease.

Inspection and unchanged polls emit no new prompts/events. Shutdown stops the loop and
releases owned scheduling leases. Paused and blocked plans remain so after restart;
completed schedules do not reopen automatically. Older candidates reject schema 24;
rollback requires a pre-upgrade backup, never changing the version of a populated database.

See `test/topology-scheduler.test.ts` for all local topology combinations, background and
separate-connection coordination, recovery, caps and stale artifact refusal. Actual CLI
configuration/EOF/SIGTERM checks are in `test/local-runtime-control.test.ts`. Controlled
resolver and negative artifact fixtures do not prove actual provider/model acceptance.


## Device coordinator execution

The same plan and control operations are available in the private device coordinator.
Add `topology_scheduler` to its existing `controlmesh.device_runtime.v1` configuration:

```json
{
  "topology_scheduler": {
    "auto_start": true,
    "parallelism": 2,
    "max_pending": 128,
    "interval_ms": 250,
    "routes": {
      "project_worker": {
        "workspace_id": "project",
        "capability": "native",
        "device_ids": ["desktop", "arm-worker"]
      },
      "project_reviewer": {
        "workspace_id": "project",
        "capability": "native",
        "device_ids": ["desktop"]
      }
    }
  }
}
```

This is a configuration fragment: task IDs must match the submitted tasks and registered
plan; workspace/capability/device IDs must already be authorized in the device catalog.
Every native role needs an explicit route. Optional `peer_tasks` and `parent_task` retain
the existing mailbox authorization rules. Aggregate nodes are reduced by the coordinator
and are never sent to a provider. Model output cannot supply routes or alter their scope.
Native continuation narrows an approved route to the handle's issuing device; a handle on
an unlisted device blocks admission. Native stores and credentials stay on that device.

The ordinary `device-runtime.ts <config> --daemon` path starts the HTTP coordinator and,
when `auto_start` is true, the topology loop. Opening the configuration without daemon
startup creates no listener or model invocation. Registration remains paused until explicit
activation. Device workers retain their existing independent startup, preflight and queues.
`drain_schedules` advances available coordinator transitions and returns when progress needs
an external worker; it does not run a second provider loop or wait forever for a device.

Schema 25 records `execution_source` on assignments and stores device run bindings in
`topology_device_runs`. Assignment generation, execution projection and immutable routing
policy are checked against the current coordinator state. Kernel claim binds the actual
worker device, episode and fence in the same transaction that creates the lease. Missing
execution ownership, substituted local runs, revoked devices or changed assignments cannot
supply accepted results. Existing local completion digests are preserved by the upgrade.

`parallelism` limits admitted topology episodes across this coordinator's device workers,
in addition to each worker's own cap. Discovery hides jobs when the cap is full; claim
rechecks the cap transactionally, including after coordinator restart. `max_pending` bounds
the queued device topology runs. Neither limit claims that an unreachable physical process
has stopped; episode fencing and uncertain-effect reconciliation remain authoritative.

Preflight release or unstarted lease expiry consumes that assignment's admission. The old
job disappears from discovery and cannot be reclaimed by a worker poll. Explicit
`retry_schedule_child` archives it and creates a new assignment under the original task;
malformed output retains the existing bounded retry and native-session rules. Unknown
side effects, cancellation and revoked execution authority cannot be replayed as retries.

Current verification uses authenticated HTTP and controlled adapters, including all four
root topologies and all sixteen nested pairs. Normal configuration, CLI EOF/SIGTERM,
restart, explicit recovery and schema-24 upgrade are covered separately. These tests do
not qualify a real native-model topology. Root file delivery still requires a topology
artifact gate; the device configuration has no remote artifact gate yet and therefore
blocks such completion with `topology_artifact_gate_required`. Remote current-source and
artifact acceptance and reviewed SpecMesh closeout remain required before full rollout.
Older candidates reject schema 25; rollback requires the pre-upgrade database backup.


## Native role input and actual acceptance

Schema 26 freezes `topology_native_inputs` at each native dispatch. The payload is ordinary
attributed mailbox data: `controlmesh.topology_task_context.v1`, with assignment identity,
role/stage/round, registered worker roles, frozen control limits, parent objective, actual
result schema and previous checkpoint results. It includes results carried on the current
checkpoint; pipeline review carries its previous worker output there. No result grants
permission or establishes current file bytes. The Agent returns one JSON object matching
the contract and reports the actual outcome.

For Claude, that attributed contract now selects native `--json-schema` output. Generation
uses a compatible Draft 7 view; CM validates the canonical schema and frozen assignment
again. The stream value must match an actual successful StructuredOutput call in the native
session. The pinned CLI can end with a structured attachment and tool receipt, without
another assistant prose message; both terminal forms retain native session identity.
Plain JSON text and a structured field alone do not waive tool/source/file evidence.
The exact native synthetic pair used to reopen a completed structured turn is excluded
from task-input/model-output counts. Up to four genuinely invalid schema attempts may
precede one successful StructuredOutput receipt; other failures or duplicate success reject.

The first integration attempt rejected the schema URI before any task input. A fresh
Draft 7 attempt then read all eight files and emitted native success, but exposed CM's
text-only final-message check and unsupported structured attachment. Those parsers are
corrected; model-free inspection of the retained stream and JSONL now verifies the result
and idle session. The original worker journal still says unknown: read-only inspection
does not reconcile it or complete its parent. Neither attempt may be replayed. Complete
worker/merger continuation through normal startup remains a separate acceptance gate.
A subsequent fresh attempt accepted its worker but the merger exhausted native schema
retries by emitting string "1" for the required numeric schema_version. The generated
schema now explicitly types that constant as integer, without accepting string coercion.
Its effect on real model reliability is not yet verified; no retry of that attempt is allowed.

The context is limited to 32768 bytes and must fit the existing native prompt budget with
older mailbox messages. Nothing is silently truncated or skipped. A child lease authorizes
only its own stored context. Native input preparation materializes an idempotent handoff
with schedule origin and zero forwarding hops. Existing native mailbox manifests and
verified user-message IDs establish delivery and consumption. Missing or altered snapshots
cannot obtain a lease; native device dispatch cannot omit the required handoff. This does
not change public task execution fields or copy native stores between devices.

Candidates upgraded from schema 25 retain completed evidence, but old pending assignments
without a context snapshot reject new admission. Explicit pending-assignment migration
remains required before rollout; do not synthesize an old input or replay an unknown run.

A real Claude/MiniMax-M3 canary used one successful preflight and two native task inputs.
The worker read all seven required documents, produced accepted structured output, and its
context message was consumed with native input evidence. The reviewer received the next
context but made zero file tool calls. Retained-evidence reconciliation later confirmed
`workspace_tool_required_read_missing` as a task failure, without another model invocation. The pipeline did not complete and the planned original-session reopen did
not execute. This is partial positive input-delivery evidence plus a real negative gate,
not full topology or native-continuity acceptance. Retained local report:
`outputs/runtime-convergence/topology-input-native-acceptance-20260912.json` in the operator
workspace. Its attempt and native sessions must not be replayed automatically.
## Canonical artifacts from device execution

The device coordinator can verify already-delivered canonical files against an explicitly
registered remote source. Add this to its `topology_scheduler` configuration:

```json
{"artifacts":{"workspace":"/absolute/canonical-project","allowed_files":["result.md"],"device_sources":{"desktop":"project","arm-worker":"project"}}}
```

`workspace` is the coordinator's actual final project directory, also named by the root
and leaf TaskHub `repo_root`. It is distinct from each worker's device-local path. The
`device_sources` map binds a device ID to its registered logical workspace ID. A filename,
matching hash or native history claim cannot create that mapping. Unknown device/workspace
pairs reject at startup; current device revocation and assignment identity are rechecked
through the normal DeviceTopologyRuntime when completing a parent.

Completion requires all of the following: the current native assignment generation and
actual episode/effect; a schema-validated device native result and original evidence/native
handle; a child file completion contract and matching digest; and the exact current bytes
at the canonical destination. Local witnesses retain their original authority boundary.
The gate works through nested aggregates and preserves each contract's file order.
Missing files report `topology_artifact_file_unavailable`; changed bytes, symlink aliases,
resumed children, changed evidence or revoked devices block or roll back the parent step.
A SpecMesh-derived root contract still checks its current independent source before commit.

This gate neither copies a file nor starts a provider. Delivery currently needs an explicit
existing file/Git workflow; automatic cross-device artifact transport and remote-only final
workspaces are still pending. Controlled HTTP/file-owner tests and the normal startup
container fixture verify this canonical-delivery profile; model acceptance is recorded
separately in the active progress file.
