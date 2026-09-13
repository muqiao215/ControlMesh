import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import { HostJobApprovals } from "./host-job-approval";
import { HostJobProcess } from "./host-job-process";
import { HostJobStore } from "./host-job-store";
import { decodeToolGrant, restrictiveGrant } from "./execution-grants";
import { enforceLocalReadSource } from "./execution-policy";
import type { Principal, RuntimeKernel, TaskSnapshot } from "./kernel";
import type { LocalTaskExecution } from "./local-task-runtime";
import { directoryIdentity } from "./providers/native-manifest";
import { digest, object, requireThat } from "./value";

/** Registered host execution shares the durable local queue without any model probe. */
export class HostJobAdapter {
  constructor(private readonly kernel: RuntimeKernel, private readonly actor: Principal,
    private readonly workspace: string, private readonly shell: string, private readonly authorize: () => void) {}
  prepare(snapshot: TaskSnapshot): LocalTaskExecution {
    const task = snapshot.task;
    const identity = () => {
      const checked: unknown = this.authorize();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(task.provider === "host" && object(task.host_job), "host_job_task_binding_required");
      enforceLocalReadSource(task.execution_context);
      const grant = decodeToolGrant(task.tool_grant);
      requireThat(!restrictiveGrant(grant) && grant.confirmation_policy === "provider_runtime", "host_job_grant_unenforceable");
      const approval = new HostJobApprovals(this.kernel.db, this.authorize).inspectReceipt(this.actor, task.host_job.approval);
      requireThat(task.host_job.job_id === approval.job_id && task.host_job.revision === approval.revision
        && task.host_job.step_id === approval.step_id, "host_job_task_binding_changed");
      const job = new HostJobStore(this.kernel.db, this.authorize).get(this.actor, approval.job_id);
      const step = job?.job.steps.find(item => item.id === approval.step_id);
      requireThat(step && job!.job.repo === this.workspace && (step.cwd || job!.job.repo) === this.workspace, "host_job_workspace_mismatch");
      requireThat(isAbsolute(this.shell) && realpathSync(this.shell) === this.shell, "host_job_shell_not_canonical");
      const stat = statSync(this.shell, { bigint: true });
      requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n, "host_job_shell_invalid");
      return digest({ workspace: directoryIdentity(this.workspace), shell: this.shell,
        shell_identity: [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String),
        task: { task_id: task.task_id, host_job: task.host_job, execution_context: task.execution_context, tool_grant: task.tool_grant } });
    };
    const binding_digest = identity();
    const assertCurrent = () => { requireThat(identity() === binding_digest, "host_job_execution_configuration_changed"); };
    return { binding_digest, assertCurrent,
      ensureReady: async (_requestId, context) => {
        context.assertCurrent(); assertCurrent();
        new HostJobApprovals(this.kernel.db, this.authorize).assertApproved(this.actor, (task.host_job as Record<string, unknown>).approval);
        return { decision: "cached", reason: "host_step_approved", retry_after: null, permit: null, report: null };
      },
      execute: (lease, context) => new HostJobProcess(this.kernel, this.actor, this.workspace, this.shell, this.authorize).execute(lease, context),
    };
  }
}
