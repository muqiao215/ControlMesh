import { randomUUID } from "node:crypto";
import { command, requireScope } from "./commands";
import { RuntimeKernel, type Principal } from "./kernel";
import type { TopologyRuntime } from "./topology-runtime";
import { RuntimeTopology } from "./runtime-topology";
import { RuntimePipeline, type PipelineChild } from "./runtime-pipeline";
import { RuntimeFanout } from "./runtime-fanout";
import { RuntimeControlTopology } from "./runtime-control-topology";
import { TopologyTaskQueue } from "./topology-task-queue";
import { DirectorPolicy } from "./team-director";
import { JudgePolicy } from "./team-judge";
import { applyPipelineResult } from "./team-pipeline";
import { applyFanoutResult, collectFanoutWorkers } from "./team-fanout";
import type { TopologyState } from "./team-topology";
import type { TopologyArtifactGate } from "./topology-artifacts";
import { decodeTopologySchedulePlan, type ScheduleNode, type TopologySchedulePlan } from "./topology-schedule-plan";
import { canonical, digest, identifier, requireThat, RuntimeConflict, terminal } from "./value";

type Mode = "paused" | "active" | "blocked" | "completed" | "failed" | "cancelled";
interface Reason { code: string; node_id?: string; child_id?: string; question?: string; retry_after?: number | null }
interface Row {
  root_id: string; principal: string; device_id: string; origin: string; plan: string; plan_digest: string;
  revision: number; mode: Mode; reason: string | null; lease_owner: string | null; lease_until: number; lease_fence: number;
}
interface Action { terminal: boolean; parent_revision: number; topology_revision: number; run(): void }
class ScheduleBlocked extends RuntimeConflict { constructor(readonly reason: Reason) { super(reason.code); } }
export interface TopologySchedulerOptions { interval_ms?: number; lease_ms?: number; max_steps?: number }

