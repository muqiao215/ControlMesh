import { command, commandReceipt, requireScope } from "./commands";
import { RuntimeDatabase } from "./database";
import { HostJobStore } from "./host-job-store";
import type { Principal } from "./kernel";
import { canonical, digest, identifier, object, requireThat } from "./value";

export interface HostJobApproval {
  schema_version: "controlmesh.host_job_approval.v1";
  request_id: string; principal: string; device_id: string | null;
  job_id: string; revision: number; step_id: string; definition_digest: string;
  approved_at: string;
  plan_request_id?: string; plan_step_index?: number;
}
export interface HostJobPlanApproval {
  schema_version: "controlmesh.host_job_plan_approval.v1";
  request_id: string; principal: string; device_id: string | null; job_id: string; revision: number; approved_at: string;
  steps: { job_id: string; revision: number; step_id: string; definition_digest: string }[];
}
/** Persisted human decision only; dispatch still requires current execution grants and a kernel lease. */
export class HostJobApprovals {
  constructor(private readonly db: RuntimeDatabase, private readonly authorize: () => void) {}
  private current(actor: Principal, scope: string) {
    requireScope(actor, scope); const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private binding(actor: Principal, jobId: string, revision: number, stepId: string) {
    identifier(jobId); identifier(stepId);
    const snapshot = new HostJobStore(this.db, this.authorize).get(actor, jobId);
    requireThat(snapshot && Number.isSafeInteger(revision) && snapshot.revision === revision, "host_job_revision_conflict");
    const job = snapshot.job;
    requireThat(!["completed", "failed", "cancelled"].includes(job.state), "host_job_terminal");
    requireThat(!job.steps.some(step => ["failed", "cancelled"].includes(step.state)), "host_job_failed_dependency");
    const step = job.steps.find(step => !["completed", "skipped"].includes(step.state));
    requireThat(step?.id === stepId, "host_job_step_not_next");
    requireThat(["pending", "awaiting_approval"].includes(step.state), "host_job_reconciliation_required");
    return { job_id: jobId, revision, step_id: stepId,
      definition_digest: digest({ repo: job.repo, source_task_id: job.source_task_id, plan_id: job.plan_id,
        command_digest: step.command_digest, cwd: step.cwd, kind: step.kind, approval_required: step.approval_required, side_effect: step.side_effect }) };
  }
  approve(actor: Principal, requestId: string, jobId: string, revision: number, stepId: string): HostJobApproval {
    this.current(actor, "task:admin"); requireThat(actor.origin === "human_request", "host_job_human_approval_required");
    const binding = this.binding(actor, jobId, revision, stepId);
    return command(this.db, actor, requestId, "host_job.approve_step", binding, () => {
      this.current(actor, "task:admin");
      requireThat(canonical(this.binding(actor, jobId, revision, stepId)) === canonical(binding), "host_job_approval_binding_changed");
      return { schema_version: "controlmesh.host_job_approval.v1", request_id: requestId, principal: actor.id, device_id: actor.device_id ?? null,
        ...binding, approved_at: new Date(this.db.now()).toISOString() };
    }, value => { this.current(actor, "task:admin"); return value; });
  }
  /** Explicit authorization of the remaining fixed graph, not a request to start it. */
  approvePlan(actor: Principal, requestId: string, jobId: string, revision: number): HostJobPlanApproval {
    this.current(actor, "task:admin"); requireThat(actor.origin === "human_request", "host_job_human_approval_required");
    return command(this.db, actor, requestId, "host_job.approve_plan", { job_id: jobId, revision }, () => {
      this.current(actor, "task:admin");
      const saved = new HostJobStore(this.db, this.authorize).get(actor, jobId);
      requireThat(saved?.revision === revision, "host_job_revision_conflict");
      const pending = saved.job.steps.filter(step => !["completed", "skipped"].includes(step.state));
      requireThat(pending.length > 0 && pending.every(step => ["pending", "awaiting_approval"].includes(step.state)), "host_job_plan_not_pending");
      this.binding(actor, jobId, revision, pending[0]!.id);
      // Each accepted step consumes one running and one terminal HostJob revision.
      const steps = pending.map((step, index) => ({ job_id: jobId, revision: revision + 2 * index, step_id: step.id,
        definition_digest: digest({ repo: saved.job.repo, source_task_id: saved.job.source_task_id, plan_id: saved.job.plan_id,
          command_digest: step.command_digest, cwd: step.cwd, kind: step.kind, approval_required: step.approval_required, side_effect: step.side_effect }) }));
      requireThat(steps.every(step => Number.isSafeInteger(step.revision)), "invalid_host_job_revision");
      return { schema_version: "controlmesh.host_job_plan_approval.v1", request_id: requestId, principal: actor.id,
        device_id: actor.device_id ?? null, job_id: jobId, revision, approved_at: new Date(this.db.now()).toISOString(), steps };
    }, value => { this.current(actor, "task:admin"); return value; });
  }
  inspectPlan(actor: Principal, raw: unknown): HostJobPlanApproval {
    this.current(actor, "task:read");
    requireThat(object(raw) && raw.schema_version === "controlmesh.host_job_plan_approval.v1" && raw.principal === actor.id
      && (raw.device_id === null || typeof raw.device_id === "string"), "invalid_host_job_plan_approval");
    identifier(raw.request_id); identifier(raw.job_id);
    requireThat(Number.isSafeInteger(raw.revision) && Number(raw.revision) > 0, "invalid_host_job_plan_approval");
    const issuer: Principal = { ...actor, origin: "human_request", device_id: raw.device_id === null ? undefined : raw.device_id as string };
    const stored = commandReceipt<HostJobPlanApproval>(this.db, issuer, raw.request_id, "host_job.approve_plan", { job_id: raw.job_id, revision: raw.revision });
    requireThat(stored && canonical(stored.value) === canonical(raw), "host_job_plan_approval_unproven");
    return structuredClone(stored.value);
  }
  planStep(actor: Principal, raw: unknown, index: number): HostJobApproval {
    const plan = this.inspectPlan(actor, raw);
    requireThat(Number.isSafeInteger(index) && index >= 0 && index < plan.steps.length, "invalid_host_job_plan_step");
    return { schema_version: "controlmesh.host_job_approval.v1", request_id: plan.request_id, principal: plan.principal,
      device_id: plan.device_id, ...plan.steps[index]!, approved_at: plan.approved_at, plan_request_id: plan.request_id, plan_step_index: index };
  }
  /** Historical receipt inspection grants no execution permission. */
  inspectReceipt(actor: Principal, raw: unknown): HostJobApproval {
    this.current(actor, "task:read");
    requireThat(object(raw) && raw.schema_version === "controlmesh.host_job_approval.v1" && raw.principal === actor.id
      && (raw.device_id === null || typeof raw.device_id === "string"), "invalid_host_job_approval");
    identifier(raw.request_id); identifier(raw.job_id); identifier(raw.step_id);
    requireThat(Number.isSafeInteger(raw.revision) && Number(raw.revision) > 0 && typeof raw.definition_digest === "string"
      && /^[a-f0-9]{64}$/.test(raw.definition_digest), "invalid_host_job_approval");
    if (raw.plan_request_id !== undefined) {
      identifier(raw.plan_request_id);
      const saved = this.db.sql.query("SELECT response FROM receipts WHERE principal=? AND request_id=?").get(actor.id, raw.plan_request_id) as { response: string } | null;
      requireThat(saved, "host_job_plan_approval_unproven");
      const derived = this.planStep(actor, JSON.parse(saved.response), raw.plan_step_index as number);
      requireThat(canonical(derived) === canonical(raw), "host_job_plan_approval_unproven");
      return derived;
    }
    const binding = { job_id: raw.job_id, revision: raw.revision, step_id: raw.step_id, definition_digest: raw.definition_digest };
    const issuer: Principal = { ...actor, origin: "human_request", ...(raw.device_id === null ? { device_id: undefined } : { device_id: raw.device_id as string }) };
    const stored = commandReceipt<HostJobApproval>(this.db, issuer, raw.request_id, "host_job.approve_step", binding);
    requireThat(stored && canonical(stored.value) === canonical(raw), "host_job_approval_unproven");
    return structuredClone(stored.value);
  }
  assertApproved(actor: Principal, raw: unknown): HostJobApproval {
    this.current(actor, "task:execute");
    const proof = this.inspectReceipt(actor, raw);
    const binding = this.binding(actor, proof.job_id, proof.revision, proof.step_id);
    requireThat(proof.definition_digest === binding.definition_digest, "host_job_approval_binding_changed");
    return proof;
  }
}
