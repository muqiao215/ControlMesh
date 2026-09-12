import { dispatchFanoutWorkers, collectFanoutWorkers, applyFanoutResult, resumeFanout, type FanoutResultOptions } from "./team-fanout";
import { applyPipelineResult, dispatchPipelineWorker, resumePipeline, type PipelineResultOptions } from "./team-pipeline";
import type { StructuredTeamResult } from "./team-result-validation";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal } from "./kernel";
import { canonical, digest, object, requireThat, terminal } from "./value";
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
      const declared = this.kernel.inspect(actor, taskId).task.topology;
      requireThat(!declared || declared === topology, "topology_task_kind_changed");
      const state = startTopology(taskId, topology, input, new Date(this.kernel.db.now()));
      this.kernel.db.sql.query("INSERT INTO team_topologies VALUES (?,1,?)").run(taskId, canonical(state));
      this.kernel.bindTopologyExecution(actor, taskId, state.execution_id);
      return { task_id: taskId, revision: 1, state };
    }, value => { this.authorize(actor, taskId); requireScope(actor, "team:write"); return value; });
  }
  reopen(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, prompt: string) {
    this.authorize(actor, taskId); requireScope(actor, "team:write");
    requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_controls WHERE task_id=?").get(taskId), "controlled_topology_requires_controller");
    return this.kernel.reopenTopology(actor, requestId, taskId, taskRevision, revision, prompt);
  }
  inspectRun(actor: Principal, taskId: string, executionId: string): { digest: string; snapshot: Record<string, unknown> } | null {
    this.authorize(actor, taskId);
    const row = this.kernel.db.sql.query("SELECT snapshot,digest FROM topology_runs WHERE task_id=? AND execution_id=?").get(taskId, executionId) as { snapshot: string; digest: string } | null;
    if (!row) return null;
    const snapshot: unknown = JSON.parse(row.snapshot);
    requireThat(object(snapshot) && digest(snapshot) === row.digest && object(snapshot.topology), "topology_archive_changed");
    const state = decodeTopologyState(snapshot.topology.state);
    requireThat(state.task_id === taskId && state.execution_id === executionId, "topology_archive_changed");
    return { digest: row.digest, snapshot };
  }
  private mutate(actor: Principal, requestId: string, taskId: string, taskRevision: number, expectedRevision: number,
    operation: string, input: unknown, transform: (state: TopologyState, at: Date) => TopologyState): TopologySnapshot {
    this.authorize(actor, taskId, taskRevision);
    return command(this.kernel.db, actor, requestId, operation, { taskId, taskRevision, expectedRevision, input }, () => {
      this.authorize(actor, taskId, taskRevision);
      const current = this.inspect(actor, taskId);
      requireThat(current, "topology_not_found");
      requireThat(Number.isSafeInteger(expectedRevision) && current.revision === expectedRevision, "revision_conflict");
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_controls WHERE task_id=?").get(taskId), "controlled_topology_requires_controller");
      const state = transform(current.state, new Date(this.kernel.db.now()));
      const revision = current.revision + 1;
      this.kernel.db.sql.query("UPDATE team_topologies SET revision=?,state=? WHERE task_id=?").run(revision, canonical(state), taskId);
      return { task_id: taskId, revision, state };
    }, value => { this.authorize(actor, taskId); requireScope(actor, "team:write"); return value; });
  }
  dispatchFanout(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, roles: string[], limit: number): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "fanout.dispatch", { roles, limit }, (state, at) => dispatchFanoutWorkers(state, roles, limit, undefined, at));
  }
  fanoutWorkers(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, results: StructuredTeamResult[], reducerRole = "reducer"): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "fanout.collect", { results, reducerRole }, (state, at) => collectFanoutWorkers(state, results, reducerRole, at));
  }
  fanoutResult(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, result: StructuredTeamResult, options: FanoutResultOptions = {}): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "fanout.result", { result, options }, (state, at) => applyFanoutResult(state, result, options, at));
  }
  resumeFanout(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, parentInput: string): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "fanout.resume", { parentInput }, (state, at) => resumeFanout(state, parentInput, undefined, at));
  }
  dispatchPipeline(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, role: string, summary?: string): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "pipeline.dispatch", { role, summary: summary ?? null }, (state, at) => dispatchPipelineWorker(state, role, summary, at));
  }
  pipelineResult(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, result: StructuredTeamResult, options: PipelineResultOptions = {}): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "pipeline.result", { result, options }, (state, at) => applyPipelineResult(state, result, options, at));
  }
  resumePipeline(actor: Principal, requestId: string, taskId: string, taskRevision: number, revision: number, parentInput: string, summary?: string): TopologySnapshot {
    return this.mutate(actor, requestId, taskId, taskRevision, revision, "pipeline.resume", { parentInput, summary: summary ?? null }, (state, at) => resumePipeline(state, parentInput, summary, at));
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