/** Owns bounded automatic transitions. Provider execution stays in LocalTaskRuntime. */
export class TopologyScheduler {
  private readonly owner = randomUUID();
  private readonly topology: RuntimeTopology;
  private readonly queue: TopologyTaskQueue;
  private readonly pipeline: RuntimePipeline;
  private readonly fanout: RuntimeFanout;
  private readonly control: RuntimeControlTopology;
  private readonly interval: number; private readonly leaseMs: number; private readonly maxSteps: number;
  private timer?: ReturnType<typeof setInterval>; private ticking?: Promise<number>; private draining?: Promise<void>;
  private stopping = false; private error: string | null = null;
  constructor(private readonly kernel: RuntimeKernel, private readonly runtime: TopologyRuntime, private readonly actor: Principal,
    options: TopologySchedulerOptions = {}, private readonly gate?: TopologyArtifactGate) {
    requireThat(runtime.kernel === kernel, "topology_queue_database_mismatch"); this.authorize();
    this.interval = options.interval_ms ?? 250; this.leaseMs = options.lease_ms ?? 30000; this.maxSteps = options.max_steps ?? 16;
    requireThat([this.interval, this.leaseMs, this.maxSteps].every(Number.isSafeInteger) && this.interval >= 100 && this.interval <= 5000
      && this.leaseMs >= 1000 && this.leaseMs <= 300000 && this.maxSteps >= 1 && this.maxSteps <= 64, "invalid_topology_scheduler_limits");
    this.topology = new RuntimeTopology(kernel); this.queue = new TopologyTaskQueue(kernel, runtime);
    this.pipeline = new RuntimePipeline(kernel, runtime, gate); this.fanout = new RuntimeFanout(kernel, runtime, gate);
    this.control = new RuntimeControlTopology(kernel, runtime, gate);
  }
  private authorize(): void {
    requireThat(!this.stopping, "topology_scheduler_stopping"); this.runtime.assertPrincipal(this.actor);
    requireScope(this.actor, "team:write"); requireScope(this.actor, "task:execute"); requireScope(this.actor, "task:resume");
  }
  private row(root: string): Row {
    identifier(root);
    const row = this.kernel.db.sql.query("SELECT * FROM topology_schedules WHERE root_id=? AND principal=? AND device_id=? AND origin=?")
      .get(root, this.actor.id, this.actor.device_id!, this.actor.origin) as Row | null;
    requireThat(row, "topology_schedule_not_found");
    requireThat(digest(JSON.parse(row.plan)) === row.plan_digest, "topology_schedule_plan_changed");
    return row;
  }
  private plan(row: Row): TopologySchedulePlan { return decodeTopologySchedulePlan(JSON.parse(row.plan), this.runtime.parallelLimit()); }
  private owned(taskId: string): void {
    this.kernel.inspect(this.actor, taskId);
    requireThat((this.kernel.db.sql.query("SELECT principal FROM tasks WHERE task_id=?").get(taskId) as { principal: string }).principal === this.actor.id, "topology_task_owner_mismatch");
  }
  register(requestId: string, input: unknown) {
    this.authorize(); const plan = decodeTopologySchedulePlan(input, this.runtime.parallelLimit());
    return command(this.kernel.db, this.actor, requestId, "schedule.register", plan, () => {
      const count = this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM topology_schedules WHERE principal=? AND device_id=?").get(this.actor.id, this.actor.device_id!) as { n: number };
      requireThat(count.n < 32, "topology_schedule_capacity");
      const all = new Set(plan.nodes.flatMap(node => [node.task_id, ...node.roles.map(item => item.task_id)]));
      for (const id of all) {
        this.owned(id);
        requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_schedule_members WHERE task_id=?").get(id), "topology_task_already_scheduled");
        const task = this.kernel.inspect(this.actor, id);
        const assigned = this.kernel.db.sql.query("SELECT parent_id,worker_role,kind FROM topology_tasks WHERE child_id=?").get(id) as { parent_id: string; worker_role: string; kind: string } | null;
        if (assigned) requireThat(plan.nodes.some(node => node.task_id === assigned.parent_id && node.roles.some(item => item.task_id === id
          && item.role === assigned.worker_role && item.aggregate === (assigned.kind === "aggregate"))), "topology_schedule_assignment_changed");
        if (!assigned) requireThat(task.task.status === "waiting" && !task.active_episode && !task.needs_reconciliation
          && !this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(id), "topology_schedule_task_not_idle");
      }
      for (const node of plan.nodes) {
        const current = this.topology.inspect(this.actor, node.task_id);
        requireThat(!current || current.state.topology === node.topology, "topology_schedule_kind_changed"); this.checkControlPolicy(node);
        const assigned = this.kernel.db.sql.query("SELECT child_id,worker_role,kind FROM topology_tasks WHERE parent_id=?").all(node.task_id) as { child_id: string; worker_role: string; kind: string }[];
        requireThat(assigned.every(row => node.roles.some(item => item.task_id === row.child_id && item.role === row.worker_role
          && item.aggregate === (row.kind === "aggregate"))), "topology_schedule_assignment_changed");
      }
      this.kernel.db.sql.query("INSERT INTO topology_schedules(root_id,principal,device_id,origin,plan,plan_digest,revision,mode) VALUES (?,?,?,?,?,?,1,'paused')")
        .run(plan.root_task_id, this.actor.id, this.actor.device_id!, this.actor.origin, canonical(plan), digest(plan));
      for (const id of all) this.kernel.db.sql.query("INSERT INTO topology_schedule_members VALUES (?,?)").run(id, plan.root_task_id);
      return this.inspect(plan.root_task_id);
    }, () => this.inspect(plan.root_task_id));
  }
  inspect(root: string) {
    this.authorize(); const row = this.row(root), plan = this.plan(row);
    return { root_task_id: root, revision: row.revision, mode: row.mode, reason: row.reason ? JSON.parse(row.reason) as Reason : null, plan_digest: row.plan_digest,
      nodes: plan.nodes.map(node => {
        const task = this.kernel.inspect(this.actor, node.task_id), topology = this.topology.inspect(this.actor, node.task_id);
        const cp = topology?.state.checkpoints.at(-1);
        return { task_id: node.task_id, task_revision: task.revision, status: task.task.status, topology_revision: topology?.revision ?? null,
          execution_id: topology?.state.execution_id ?? null,
          stage: cp?.substage ?? null, summary: cp?.latest_summary ?? null, active_roles: cp?.active_roles ?? [],
          children: node.roles.map(role => {
            const child = this.kernel.inspect(this.actor, role.task_id);
            const assignment = this.kernel.db.sql.query("SELECT run_id,kind FROM topology_tasks WHERE child_id=? AND parent_id=? AND execution_id=?").get(role.task_id, node.task_id, topology?.state.execution_id ?? "") as { run_id: string; kind: string } | null;
            return { task_id: role.task_id, role: role.role, revision: child.revision, status: child.task.status,
              run: assignment?.kind === "native" ? this.runtime.inspect(assignment.run_id) : null };
          }) };
      }) };
  }
  setMode(requestId: string, root: string, revision: number, mode: "active" | "paused") {
    this.authorize(); requireThat(mode === "active" || mode === "paused", "invalid_topology_schedule_mode");
    return command(this.kernel.db, this.actor, requestId, "schedule.mode", { root, revision, mode }, () => {
      const row = this.row(root); requireThat(row.revision === revision && Number.isSafeInteger(revision), "revision_conflict");
      requireThat(!["completed", "failed", "cancelled"].includes(row.mode), "topology_schedule_terminal");
      this.set(row, mode, null); return this.inspect(root);
    }, () => this.inspect(root));
  }
  /** Explicit project continuation; a restart or an old command receipt never opens another run. */
  reopen(requestId: string, root: string, revision: number, taskRevision: number, topologyRevision: number, prompt: string) {
    this.authorize();
    requireThat([revision, taskRevision, topologyRevision].every(value => Number.isSafeInteger(value) && value > 0), "revision_conflict");
    requireThat(typeof prompt === "string" && prompt.trim().length > 0 && Buffer.byteLength(prompt) <= 32768, "invalid_resume_prompt");
    return command(this.kernel.db, this.actor, requestId, "schedule.reopen", { root, revision, taskRevision, topologyRevision, prompt }, () => {
      const row = this.row(root);
      requireThat(row.revision === revision, "revision_conflict");
      requireThat(["completed", "failed"].includes(row.mode), "topology_schedule_not_reopenable");
      requireThat(this.topology.inspect(this.actor, root)?.revision === topologyRevision, "revision_conflict");
      const plan = this.plan(row);
      for (const node of plan.nodes) {
        this.owned(node.task_id); this.checkControlPolicy(node);
        for (const role of node.roles) this.owned(role.task_id);
      }
      for (const taskId of new Set(plan.nodes.flatMap(node => [node.task_id, ...node.roles.map(role => role.task_id)]))) {
        const task = this.kernel.inspect(this.actor, taskId);
        requireThat(!task.active_episode && !task.needs_reconciliation
          && !this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(taskId),
        "topology_schedule_member_not_idle");
        const assignment = this.kernel.db.sql.query("SELECT run_id FROM topology_tasks WHERE child_id=? AND kind='native'").get(taskId) as { run_id: string } | null;
        if (assignment) requireThat(this.runtime.inspect(assignment.run_id).state === "completed", "topology_schedule_member_not_idle");
        else requireThat(!this.kernel.db.sql.query("SELECT 1 FROM device_assignments WHERE task_id=?").get(taskId), "topology_schedule_member_not_idle");
      }
      // The kernel archives verified completion; the next ordinary tick dispatches the frozen roles.
      const result = this.kernel.reopenTopology(this.actor, `schedule-reopen-${digest(requestId)}`, root, taskRevision, topologyRevision, prompt);
      this.set(row, "active", null);
      return { schedule: this.inspect(root), result };
    }, value => { this.inspect(root); return value; });
  }
  inspectRun(root: string, executionId: string) {
    this.authorize(); this.row(root); this.owned(root); identifier(executionId);
    return this.topology.inspectRun(this.actor, root, executionId);
  }
  private set(row: Row, mode: Mode, reason: Reason | null) {
    requireThat(Number.isSafeInteger(row.revision + 1) && Number.isSafeInteger(row.lease_fence + 1), "topology_schedule_revision_exhausted");
    this.kernel.db.sql.query("UPDATE topology_schedules SET revision=revision+1,mode=?,reason=?,lease_owner=NULL,lease_until=0,lease_fence=lease_fence+1 WHERE root_id=? AND revision=?")
      .run(mode, reason ? canonical(reason) : null, row.root_id, row.revision);
  }
  retry(requestId: string, root: string, revision: number, nodeId: string, parentRevision: number, topologyRevision: number, childId: string, childRevision: number, prompt?: string) {
    this.authorize();
    return command(this.kernel.db, this.actor, requestId, "schedule.retry", { root, revision, nodeId, parentRevision, topologyRevision, childId, childRevision, prompt: prompt ?? null }, () => {
      const row = this.row(root); requireThat(row.revision === revision && row.mode === "blocked", "topology_schedule_recovery_conflict");
      const plan = this.plan(row), node = plan.nodes.find(item => item.task_id === nodeId);
      requireThat(node?.roles.some(item => item.task_id === childId && !item.aggregate), "topology_schedule_child_not_registered");
      const result = this.queue.retry(this.actor, `schedule-retry-${digest(requestId)}`, nodeId, parentRevision, topologyRevision, childId, childRevision, prompt);
      this.set(row, "active", null); return { schedule: this.inspect(root), result };
    }, value => { this.inspect(root); return value; });
  }
  answer(requestId: string, root: string, revision: number, nodeId: string, parentRevision: number, topologyRevision: number, input: string) {
    this.authorize(); requireThat(typeof input === "string" && input.trim().length > 0 && Buffer.byteLength(input) <= 8000, "invalid_parent_input");
    return command(this.kernel.db, this.actor, requestId, "schedule.answer", { root, revision, nodeId, parentRevision, topologyRevision, input }, () => {
      const row = this.row(root), node = this.plan(row).nodes.find(item => item.task_id === nodeId);
      requireThat(row.revision === revision && row.mode === "blocked" && node, "topology_schedule_recovery_conflict");
      const state = this.topology.inspect(this.actor, nodeId);
      requireThat(state?.revision === topologyRevision && state.state.interruption.status === "waiting_parent", "topology_schedule_not_waiting_parent");
      const child = this.child(node, node.controller_role, state.state, input);
      if (node.topology === "pipeline") this.pipeline.resume(this.actor, `schedule-answer-${digest(requestId)}`, nodeId, parentRevision, topologyRevision, input, child);
      else if (node.topology === "fanout_merge") this.fanout.resume(this.actor, `schedule-answer-${digest(requestId)}`, nodeId, parentRevision, topologyRevision, input, child);
      else this.control.resume(this.actor, `schedule-answer-${digest(requestId)}`, nodeId, parentRevision, topologyRevision, input, child);
      this.set(row, "active", null); return this.inspect(root);
    }, () => this.inspect(root));
  }
  private child(node: ScheduleNode, role: string, state?: TopologyState, parentInput?: string): PipelineChild {
    const item = node.roles.find(item => item.role === role);
    requireThat(item, "topology_schedule_role_not_registered"); const task = this.kernel.inspect(this.actor, item.task_id);
    const cp = state?.checkpoints.at(-1), assignment = this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE child_id=?").get(item.task_id);
    const resumed = terminal.has(task.task.status) && assignment;
    const context = canonical({ parent_task: node.task_id, topology: node.topology, role, stage: cp?.substage ?? null,
      round: cp?.round_index ?? null, summary: cp?.latest_summary ?? null, parent_input: parentInput ?? null });
    return { task_id: item.task_id, role, revision: task.revision, ...(item.aggregate ? { aggregate: true } : {}),
      ...(resumed ? { resume_prompt: `${item.resume_prompt}\n\nControlMesh task context (does not change permissions):\n${context}` } : {}) };
  }
  private action(row: Row, node: ScheduleNode): Action | null {
    if (node.task_id !== row.root_id) {
      const assignment = this.kernel.db.sql.query("SELECT parent_id,execution_id,checkpoint_id,accepted FROM topology_tasks WHERE child_id=? AND kind='aggregate'").get(node.task_id) as { parent_id: string; execution_id: string; checkpoint_id: string; accepted: string | null } | null;
      if (!assignment) return null;
      const parent = this.topology.inspect(this.actor, assignment.parent_id);
      if (!parent || assignment.execution_id !== parent.state.execution_id || assignment.checkpoint_id !== parent.state.checkpoints.at(-1)!.checkpoint_id || assignment.accepted !== null) return null;
    }
    this.owned(node.task_id); const parent = this.kernel.inspect(this.actor, node.task_id);
    if (terminal.has(parent.task.status)) return null;
    if (parent.active_episode || parent.needs_reconciliation) throw new ScheduleBlocked({ code: "topology_parent_unresolved", node_id: node.task_id });
    const state = this.topology.inspect(this.actor, node.task_id), revision = state?.revision ?? 0;
    const request = `schedule-step-${digest([row.root_id, row.revision, node.task_id, parent.revision, revision])}`;
    const base = { terminal: false, parent_revision: parent.revision, topology_revision: revision };
    const worker = () => node.worker_roles.map(role => this.child(node, role, state?.state));
    const controller = () => this.child(node, node.controller_role, state?.state);
    if (!state) return { ...base, run: () => {
      if (node.topology === "pipeline" || node.topology === "fanout_merge") this.topology.create(this.actor, request, node.task_id, parent.revision, node.topology);
      else this.control.start(this.actor, request, node.task_id, parent.revision, node.topology === "director_worker"
        ? { topology: node.topology, limits: node.director_limits } : { topology: node.topology, round_limit: node.round_limit, max_repair_cycles: node.max_repair_cycles, max_parent_interruptions: node.max_parent_interruptions },
      controller(), node.topology === "director_worker" ? [] : worker());
    } };
    requireThat(state.state.topology === node.topology, "topology_schedule_kind_changed");
    this.checkControlPolicy(node);
    const cp = state.state.checkpoints.at(-1)!;
    if (state.state.interruption.status === "waiting_parent") throw new ScheduleBlocked({ code: "topology_waiting_parent", node_id: node.task_id, question: state.state.interruption.question ?? undefined });
    const assignments = this.kernel.db.sql.query("SELECT child_id,worker_role,kind,run_id FROM topology_tasks WHERE parent_id=? AND execution_id=? AND checkpoint_id=?")
      .all(node.task_id, state.state.execution_id, cp.checkpoint_id) as { child_id: string; worker_role: string; kind: string; run_id: string }[];
    if (cp.substage === "planning" && assignments.length === 0) return { ...base, run: () => {
      if (node.topology === "pipeline") this.pipeline.dispatch(this.actor, request, node.task_id, parent.revision, revision, worker()[0]!);
      else if (node.topology === "fanout_merge") this.fanout.dispatch(this.actor, request, node.task_id, parent.revision, revision, worker());
      else this.control.dispatch(this.actor, request, node.task_id, parent.revision, revision, controller(), node.topology === "director_worker" ? [] : worker());
    } };
    requireThat(cp.phase_status === "in_progress" && assignments.length === cp.active_roles.length && assignments.length > 0, "topology_schedule_assignment_missing");
    const children = cp.active_roles.map(role => {
      const child = this.child(node, role, state.state), assigned = assignments.find(item => item.worker_role === role);
      requireThat(assigned?.child_id === child.task_id && (assigned.kind === "aggregate") === !!child.aggregate, "topology_schedule_assignment_changed");
      const task = this.kernel.inspect(this.actor, child.task_id);
      if (task.needs_reconciliation || task.active_episode && task.task.status !== "running") throw new ScheduleBlocked({ code: "topology_child_unresolved", node_id: node.task_id, child_id: child.task_id });
      if (task.task.status === "cancelled" || (task.task.status === "failed" && !child.aggregate)) throw new ScheduleBlocked({ code: "topology_child_failed", node_id: node.task_id, child_id: child.task_id });
      if (!child.aggregate) {
        const run = this.runtime.inspect(assigned.run_id);
        if (["blocked", "interrupted", "cancelled"].includes(run.state)) throw new ScheduleBlocked({ code: run.outcome?.reason ?? "topology_child_blocked", node_id: node.task_id, child_id: child.task_id, retry_after: run.outcome?.retry_after ?? null });
      }
      return { child, ready: terminal.has(task.task.status) };
    });
    if (children.some(item => !item.ready)) return null;
    const current = children.map(item => item.child), first = current[0]!;
    const isControl = (node.topology === "director_worker" && ["planning", "director_deciding", "repairing"].includes(cp.substage)) || (node.topology === "debate_judge" && cp.substage === "judging");
    if (isControl) {
      const result = this.queue.peekDecision(this.actor, node.task_id, parent.revision, revision, first.task_id, first.revision).result;
      const parentQuestion = { question: result.next_action || result.summary, waiting_on: "user" };
      const next = this.control.previewDecision(this.actor, node.task_id, parent.revision, revision, first, parentQuestion);
      return { ...base, terminal: next.checkpoints.at(-1)!.substage === "completed", run: () => {
        this.control.decide(this.actor, request, node.task_id, parent.revision, revision, first, this.next(node, next), parentQuestion);
      } };
    }
    const results = current.map(child => this.queue.peek(this.actor, node.task_id, parent.revision, revision, child.task_id, child.revision).result);
    if ((node.topology === "director_worker" && cp.substage === "dispatching") || (node.topology === "debate_judge" && cp.substage === "candidate_round"))
      {
        const config = this.control.inspect(this.actor, node.task_id)!.config;
        const next = config.topology === "director_worker" ? new DirectorPolicy(config.parallel_limit, config.limits).collect(state.state, results, config.controller_role)
          : new JudgePolicy(config.parallel_limit).collect(state.state, results, config.controller_role);
        return { ...base, run: () => { this.control.collectWorkers(this.actor, request, node.task_id, parent.revision, revision, current, this.next(node, next)[0]!); } };
      }
    if (node.topology === "fanout_merge" && cp.substage === "dispatching") {
      const next = collectFanoutWorkers(state.state, results, node.controller_role);
      return { ...base, run: () => { this.fanout.collectWorkers(this.actor, request, node.task_id, parent.revision, revision, current, this.next(node, next)[0]); } };
    }
    const result = results[0]!, options = { max_repair_cycles: node.max_repair_cycles, max_parent_interruptions: node.max_parent_interruptions,
      reviewer_role: node.controller_role, reducer_role: node.controller_role, repair_worker_role: node.worker_roles[0], parent_question: result.next_action || result.summary, waiting_on: "user" };
    const next = node.topology === "pipeline" ? applyPipelineResult(state.state, result, options) : applyFanoutResult(state.state, result, options);
    return { ...base, terminal: next.checkpoints.at(-1)!.substage === "completed", run: () => {
      const child = this.next(node, next)[0];
      if (node.topology === "pipeline") this.pipeline.advance(this.actor, request, node.task_id, parent.revision, revision, first.task_id, first.revision, options, child);
      else this.fanout.advance(this.actor, request, node.task_id, parent.revision, revision, first.task_id, first.revision, options, child);
    } };
  }
  private checkControlPolicy(node: ScheduleNode) {
    if (node.topology !== "director_worker" && node.topology !== "debate_judge") return;
    const config = this.control.inspect(this.actor, node.task_id)?.config;
    if (!config) return;
    const controller = node.roles.find(role => role.role === node.controller_role)!;
    const expected = { controller_task_id: controller.task_id, controller_role: controller.role, parallel_limit: this.runtime.parallelLimit(),
      ...(node.topology === "director_worker" ? { topology: node.topology, limits: node.director_limits } : {
        topology: node.topology, round_limit: node.round_limit, max_repair_cycles: node.max_repair_cycles, max_parent_interruptions: node.max_parent_interruptions }) };
    requireThat(canonical(config) === canonical(expected), "topology_schedule_policy_mismatch");
  }
  private next(node: ScheduleNode, state: TopologyState): PipelineChild[] {
    const cp = state.checkpoints.at(-1)!;
    return cp.phase_status === "in_progress" ? cp.active_roles.map(role => this.child(node, role, state)) : [];
  }
  private acquire(root: string): Row | null {
    return this.kernel.db.transaction(() => {
      const row = this.row(root), now = this.kernel.db.now();
      if (row.mode !== "active" || row.lease_owner && row.lease_until > now) return null;
      requireThat(Number.isSafeInteger(row.lease_fence + 1), "topology_schedule_revision_exhausted");
      this.kernel.db.sql.query("UPDATE topology_schedules SET lease_owner=?,lease_until=?,lease_fence=lease_fence+1 WHERE root_id=?").run(this.owner, now + this.leaseMs, root);
      return this.row(root);
    });
  }
  private lease(row: Row) {
    this.authorize(); const current = this.row(row.root_id);
    requireThat(current.mode === "active" && current.revision === row.revision && current.lease_owner === this.owner
      && current.lease_fence === row.lease_fence && current.lease_until > this.kernel.db.now(), "topology_schedule_lease_changed");
  }
  private async advance(row: Row): Promise<number> {
    let steps = 0;
    try {
      for (; steps < this.maxSteps;) {
        this.lease(row); const root = this.kernel.inspect(this.actor, row.root_id);
        if (terminal.has(root.task.status)) {
          this.kernel.db.transaction(() => { this.lease(row); this.set(row, root.task.status === "done" ? "completed" : root.task.status as "failed" | "cancelled", null); });
          break;
        }
        let progress = false;
        for (const node of this.plan(row).nodes) {
          this.lease(row);
          let action: Action | null;
          try { action = this.action(row, node); }
          catch (error) { throw error instanceof ScheduleBlocked ? error : new ScheduleBlocked({ code: error instanceof RuntimeConflict ? error.code : "topology_schedule_step_failed", node_id: node.task_id }); }
          if (!action) continue;
          if (action.terminal && this.kernel.inspect(this.actor, node.task_id).task.completion_requirements) {
            requireThat(this.gate, "topology_artifact_gate_required");
            await this.gate.prepare(this.actor, node.task_id, action.parent_revision, action.topology_revision);
          }
          this.kernel.db.transaction(() => {
            this.lease(row); this.kernel.scheduledTransition(this.actor, action!.run);
            this.kernel.db.sql.query("UPDATE topology_schedules SET revision=revision+1,lease_until=? WHERE root_id=?")
              .run(this.kernel.db.now() + this.leaseMs, row.root_id);
            row.revision++; row.lease_until = this.kernel.db.now() + this.leaseMs;
          });
          progress = true; steps++; if (steps >= this.maxSteps) break;
        }
        if (!progress) break;
      }
    } catch (error) {
      if (this.stopping) return steps;
      // A pause, replacement owner or revoked host configuration wins over this observer.
      this.kernel.db.transaction(() => {
        const current = this.row(row.root_id);
        if (current.mode !== "active" || current.revision !== row.revision || current.lease_owner !== this.owner || current.lease_fence !== row.lease_fence) return;
        this.set(current, "blocked", error instanceof ScheduleBlocked ? error.reason : { code: error instanceof RuntimeConflict ? error.code : "topology_schedule_step_failed" });
      });
    } finally {
      this.kernel.db.sql.query("UPDATE topology_schedules SET lease_owner=NULL,lease_until=0 WHERE root_id=? AND lease_owner=? AND lease_fence=?")
        .run(row.root_id, this.owner, row.lease_fence);
    }
    return steps;
  }
  tick(): Promise<number> {
    this.authorize();
    if (this.ticking) return this.ticking;
    const pass = async () => {
      let count = 0;
      const rows = this.kernel.db.sql.query("SELECT root_id FROM topology_schedules WHERE principal=? AND device_id=? AND origin=? AND mode='active' ORDER BY rowid LIMIT 32")
        .all(this.actor.id, this.actor.device_id!, this.actor.origin) as { root_id: string }[];
      for (const item of rows) { const row = this.acquire(item.root_id); if (row) count += await this.advance(row); }
      if (!this.draining && !this.stopping) {
        this.draining = this.runtime.drain().catch(error => { this.error = error instanceof RuntimeConflict ? error.code : "topology_native_drain_failed"; }).finally(() => { this.draining = undefined; });
      }
      return count;
    };
    this.ticking = pass().finally(() => { this.ticking = undefined; }); return this.ticking;
  }
  start() {
    this.authorize();
    if (!this.timer) {
      const tick = () => { try { void this.tick().catch(error => { this.error = error instanceof RuntimeConflict ? error.code : "topology_scheduler_failed"; }); }
        catch (error) { this.error = error instanceof RuntimeConflict ? error.code : "topology_scheduler_failed"; } };
      this.timer = setInterval(tick, this.interval); tick();
    }
    return this.status();
  }
  status() { return { running: !!this.timer, stopping: this.stopping, error: this.error }; }
  async drain() {
    for (let i = 0; i < 256; i++) {
      const changes = await this.tick(); await this.draining;
      if (this.runtime.topologySource === "device" && changes === 0) return;
      if (!changes && this.runtime.queueStatus().queued === 0 && this.runtime.queueStatus().running === 0) {
        // One final pass observes native completion or a retained preflight block.
        if (await this.tick() === 0) return;
        await this.draining;
      }
    }
    throw new RuntimeConflict("topology_schedule_drain_budget");
  }
  async stop() {
    this.stopping = true; if (this.timer) clearInterval(this.timer); this.timer = undefined;
    await this.ticking;
  }
}
