import type { TopologyArtifactGate } from "./topology-artifacts";
import { completeTopologyStep } from "./topology-completion";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { RuntimeTopology, type TopologySnapshot } from "./runtime-topology";
import { TopologyTaskQueue } from "./topology-task-queue";
import { DirectorPolicy, type DirectorLimits, type DirectorOptions } from "./team-director";
import { JudgePolicy } from "./team-judge";
import { appendTopologyCheckpoint, decodeTopologyState, type TopologyState } from "./team-topology";
import { canonical, digest, identifier, requireThat, terminal } from "./value";

export interface ControlChild { task_id: string; revision: number; role: string; resume_prompt?: string; aggregate?: boolean }
export type ControlSetup = { topology: "director_worker"; limits?: DirectorOptions }
  | { topology: "debate_judge"; round_limit: number; max_repair_cycles?: number; max_parent_interruptions?: number };
interface ControlIdentity { controller_task_id: string; controller_role: string; parallel_limit: number }
export type ControlConfig = ControlIdentity & ({ topology: "director_worker"; limits: DirectorLimits }
  | { topology: "debate_judge"; round_limit: number; max_repair_cycles: number; max_parent_interruptions: number });
interface ControlSnapshot { topology: TopologySnapshot; config: ControlConfig }
/** Explicit local controller steps. Frozen identities/budgets survive restart; no model polling loop. */
export class RuntimeControlTopology {
  private readonly topology: RuntimeTopology;
  private readonly queue: TopologyTaskQueue;
  constructor(private readonly kernel: RuntimeKernel, private readonly runtime: LocalTaskRuntime, private readonly completionGate?: TopologyArtifactGate) {
    this.topology = new RuntimeTopology(kernel); this.queue = new TopologyTaskQueue(kernel, runtime);
  }
  private authorize(actor: Principal, parentId: string, children: readonly ControlChild[] = []): void {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    for (const id of [parentId, ...children.map(child => child.task_id)]) {
      this.kernel.inspect(actor, id);
      requireThat((this.kernel.db.sql.query("SELECT principal FROM tasks WHERE task_id=?").get(id) as { principal: string }).principal === actor.id, "control_task_owner_mismatch");
    }
    for (const child of children) if (child.resume_prompt !== undefined) requireScope(actor, "task:resume");
  }
  private config(value: ControlConfig): ControlConfig {
    identifier(value.controller_task_id);
    requireThat(typeof value.controller_role === "string" && value.controller_role.length > 0 && value.controller_role.length <= 128
      && Number.isSafeInteger(value.parallel_limit) && value.parallel_limit >= 1, "invalid_control_identity");
    if (value.topology === "director_worker") {
      const policy = new DirectorPolicy(value.parallel_limit, value.limits);
      requireThat(canonical(policy.limits) === canonical(value.limits), "invalid_frozen_director_limits");
    } else {
      requireThat(value.topology === "debate_judge" && value.parallel_limit >= 2
        && [value.round_limit, value.max_repair_cycles, value.max_parent_interruptions].every(Number.isSafeInteger)
        && value.round_limit >= 1 && value.max_repair_cycles >= 0 && value.max_parent_interruptions >= 0, "invalid_frozen_judge_limits");
    }
    return value;
  }
  inspect(actor: Principal, parentId: string): ControlSnapshot | null {
    const topology = this.topology.inspect(actor, parentId);
    const row = this.kernel.db.sql.query("SELECT config FROM topology_controls WHERE task_id=?").get(parentId) as { config: string } | null;
    if (!row) return null;
    const config = this.config(JSON.parse(row.config));
    requireThat(topology && topology.state.topology === config.topology && topology.state.checkpoints[0]!.active_roles[0] === config.controller_role, "control_topology_mismatch");
    return { topology, config };
  }
  private current(actor: Principal, parentId: string, parentRevision: number, revision: number): ControlSnapshot {
    this.authorize(actor, parentId);
    const task = this.kernel.inspect(actor, parentId), current = this.inspect(actor, parentId);
    requireThat(Number.isSafeInteger(parentRevision) && task.revision === parentRevision && Number.isSafeInteger(revision) && current?.topology.revision === revision, "revision_conflict");
    requireThat(!terminal.has(task.task.status) && !task.needs_reconciliation, "control_parent_inactive");
    return current!;
  }
  private controller(config: ControlConfig, child: ControlChild): void {
    requireThat(!child.aggregate, "aggregate_cannot_issue_control_decision");
    requireThat(child.task_id === config.controller_task_id && child.role === config.controller_role, "control_controller_identity_changed");
  }
  private save(current: TopologySnapshot, state: TopologyState): TopologySnapshot {
    state = decodeTopologyState(state);
    requireThat(state.task_id === current.task_id, "control_task_mismatch");
    const revision = current.revision + 1;
    this.kernel.db.sql.query("UPDATE team_topologies SET revision=?,state=? WHERE task_id=? AND revision=?")
      .run(revision, canonical(state), current.task_id, current.revision);
    return { task_id: current.task_id, revision, state };
  }
  private enqueue(actor: Principal, requestId: string, parentRevision: number, snapshot: ControlSnapshot, children: ControlChild[]) {
    const { topology, config } = snapshot, cp = topology.state.checkpoints.at(-1)!;
    if (cp.phase_status !== "in_progress") { requireThat(children.length === 0, "control_unexpected_next_children"); return []; }
    requireThat(children.length > 0 && children.length <= config.parallel_limit && children.length <= this.runtime.parallelLimit()
      && children.length === cp.active_roles.length && new Set(children.map(child => child.task_id)).size === children.length
      && new Set(children.map(child => child.role)).size === children.length
      && cp.active_roles.every(role => children.some(child => child.role === role)), "control_complete_next_batch_required");
    const controlStage = cp.substage === "planning" || cp.substage === "director_deciding" || cp.substage === "judging"
      || (config.topology === "director_worker" && cp.substage === "repairing");
    // The dispatch order belongs to the persisted checkpoint, not the caller's array.
    return cp.active_roles.map(role => {
      const child = children.find(item => item.role === role)!;
      if (controlStage) this.controller(config, child);
      else requireThat(child.task_id !== config.controller_task_id && child.role !== config.controller_role, "control_worker_is_controller");
      const prior = this.kernel.db.sql.query("SELECT child_id FROM topology_tasks WHERE parent_id=? AND worker_role=?").all(topology.task_id, role) as { child_id: string }[];
      requireThat(prior.every(item => item.child_id === child.task_id), "control_role_task_changed");
      const id = `control-queue-${digest([requestId, role])}`;
      if (child.aggregate) return this.queue.aggregate(actor, id, topology.task_id, parentRevision, topology.revision, child.task_id, child.revision, role, child.resume_prompt);
      if (child.resume_prompt !== undefined) return this.queue.resume(actor, id, topology.task_id, parentRevision, topology.revision, child.task_id, child.revision, role, child.resume_prompt);
      return this.queue.enqueue(actor, id, topology.task_id, parentRevision, topology.revision, child.task_id, child.revision, role);
    });
  }
  start(actor: Principal, requestId: string, parentId: string, parentRevision: number, setup: ControlSetup,
    controller: ControlChild, workers: ControlChild[] = [], summary = "Plan") {
    this.authorize(actor, parentId, [controller, ...workers]);
    return command(this.kernel.db, actor, requestId, "control.start", { parentId, parentRevision, setup, controller, workers, summary }, () => {
      this.authorize(actor, parentId, [controller, ...workers]);
      const parent = this.kernel.inspect(actor, parentId), at = new Date(this.kernel.db.now());
      requireThat(Number.isSafeInteger(parentRevision) && parent.revision === parentRevision, "revision_conflict");
      requireThat(!terminal.has(parent.task.status) && !parent.needs_reconciliation, "control_parent_inactive");
      requireThat(!this.topology.inspect(actor, parentId), "topology_exists");
      requireThat(!parent.task.topology || parent.task.topology === setup.topology, "topology_task_kind_changed");
      requireThat(controller.task_id !== parentId && !workers.some(child => child.task_id === parentId), "control_parent_is_child");
      requireThat(!controller.aggregate, "aggregate_cannot_issue_control_decision");
      this.kernel.assertNativeTask(actor, controller.task_id);
      const controlTask = this.kernel.inspect(actor, controller.task_id);
      requireThat(Number.isSafeInteger(controller.revision) && controlTask.revision === controller.revision && controlTask.task.status === "waiting"
        && !controlTask.active_episode && !controlTask.needs_reconciliation && controller.resume_prompt === undefined
        && !this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE child_id=?").get(controller.task_id)
        && !this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(controller.task_id), "control_controller_not_admitted");
      const identity = { controller_task_id: controller.task_id, controller_role: controller.role, parallel_limit: this.runtime.parallelLimit() };
      const config = this.config(setup.topology === "director_worker" ? { ...identity, topology: setup.topology, limits: { ...new DirectorPolicy(identity.parallel_limit, setup.limits).limits } }
        : { ...identity, topology: setup.topology, round_limit: setup.round_limit, max_repair_cycles: setup.max_repair_cycles ?? 1, max_parent_interruptions: setup.max_parent_interruptions ?? 1 });
      let state: TopologyState;
      if (config.topology === "director_worker") {
        requireThat(workers.length === 0, "director_initial_workers_unexpected");
        state = new DirectorPolicy(config.parallel_limit, config.limits).start(parentId, summary, config.controller_role, undefined, at);
      } else {
        const policy = new JudgePolicy(config.parallel_limit);
        state = policy.candidates(policy.start(parentId, summary, config.round_limit, config.controller_role, at), workers.map(child => child.role), undefined, at);
      }
      this.kernel.db.sql.query("INSERT INTO team_topologies VALUES (?,1,?)").run(parentId, canonical(state));
      this.kernel.db.sql.query("INSERT INTO topology_controls VALUES (?,?)").run(parentId, canonical(config));
      this.kernel.bindTopologyExecution(actor, parentId, state.execution_id);
      const snapshot = { topology: { task_id: parentId, revision: 1, state }, config };
      const runs = this.enqueue(actor, requestId, parentRevision, snapshot, config.topology === "director_worker" ? [controller] : workers);
      return { ...snapshot, runs };
    }, value => { this.authorize(actor, parentId, [controller, ...workers]); return value; });
  }
  /** Dispatch a prepared execution, including a nested aggregate reopened by its parent. */
  dispatch(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number,
    controller: ControlChild, workers: ControlChild[] = []) {
    this.authorize(actor, parentId, [controller, ...workers]);
    return command(this.kernel.db, actor, requestId, "control.dispatch_prepared", { parentId, parentRevision, revision, controller, workers }, () => {
      const current = this.current(actor, parentId, parentRevision, revision);
      this.controller(current.config, controller);
      requireThat(current.topology.state.checkpoints.length === 1 && current.topology.state.checkpoints[0]!.substage === "planning", "control_not_prepared");
      let topology = current.topology;
      if (current.config.topology === "debate_judge") topology = this.save(topology,
        new JudgePolicy(current.config.parallel_limit).candidates(topology.state, workers.map(child => child.role), undefined, new Date(this.kernel.db.now())));
      else requireThat(workers.length === 0, "director_initial_workers_unexpected");
      const snapshot = { topology, config: current.config };
      return { ...snapshot, runs: this.enqueue(actor, requestId, parentRevision, snapshot, current.config.topology === "director_worker" ? [controller] : workers) };
    }, value => { this.authorize(actor, parentId, [controller, ...workers]); return value; });
  }
  reopen(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number, prompt: string,
    controller: ControlChild, workers: ControlChild[] = []) {
    this.authorize(actor, parentId, [controller, ...workers]); requireScope(actor, "task:resume");
    return command(this.kernel.db, actor, requestId, "control.reopen_and_queue", { parentId, parentRevision, revision, prompt, controller, workers }, () => {
      const prior = this.inspect(actor, parentId); requireThat(prior, "control_topology_missing");
      this.controller(prior.config, controller);
      const reopened = this.kernel.reopenTopology(actor, `control-reopen-${digest(requestId)}`, parentId, parentRevision, revision, prompt);
      let topology = reopened.topology;
      if (prior.config.topology === "debate_judge") {
        const state = new JudgePolicy(prior.config.parallel_limit).candidates(topology.state, workers.map(child => child.role), undefined, new Date(this.kernel.db.now()));
        topology = this.save(topology, state);
      } else requireThat(workers.length === 0, "director_initial_workers_unexpected");
      const snapshot = { topology, config: prior.config };
      const runs = this.enqueue(actor, requestId, reopened.parent.revision, snapshot, prior.config.topology === "director_worker" ? [controller] : workers);
      return { ...snapshot, parent: reopened.parent, runs };
    }, value => { this.authorize(actor, parentId, [controller, ...workers]); requireScope(actor, "task:resume"); return value; });
  }
  collectWorkers(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number, workers: ControlChild[], controller: ControlChild) {
    this.authorize(actor, parentId, [...workers, controller]);
    return command(this.kernel.db, actor, requestId, "control.collect_workers", { parentId, parentRevision, revision, workers, controller }, () => {
      const current = this.current(actor, parentId, parentRevision, revision), { config } = current, cp = current.topology.state.checkpoints.at(-1)!;
      this.controller(config, controller);
      requireThat(cp.substage === (config.topology === "director_worker" ? "dispatching" : "candidate_round"), "control_worker_stage_mismatch");
      requireThat(workers.length === cp.active_roles.length && new Set(workers.map(child => child.task_id)).size === workers.length
        && new Set(workers.map(child => child.role)).size === workers.length && cp.active_roles.every(role => workers.some(child => child.role === role)), "control_complete_worker_batch_required");
      const results = cp.active_roles.map(role => {
        const child = workers.find(item => item.role === role)!;
        const accepted = this.queue.collect(actor, `control-collect-${digest([requestId, role])}`, parentId, parentRevision, revision, child.task_id, child.revision);
        requireThat(accepted.result.worker_role === role, "control_worker_role_mismatch"); return accepted.result;
      });
      const at = new Date(this.kernel.db.now());
      const state = config.topology === "director_worker" ? new DirectorPolicy(config.parallel_limit, config.limits).collect(current.topology.state, results, config.controller_role, at)
        : new JudgePolicy(config.parallel_limit).collect(current.topology.state, results, config.controller_role, at);
      const topology = this.save(current.topology, state);
      return { topology, runs: this.enqueue(actor, requestId, parentRevision, { topology, config }, [controller]) };
    }, value => { this.authorize(actor, parentId, [...workers, controller]); return value; });
  }
  decide(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number,
    controller: ControlChild, next: ControlChild[] = [], parent: { question?: string; waiting_on?: string } = {}) {
    this.authorize(actor, parentId, [controller, ...next]);
    return command(this.kernel.db, actor, requestId, "control.decide", { parentId, parentRevision, revision, controller, next, parent }, () => {
      const current = this.current(actor, parentId, parentRevision, revision), { config } = current, at = new Date(this.kernel.db.now());
      this.controller(config, controller);
      const accepted = this.queue.collectDecision(actor, `control-decision-${digest(requestId)}`, parentId, parentRevision, revision, controller.task_id, controller.revision);
      let state: TopologyState;
      if (config.topology === "director_worker" && accepted.result.topology === "director_worker") {
        state = new DirectorPolicy(config.parallel_limit, config.limits).decide(current.topology.state, accepted.result, parent, at);
      } else {
        requireThat(config.topology === "debate_judge" && accepted.result.topology === "debate_judge", "control_decision_kind_mismatch");
        const configJudge = config as Extract<ControlConfig, { topology: "debate_judge" }>, raw = current.topology.state, policy = new JudgePolicy(config.parallel_limit);
        const kind = accepted.result.decision, cap = kind === "needs_repair" ? configJudge.max_repair_cycles : configJudge.max_parent_interruptions;
        const count = raw.checkpoints.filter(cp => cp.substage === (kind === "needs_repair" ? "repairing" : "waiting_parent")).length;
        if ((kind === "needs_repair" || kind === "needs_parent_input") && count >= cap) {
          const cp = raw.checkpoints.at(-1)!, summary = `debate_judge stopped: ${kind === "needs_repair" ? "max_repair_cycles" : "max_parent_interruptions"} exhausted (${cap}).`;
          state = appendTopologyCheckpoint(raw, { substage: "failed", phase_status: "failed", active_roles: [], completed_roles: [...new Set([...cp.completed_roles, config.controller_role])],
            latest_summary: summary, round_index: cp.round_index, round_limit: cp.round_limit,
            reduced_result: { schema_version: 1, topology: "debate_judge", final_status: "failed", reduced_summary: summary, selected_evidence: [], selected_artifacts: [], next_action: null } }, at);
        } else {
          requireThat(accepted.result.topology === "debate_judge", "control_decision_kind_mismatch");
          state = policy.decide(raw, accepted.result, parent, at);
          if (state.checkpoints.at(-1)!.substage === "repairing") state = policy.candidates(state, state.checkpoints.at(-1)!.active_roles, undefined, at);
        }
      }
      const topology = this.save(current.topology, state);
      return { topology, runs: this.enqueue(actor, requestId, parentRevision, { topology, config }, next),
        parent: completeTopologyStep(this.kernel, actor, `control-complete-${digest(requestId)}`, parentRevision, topology, this.completionGate) };
    }, value => { this.authorize(actor, parentId, [controller, ...next]); return value; });
  }
  resume(actor: Principal, requestId: string, parentId: string, parentRevision: number, revision: number, parentInput: string, controller: ControlChild) {
    this.authorize(actor, parentId, [controller]);
    return command(this.kernel.db, actor, requestId, "control.resume", { parentId, parentRevision, revision, parentInput, controller }, () => {
      const current = this.current(actor, parentId, parentRevision, revision), { config } = current, at = new Date(this.kernel.db.now());
      this.controller(config, controller);
      const state = config.topology === "director_worker" ? new DirectorPolicy(config.parallel_limit, config.limits).resume(current.topology.state, parentInput, undefined, at)
        : new JudgePolicy(config.parallel_limit).resume(current.topology.state, parentInput, undefined, at);
      const topology = this.save(current.topology, state);
      return { topology, runs: this.enqueue(actor, requestId, parentRevision, { topology, config }, [controller]) };
    }, value => { this.authorize(actor, parentId, [controller]); return value; });
  }
}
