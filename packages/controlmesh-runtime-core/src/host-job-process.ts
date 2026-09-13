import { decodeHostJob } from "./host-job-model";
import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import { HostJobApprovals } from "./host-job-approval";
import { HostJobStore } from "./host-job-store";
import { RuntimeKernel, type Principal, type Lease, type ReconciliationBinding } from "./kernel";
import { ProcessSupervisor, type ProcessAdmission } from "./process-supervisor";
import { decodeToolGrant, restrictiveGrant } from "./execution-grants";
import { enforceLocalReadSource } from "./execution-policy";
import { directoryIdentity } from "./providers/native-manifest";
import { canonical, digest, object, requireThat } from "./value";

/** Single local-foreground step. Container/source variants and retained-result recovery are separate owners. */
export class HostJobProcess {
  private readonly actor: Principal;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, private readonly workspace: string,
    private readonly shell: string, private readonly authorize: () => void) { this.actor = structuredClone(actor); }
  async execute(lease: Lease, admission: ProcessAdmission) {
    const actor = this.actor, task = this.kernel.inspect(actor, lease.task_id).task;
    requireThat(object(task.host_job) && task.provider === "host", "host_job_task_binding_required");
    const binding = structuredClone(task.host_job);
    const context = enforceLocalReadSource(task.execution_context), grant = decodeToolGrant(task.tool_grant);
    requireThat(!restrictiveGrant(grant) && grant.confirmation_policy === "provider_runtime", "host_job_grant_unenforceable");
    const workspace = directoryIdentity(this.workspace);
    requireThat(isAbsolute(this.shell) && realpathSync(this.shell) === this.shell, "host_job_shell_not_canonical");
    const shellIdentity = () => { const s = statSync(this.shell, { bigint: true }); requireThat(s.isFile() && (s.mode & 0o111n) !== 0n, "host_job_shell_invalid"); return digest([s.dev,s.ino,s.size,s.mtimeNs,s.ctimeNs].map(String)); };
    const shell = shellIdentity(), store = new HostJobStore(this.kernel.db, this.authorize);
    const approval = new HostJobApprovals(this.kernel.db, this.authorize).assertApproved(actor, binding.approval);
    requireThat(binding.job_id === approval.job_id && binding.revision === approval.revision && binding.step_id === approval.step_id, "host_job_task_binding_changed");
    const initial = store.get(actor, approval.job_id)!;
    const step = initial.job.steps.find(step => step.id === approval.step_id)!;
    requireThat((step.cwd || initial.job.repo) === workspace.path && initial.job.repo === workspace.path, "host_job_workspace_mismatch");
    const effect = `host-${digest([lease.episode_id, approval.job_id, approval.step_id])}`;
    let runningRevision = initial.revision, dispatched = false;
    const guard = () => {
      const checked: unknown = this.authorize();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      admission.assertCurrent(); this.kernel.withLease(actor, lease, () => {});
      requireThat(digest(directoryIdentity(this.workspace)) === digest(workspace) && shellIdentity() === shell, "host_job_execution_configuration_changed");
      const current = this.kernel.inspect(actor, lease.task_id).task;
      requireThat(canonical(current.host_job) === canonical(binding) && canonical(current.execution_context) === canonical(context)
        && canonical(current.tool_grant) === canonical(grant), "host_job_task_binding_changed");
      requireThat(store.get(actor, approval.job_id)?.revision === runningRevision, "host_job_revision_conflict");
    };
    this.kernel.db.transaction(() => {
      guard();
      this.kernel.start(actor, `${effect}-start`, lease);
      const started = new Date(this.kernel.db.now()).toISOString();
      const running = store.put(actor, `${effect}-running`, initial.revision, { ...initial.job, state: "running", current_step_id: step.id, updated_at: started,
        steps: initial.job.steps.map(item => item.id === step.id ? { ...item, state: "running", started_at: started, pid: null, pgid: null } : item) });
      runningRevision = running.revision;
      const permit = this.kernel.dispatchEffect(actor, `${effect}-dispatch`, lease, effect, { job_id: approval.job_id, step_id: step.id, command_digest: step.command_digest },
        { schema_version: "controlmesh.host_step_execution.v1", approval, workspace, shell, running_revision: runningRevision, job: running.job });
      requireThat(permit.dispatch_permitted, "host_job_dispatch_already_attempted"); dispatched = true;
    });
    try {
      const outcome = await new ProcessSupervisor().run({ command: [this.shell, "--noprofile", "--norc", "-c", step.command], cwd: workspace.path,
        env: { PATH: "/usr/bin:/bin", LANG: "C.UTF-8" }, timeout_ms: 300000, max_output_bytes: 262144 }, { ...admission, assertCurrent: guard });
      // Retain the owned process outcome even after lease loss; it cannot authorize completion alone.
      this.kernel.db.transaction(() => {
        const changed = this.kernel.db.sql.query("UPDATE effects SET result=? WHERE effect_id=? AND task_id=? AND episode_id=? AND fence=? AND state='dispatched' AND result IS NULL")
          .run(canonical(outcome), effect, lease.task_id, lease.episode_id, lease.fence);
        requireThat(changed.changes === 1, "host_job_outcome_retention_conflict");
        this.kernel.db.sql.query("INSERT INTO effect_observations VALUES(?,?,?)").run(effect, digest(outcome), canonical(outcome));
      });
      guard(); requireThat(outcome.reason === "exited" && outcome.exit_code !== null, "host_job_outcome_uncertain");
      return this.kernel.db.transaction(() => {
        guard(); const current = store.get(actor, approval.job_id)!, finished = new Date(this.kernel.db.now()).toISOString();
        const success = outcome.exit_code === 0;
        const steps = current.job.steps.map(item => item.id === step.id ? { ...item, state: success ? "completed" : "failed", exit_code: outcome.exit_code, finished_at: finished, completed_at: finished } : item);
        const done = steps.every(item => ["completed", "skipped"].includes(item.state));
        const saved = store.put(actor, `${effect}-result`, runningRevision, { ...current.job, steps, state: !success ? "failed" : done ? "completed" : current.job.state,
          updated_at: finished, completed_at: done || !success ? finished : "" });
        const result = { host_job_id: approval.job_id, step_id: step.id, host_job_revision: saved.revision, exit_code: outcome.exit_code, observation_digest: digest(outcome) };
        this.kernel.confirmEffect(actor, `${effect}-confirm`, lease, effect, result);
        return this.kernel.finish(actor, `${effect}-finish`, lease, success ? "done" : "failed", result);
      });
    } catch (error) {
      if (dispatched) { try { this.kernel.markUnknown(actor, `${effect}-unknown`, lease, "host_job_outcome_unproven"); } catch { /* cancellation/lease recovery retains the pending effect */ } }
      throw error;
    }
  }
  reconcile(requestId: string, taskId: string, expectedRevision: number, binding: ReconciliationBinding) {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    const actor = this.actor;
    const replay = this.kernel.reconciliationReceipt(actor, requestId, taskId, expectedRevision, binding);
    if (replay) return replay;
    return this.kernel.reconcileEffect(actor, requestId, taskId, expectedRevision, binding, evidence => {
      const manifest = evidence.manifest, outcome = evidence.observation;
      requireThat(manifest.schema_version === "controlmesh.host_step_execution.v1", "host_job_manifest_unproven");
      const approval = new HostJobApprovals(this.kernel.db, this.authorize).inspectReceipt(actor, manifest.approval);
      const task = evidence.task.task;
      requireThat(task.provider === "host" && object(task.host_job) && task.host_job.job_id === approval.job_id
        && task.host_job.step_id === approval.step_id && task.host_job.revision === approval.revision
        && canonical(task.host_job.approval) === canonical(approval), "host_job_task_binding_changed");
      enforceLocalReadSource(task.execution_context);
      const grant = decodeToolGrant(task.tool_grant);
      requireThat(!restrictiveGrant(grant) && grant.confirmation_policy === "provider_runtime", "host_job_grant_unenforceable");
      requireThat(canonical(directoryIdentity(this.workspace)) === canonical(manifest.workspace), "host_job_execution_configuration_changed");
      requireThat(isAbsolute(this.shell) && realpathSync(this.shell) === this.shell, "host_job_shell_not_canonical");
      const stat = statSync(this.shell, { bigint: true });
      requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n
        && digest([stat.dev,stat.ino,stat.size,stat.mtimeNs,stat.ctimeNs].map(String)) === manifest.shell, "host_job_execution_configuration_changed");
      const running = decodeHostJob(manifest.job), step = running.steps.find(item => item.id === approval.step_id);
      requireThat(running.job_id === approval.job_id && step?.state === "running" && running.repo === this.workspace
        && (step.cwd || running.repo) === this.workspace && manifest.running_revision === approval.revision + 1, "host_job_manifest_unproven");
      requireThat(digest({ repo: running.repo, source_task_id: running.source_task_id, plan_id: running.plan_id,
        command_digest: step.command_digest, cwd: step.cwd, kind: step.kind, approval_required: step.approval_required, side_effect: step.side_effect }) === approval.definition_digest, "host_job_approval_binding_changed");
      const store = new HostJobStore(this.kernel.db, this.authorize), current = store.get(actor, approval.job_id);
      requireThat(current?.revision === manifest.running_revision && canonical(current.job) === canonical(running), "host_job_recovery_binding_changed");
      requireThat(outcome.reason === "exited" && Number.isSafeInteger(outcome.exit_code) && Number(outcome.exit_code) >= 0 && Number(outcome.exit_code) <= 255
        && typeof outcome.stdout === "string" && typeof outcome.stderr === "string"
        && Buffer.byteLength(outcome.stdout) + Buffer.byteLength(outcome.stderr) <= 524288, "host_job_outcome_unproven");
      const success = outcome.exit_code === 0, finished = new Date(this.kernel.db.now()).toISOString();
      const steps = running.steps.map(item => item.id === step.id ? { ...item, state: success ? "completed" : "failed", exit_code: outcome.exit_code, finished_at: finished, completed_at: finished } : item);
      const done = steps.every(item => ["completed", "skipped"].includes(item.state));
      const saved = store.put(actor, `host-recover-${digest([requestId, binding])}`, current.revision, { ...running, steps,
        state: !success ? "failed" : done ? "completed" : running.state, updated_at: finished, completed_at: done || !success ? finished : "" });
      return { host_job_id: approval.job_id, step_id: step.id, host_job_revision: saved.revision, exit_code: outcome.exit_code, observation_digest: evidence.observation_digest };
    });
  }

}
