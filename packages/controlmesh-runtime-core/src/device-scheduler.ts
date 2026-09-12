import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { command, requireScope } from "./commands";
import type { RuntimeDatabase } from "./database";
import type { Principal } from "./kernel";
import type { DeviceClient } from "./device-client";
import type { DeviceJob } from "./device-coordinator";
import type { DeviceRunAdmission, DeviceRunOutcome } from "./device-worker";
import { elapsedMs } from "./elapsed-clock";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";

export interface DeviceSchedulerOptions {
  parallelism?: number; max_pending?: number; poll_ms?: number; lease_ms?: number; max_backoff_ms?: number;
  elapsed?: () => number; boot_id?: string;
}
interface WorkRow {
  work_id: string; principal: string; device_id: string; task_id: string; assignment_digest: string; execution_digest: string;
  state: string; attempt: number; expected_revision: number; run_id: string | null; outcome: string | null;
  retry_after: number | null; created_at: number;
}
interface SchedulerState { enabled: boolean; cursor: string | null; review_cursor: string | null; failures: number; next_poll_at: number; last_error: string | null }
interface LeaseRow { token: string; generation: number; boot_id: string; deadline_ms: number }
export interface ScheduledExecutor {
  capacity(): number;
  run(id: string, job: DeviceJob, admission: DeviceRunAdmission): Promise<DeviceRunOutcome>;
}

/** A durable device work queue. It discovers assignments; it never creates a human request or replays unknown effects. */
export class DeviceScheduler {
  private readonly token = randomUUID();
  private readonly key: string;
  private readonly boot: string;
  private readonly elapsed: () => number;
  private readonly parallelism: number;
  private readonly maxPending: number;
  private readonly pollMs: number;
  private readonly leaseMs: number;
  private readonly maxBackoff: number;
  private generation: number | undefined;
  private lastElapsed = 0;
  private stopping = false;
  private ticking?: Promise<void>;
  private timer?: ReturnType<typeof setInterval>;
  private readonly active = new Map<string, { abort: AbortController; promise: Promise<void> }>();

  constructor(private readonly db: RuntimeDatabase, private readonly actor: Principal, private readonly client: Pick<DeviceClient, "queuePage" | "inspect">,
    private readonly executor: ScheduledExecutor, private readonly authorize: () => void, options: DeviceSchedulerOptions = {}) {
    requireScope(actor, "device:schedule"); identifier(actor.device_id);
    this.key = `device-scheduler:${digest([actor.id, actor.device_id])}`;
    this.elapsed = options.elapsed ?? elapsedMs;
    this.boot = options.boot_id ?? readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim();
    requireThat(/^[A-Za-z0-9-]{1,80}$/.test(this.boot), "scheduler_boot_identity_unavailable");
    this.parallelism = options.parallelism ?? 2; this.maxPending = options.max_pending ?? 128;
    this.pollMs = options.poll_ms ?? 2000; this.leaseMs = options.lease_ms ?? 10_000; this.maxBackoff = options.max_backoff_ms ?? 60_000;
    requireThat([[this.parallelism, 1, 8], [this.maxPending, 1, 1024], [this.pollMs, 100, 60_000],
      [this.leaseMs, 2000, 30_000], [this.maxBackoff, this.pollMs, 300_000]].every(([value, min, max]) => Number.isSafeInteger(value) && value >= min && value <= max), "invalid_device_scheduler_limits");
  }

