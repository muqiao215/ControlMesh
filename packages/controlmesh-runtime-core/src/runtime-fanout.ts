import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { RuntimeTopology, type TopologySnapshot } from "./runtime-topology";
import { TopologyTaskQueue } from "./topology-task-queue";
import type { FanoutResultOptions } from "./team-fanout";
import { digest, requireThat } from "./value";

export interface FanoutChild { task_id: string; revision: number; role: string; resume_prompt?: string }
/** Explicit fanout steps, with whole-batch acceptance under one stable dispatch checkpoint. */
export class RuntimeFanout {
  private readonly topology: RuntimeTopology;
  private readonly queue: TopologyTaskQueue;
  constructor(private readonly kernel: RuntimeKernel, private readonly runtime: LocalTaskRuntime) {
    this.topology = new RuntimeTopology(kernel); this.queue = new TopologyTaskQueue(kernel, runtime);
  }
  private authorize(actor: Principal, parentId: string, children: readonly FanoutChild[]): void {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    this.kernel.inspect(actor, parentId);
    requireThat(children.length <= this.runtime.parallelLimit(), "fanout_parallel_limit");
    for (const child of children) {
      this.kernel.inspect(actor, child.task_id);
      if (child.resume_prompt !== undefined) requireScope(actor, "task:resume");
    }
  }
  private enqueue(actor: Principal, requestId: string, parentRevision: number, state: TopologySnapshot, child: FanoutChild) {
    if (child.resume_prompt !== undefined) return this.queue.resume(actor, requestId, state.task_id, parentRevision, state.revision,
      child.task_id, child.revision, child.role, child.resume_prompt);
    return this.queue.enqueue(actor, requestId, state.task_id, parentRevision, state.revision, child.task_id, child.revision, child.role);
  }
  private next(actor: Principal, requestId: string, parentRevision: number, state: TopologySnapshot, child?: FanoutChild) {
    const cp = state.state.checkpoints.at(-1)!;
    if (cp.phase_status !== "in_progress") return null;
    requireThat(child && cp.active_roles.length === 1 && cp.active_roles[0] === child.role, "fanout_next_child_required");
    return this.enqueue(actor, requestId, parentRevision, state, child);
  }
  dispatch(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number, workers: FanoutChild[]) {
    this.authorize(actor, parentId, workers);
    requireThat(workers.length > 0 && new Set(workers.map(child => child.role)).size === workers.length
      && new Set(workers.map(child => child.task_id)).size === workers.length, "fanout_distinct_workers_required");
    return command(this.kernel.db, actor, requestId, "fanout.queue_workers", { parentId, parentRevision, revision, workers }, () => {
      this.authorize(actor, parentId, workers);
      const state = this.topology.dispatchFanout(actor, `fanout-phase-${digest(requestId)}`, parentId, parentRevision, revision, workers.map(child => child.role), this.runtime.parallelLimit());
      const runs = workers.map(child => this.enqueue(actor, `fanout-queue-${digest([requestId, child.role])}`, parentRevision, state, child));
      return { topology: state, runs };
    }, value => { this.authorize(actor, parentId, workers); return value; });
  }
  collectWorkers(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number, workers: FanoutChild[], reducer?: FanoutChild) {
    this.authorize(actor, parentId, workers); if (reducer) this.authorize(actor, parentId, [reducer]);
    return command(this.kernel.db, actor, requestId, "fanout.accept_workers", { parentId, parentRevision, revision, workers, reducer: reducer ?? null }, () => {
      const current = this.topology.inspect(actor, parentId), cp = current?.state.checkpoints.at(-1);
      requireThat(current?.revision === revision && current.state.topology === "fanout_merge" && cp?.substage === "dispatching", "fanout_stage_mismatch");
      requireThat(workers.length === cp.active_roles.length && new Set(workers.map(child => child.task_id)).size === workers.length
        && new Set(workers.map(child => child.role)).size === workers.length && cp.active_roles.every(role => workers.some(child => child.role === role)), "fanout_complete_batch_required");
      // Dispatch order is authoritative; completion order and caller ordering cannot reorder fallback evidence.
      const results = cp.active_roles.map(role => {
        const child = workers.find(candidate => candidate.role === role)!;
        const accepted = this.queue.collect(actor, `fanout-collect-${digest([requestId, role])}`, parentId, parentRevision, revision, child.task_id, child.revision);
        requireThat(accepted.result.worker_role === role, "fanout_worker_role_mismatch"); return accepted.result;
      });
      const state = this.topology.fanoutWorkers(actor, `fanout-phase-${digest(requestId)}`, parentId, parentRevision, revision, results, reducer?.role ?? "reducer");
      return { topology: state, next_run: this.next(actor, `fanout-next-${digest(requestId)}`, parentRevision, state, reducer) };
    }, value => { this.authorize(actor, parentId, workers); if (reducer) this.authorize(actor, parentId, [reducer]); return value; });
  }
  advance(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number,
    childId: string, childRevision: number, options: FanoutResultOptions = {}, next?: FanoutChild) {
    this.authorize(actor, parentId, next ? [next] : []); this.kernel.inspect(actor, childId);
    return command(this.kernel.db, actor, requestId, "fanout.advance", { parentId, parentRevision, revision, childId, childRevision, options, next: next ?? null }, () => {
      const accepted = this.queue.collect(actor, `fanout-collect-${digest(requestId)}`, parentId, parentRevision, revision, childId, childRevision);
      const state = this.topology.fanoutResult(actor, `fanout-phase-${digest(requestId)}`, parentId, parentRevision, revision, accepted.result, options);
      return { topology: state, next_run: this.next(actor, `fanout-next-${digest(requestId)}`, parentRevision, state, next) };
    }, value => { this.authorize(actor, parentId, next ? [next] : []); this.kernel.inspect(actor, childId); return value; });
  }
  resume(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number, parentInput: string, reducer: FanoutChild) {
    this.authorize(actor, parentId, [reducer]);
    return command(this.kernel.db, actor, requestId, "fanout.resume_and_queue", { parentId, parentRevision, revision, parentInput, reducer }, () => {
      const state = this.topology.resumeFanout(actor, `fanout-phase-${digest(requestId)}`, parentId, parentRevision, revision, parentInput);
      return { topology: state, next_run: this.next(actor, `fanout-next-${digest(requestId)}`, parentRevision, state, reducer) };
    }, value => { this.authorize(actor, parentId, [reducer]); return value; });
  }
}
