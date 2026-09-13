import { CronStore, type CronExecutionAttemptRecord } from "./cron-store";
import type { Principal, RuntimeKernel, TaskSnapshot } from "./kernel";
import { TaskIngress } from "./task-ingress";
import { resolveCronTimezone } from "./cron-schedule";
import type { LocalTaskRuntime } from "./local-task-runtime";
import { directoryIdentity } from "./providers/native-manifest";
import { requireScope } from "./commands";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";

const foregroundCapabilities = new Set(["repo_write", "git_write", "network_write", "github_release", "publish"]);

/** Trusted scheduler seam for TaskHub-mode occurrences. No timer or provider is started.
 * Dependency wait order is persisted in bounded versioned metadata;
 * native execution still requires the existing queue, source, grant and sandbox checks.
 */
export class CronTaskAdmission {
  private readonly store: CronStore;
  private readonly ingress: TaskIngress;
  private readonly actor: Principal;
  private readonly quietTimezone: string;
  private readonly workspace: Readonly<ReturnType<typeof directoryIdentity>> | undefined;

  constructor(private readonly kernel: RuntimeKernel, actor: Principal, private readonly generation: number,
    timezone: { userTimezone?: string; hostTimezone?: string; workspace?: string } = {}, private readonly runtime?: LocalTaskRuntime) {
    requireThat(!runtime || runtime.kernel === kernel, "cron_queue_kernel_mismatch");
    if (timezone.workspace !== undefined) {
      this.workspace = Object.freeze(directoryIdentity(timezone.workspace));
      requireThat(this.workspace.path === timezone.workspace, "cron_workspace_not_canonical");
    }
    identifier(actor.id); identifier(actor.device_id);
    requireThat(actor.origin === "schedule" && Number.isSafeInteger(generation) && generation > 0, "invalid_cron_controller");
    this.actor = Object.freeze({ ...actor, scopes: Object.freeze([...actor.scopes]) });
    // Python CronObserver uses the configured user zone for quiet hours, not
    // each job's recurrence zone and not heartbeat's default quiet window.
    this.quietTimezone = resolveCronTimezone({ configuredTimezone: timezone.userTimezone, hostTimezone: timezone.hostTimezone });
    this.store = new CronStore(kernel.db);
    this.ingress = new TaskIngress(kernel, { command_origin: "schedule", origin: "cron", source_scope: "cron", transport: "cron" }, () => this.current());
    this.current();
  }

  private current(): void {
    requireThat(this.store.getCoordinatorEpoch(this.actor.id).current_generation === this.generation, "stale_coordinator_fence");
    if (this.workspace) requireThat(canonical(directoryIdentity(this.workspace.path)) === canonical(this.workspace), "cron_workspace_changed");
  }

