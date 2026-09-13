import { setTimeout as delay } from "node:timers/promises";
import { requireScope } from "./commands";
import { CronStore } from "./cron-store";
import { CronTaskAdmission } from "./cron-task-admission";
import type { LocalTaskRuntime } from "./local-task-runtime";
import { ToolGrantDenied } from "./execution-grants";
import { ExecutionPolicyDenied } from "./execution-policy";
import { CronScheduleError, nextCronOccurrence, resolveCronTimezone } from "./cron-schedule";
import type { Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, object, requireThat, RuntimeConflict } from "./value";

interface Cursor {
  version: 1; definition: string; revision: number; timezone: string;
  next_at: number | null; pending: string | null; reason: string | null; last_task: string | null;
}
export interface CronTickResult { job_id: string; changed: boolean; next_at: number | null; pending: string | null; reason: string | null; task_id: string | null }

/** Explicit model-free scheduling loop. It submits TaskHub work, never starts providers.
 * First activation schedules forward. Recovery advances at most one saved slot per job
 * per tick, then plans from current time; it does not replay every missed interval.
 */
export class CronScheduler {
  private readonly store: CronStore;
  private readonly admission: CronTaskAdmission;
  private readonly actor: Principal;
  private readonly settings: { userTimezone?: string; hostTimezone?: string; workspace?: string; maxJobs: number; intervalMs: number };
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, private readonly generation: number,
    options: { userTimezone?: string; hostTimezone?: string; workspace?: string; maxJobs?: number; intervalMs?: number } = {}, runtime?: LocalTaskRuntime) {
    this.actor = Object.freeze({ ...actor, scopes: Object.freeze([...actor.scopes]) });
    this.settings = Object.freeze({ ...options, maxJobs: options.maxJobs ?? 256, intervalMs: options.intervalMs ?? 1000 });
    requireThat(Number.isSafeInteger(this.settings.maxJobs) && this.settings.maxJobs > 0 && this.settings.maxJobs <= 4096
      && Number.isSafeInteger(this.settings.intervalMs) && this.settings.intervalMs >= 100 && this.settings.intervalMs <= 60000, "invalid_cron_scheduler_limits");
    this.store = new CronStore(kernel.db);
    this.admission = new CronTaskAdmission(kernel, this.actor, generation, this.settings, runtime);
  }
  private current(): void {
    requireScope(this.actor, "task:create");
    requireThat(this.store.getCoordinatorEpoch(this.actor.id).current_generation === this.generation, "stale_coordinator_fence");
  }
  tick(): CronTickResult[] {
    this.current();
    const rows = this.kernel.db.sql.query("SELECT job_id FROM cron_jobs WHERE archived=0 AND enabled=1 ORDER BY job_id LIMIT ?")
      .all(this.settings.maxJobs + 1) as { job_id: string }[];
    requireThat(rows.length <= this.settings.maxJobs, "cron_scheduler_job_limit");
    return rows.map(row => this.kernel.db.transaction(() => {
      this.current();
      const job = this.store.getJob(row.job_id);
      requireThat(job, "cron_definition_not_active");
      const now = this.kernel.db.now(), key = `cron_cursor:${digest(job.id)}`;
      const timezone = resolveCronTimezone({ jobTimezone: job.timezone, configuredTimezone: this.settings.userTimezone, hostTimezone: this.settings.hostTimezone });
      const saved = this.kernel.db.sql.query("SELECT value FROM meta WHERE key=?").get(key) as { value: string } | null;
      let cursor: Cursor;
      if (saved) {
        const value: unknown = JSON.parse(saved.value);
        requireThat(object(value) && value.version === 1 && typeof value.definition === "string" && Number.isSafeInteger(value.revision)
          && typeof value.timezone === "string" && (value.next_at === null || Number.isSafeInteger(value.next_at))
          && (value.pending === null || typeof value.pending === "string") && (value.reason === null || typeof value.reason === "string")
          && (value.last_task === null || typeof value.last_task === "string"), "invalid_cron_cursor");
        cursor = value as unknown as Cursor;
      } else cursor = { version: 1, definition: "", revision: 0, timezone, next_at: null, pending: null, reason: null, last_task: null };
      const next = () => nextCronOccurrence(job.schedule, { afterMs: now, timeZone: timezone })?.scheduledAtMs ?? null;
      if (cursor.definition !== job.storage_spec_digest || cursor.revision !== job.storage_version || cursor.timezone !== timezone) {
        cursor = { version: 1, definition: job.storage_spec_digest, revision: job.storage_version, timezone, next_at: null, pending: null, reason: null, last_task: null };
        try { cursor.next_at = next(); }
        catch (error) { if (!(error instanceof CronScheduleError)) throw error; cursor.reason = error.code; }
      } else if (cursor.pending || (cursor.next_at !== null && cursor.next_at <= now)) {
        const occurrence = cursor.pending ? this.store.getOccurrence(cursor.pending) : this.store.createOccurrence(job.id, cursor.next_at!);
        requireThat(occurrence && occurrence.job_id === job.id && occurrence.scheduled_at === cursor.next_at
          && occurrence.definition_digest === cursor.definition && occurrence.schedule_revision === cursor.revision, "cron_cursor_occurrence_mismatch");
        cursor.pending = occurrence.occurrence_id;
        try {
          const submitted = this.admission.submit(occurrence.occurrence_id);
          cursor.last_task = submitted.task.task.task_id; cursor.reason = null; cursor.pending = null; cursor.next_at = next();
        } catch (error) {
          if (error instanceof ToolGrantDenied || error instanceof ExecutionPolicyDenied) {
            cursor.reason = error instanceof ToolGrantDenied ? `tool_grant_denied:${error.reason_code}` : `execution_policy_denied:${error.decision.reason_code}`;
          } else {
          if (!(error instanceof RuntimeConflict)) throw error;
          const reason = error.code;
          if (["cron_quiet_hours", "active_or_uncertain_attempt_exists"].includes(reason)) {
            this.store.skipUnstartedOccurrence(occurrence.occurrence_id,
              reason === "cron_quiet_hours" ? "skipped_quiet" : "skipped_duplicate", { coordinatorId: this.actor.id, fence: this.generation });
            cursor.pending = null; cursor.next_at = next(); cursor.reason = reason;
          } else if (["local_queue_full", "cron_dependency_busy", "cron_attempt_requires_reconciliation", "cron_taskhub_mode_required",
            "cron_taskhub_requires_summarized_only", "cron_taskhub_requires_foreground", "cron_provider_not_configured",
            "source_execution_floor_unavailable", "opencode_not_registered", "claude_not_registered", "codex_not_registered", "gemini_not_registered", "host_not_registered"].includes(reason)) cursor.reason = reason;
          else throw error;
          }
        }
      }
      const serialized = canonical(cursor), changed = saved?.value !== serialized;
      if (changed) this.kernel.db.sql.query("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").run(key, serialized);
      return { job_id: job.id, changed, next_at: cursor.next_at, pending: cursor.pending, reason: cursor.reason, task_id: cursor.last_task };
    }));
  }
  async run(signal: AbortSignal): Promise<void> {
    while (!signal.aborted) {
      this.tick();
      try { await delay(this.settings.intervalMs, undefined, { signal }); }
      catch (error) { if (!signal.aborted) throw error; }
    }
  }
}
