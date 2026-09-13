import { appendHostLog } from "./host-job-log";
import { SpecMeshPort, type SpecMeshObservation } from "./specmesh-port";
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

/** Approved local-foreground step with retained-result recovery and optional independent workflow checks. */
export class HostJobProcess {
  private readonly actor: Principal;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, private readonly workspace: string,
    private readonly shell: string, private readonly authorize: () => void, private readonly workflow?: SpecMeshPort) { this.actor = structuredClone(actor); }
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
      this.workflow?.assertCurrent();
      admission.assertCurrent(); this.kernel.withLease(actor, lease, () => {});
      requireThat(digest(directoryIdentity(this.workspace)) === digest(workspace) && shellIdentity() === shell, "host_job_execution_configuration_changed");
      const current = this.kernel.inspect(actor, lease.task_id).task;
      requireThat(canonical(current.host_job) === canonical(binding) && canonical(current.execution_context) === canonical(context)
        && canonical(current.tool_grant) === canonical(grant), "host_job_task_binding_changed");
      requireThat(store.get(actor, approval.job_id)?.revision === runningRevision, "host_job_revision_conflict");
    };
    const workflowStart = this.workflow ? await this.workflow.inspect("check", admission) : undefined;
    if (workflowStart) requireThat(workflowStart.result.status === "pass", "specmesh_start_gate_blocked");
    this.kernel.db.transaction(() => {
      guard(); workflowStart?.assertCurrent();
      this.kernel.start(actor, `${effect}-start`, lease);
      const started = new Date(this.kernel.db.now()).toISOString();
      const running = store.put(actor, `${effect}-running`, initial.revision, { ...initial.job, state: "running", current_step_id: step.id, updated_at: started,
        steps: initial.job.steps.map(item => item.id === step.id ? { ...item, state: "running", started_at: started, pid: null, pgid: null } : item) });
      runningRevision = running.revision;
      const permit = this.kernel.dispatchEffect(actor, `${effect}-dispatch`, lease, effect, { job_id: approval.job_id, step_id: step.id, command_digest: step.command_digest },
        { schema_version: "controlmesh.host_step_execution.v1", approval, workspace, shell, running_revision: runningRevision, job: running.job, workflow: this.workflow ? { binding_digest: this.workflow.binding_digest, start_snapshot_digest: workflowStart!.snapshot_digest } : null });
      requireThat(permit.dispatch_permitted, "host_job_dispatch_already_attempted"); dispatched = true;
    });
    try {
      const outcome = await new ProcessSupervisor().run({ command: [this.shell, "--noprofile", "--norc", "-c", step.command], cwd: workspace.path,
        env: { PATH: "/usr/bin:/bin", LANG: "C.UTF-8" }, timeout_ms: 300000, max_output_bytes: 262144 }, { ...admission, assertCurrent: guard, onOutput: (stream, text) => appendHostLog(this.kernel, actor, lease, effect, stream, text) });
      // Retain the owned process outcome even after lease loss; it cannot authorize completion alone.
      this.kernel.db.transaction(() => {
        const changed = this.kernel.db.sql.query("UPDATE effects SET result=? WHERE effect_id=? AND task_id=? AND episode_id=? AND fence=? AND state IN ('dispatched','unknown') AND result IS NULL")
          .run(canonical(outcome), effect, lease.task_id, lease.episode_id, lease.fence);
        requireThat(changed.changes === 1, "host_job_outcome_retention_conflict");
        this.kernel.db.sql.query("INSERT INTO effect_observations VALUES(?,?,?)").run(effect, digest(outcome), canonical(outcome));
      });
      // Cancellation revokes the lease before the supervised process reports its end.
      // Record cancellation only for that same task/episode and the unchanged running job.
      const cancelled = this.kernel.inspect(actor, lease.task_id);
      if (cancelled.task.status === "cancelled" && ["cancelled", "authority_lost", "exited"].includes(outcome.reason)) {
        this.kernel.db.transaction(() => {
          const current = this.kernel.inspect(actor, lease.task_id);
          const episode = this.kernel.db.sql.query("SELECT state FROM episodes WHERE episode_id=? AND task_id=? AND fence=?")
            .get(lease.episode_id, lease.task_id, lease.fence) as { state: string } | null;
          requireThat(current.task.status === "cancelled" && current.fence === lease.fence + 1 && episode?.state === "cancelled"
            && canonical(current.task.host_job) === canonical(binding), "host_job_cancellation_binding_changed");
          const saved = store.get(actor, approval.job_id);
          requireThat(saved?.revision === runningRevision && saved.job.steps.find(item => item.id === step.id)?.state === "running", "host_job_revision_conflict");
          const finished = new Date(this.kernel.db.now()).toISOString();
          store.put(actor, `${effect}-cancelled`, runningRevision, { ...saved.job, state: "cancelled", updated_at: finished, completed_at: finished,
            steps: saved.job.steps.map(item => item.id === step.id ? { ...item, state: "cancelled", detail: "cancelled",
              exit_code: outcome.exit_code, finished_at: finished, completed_at: finished } : item) });
        });
        requireThat(false, "host_job_cancelled");
      }
      guard(); requireThat(outcome.reason === "exited" && outcome.exit_code !== null, "host_job_outcome_uncertain");
      const workflowEnd = this.workflow ? await this.workflow.inspect("check", { ...admission, assertCurrent: guard }) : undefined;
      if (workflowEnd) requireThat(workflowEnd.result.status === "pass", "specmesh_publication_gate_blocked");
      return this.kernel.db.transaction(() => {
        guard(); workflowEnd?.assertCurrent(); const current = store.get(actor, approval.job_id)!, finished = new Date(this.kernel.db.now()).toISOString();
        const success = outcome.exit_code === 0;
        const steps = current.job.steps.map(item => item.id === step.id ? { ...item, state: success ? "completed" : "failed", exit_code: outcome.exit_code, finished_at: finished, completed_at: finished } : item);
        const done = steps.every(item => ["completed", "skipped"].includes(item.state));
        const saved = store.put(actor, `${effect}-result`, runningRevision, { ...current.job, steps, state: !success ? "failed" : done ? "completed" : current.job.state,
          updated_at: finished, completed_at: done || !success ? finished : "" });
        const result = { host_job_id: approval.job_id, step_id: step.id, host_job_revision: saved.revision, exit_code: outcome.exit_code, observation_digest: digest(outcome), ...(workflowEnd ? { specmesh: { snapshot_digest: workflowEnd.snapshot_digest, status: "pass", closeout_verified: false } } : {}) };
        this.kernel.confirmEffect(actor, `${effect}-confirm`, lease, effect, result);
        return this.kernel.finish(actor, `${effect}-finish`, lease, success ? "done" : "failed", result);
      });
    } catch (error) {
      if (dispatched) { try { this.kernel.markUnknown(actor, `${effect}-unknown`, lease, "host_job_outcome_unproven"); } catch { /* cancellation/lease recovery retains the pending effect */ } }
      throw error;
    }
  }
  async recover(requestId: string, taskId: string, expectedRevision: number, binding: ReconciliationBinding) {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    this.workflow?.assertCurrent();
    const replay = this.kernel.reconciliationReceipt(this.actor, requestId, taskId, expectedRevision, binding);
    if (replay) return replay;
    const observation = this.workflow ? await this.workflow.inspect("check", { assertCurrent: this.authorize }) : undefined;
    return this.acceptRecovery(requestId, taskId, expectedRevision, binding, observation);
  }
  reconcile(requestId: string, taskId: string, expectedRevision: number, binding: ReconciliationBinding) {
    requireThat(!this.workflow, "host_workflow_recovery_required");
    return this.acceptRecovery(requestId, taskId, expectedRevision, binding);
  }
  private acceptRecovery(requestId: string, taskId: string, expectedRevision: number, binding: ReconciliationBinding, workflowEnd?: SpecMeshObservation) {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    const actor = this.actor;
    const replay = this.kernel.reconciliationReceipt(actor, requestId, taskId, expectedRevision, binding);
    if (replay) return replay;
    return this.kernel.reconcileEffect(actor, requestId, taskId, expectedRevision, binding, evidence => {
      const manifest = evidence.manifest, outcome = evidence.observation;
      if (this.workflow) {
        requireThat(object(manifest.workflow) && manifest.workflow.binding_digest === this.workflow.binding_digest
          && typeof manifest.workflow.start_snapshot_digest === "string" && /^[a-f0-9]{64}$/.test(manifest.workflow.start_snapshot_digest), "host_workflow_binding_changed");
        requireThat(workflowEnd?.result.status === "pass", "specmesh_publication_gate_blocked");
        workflowEnd.assertCurrent();
      } else requireThat(manifest.workflow === undefined || manifest.workflow === null, "host_workflow_binding_changed");
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
      return { host_job_id: approval.job_id, step_id: step.id, host_job_revision: saved.revision, exit_code: outcome.exit_code, observation_digest: evidence.observation_digest, ...(workflowEnd ? { specmesh: { snapshot_digest: workflowEnd.snapshot_digest, status: "pass", closeout_verified: false } } : {}) };
    });
  }

}
