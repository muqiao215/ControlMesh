import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal } from "./kernel";
import { canonical, requireThat, terminal } from "./value";
import { appendTopologyCheckpoint, decodeTopologyState, interruptTopology, resumeTopology, startTopology,
  type TopologyState, type CheckpointInput, type TopologyInterruptInput, type TopologyResumeInput } from "./team-topology";

export interface TopologySnapshot { task_id: string; revision: number; state: TopologyState }
/** Private topology persistence owner. Mutations do not dispatch or grant provider execution. */
export class RuntimeTopology {
  constructor(private readonly kernel: RuntimeKernel) {}
  private authorize(actor: Principal, taskId: string, taskRevision?: number): void {
    const task = this.kernel.inspect(actor, taskId);
    if (taskRevision !== undefined) {
      requireScope(actor, "team:write");
      requireThat(Number.isSafeInteger(taskRevision) && task.revision === taskRevision, "revision_conflict");
      requireThat(!terminal.has(task.task.status) && !task.needs_reconciliation, "topology_task_not_active");
    }
  }
  inspect(actor: Principal, taskId: string): TopologySnapshot | null {
    this.authorize(actor, taskId);
    const row = this.kernel.db.sql.query("SELECT revision,state FROM team_topologies WHERE task_id=?").get(taskId) as { revision: number; state: string } | null;
    if (!row) return null;
    const state = decodeTopologyState(JSON.parse(row.state));
    requireThat(state.task_id === taskId, "topology_task_mismatch");
    return { task_id: taskId, revision: row.revision, state };
  }
  create(actor: Principal, requestId: string, taskId: string, taskRevision: number, topology: string, input: Parameters<typeof startTopology>[2] = {}): TopologySnapshot {
    this.authorize(actor, taskId, taskRevision);
    return command(this.kernel.db, actor, requestId, "topology.create", { taskId, taskRevision, topology, input }, () => {
      this.authorize(actor, taskId, taskRevision);
      requireThat(!this.inspect(actor, taskId), "topology_exists");
      const state = startTopology(taskId, topology, input, new Date(this.kernel.db.now()));
      this.kernel.db.sql.query("INSERT INTO team_topologies VALUES (?,1,?)").run(taskId, canonical(state));
      return { task_id: taskId, revision: 1, state };
    }, value => { this.authorize(actor, taskId); requireScope(actor, "team:write"); return value; });
  }
  private mutate(actor: Principal, requestId: string, taskId: string, taskRevision: number, expectedRevision: number,
    operation: string, input: unknown, transform: (state: TopologyState, at: Date) => TopologyState): TopologySnapshot {
    this.authorize(actor, taskId, taskRevision);
    return command(this.kernel.db, actor, requestId, operation, { taskId, taskRevision, expectedRevision, input }, () => {
      this.authorize(actor, taskId, taskRevision);
      const current = this.inspect(actor, taskId);
      requireThat(current, "topology_not_found");
      requireThat(Number.isSafeInteger(expectedRevision) && current.revision === expectedRevision, "revision_conflict");
      const state = transform(current.state, new Date(this.kernel.db.now()));
      const revision = current.revision + 1;
      this.kernel.db.sql.query("UPDATE team_topologies SET revision=?,state=? WHERE task_id=?").run(revision, canonical(state), taskId);
      return { task_id: taskId, revision, state };
    }, value => { this.authorize(actor, taskId); requireScope(actor, "team:write"); return value; });
  }
  checkpoint(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, input: CheckpointInput): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "topology.checkpoint", input, (state, at) => appendTopologyCheckpoint(state, input, at));
  }
  interrupt(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, input: TopologyInterruptInput): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "topology.interrupt", input, (state, at) => interruptTopology(state, input, at));
  }
  resume(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, input: TopologyResumeInput): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "topology.resume", input, (state, at) => resumeTopology(state, input, at));
  }
}
