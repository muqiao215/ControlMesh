# Findings

The roadmap is grounded in repository code, existing contracts and prior recorded acceptance, not the prototype archive alone. Implementation status and remaining gates are in task_plan.md. No new runtime migration or fleet rollout is claimed complete by this plan.

2026-09-11 implementation: TaskRegistry.__init__ calls orphan cleanup and may delete folders; its cached JSON writes are not a cross-device store. InterAgentBus is explicitly in-memory and trims message history. Existing TS lifecycle parity switches on fixture case IDs and is not a callable production lifecycle. These are source observations, not completion evidence.

The generated source baseline now inventories all 512 Python modules under `controlmesh`/`controlmesh_runtime` and selected model fields. The actual `TaskEntry.to_dict()` fixture has 57 serialized fields; `original_prompt` is not serialized, and `thread_id` is conditional. Snapshot import preserves unknown fields without passing through a lossy reconstruction. Active imported tasks remain non-executable until explicit reconciliation; cancelled tasks retain their status.

Two different persisted subsystems remain in scope: TaskHub's registry/task folders and `controlmesh_runtime/store.py`'s task packets, workers, reviews, control/runtime/execution events, summaries and promotion receipts. The latter is not retired by adding the new kernel. All additional owners appear in the source ledger, including CLI commands, topology/transport ingress and generated protocol modules.

`controlmesh/cli/service.py:resolve_runtime_provider_target` currently logs a failed explicit OpenCode probe and continues with the requested model. Existing native-adoption checks are stronger. The TS port must reconcile these different admission paths rather than copy the fail-open path as desired behavior. Quota classification currently lives in `cli/opencode_quota.py` and only trusts native error records; ordinary assistant/tool text must not trigger it.

The new kernel's transactional fences prevent stale coordinator writes. They do not prove an external tool honors fences. External dispatch is recorded first and identical retries cannot obtain another dispatch permit. Expired running episodes become outcome-unknown and require reconciliation. Provider/native enforcement and actual process ownership remain required.

Read-only local snapshot preview found three tasks (one done, two cancelled), no active tasks. Preview used an in-memory destination, did not construct TaskRegistry, transfer writer authority or modify folders. No private task IDs/payloads are recorded here.
