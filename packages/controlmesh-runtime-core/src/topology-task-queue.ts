import { readAggregateResult } from "./topology-aggregate";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal, type Lease } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { RuntimeTopology } from "./runtime-topology";
import { readTeamTaskResult, readTeamControlDecision, teamWorkerSubstage, type TeamTaskResultBinding } from "./team-task-result";
import { canonical, digest, identifier, requireThat, terminal } from "./value";

interface Assignment {
  child_id: string; parent_id: string; topology: string; substage: string;
  worker_role: string; checkpoint_id: string; run_id: string; accepted: string | null; generation: number; execution_id: string; kind: "native" | "aggregate";
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
      this.kernel.db.sql.query("INSERT INTO topology_tasks (child_id,parent_id,topology,substage,worker_role,checkpoint_id,run_id,accepted,execution_id) VALUES (?,?,?,?,?,?,?,NULL,?)")
        .run(childId, parentId, topology.state.topology, cp.substage, role, cp.checkpoint_id, run.run_id, topology.state.execution_id);
      return { child_id: childId, run_id: run.run_id };
    }, value => { this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute"); this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }
  /** Preserve task/native identity while atomically replacing a completed assignment. */
  resume(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number, role: string, prompt: string): { child_id: string; run_id: string; generation: number } {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute"); requireScope(actor, "task:resume");
    this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId);
    return command(this.kernel.db, actor, requestId, "topology.resume_child", { parentId, parentRevision, topologyRevision, childId, childRevision, role, prompt }, () => {
      const topology = this.parent(actor, parentId, parentRevision, topologyRevision);
      const prior = this.kernel.db.sql.query("SELECT * FROM topology_tasks WHERE child_id=? AND parent_id=?").get(childId, parentId) as Assignment | null;
      requireThat(prior && prior.kind === "native" && (prior.execution_id !== topology.state.execution_id || prior.checkpoint_id !== topology.state.checkpoints.at(-1)!.checkpoint_id), "topology_new_checkpoint_required");
      const child = this.kernel.inspect(actor, childId);
      requireThat(child.revision === childRevision && !child.needs_reconciliation && child.active_episode === null
        && (child.task.status === "failed" || (child.task.status === "done" && prior.accepted !== null)), "topology_previous_result_unresolved");
      requireThat(Number.isSafeInteger(prior.generation) && prior.generation >= 1 && prior.generation < Number.MAX_SAFE_INTEGER, "invalid_assignment_generation");
      const generation = prior.generation + 1;
      this.kernel.db.sql.query("INSERT INTO topology_task_history VALUES (?,?,?)").run(childId, prior.generation, canonical(prior));
      const resumed = this.runtime.resume(`topology-resume-${digest([actor.id, requestId])}`, childId, childRevision, prompt);
      this.kernel.db.sql.query("DELETE FROM topology_tasks WHERE child_id=?").run(childId);
      const queued = this.enqueue(actor, `topology-reassign-${digest([actor.id, requestId])}`, parentId, parentRevision, topologyRevision, childId, resumed.revision, role);
      this.kernel.db.sql.query("UPDATE topology_tasks SET generation=? WHERE child_id=?").run(generation, childId);
      return { ...queued, generation };
    }, value => { this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute"); requireScope(actor, "task:resume"); this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }

  /** Reserve an independently authorized topology child; no provider job, episode or grant is invented. */
  aggregate(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number, role: string, resumePrompt?: string) {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    if (resumePrompt !== undefined) requireScope(actor, "task:resume");
    this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId);
    requireThat(typeof role === "string" && role.length > 0 && role.length <= 128, "invalid_topology_role");
    return command(this.kernel.db, actor, requestId, "topology.assign_aggregate", { parentId, parentRevision, topologyRevision, childId, childRevision, role, resumePrompt: resumePrompt ?? null }, () => {
      const parent = this.parent(actor, parentId, parentRevision, topologyRevision), cp = parent.state.checkpoints.at(-1)!;
      requireThat(cp.active_roles.includes(role), "topology_role_not_active");
      requireThat(!((parent.state.topology === "director_worker" && ["planning", "director_deciding", "repairing"].includes(cp.substage))
        || (parent.state.topology === "debate_judge" && cp.substage === "judging")), "aggregate_cannot_issue_control_decision");
      const child = this.kernel.inspect(actor, childId);
      requireThat(child.revision === childRevision && !child.active_episode && !child.needs_reconciliation, "aggregate_child_changed");
      const owner = (id: string) => (this.kernel.db.sql.query("SELECT principal FROM tasks WHERE task_id=?").get(id) as { principal: string }).principal;
      requireThat(owner(childId) === actor.id && owner(parentId) === actor.id, "topology_task_owner_mismatch");
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(childId), "aggregate_provider_queued");
      const seen = new Set([childId]); let ancestor: string | null = parentId;
      for (let depth = 0; ancestor !== null; depth++) {
        requireThat(depth < 31 && !seen.has(ancestor), "topology_cycle_or_depth_limit"); seen.add(ancestor);
        const edge = this.kernel.db.sql.query("SELECT parent_id FROM topology_tasks WHERE child_id=?").get(ancestor) as { parent_id: string } | null;
        ancestor = edge?.parent_id ?? null;
      }
      let generation = 1;
      if (resumePrompt !== undefined) {
        const prior = this.kernel.db.sql.query("SELECT * FROM topology_tasks WHERE child_id=? AND parent_id=?").get(childId, parentId) as Assignment | null;
        requireThat(prior?.kind === "aggregate" && prior.accepted !== null && (prior.execution_id !== parent.state.execution_id || prior.checkpoint_id !== cp.checkpoint_id), "aggregate_resume_not_admitted");
        requireThat(Number.isSafeInteger(prior.generation) && prior.generation >= 1 && prior.generation < Number.MAX_SAFE_INTEGER, "invalid_assignment_generation");
        const previous = new RuntimeTopology(this.kernel).inspect(actor, childId); requireThat(previous, "aggregate_topology_missing");
        generation = prior.generation + 1;
        this.kernel.db.sql.query("INSERT INTO topology_task_history VALUES (?,?,?)").run(childId, prior.generation, canonical(prior));
        this.kernel.db.sql.query("DELETE FROM topology_tasks WHERE child_id=?").run(childId);
        // The outer transaction rebinds the same child before any work can be admitted.
        this.kernel.reopenTopology(actor, `aggregate-reopen-${digest(requestId)}`, childId, childRevision, previous.revision, resumePrompt);
      } else requireThat(child.task.status === "waiting", "aggregate_child_not_waiting");
      const state = new RuntimeTopology(this.kernel).inspect(actor, childId);
      requireThat(state || ["pipeline", "fanout_merge", "director_worker", "debate_judge"].includes(String(child.task.topology)), "aggregate_topology_required");
      requireThat(!state || (state.state.checkpoints.length === 1 && state.state.checkpoints[0]!.substage === "planning"
        && !this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE parent_id=? AND execution_id=?").get(childId, state.state.execution_id)), "aggregate_execution_already_started");
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE child_id=? OR (parent_id=? AND checkpoint_id=? AND worker_role=?)").get(childId, parentId, cp.checkpoint_id, role), "topology_assignment_exists");
      this.kernel.db.sql.query("INSERT INTO topology_tasks (child_id,parent_id,topology,substage,worker_role,checkpoint_id,run_id,accepted,generation,execution_id,kind) VALUES (?,?,?,?,?,?,?,NULL,?,?,'aggregate')")
        .run(childId, parentId, parent.state.topology, cp.substage, role, cp.checkpoint_id, state?.state.execution_id ?? "", generation, parent.state.execution_id);
      return { child_id: childId, run_id: state?.state.execution_id ?? "", execution_kind: "aggregate" as const, generation, child_revision: this.kernel.inspect(actor, childId).revision };
    }, value => { this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute"); if (resumePrompt !== undefined) requireScope(actor, "task:resume"); this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }

  collect(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number): ReturnType<typeof readTeamTaskResult> | ReturnType<typeof readAggregateResult> {
    return this.collectBound<ReturnType<typeof readTeamTaskResult> | ReturnType<typeof readAggregateResult>>(actor, requestId, parentId, parentRevision, topologyRevision, childId, childRevision, "topology.collect", (kernel, actor, { round_index: _round, ...binding }) => readTeamTaskResult(kernel, actor, binding), assignment => {
      const topology = new RuntimeTopology(this.kernel).inspect(actor, childId); requireThat(topology, "aggregate_topology_missing");
      return readAggregateResult(this.kernel, actor, { source: "topology", task_id: childId, revision: childRevision, execution_id: assignment.run_id,
        topology_revision: topology.revision, topology: assignment.topology, substage: teamWorkerSubstage(assignment.topology, assignment.substage), worker_role: assignment.worker_role }, new Set([parentId]));
    });
  }
  collectDecision(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number): ReturnType<typeof readTeamControlDecision> {
    return this.collectBound(actor, requestId, parentId, parentRevision, topologyRevision, childId, childRevision, "topology.collect_decision", readTeamControlDecision);
  }
  private collectBound<T>(actor: Principal, requestId: string, parentId: string, parentRevision: number, topologyRevision: number,
    childId: string, childRevision: number, operation: string,
    read: (kernel: RuntimeKernel, actor: Principal, binding: TeamTaskResultBinding & { round_index: number }) => T, aggregate?: (assignment: Assignment) => T): T {
    this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); requireScope(actor, "task:execute");
    this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId);
    return command(this.kernel.db, actor, requestId, operation, { parentId, parentRevision, topologyRevision, childId, childRevision }, () => {
      const topology = this.parent(actor, parentId, parentRevision, topologyRevision), cp = topology.state.checkpoints.at(-1)!;
      const assignment = this.kernel.db.sql.query("SELECT * FROM topology_tasks WHERE child_id=? AND parent_id=?").get(childId, parentId) as Assignment | null;
      requireThat(assignment && assignment.execution_id === topology.state.execution_id && assignment.accepted === null && assignment.checkpoint_id === cp.checkpoint_id
        && assignment.topology === topology.state.topology && assignment.substage === cp.substage && cp.active_roles.includes(assignment.worker_role), "topology_assignment_changed");
      if (assignment.kind === "aggregate") {
        requireThat(aggregate, "aggregate_cannot_issue_control_decision");
        const accepted = aggregate(assignment);
        this.kernel.db.sql.query("UPDATE topology_tasks SET accepted=? WHERE child_id=?").run(canonical(accepted), childId);
        return accepted;
      }
      const run = this.runtime.inspect(assignment.run_id);
      requireThat(run.task_id === childId && run.state === "completed", "topology_child_not_completed");
      const row = this.kernel.db.sql.query("SELECT lease FROM local_runs WHERE run_id=?").get(run.run_id) as { lease: string | null };
      requireThat(row.lease !== null, "topology_child_execution_missing");
      const lease = JSON.parse(row.lease) as Lease;
      const effects = this.kernel.db.sql.query("SELECT e.effect_id FROM effects e JOIN episodes p ON p.episode_id=e.episode_id WHERE e.task_id=? AND e.episode_id=? AND e.fence=? AND e.state='confirmed' AND e.result=p.result")
        .all(childId, lease.episode_id, lease.fence) as { effect_id: string }[];
      requireThat(effects.length === 1, "topology_child_result_ambiguous");
      const accepted = read(this.kernel, actor, { task_id: childId, revision: childRevision, episode_id: lease.episode_id,
        effect_id: effects[0]!.effect_id, topology: assignment.topology,
        substage: teamWorkerSubstage(assignment.topology, assignment.substage),
        worker_role: assignment.worker_role, round_index: cp.round_index ?? 0 });
      this.kernel.db.sql.query("UPDATE topology_tasks SET accepted=? WHERE child_id=?").run(canonical(accepted), childId);
      return accepted;
    }, value => { this.runtime.assertPrincipal(actor); requireScope(actor, "team:write"); this.kernel.inspect(actor, parentId); this.kernel.inspect(actor, childId); return value; });
  }
}