  submit(occurrenceId: string): { task: TaskSnapshot; attempt: CronExecutionAttemptRecord } {
    identifier(occurrenceId);
    const result = this.kernel.db.transaction(() => {
      this.current();
      requireScope(this.actor, "task:create");
      const occurrence = this.store.getOccurrence(occurrenceId);
      requireThat(occurrence, "occurrence_not_found");
      const attempts = this.store.listAttempts(occurrenceId);
      if (attempts.length) {
        // A retry observes the original linkage; it never creates a second task or
        // turns an uncertain/foreign attempt into newly authorized work.
        requireThat(attempts.length === 1 && attempts[0].task_id !== null
          && attempts[0].coordinator_id === this.actor.id && attempts[0].executor_device_id === this.actor.device_id
          && attempts[0].fencing_generation === this.generation && attempts[0].state !== "uncertain",
        "cron_attempt_requires_reconciliation");
        return { task: this.kernel.inspect(this.actor, attempts[0].task_id!), attempt: attempts[0] };
      }
      const job = this.store.getJob(occurrence.job_id);
      requireThat(job, "cron_definition_not_active");
      const now = this.kernel.db.now();
      requireThat(occurrence.scheduled_at <= now, "cron_occurrence_not_due");
      const start = job.quiet_start ?? 0, end = job.quiet_end ?? 0;
      requireThat(Number.isInteger(start) && Number(start) >= 0 && Number(start) <= 23
        && Number.isInteger(end) && Number(end) >= 0 && Number(end) <= 23, "invalid_cron_quiet_window");
      const hour = Number(new Intl.DateTimeFormat("en-US", { timeZone: this.quietTimezone, hour: "2-digit", hourCycle: "h23" }).format(now));
      const quiet = start !== end && (Number(start) < Number(end)
        ? hour >= Number(start) && hour < Number(end) : hour >= Number(start) || hour < Number(end));
      requireThat(!quiet, "cron_quiet_hours");
      requireThat(job.execution_mode === "taskhub", "cron_taskhub_mode_required");
      requireThat(job.output_policy === "summarized_only", "cron_taskhub_requires_summarized_only");
      const risk = String(job.risk ?? "low").trim().toLowerCase();
      const kind = String(job.workunit_kind ?? "").trim().toLowerCase();
      requireThat(["low", "medium"].includes(risk) && !foregroundCapabilities.has(kind), "cron_taskhub_requires_foreground");
      requireThat(typeof job.provider === "string" && job.provider.length > 0, "cron_provider_not_configured");
      requireThat(this.kernel.db.sql.query("SELECT 1 FROM cron_jobs WHERE job_id=? AND archived=0 AND enabled=1 AND version=? AND spec_digest=?")
        .get(job.id, occurrence.schedule_revision, occurrence.definition_digest), "cron_definition_not_active");
      let queueKey: string | undefined;
      let queue: string[] = [];
      if (job.dependency != null) {
        requireThat(typeof job.dependency === "string" && job.dependency.trim().length > 0, "invalid_dependency_key");
        queueKey = `cron_dependency_queue:${digest(job.dependency)}`;
        const saved = this.kernel.db.sql.query("SELECT value FROM meta WHERE key=?").get(queueKey) as { value: string } | null;
        if (saved) {
          const value: unknown = JSON.parse(saved.value);
          requireThat(object(value) && value.version === 1 && value.dependency === job.dependency
            && Array.isArray(value.entries) && value.entries.length <= 256 && value.entries.every(id => typeof id === "string")
            && new Set(value.entries).size === value.entries.length, "invalid_cron_dependency_queue");
          queue = value.entries as string[];
        }
        // Definition removal/replacement cannot strand a waiting head forever.
        // Active/uncertain execution remains guarded independently by the lock.
        queue = queue.filter(id => Boolean(this.kernel.db.sql.query(`SELECT 1 FROM cron_occurrences o JOIN cron_jobs j ON j.job_id=o.job_id
          WHERE o.occurrence_id=? AND o.state='scheduled' AND j.archived=0 AND j.enabled=1
          AND j.version=o.schedule_revision AND j.spec_digest=o.definition_digest AND j.dependency=?`).get(id, job.dependency)));
        if (!queue.includes(occurrenceId)) {
          requireThat(queue.length < 256, "cron_dependency_queue_full");
          queue.push(occurrenceId);
        }
        this.kernel.db.sql.query("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value")
          .run(queueKey, canonical({ version: 1, dependency: job.dependency, entries: queue }));
        if (queue[0] !== occurrenceId || this.store.getDependencyLock(job.dependency)) {
          return { blocked: true as const }; // Commit waiting order, not a task/attempt.
        }
      }
      const taskId = `cron-${occurrenceId}`;
      const chatId = String(job.chat_id ?? 0);
      const task = this.ingress.submit(this.actor, `cron-submit-${occurrenceId}`, {
        task_id: taskId, chat_id: chatId, status: "waiting", title: job.title, prompt: job.agent_instruction,
        provider: job.provider, model: job.model, workunit_kind: kind, risk, output_policy: "summarized_only",
        ...(this.workspace ? { repo_root: this.workspace.path } : {}),
        cron_occurrence_id: occurrenceId, cron_job_id: job.id, cron_definition_digest: occurrence.definition_digest,
      }, { source_id: job.id, chat_id: chatId, ...(job.topic_id != null ? { topic_id: String(job.topic_id) } : {}) });
      const attempt = this.store.createAttempt(occurrenceId, { coordinatorId: this.actor.id,
        executorDeviceId: this.actor.device_id!, fencingGeneration: this.generation, taskId });
      this.runtime?.enqueue(`cron-enqueue-${occurrenceId}`, taskId, task.revision);
      if (job.dependency != null) {
        requireThat(typeof job.dependency === "string" && this.store.acquireDependencyLock(job.dependency,
          occurrenceId, attempt.attempt_id, 60_000), "cron_dependency_busy");
      }
      if (job.job_kind === "monitor") this.store.setEnabled(job.id, false);
      if (queueKey) {
        const remaining = queue.slice(1);
        if (remaining.length) this.kernel.db.sql.query("UPDATE meta SET value=? WHERE key=?")
          .run(canonical({ version: 1, dependency: job.dependency, entries: remaining }), queueKey);
        else this.kernel.db.sql.query("DELETE FROM meta WHERE key=?").run(queueKey);
      }
      return { task, attempt };
    });
    if ("blocked" in result) throw new RuntimeConflict("cron_dependency_busy");
    return result;
  }
}
