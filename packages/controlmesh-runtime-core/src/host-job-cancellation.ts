import { HostJobApprovals } from "./host-job-approval";
import { HostJobStore } from "./host-job-store";
import type { Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, object, requireThat } from "./value";

/** Projection of an already cancelled task; never starts a process or confirms side effects. */
export function recoverHostCancellation(kernel: RuntimeKernel, actor: Principal, taskId: string, authorize: () => void): boolean {
  return kernel.db.transaction(() => {
    const checked: unknown = authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    const task = kernel.inspect(actor, taskId);
    if (task.task.status !== "cancelled" || task.task.provider !== "host" || !object(task.task.host_job)) return false;
    const binding = task.task.host_job;
    const rows = kernel.db.sql.query(`SELECT e.effect_id,e.result,m.payload AS manifest,m.digest AS manifest_digest,
      o.payload AS observation,o.digest AS observation_digest FROM effects e
      JOIN episodes p ON p.episode_id=e.episode_id AND p.task_id=e.task_id AND p.fence=e.fence
      JOIN execution_manifests m ON m.effect_id=e.effect_id JOIN effect_observations o ON o.effect_id=e.effect_id
      WHERE e.task_id=? AND e.fence=? AND e.state='unknown' AND p.state='cancelled'`).all(taskId, task.fence - 1) as
      { effect_id: string; result: string; manifest: string; manifest_digest: string; observation: string; observation_digest: string }[];
    if (rows.length !== 1) return false;
    const row = rows[0]!, manifest = JSON.parse(row.manifest), outcome = JSON.parse(row.observation);
    requireThat(object(manifest) && digest(manifest) === row.manifest_digest && object(outcome) && digest(outcome) === row.observation_digest
      && row.result === row.observation && manifest.schema_version === "controlmesh.host_step_execution.v1", "host_job_cancellation_evidence_changed");
    if (!["cancelled", "authority_lost", "exited"].includes(String(outcome.reason))) return false;
    const approval = new HostJobApprovals(kernel.db, authorize).inspectReceipt(actor, manifest.approval);
    requireThat(binding.job_id === approval.job_id && binding.step_id === approval.step_id && binding.revision === approval.revision
      && canonical(binding.approval) === canonical(approval), "host_job_cancellation_binding_changed");
    const store = new HostJobStore(kernel.db, authorize), saved = store.get(actor, approval.job_id);
    if (!saved || saved.job.state === "cancelled") return false;
    requireThat(saved.revision === manifest.running_revision && saved.revision === approval.revision + 1
      && canonical(saved.job) === canonical(manifest.job), "host_job_cancellation_binding_changed");
    const step = saved.job.steps.find(item => item.id === approval.step_id);
    requireThat(step?.state === "running", "host_job_cancellation_binding_changed");
    const finished = new Date(kernel.db.now()).toISOString();
    store.put(actor, `host-cancel-recover-${digest([taskId, row.effect_id, row.observation_digest])}`, saved.revision,
      { ...saved.job, state: "cancelled", updated_at: finished, completed_at: finished,
        steps: saved.job.steps.map(item => item.id === step.id ? { ...item, state: "cancelled", detail: "cancelled",
          exit_code: outcome.exit_code, finished_at: finished, completed_at: finished } : item) });
    return true;
  });
}
