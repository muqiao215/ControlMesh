import type { TopologyArtifactGate } from "./topology-artifacts";
import { completeTopologyStep } from "./topology-completion";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { RuntimeTopology, type TopologySnapshot } from "./runtime-topology";
import { TopologyTaskQueue } from "./topology-task-queue";
import type { PipelineResultOptions } from "./team-pipeline";
import { digest, requireThat } from "./value";

export interface PipelineChild { task_id: string; revision: number; role: string; resume_prompt?: string; aggregate?: boolean }
/** One explicit, transactional pipeline step; uses authorized children and never starts a polling loop. */
export class RuntimePipeline {
  private readonly topology: RuntimeTopology;
  private readonly queue: TopologyTaskQueue;
  constructor(private readonly kernel: RuntimeKernel, private readonly runtime: LocalTaskRuntime, private readonly completionGate?: TopologyArtifactGate) {
    this.topology = new RuntimeTopology(kernel); this.queue = new TopologyTaskQueue(kernel, runtime);
  }
  private authorize(actor: Principal, taskId: string): void {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    this.kernel.inspect(actor, taskId);
  }
  private authorizeChild(actor: Principal, child?: PipelineChild): void {
    if (child) this.kernel.inspect(actor, child.task_id);
    if (child?.resume_prompt !== undefined) requireScope(actor, "task:resume");
  }
  private enqueue(actor: Principal, requestId: string, parentRevision: number, state: TopologySnapshot, next?: PipelineChild) {
    const cp = state.state.checkpoints.at(-1)!;
    if (cp.phase_status !== "in_progress") { requireThat(next === undefined, "pipeline_unexpected_next_child"); return null; }
    requireThat(next && cp.active_roles.length === 1 && cp.active_roles[0] === next.role, "pipeline_next_child_required");
    if (next.aggregate) return this.queue.aggregate(actor, requestId, state.task_id, parentRevision, state.revision, next.task_id, next.revision, next.role, next.resume_prompt);
    if (next.resume_prompt !== undefined) return this.queue.resume(actor, requestId, state.task_id, parentRevision, state.revision,
      next.task_id, next.revision, next.role, next.resume_prompt);
    return this.queue.enqueue(actor, requestId, state.task_id, parentRevision, state.revision, next.task_id, next.revision, next.role);
  }
  dispatch(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number, worker: PipelineChild) {
    this.authorize(actor, parentId); this.authorizeChild(actor, worker);
    return command(this.kernel.db, actor, requestId, "pipeline.queue_worker", { parentId, parentRevision, topologyRevision, worker }, () => {
      this.authorize(actor, parentId);
      const state = this.topology.dispatchPipeline(actor, `pipeline-phase-${digest(requestId)}`, parentId, parentRevision, topologyRevision, worker.role);
      return { topology: state, next_run: this.enqueue(actor, `pipeline-queue-${digest(requestId)}`, parentRevision, state, worker) };
    }, value => { this.authorize(actor, parentId); return value; });
  }
  advance(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number, options: PipelineResultOptions = {}, next?: PipelineChild) {
    this.authorize(actor, parentId); this.authorizeChild(actor, next);
    return command(this.kernel.db, actor, requestId, "pipeline.advance", { parentId, parentRevision, topologyRevision, childId, childRevision, options, next: next ?? null }, () => {
      this.authorize(actor, parentId);
      const accepted = this.queue.collect(actor, `pipeline-collect-${digest(requestId)}`, parentId, parentRevision, topologyRevision, childId, childRevision);
      const state = this.topology.pipelineResult(actor, `pipeline-phase-${digest(requestId)}`, parentId, parentRevision, topologyRevision, accepted.result, options);
      return { topology: state, next_run: this.enqueue(actor, `pipeline-queue-${digest(requestId)}`, parentRevision, state, next),
        parent: completeTopologyStep(this.kernel, actor, `pipeline-complete-${digest(requestId)}`, parentRevision, state, this.completionGate) };
    }, value => { this.authorize(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }
  resume(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number, parentInput: string, reviewer: PipelineChild) {
    this.authorize(actor, parentId); this.authorizeChild(actor, reviewer);
    return command(this.kernel.db, actor, requestId, "pipeline.resume_and_queue", { parentId, parentRevision, topologyRevision, parentInput, reviewer }, () => {
      this.authorize(actor, parentId);
      const state = this.topology.resumePipeline(actor, `pipeline-phase-${digest(requestId)}`, parentId, parentRevision, topologyRevision, parentInput);
      return { topology: state, next_run: this.enqueue(actor, `pipeline-queue-${digest(requestId)}`, parentRevision, state, reviewer) };
    }, value => { this.authorize(actor, parentId); return value; });
  }
}
