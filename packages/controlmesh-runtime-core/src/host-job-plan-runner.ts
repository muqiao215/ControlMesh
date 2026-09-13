import { command, commandReceipt, requireScope } from "./commands";
import { HostJobApprovals, type HostJobApproval, type HostJobPlanApproval } from "./host-job-approval";
import { HostJobStore } from "./host-job-store";
import type { Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";
export interface HostPlanRun {
  schema_version: "controlmesh.host_plan_run.v1"; run_id: string; principal: string; device_id: string;
  workspace: string; job_id: string; revision: number; plan: HostJobPlanApproval;
}
export const hostStepTaskId = (principal: string, proof: HostJobApproval) => `host-step-${digest([principal, proof.job_id, proof.revision, proof.step_id]).slice(0, 40)}`;
/** Immutable run intent is a command receipt; job/task/effect state owns progress. */
export class HostJobPlanRunner {
  constructor(private readonly kernel: RuntimeKernel, private readonly actor: Principal, private readonly workspace: string,
    private readonly authorize: () => void, private readonly start: (requestId: string, proof: HostJobApproval) => unknown) {}
  private current() {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireScope(this.actor, "task:read");
  }
  register(requestId: string, jobId: string, revision: number): HostPlanRun {
    this.current(); requireScope(this.actor, "task:admin"); requireScope(this.actor, "task:create"); requireScope(this.actor, "task:execute");
    requireThat(this.actor.origin === "human_request", "host_job_human_approval_required");
    return command(this.kernel.db, this.actor, requestId, "local.run_host_job", { job_id: jobId, revision, workspace: this.workspace }, () => {
      const job = new HostJobStore(this.kernel.db, this.authorize).get(this.actor, jobId);
      requireThat(job?.job.repo === this.workspace, "host_job_workspace_mismatch");
      const plan = new HostJobApprovals(this.kernel.db, this.authorize).approvePlan(this.actor, `host-run-approval-${digest(requestId)}`, jobId, revision);
      return { schema_version: "controlmesh.host_plan_run.v1", run_id: requestId, principal: this.actor.id, device_id: this.actor.device_id!, workspace: this.workspace, job_id: jobId, revision, plan };
    }, value => { this.current(); return value; });
  }
  private read(runId: string): HostPlanRun {
    this.current(); identifier(runId);
    const row = this.kernel.db.sql.query("SELECT response FROM receipts WHERE principal=? AND request_id=?").get(this.actor.id, runId) as { response: string } | null;
    requireThat(row, "host_plan_not_found"); const run = JSON.parse(row.response);
    requireThat(object(run) && run.schema_version === "controlmesh.host_plan_run.v1" && run.run_id === runId
      && run.principal === this.actor.id && run.device_id === this.actor.device_id && run.workspace === this.workspace, "host_plan_binding_changed");
    const stored = commandReceipt<HostPlanRun>(this.kernel.db, this.actor, runId, "local.run_host_job", { job_id: run.job_id, revision: run.revision, workspace: this.workspace });
    requireThat(stored && canonical(stored.value) === canonical(run), "host_plan_unproven");
    new HostJobApprovals(this.kernel.db, this.authorize).inspectPlan(this.actor, stored.value.plan);
    return stored.value;
  }
  private successful(proof: HostJobApproval): boolean {
    const taskId = hostStepTaskId(this.actor.id, proof);
    const row = this.kernel.db.sql.query(`SELECT t.raw,t.status,t.needs_reconciliation,e.result,m.payload AS manifest,m.digest AS manifest_digest,
      o.payload AS observation,o.digest AS observation_digest FROM tasks t JOIN effects e ON e.task_id=t.task_id AND e.fence=t.fence
      JOIN episodes p ON p.episode_id=e.episode_id AND p.state='done'
      JOIN execution_manifests m ON m.effect_id=e.effect_id JOIN effect_observations o ON o.effect_id=e.effect_id
      WHERE t.task_id=? AND t.principal=? AND e.state='confirmed'`).get(taskId, this.actor.id) as
      { raw: string; status: string; needs_reconciliation: number; result: string; manifest: string; manifest_digest: string; observation: string; observation_digest: string } | null;
    if (!row || row.status !== "done" || row.needs_reconciliation) return false;
    const raw = JSON.parse(row.raw), manifest = JSON.parse(row.manifest), observation = JSON.parse(row.observation), result = JSON.parse(row.result);
    return raw.provider === "host" && canonical(raw.host_job?.approval) === canonical(proof)
      && manifest.schema_version === "controlmesh.host_step_execution.v1" && canonical(manifest.approval) === canonical(proof)
      && digest(manifest) === row.manifest_digest && digest(observation) === row.observation_digest
      && observation.reason === "exited" && observation.exit_code === 0 && result.exit_code === 0
      && result.host_job_id === proof.job_id && result.step_id === proof.step_id && result.host_job_revision === proof.revision + 2
      && result.observation_digest === row.observation_digest;
  }
  inspect(runId: string) {
    const run = this.read(runId), job = new HostJobStore(this.kernel.db, this.authorize).get(this.actor, run.job_id)!;
    const summary = { run_id: runId, job_id: run.job_id, job_revision: job.revision, total_steps: run.plan.steps.length };
    if (["failed", "cancelled"].includes(job.job.state)) return { ...summary, state: job.job.state, reason: "host_job_terminal", next_step: null };
    const approvals = new HostJobApprovals(this.kernel.db, this.authorize);
    for (let index = 0; index < run.plan.steps.length; index++) {
      const proof = approvals.planStep(this.actor, run.plan, index), step = job.job.steps.find(item => item.id === proof.step_id);
      if (step?.state === "completed") {
        if (!this.successful(proof)) return { ...summary, state: "blocked", reason: "host_plan_predecessor_unproven", next_step: proof.step_id };
        continue;
      }
      const taskId = hostStepTaskId(this.actor.id, proof);
      const existing = this.kernel.db.sql.query("SELECT status FROM tasks WHERE task_id=? AND principal=?").get(taskId, this.actor.id) as { status: string } | null;
      if (existing) return { ...summary, state: existing.status === "running" ? "running" : "waiting", reason: "existing_step_task", next_step: proof.step_id, task_id: taskId };
      if (job.revision !== proof.revision) return { ...summary, state: "blocked", reason: "host_plan_revision_changed", next_step: proof.step_id };
      return { ...summary, state: "ready", reason: "approved_next_step", next_step: proof.step_id, step_index: index };
    }
    return { ...summary, state: job.job.state === "completed" ? "completed" : "blocked", reason: job.job.state === "completed" ? "all_steps_confirmed" : "host_plan_terminal_unproven", next_step: null };
  }
  advance(after = "", approvalId?: string): string {
    this.current();
    const rows = this.kernel.db.sql.query(`SELECT r.request_id FROM receipts r JOIN host_jobs j ON j.principal=r.principal AND j.job_id=json_extract(r.response,'$.job_id')
      WHERE r.principal=? AND json_extract(r.response,'$.schema_version')='controlmesh.host_plan_run.v1'
      AND json_extract(r.response,'$.device_id')=? AND (? IS NULL OR json_extract(r.response,'$.plan.request_id')=?) AND j.state NOT IN ('completed','failed','cancelled') AND r.request_id>?
      ORDER BY r.request_id LIMIT 128`).all(this.actor.id, this.actor.device_id!, approvalId ?? null, approvalId ?? null, after) as { request_id: string }[];
    for (const row of rows) {
      try { this.kernel.db.transaction(() => {
        const status = this.inspect(row.request_id); if (status.state !== "ready" || !("step_index" in status)) return;
        const run = this.read(row.request_id), proof = new HostJobApprovals(this.kernel.db, this.authorize).planStep(this.actor, run.plan, status.step_index!);
        this.start(`host-plan-start-${digest([row.request_id, proof.step_id])}`, proof);
        const taskId = hostStepTaskId(this.actor.id, proof), task = this.kernel.inspect(this.actor, taskId);
        this.kernel.db.sql.query("INSERT INTO events (task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,'host.plan.step_enqueued',?,?,?,'internal',?,?)")
          .run(taskId, task.revision, task.fence, this.actor.id, this.kernel.db.now(), canonical({ plan_run_id: row.request_id, approval_request_id: proof.plan_request_id, step_index: proof.plan_step_index }));
      }); } catch (error) { if (!(error instanceof RuntimeConflict) || error.code !== "local_queue_full") throw error; return after; }
    }
    return rows.length === 128 ? rows.at(-1)!.request_id : "";
  }
}
