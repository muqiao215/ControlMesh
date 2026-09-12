import type { RuntimeKernel, Principal, Lease } from "./kernel";
import type { LocalRun } from "./local-task-runtime";
import { requireThat } from "./value";
export interface TopologyExecution extends LocalRun { lease: Lease | null }
interface DeviceExecutionOwner {
  binding: string;
  read(actor: Principal, runId: string): TopologyExecution;
  claim(actor: Principal, runId: string, lease?: Lease): void;
}
const owners = new WeakMap<RuntimeKernel, DeviceExecutionOwner>();
export function registerDeviceTopologyOwner(kernel: RuntimeKernel, owner: DeviceExecutionOwner) {
  requireThat(!owners.has(kernel) || owners.get(kernel)!.binding === owner.binding, "device_topology_owner_conflict"); owners.set(kernel, owner);
}
function assigned(kernel: RuntimeKernel, taskId: string) {
  return kernel.db.sql.query("SELECT run_id,execution_source,kind FROM topology_tasks WHERE child_id=?").get(taskId) as { run_id: string; execution_source: string; kind: string } | null;
}
/** Kernel calls this before claim and binds the actual episode inside the same transaction. */
export function topologyNativeClaim(kernel: RuntimeKernel, actor: Principal, taskId: string, lease?: Lease): void {
  const assignment = assigned(kernel, taskId);
  if (!assignment || assignment.kind !== "native" || assignment.execution_source !== "device") return;
  const owner = owners.get(kernel); requireThat(owner, "device_topology_owner_unavailable"); owner.claim(actor, assignment.run_id, lease);
}
export function topologyExecution(kernel: RuntimeKernel, actor: Principal, taskId: string, runId: string): TopologyExecution {
  kernel.inspect(actor, taskId);
  const assignment = assigned(kernel, taskId);
  requireThat(assignment?.kind === "native" && assignment.run_id === runId, "topology_execution_assignment_changed");
  if (assignment.execution_source === "device") {
    const owner = owners.get(kernel); requireThat(owner, "device_topology_owner_unavailable");
    const result = owner.read(actor, runId); requireThat(result.task_id === taskId, "topology_child_run_mismatch"); return result;
  }
  requireThat(assignment.execution_source === "local", "unknown_topology_execution_source");
  const row = kernel.db.sql.query("SELECT run_id,task_id,state,outcome,lease FROM local_runs WHERE run_id=? AND principal=?")
    .get(runId, actor.id) as { run_id: string; task_id: string; state: LocalRun["state"]; outcome: string | null; lease: string | null } | null;
  requireThat(row?.task_id === taskId, "topology_child_run_mismatch");
  return { ...row, outcome: row.outcome ? JSON.parse(row.outcome) : null, lease: row.lease ? JSON.parse(row.lease) : null };
}
