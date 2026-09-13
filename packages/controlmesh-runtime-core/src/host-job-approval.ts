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
  assertApproved(actor: Principal, raw: unknown): HostJobApproval {
    this.current(actor, "task:execute");
    requireThat(object(raw) && raw.schema_version === "controlmesh.host_job_approval.v1" && raw.principal === actor.id
      && (raw.device_id === null || typeof raw.device_id === "string"), "invalid_host_job_approval");
    identifier(raw.request_id); identifier(raw.job_id); identifier(raw.step_id);
    const binding = this.binding(actor, raw.job_id, raw.revision as number, raw.step_id);
    requireThat(raw.definition_digest === binding.definition_digest, "host_job_approval_binding_changed");
    const issuer: Principal = { ...actor, origin: "human_request", ...(raw.device_id === null ? { device_id: undefined } : { device_id: raw.device_id as string }) };
    const stored = commandReceipt<HostJobApproval>(this.db, issuer, raw.request_id, "host_job.approve_step", binding);
    requireThat(stored && canonical(stored.value) === canonical(raw), "host_job_approval_unproven");
    return structuredClone(stored.value);
  }
}