  private authorized(): void {
    requireThat(!this.stopping, "device_scheduler_stopped");
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private clock(): number {
    const now = Math.floor(this.elapsed());
    requireThat(Number.isSafeInteger(now) && now >= this.lastElapsed, "scheduler_clock_invalid");
    this.lastElapsed = now; return now;
  }
  private state(): SchedulerState {
    const row = this.db.sql.query("SELECT value FROM meta WHERE key=?").get(this.key) as { value: string } | null;
    if (!row) return { enabled: true, cursor: null, review_cursor: null, failures: 0, next_poll_at: 0, last_error: null };
    const value: unknown = JSON.parse(row.value);
    requireThat(object(value) && typeof value.enabled === "boolean" && Number.isSafeInteger(value.failures) && Number(value.failures) >= 0
      && Number.isSafeInteger(value.next_poll_at) && (value.cursor === null || typeof value.cursor === "string")
      && (value.review_cursor === null || typeof value.review_cursor === "string") && (value.last_error === null || typeof value.last_error === "string"), "device_scheduler_state_corrupt");
    return value as unknown as SchedulerState;
  }
  private save(update: Partial<SchedulerState>): void {
    const state = { ...this.state(), ...update };
    this.db.sql.query("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").run(this.key, canonical(state));
  }
  private lease(): LeaseRow | null {
    return this.db.sql.query("SELECT token,generation,boot_id,deadline_ms FROM device_scheduler_leases WHERE principal=? AND device_id=?")
      .get(this.actor.id, this.actor.device_id!) as LeaseRow | null;
  }
  private current(): void {
    this.authorized(); const row = this.lease(), now = this.clock();
    requireThat(row && row.token === this.token && row.generation === this.generation && row.boot_id === this.boot && row.deadline_ms > now, "device_scheduler_lease_lost");
  }
  private renew(): void {
    this.db.transaction(() => { this.current(); this.db.sql.query("UPDATE device_scheduler_leases SET deadline_ms=? WHERE principal=? AND device_id=? AND token=?")
      .run(this.clock() + this.leaseMs, this.actor.id, this.actor.device_id!, this.token); });
  }
  private own(): void {
    this.authorized();
    this.db.transaction(() => {
      const row = this.lease(), now = this.clock();
      requireThat(!row || row.token === this.token || row.boot_id !== this.boot || row.deadline_ms <= now, "device_scheduler_already_running");
      this.generation = (row?.generation ?? 0) + 1;
      this.db.sql.query("INSERT INTO device_scheduler_leases VALUES (?,?,?,?,?,?) ON CONFLICT(principal,device_id) DO UPDATE SET token=excluded.token,generation=excluded.generation,boot_id=excluded.boot_id,deadline_ms=excluded.deadline_ms")
        .run(this.actor.id, this.actor.device_id!, this.token, this.generation, this.boot, now + this.leaseMs);
      this.db.sql.query("UPDATE device_scheduled_work SET state='unknown',retry_after=NULL,outcome=? WHERE principal=? AND device_id=? AND state='running'")
        .run(canonical({ reason: "scheduler_interrupted", retry_after: null }), this.actor.id, this.actor.device_id!);
    });
  }
  /** Explicit command IDs preserve a later pause when an old start command is replayed. */
  start(requestId?: string): Record<string, unknown> {
    this.authorized();
    let acquired = false;
    if (requestId) command(this.db, this.actor, requestId, "device.scheduler.start", {}, () => {
      if (!this.timer) { this.own(); acquired = true; }
      this.save({ enabled: true, failures: 0, next_poll_at: 0, last_error: null }); return { started: true };
    });
    if (!this.state().enabled) return this.status();
    if (!this.timer) {
      if (!acquired) this.own();
      this.timer = setInterval(() => {
        try { this.renew(); void this.tick().catch(() => {}); }
        catch { for (const item of this.active.values()) item.abort.abort(); if (this.timer) clearInterval(this.timer); this.timer = undefined; }
      }, Math.min(this.pollMs, Math.floor(this.leaseMs / 3)));
      void this.tick().catch(() => {});
    }
    return this.status();
  }
  async pause(requestId: string): Promise<Record<string, unknown>> {
    this.authorized();
    command(this.db, this.actor, requestId, "device.scheduler.pause", {}, () => { this.save({ enabled: false }); return { paused: true }; });
    if (!this.state().enabled) {
      await this.ticking?.catch(() => {}); await Promise.all([...this.active.values()].map(item => item.promise));
      if (this.timer) clearInterval(this.timer); this.timer = undefined; this.release();
    }
    return this.status();
  }
  private release(): void {
    this.db.sql.query("UPDATE device_scheduler_leases SET deadline_ms=0 WHERE principal=? AND device_id=? AND token=? AND generation=?")
      .run(this.actor.id, this.actor.device_id!, this.token, this.generation ?? -1);
    this.generation = undefined;
  }
  async stop(): Promise<void> {
    this.stopping = true; if (this.timer) clearInterval(this.timer); this.timer = undefined;
    for (const item of this.active.values()) item.abort.abort();
    await this.ticking?.catch(() => {}); await Promise.allSettled([...this.active.values()].map(item => item.promise));
    this.db.transaction(() => {
      if (this.lease()?.token === this.token) this.db.sql.query("UPDATE device_scheduled_work SET state='unknown',retry_after=NULL,outcome=? WHERE principal=? AND device_id=? AND state='running'")
        .run(canonical({ reason: "scheduler_stopped", retry_after: null }), this.actor.id, this.actor.device_id!);
      this.release();
    });
  }
  status(): Record<string, unknown> {
    this.authorized(); const state = this.state(), lease = this.lease();
    const counts = this.db.sql.query("SELECT state,COUNT(*) AS count FROM device_scheduled_work WHERE principal=? AND device_id=? GROUP BY state").all(this.actor.id, this.actor.device_id!);
    return { ...state, running: !!this.timer, active: this.active.size, parallelism: this.parallelism, counts,
      generation: lease?.generation ?? null, lease_current: !!lease && lease.boot_id === this.boot && lease.deadline_ms > this.clock() };
  }
  inspect(workId: string): Record<string, unknown> {
    this.authorized(); identifier(workId); const row = this.row(workId); requireThat(row, "scheduled_work_missing");
    return { work_id: row.work_id, task_id: row.task_id, state: row.state, attempt: row.attempt, run_id: row.run_id,
      retry_after: row.retry_after, outcome: row.outcome ? JSON.parse(row.outcome) : null };
  }
  async retry(requestId: string, workId: string, expectedAttempt: number): Promise<Record<string, unknown>> {
    this.authorized(); identifier(workId);
    const selected = this.row(workId); requireThat(selected, "scheduled_work_missing");
    const job = await this.client.inspect(selected.task_id); this.authorized();
    requireThat(this.same(selected, job) && job.status === "waiting" && job.active_episode === false && job.needs_reconciliation === false, "scheduled_retry_not_admitted");
    command(this.db, this.actor, requestId, "device.scheduler.retry", { workId, expectedAttempt }, () => {
      const row = this.row(workId);
      requireThat(row && row.attempt === expectedAttempt && ["blocked", "waiting", "unknown"].includes(row.state), "scheduled_retry_not_admitted");
      this.db.sql.query("UPDATE device_scheduled_work SET state='queued',retry_after=NULL,outcome=NULL WHERE work_id=?").run(workId);
      return { queued: true };
    });
    return this.inspect(workId);
  }
  private row(id: string): WorkRow | null {
    return this.db.sql.query("SELECT * FROM device_scheduled_work WHERE work_id=? AND principal=? AND device_id=?").get(id, this.actor.id, this.actor.device_id!) as WorkRow | null;
  }
  private set(row: WorkRow, state: string, reason: string, retry: number | null = null): void {
    this.current();
    this.db.sql.query("UPDATE device_scheduled_work SET state=?,outcome=?,retry_after=? WHERE work_id=? AND attempt=?")
      .run(state, canonical({ reason, retry_after: retry }), retry, row.work_id, row.attempt);
  }
  private same(row: WorkRow, job: DeviceJob): boolean { return row.assignment_digest === job.assignment_digest && row.execution_digest === job.execution_digest; }
  private settle(row: WorkRow, job: DeviceJob): boolean {
    if (!this.same(row, job)) { this.set(row, "superseded", "assignment_changed"); return true; }
    if (job.status === "done" || job.status === "failed" || job.status === "cancelled") { this.set(row, job.status === "cancelled" ? "cancelled" : "completed", "coordinator_terminal"); return true; }
    return false;
  }
  private async inspectAssignment(row: WorkRow): Promise<DeviceJob | null> {
    try { const job = await this.client.inspect(row.task_id); this.current(); return job; }
    catch (error) {
      this.current();
      if (error instanceof RuntimeConflict && ["assignment_unavailable", "assignment_authority_changed", "device_capability_unavailable"].includes(error.code)) {
        this.set(row, "superseded", error.code); return null;
      }
      throw error;
    }
  }
  /** One bounded pass. Provider work continues independently, inside this lease and the coordinator lease. */
  tick(): Promise<void> {
    if (this.ticking) return this.ticking;
    const pending = this.pump().catch(error => {
      const reason = error instanceof RuntimeConflict ? error.code : "device_scheduler_unavailable";
      try {
        this.current();
        const failures = Math.min(this.state().failures + 1, 20);
        this.save({ failures, last_error: reason, next_poll_at: this.db.now() + Math.min(this.maxBackoff, this.pollMs * 2 ** failures),
          ...(["unauthorized", "device_revoked", "invalid_device_queue"].includes(reason) ? { enabled: false } : {}) });
      } catch { for (const item of this.active.values()) item.abort.abort(); if (this.timer) clearInterval(this.timer); this.timer = undefined; }
      throw error;
    }).finally(() => { this.ticking = undefined; });
    this.ticking = pending; return pending;
  }
  private async pump(): Promise<void> {
    this.renew();
    const state = this.state(); if (!state.enabled || state.next_poll_at > this.db.now()) return;
    const page = await this.client.queuePage(state.cursor); this.current();
    this.db.transaction(() => {
      this.current();
      let queued = (this.db.sql.query("SELECT COUNT(*) AS n FROM device_scheduled_work WHERE principal=? AND device_id=? AND state IN ('queued','running','waiting')")
        .get(this.actor.id, this.actor.device_id!) as { n: number }).n;
      for (const job of page.items) {
        requireThat(job.execution_digest && /^[a-f0-9]{64}$/.test(job.execution_digest), "invalid_device_queue");
        const id = digest([this.actor.id, this.actor.device_id, job.task_id, job.assignment_digest, job.execution_digest]);
        if (this.row(id) || queued >= this.maxPending) continue;
        this.db.sql.query("INSERT INTO device_scheduled_work (work_id,principal,device_id,task_id,assignment_digest,execution_digest,state,expected_revision,created_at) VALUES (?,?,?,?,?,?,'queued',?,?)")
          .run(id, this.actor.id, this.actor.device_id!, job.task_id, job.assignment_digest, job.execution_digest, job.revision, this.db.now()); queued++;
      }
      this.save({ cursor: page.next_cursor, failures: 0, last_error: null, next_poll_at: this.db.now() + this.pollMs });
    });
    const unknown = this.db.sql.query("SELECT * FROM device_scheduled_work WHERE principal=? AND device_id=? AND state='unknown' AND work_id>? ORDER BY work_id LIMIT 8")
      .all(this.actor.id, this.actor.device_id!, state.review_cursor ?? "") as WorkRow[];
    for (const row of unknown) {
      const job = await this.inspectAssignment(row); if (!job) continue;
      this.settle(row, job);
    }
    this.save({ review_cursor: unknown.length === 8 ? unknown.at(-1)!.work_id : null });
    const waiting = this.db.sql.query("SELECT * FROM device_scheduled_work WHERE principal=? AND device_id=? AND (state='queued' OR (state='waiting' AND retry_after<=?)) ORDER BY created_at,work_id LIMIT ?")
      .all(this.actor.id, this.actor.device_id!, this.db.now(), this.maxPending) as WorkRow[];
    for (const row of waiting) {
      this.current(); if (!this.state().enabled || this.active.size >= this.parallelism || this.executor.capacity() <= 0) break;
      const job = await this.inspectAssignment(row); if (!job) continue;
      if (this.settle(row, job)) continue;
      if (job.status !== "waiting" || job.active_episode || job.needs_reconciliation) { this.set(row, "unknown", "coordinator_execution_pending"); continue; }
      const abort = new AbortController(), attempt = row.attempt + 1, id = `scheduled-${row.work_id}-${attempt}`;
      this.db.transaction(() => { this.current();
        requireThat(this.row(row.work_id)?.attempt === row.attempt, "scheduled_attempt_changed");
        this.db.sql.query("UPDATE device_scheduled_work SET state='running',attempt=?,expected_revision=?,run_id=?,outcome=NULL,retry_after=NULL WHERE work_id=?")
          .run(attempt, job.revision, id, row.work_id); });
      const started = { ...row, attempt, run_id: id }, admission = { signal: abort.signal, assertCurrent: () => { this.current(); requireThat(!abort.signal.aborted, "device_scheduler_stopped"); } };
      const promise = Promise.resolve().then(() => this.executor.run(id, job, admission)).then(result => {
        this.current();
        const retry = result.status === "unavailable" && Number.isSafeInteger(result.retry_after) && Number(result.retry_after) > this.db.now() ? Number(result.retry_after) : null;
        this.set(started, result.status === "done" || result.status === "failed" ? "completed" : result.status === "unknown" ? "unknown" : retry !== null ? "waiting" : "blocked",
          result.reason ?? result.status, retry);
      }).catch(error => {
        try {
          const reason = error instanceof RuntimeConflict ? error.code : "scheduled_execution_unknown";
          this.set(started, ["device_worker_backpressure", "device_task_already_running"].includes(reason) ? "waiting"
            : ["local_capability_unavailable", "runtime_configuration_changed", "worker_workspace_changed"].includes(reason) ? "blocked" : "unknown", reason,
            ["device_worker_backpressure", "device_task_already_running"].includes(reason) ? this.db.now() + this.pollMs : null);
        } catch { /* Lost local ownership may not overwrite the successor's bookkeeping. */ }
      }).finally(() => this.active.delete(row.work_id));
      this.active.set(row.work_id, { abort, promise });
    }
  }
}
