import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal, type Lease } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { RuntimeTopology } from "./runtime-topology";
import { readTeamTaskResult } from "./team-task-result";
import { canonical, digest, identifier, requireThat, terminal } from "./value";

interface Assignment {
  child_id: string; parent_id: string; topology: string; substage: string;
  worker_role: string; checkpoint_id: string; run_id: string; accepted: string | null;
}
/** Associates already-authorized child tasks with topology roles and the existing local queue. */
export class TopologyTaskQueue {
  constructor(private readonly kernel: RuntimeKernel, private readonly runtime: LocalTaskRuntime) {
    requireThat(runtime.kernel === kernel, "topology_queue_database_mismatch");
  }
  private parent(actor: Principal, parentId: string, taskRevision: number, topologyRevision: number) {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    const task = this.kernel.inspect(actor, parentId);
    requireThat(task.revision === taskRevision && Number.isSafeInteger(taskRevision), "revision_conflict");
    requireThat(!terminal.has(task.task.status) && !task.needs_reconciliation, "topology_parent_inactive");
    const topology = new RuntimeTopology(this.kernel).inspect(actor, parentId);
    requireThat(topology && topology.revision === topologyRevision && Number.isSafeInteger(topologyRevision), "revision_conflict");
    requireThat(topology.state.interruption.status === "idle" && topology.state.checkpoints.at(-1)!.phase_status === "in_progress", "topology_assignment_inactive");
    return topology;
  }
  enqueue(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number, role: string): { child_id: string; run_id: string } {
    identifier(childId); requireThat(typeof role === "string" && role.length > 0 && role.length <= 128, "invalid_topology_role");
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId);
    return command(this.kernel.db, actor, requestId, "topology.enqueue", { parentId, parentRevision, topologyRevision, childId, childRevision, role }, () => {
      const topology = this.parent(actor, parentId, parentRevision, topologyRevision), cp = topology.state.checkpoints.at(-1)!;
      requireThat(cp.active_roles.includes(role), "topology_role_not_active");
      const child = this.kernel.inspect(actor, childId);
      requireThat(child.revision === childRevision && child.task.status === "waiting" && !child.active_episode && !child.needs_reconciliation, "topology_child_not_admitted");
      const owner = (id: string) => (this.kernel.db.sql.query("SELECT principal FROM tasks WHERE task_id=?").get(id) as { principal: string }).principal;
      requireThat(owner(parentId) === actor.id && owner(childId) === actor.id, "topology_task_owner_mismatch");
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE child_id=? OR (parent_id=? AND checkpoint_id=? AND worker_role=?)")
        .get(childId, parentId, cp.checkpoint_id, role), "topology_assignment_exists");
      // Each child has one parent. Bound and validate the complete ancestry before adding an edge.
      const seen = new Set<string>([childId]); let ancestor: string | null = parentId;
      for (let depth = 0; ancestor !== null; depth++) {
        requireThat(depth < 31 && !seen.has(ancestor), "topology_cycle_or_depth_limit"); seen.add(ancestor);
        const row = this.kernel.db.sql.query("SELECT parent_id FROM topology_tasks WHERE child_id=?").get(ancestor) as { parent_id: string } | null;
        ancestor = row?.parent_id ?? null;
      }
      const run = this.runtime.enqueue(`topology-run-${digest([actor.id, requestId])}`, childId, childRevision);
      this.kernel.db.sql.query("INSERT INTO topology_tasks VALUES (?,?,?,?,?,?,?,NULL)")
        .run(childId, parentId, topology.state.topology, cp.substage, role, cp.checkpoint_id, run.run_id);
      return { child_id: childId, run_id: run.run_id };
    }, value => { this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute"); this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }
  collect(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number): ReturnType<typeof readTeamTaskResult> {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId);
    return command(this.kernel.db, actor, requestId, "topology.collect", { parentId, parentRevision, topologyRevision, childId, childRevision }, () => {
      const topology = this.parent(actor, parentId, parentRevision, topologyRevision), cp = topology.state.checkpoints.at(-1)!;
      const assignment = this.kernel.db.sql.query("SELECT * FROM topology_tasks WHERE child_id=? AND parent_id=?").get(childId, parentId) as Assignment | null;
      requireThat(assignment && assignment.accepted === null && assignment.checkpoint_id === cp.checkpoint_id
        && assignment.topology === topology.state.topology && assignment.substage === cp.substage && cp.active_roles.includes(assignment.worker_role), "topology_assignment_changed");
      const run = this.runtime.inspect(assignment.run_id);
      requireThat(run.task_id === childId && run.state === "completed", "topology_child_not_completed");
      const row = this.kernel.db.sql.query("SELECT lease FROM local_runs WHERE run_id=?").get(run.run_id) as { lease: string | null };
      requireThat(row.lease !== null, "topology_child_execution_missing");
      const lease = JSON.parse(row.lease) as Lease;
      const effects = this.kernel.db.sql.query("SELECT e.effect_id FROM effects e JOIN episodes p ON p.episode_id=e.episode_id WHERE e.task_id=? AND e.episode_id=? AND e.fence=? AND e.state='confirmed' AND e.result=p.result")
        .all(childId, lease.episode_id, lease.fence) as { effect_id: string }[];
      requireThat(effects.length === 1, "topology_child_result_ambiguous");
      const accepted = readTeamTaskResult(this.kernel, actor, { task_id: childId, revision: childRevision, episode_id: lease.episode_id,
        effect_id: effects[0]!.effect_id, topology: assignment.topology, substage: assignment.substage, worker_role: assignment.worker_role });
      this.kernel.db.sql.query("UPDATE topology_tasks SET accepted=? WHERE child_id=?").run(canonical(accepted), childId);
      return accepted;
    }, value => { this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }
}
