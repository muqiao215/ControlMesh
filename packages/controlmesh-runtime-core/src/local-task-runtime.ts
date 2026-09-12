import { randomUUID } from "node:crypto";
import { command, requireScope } from "./commands";
import { AgentMailbox, type AgentMessage } from "./mailbox";
import { RuntimeKernel, type Lease, type Principal, type TaskSnapshot } from "./kernel";
import type { ProbeDecision } from "./providers/preflight-cache";
import { TaskIngress, type IngressSource, type SubmissionIdentity, type SubmissionRestrictions } from "./task-ingress";
import { canonical, digest, identifier, requireThat, RuntimeConflict, type LegacyTask } from "./value";

export interface LocalExecutionContext {
  signal: AbortSignal; assertCurrent: () => void; remainingMs: () => number;
  /** Only the sealed workspace publisher uses this; native execution must retain assertCurrent. */
  assertPublicationAuthority?: () => void;
  verifyPublication?: (assertPublished: () => void) => Promise<Record<string, unknown>>;
}
export interface LocalTaskExecution {
  binding_digest: string;
  assertCurrent(): void;
  assertPublicationAuthority?(): void;
  ensureReady(requestId: string, context: LocalExecutionContext): Promise<ProbeDecision>;
  execute(lease: Lease, context: LocalExecutionContext): Promise<TaskSnapshot>;
}
/** Resolve from trusted local registration only; this callback must not launch a process/model. */
export type LocalTaskResolver = (task: TaskSnapshot) => LocalTaskExecution;
export interface LocalRun {
  run_id: string; task_id: string;
  state: "queued" | "running" | "completed" | "blocked" | "cancelled" | "interrupted";
  outcome: { reason: string; retry_after: number | null } | null;
}
interface RunRow extends Omit<LocalRun, "outcome"> {
  principal: string; device_id: string; origin: Principal["origin"]; expected_revision: number;
  binding_digest: string; owner: string | null; lease: string | null; outcome: string | null;
}
export interface LocalRuntimeOptions { parallelism?: number; max_pending?: number; lease_ms?: number }

/** Durable local execution entrypoint. No automatic retries, provider fallback or legacy-writer activation. */
export class LocalTaskRuntime {
  private readonly owner = randomUUID();
  private readonly actor: Principal;
  private readonly ingress: TaskIngress;
  private readonly parallelism: number;
  private readonly maxPending: number;
  private readonly leaseMs: number;
  private readonly active = new Map<string, { controller: AbortController; promise: Promise<void> }>();
  private stopping = false;
  private persistenceFailure: unknown;

  constructor(readonly kernel: RuntimeKernel, actor: Principal, source: IngressSource,
    private readonly resolve: LocalTaskResolver, private readonly authorize: () => void, options: LocalRuntimeOptions = {}) {
    this.actor = structuredClone(actor);
    identifier(actor.device_id);
    for (const scope of ["task:read", "task:execute", "task:reconcile", "task:admin"]) requireScope(actor, scope);
    this.parallelism = options.parallelism ?? 2; this.maxPending = options.max_pending ?? 128; this.leaseMs = options.lease_ms ?? 300_000;
    requireThat(Number.isSafeInteger(this.parallelism) && this.parallelism >= 1 && this.parallelism <= 16
      && Number.isSafeInteger(this.maxPending) && this.maxPending >= 1 && this.maxPending <= 1024
      && Number.isSafeInteger(this.leaseMs) && this.leaseMs >= 1000 && this.leaseMs <= 300_000, "invalid_local_runtime_limits");
    this.current();
    this.ingress = new TaskIngress(kernel, source, () => this.current());
    // Two controllers cannot claim different concurrency budgets for the same configured device/owner.
    const key = `local-policy:${digest([actor.id, actor.device_id])}`;
    const policy = canonical({ source, parallelism: this.parallelism, max_pending: this.maxPending, lease_ms: this.leaseMs, origin: actor.origin });
    kernel.db.transaction(() => {
      const existing = kernel.db.sql.query("SELECT value FROM meta WHERE key=?").get(key) as { value: string } | null;
      requireThat(!existing || existing.value === policy, "local_runtime_policy_conflict");
      if (!existing) kernel.db.sql.query("INSERT INTO meta VALUES (?,?)").run(key, policy);
    });
  }

  private current(): void {
    requireThat(!this.stopping, "local_runtime_stopping");
    const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private rows(state: "queued" | "running" | "interrupted"): RunRow[] {
    return this.kernel.db.sql.query("SELECT * FROM local_runs WHERE principal=? AND device_id=? AND state=? ORDER BY created_at,rowid LIMIT ?")
      .all(this.actor.id, this.actor.device_id!, state, this.maxPending + this.parallelism) as RunRow[];
  }
  private checkExecution(execution: LocalTaskExecution): void {
    requireThat(execution && typeof execution.ensureReady === "function" && typeof execution.execute === "function"
      && /^[a-f0-9]{64}$/.test(execution.binding_digest), "invalid_execution_binding");
    const checked: unknown = execution.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private view(row: RunRow): LocalRun {
    return { run_id: row.run_id, task_id: row.task_id, state: row.state, outcome: row.outcome ? JSON.parse(row.outcome) : null };
  }
  inspect(runId: string): LocalRun {
    this.current(); requireScope(this.actor, "task:read"); identifier(runId);
    const row = this.kernel.db.sql.query("SELECT * FROM local_runs WHERE run_id=? AND principal=? AND device_id=?")
      .get(runId, this.actor.id, this.actor.device_id!) as RunRow | null;
    requireThat(row, "local_run_not_found");
    this.kernel.inspect(this.actor, row.task_id);
    return this.view(row);
  }
  assertPrincipal(actor: Principal): void {
    this.current();
    requireThat(actor.id === this.actor.id && actor.device_id === this.actor.device_id && actor.origin === this.actor.origin, "local_principal_mismatch");
  }
  inspectTask(taskId: string): TaskSnapshot { this.current(); return this.kernel.inspect(this.actor, taskId); }
  parallelLimit(): number { this.current(); return this.parallelism; }
  queueStatus(): { queued: number; running: number } {
    this.current(); requireScope(this.actor, "task:read");
    return { queued: this.rows("queued").length, running: this.rows("running").length };
  }
  submit(requestId: string, task: LegacyTask, identity: SubmissionIdentity, restrictions?: SubmissionRestrictions): TaskSnapshot {
    this.current(); return this.ingress.submit(this.actor, requestId, task, identity, restrictions);
  }
  resume(requestId: string, taskId: string, expectedRevision: number, prompt: string): TaskSnapshot {
    this.current(); return this.kernel.resume(this.actor, requestId, taskId, expectedRevision, prompt);
  }
  tell(requestId: string, taskId: string, text: string, ttlMs = 300_000): AgentMessage {
    this.current(); requireThat(typeof text === "string" && text.trim().length > 0, "empty_task_update");
    return new AgentMailbox(this.kernel).send(this.actor, requestId, { recipient_task: taskId, sender_lease: null,
      kind: "tell", payload: { text }, causation_id: null, ttl_ms: ttlMs });
  }
  inspectMessage(taskId: string, messageId: string): AgentMessage {
    this.current(); return new AgentMailbox(this.kernel).inspect(this.actor, taskId, messageId);
  }
  mailboxStatus(taskId: string): { pending_count: number } {
    this.current(); return { pending_count: new AgentMailbox(this.kernel).pendingCount(this.actor, taskId) };
  }
  cancel(requestId: string, taskId: string, expectedRevision: number): TaskSnapshot {
    this.current();
    const task = this.kernel.db.transaction(() => {
      const cancelled = this.kernel.cancel(this.actor, requestId, taskId, expectedRevision);
      this.kernel.db.sql.query("UPDATE local_runs SET state='cancelled',outcome=? WHERE task_id=? AND state='queued'")
        .run(canonical({ reason: "task_cancelled", retry_after: null }), taskId);
      return cancelled;
    });
    for (const row of this.rows("running")) if (row.task_id === taskId) this.active.get(row.run_id)?.controller.abort();
    return task;
  }

  enqueue(requestId: string, taskId: string, expectedRevision: number): LocalRun {
    this.current(); requireScope(this.actor, "task:execute"); identifier(requestId);
    const runId = digest([this.actor.id, this.actor.device_id, requestId]);
    command(this.kernel.db, this.actor, requestId, "local.enqueue", { taskId, expectedRevision }, () => {
      this.current();
      const task = this.kernel.inspect(this.actor, taskId);
      requireThat(task.revision === expectedRevision, "revision_conflict");
      requireThat(task.task.status === "waiting" && !task.needs_reconciliation && task.active_episode === null, "task_not_admitted");
      requireThat(this.rows("queued").length < this.maxPending, "local_queue_full");
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(taskId), "task_already_queued");
      const execution = this.resolve(task); this.checkExecution(execution);
      this.kernel.db.sql.query("INSERT INTO local_runs (run_id,principal,device_id,origin,task_id,expected_revision,binding_digest,state,created_at) VALUES (?,?,?,?,?,?,?,'queued',?)")
        .run(runId, this.actor.id, this.actor.device_id!, this.actor.origin, taskId, expectedRevision, execution.binding_digest, this.kernel.db.now());
      return { run_id: runId };
    });
    return this.inspect(runId);
  }

  /** Reconcile queue bookkeeping from authoritative episodes; never retry or invent a native result. */
  recover(): void {
    this.current();
    this.kernel.recoverExpired({ ...this.actor, origin: "recovery" });
    this.kernel.db.transaction(() => {
      for (const row of [...this.rows("running"), ...this.rows("interrupted")]) {
        const lease = row.lease ? JSON.parse(row.lease) as Lease : null;
        const episode = lease ? this.kernel.db.sql.query("SELECT state FROM episodes WHERE episode_id=? AND task_id=? AND fence=?")
          .get(lease.episode_id, row.task_id, lease.fence) as { state: string } | null : null;
        if (episode && ["leased", "running"].includes(episode.state)) continue;
        if (row.state === "interrupted" && !["done", "failed", "cancelled"].includes(episode?.state ?? "")) continue;
        const state = episode?.state === "done" || episode?.state === "failed" ? "completed" : episode?.state === "cancelled" ? "cancelled" : "interrupted";
        this.kernel.db.sql.query("UPDATE local_runs SET state=?,outcome=? WHERE run_id=? AND state IN ('running','interrupted')")
          .run(state, canonical({ reason: episode?.state ?? "missing_execution_episode", retry_after: null }), row.run_id);
      }
    });
  }

  /** One bounded queue pass; callers can tick a service loop without repeating blocked model probes. */
  tick(): void {
    this.current(); this.recover();
    for (let scanned = 0; scanned < this.maxPending && this.active.size < this.parallelism; scanned++) {
      let prepared: { row: RunRow; lease: Lease; execution: LocalTaskExecution } | null = null;
      let skipped = false;
      this.kernel.db.transaction(() => {
        if (this.rows("running").length >= this.parallelism) return;
        const row = this.rows("queued")[0]; if (!row) return;
        try {
          this.kernel.db.transaction(() => {
          this.current(); requireThat(row.origin === this.actor.origin, "local_origin_changed");
          const task = this.kernel.inspect(this.actor, row.task_id), execution = this.resolve(task);
          this.checkExecution(execution);
          requireThat(execution.binding_digest === row.binding_digest, "queued_execution_binding_changed");
          const lease = this.kernel.claim(this.actor, `local-claim-${row.run_id}`, row.task_id, row.expected_revision, this.leaseMs);
          this.kernel.withLease(this.actor, lease, () => {});
          this.kernel.db.sql.query("UPDATE local_runs SET state='running',owner=?,lease=? WHERE run_id=?")
            .run(this.owner, canonical(lease), row.run_id);
          prepared = { row, lease, execution };
          });
        } catch (error) {
          this.kernel.db.sql.query("UPDATE local_runs SET state='blocked',outcome=? WHERE run_id=?")
            .run(canonical({ reason: this.reason(error), retry_after: null }), row.run_id);
          skipped = true;
        }
      });
      if (!prepared) { if (skipped) continue; break; }
      const launch = prepared as { row: RunRow; lease: Lease; execution: LocalTaskExecution };
      const controller = new AbortController();
      const promise = Promise.resolve().then(() => this.perform(launch.row, launch.lease, launch.execution, controller.signal))
        .finally(() => this.active.delete(launch.row.run_id));
      // A fatal persistence error is observed by drain(), not an unhandled rejection.
      void promise.catch(error => { this.persistenceFailure = error; });
      this.active.set(launch.row.run_id, { controller, promise });
    }
  }
  private reason(error: unknown): string {
    return error instanceof RuntimeConflict ? error.code : "local_execution_failed";
  }
  private async perform(row: RunRow, lease: Lease, execution: LocalTaskExecution, signal: AbortSignal): Promise<void> {
    let state: LocalRun["state"] = "interrupted", reason = "local_execution_failed", retryAfter: number | null = null;
    const context: LocalExecutionContext = { signal, remainingMs: () => lease.lease_until - this.kernel.db.now(), assertCurrent: () => {
      this.current(); requireThat(!signal.aborted, "local_execution_interrupted");
      this.kernel.withLease(this.actor, lease, () => {}); this.checkExecution(execution);
    }, assertPublicationAuthority: () => {
      this.current(); requireThat(!signal.aborted, "local_execution_interrupted");
      this.kernel.withLease(this.actor, lease, () => {});
      const checked: unknown = execution.assertPublicationAuthority ? execution.assertPublicationAuthority() : execution.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    } };
    try {
      context.assertCurrent();
      const ready = await execution.ensureReady(`local-probe-${row.run_id}`, context);
      context.assertCurrent();
      if (ready.decision !== "cached") { state = "blocked"; reason = ready.reason; retryAfter = ready.retry_after; }
      else {
        const result = await execution.execute(lease, context);
        requireThat(result.task.task_id === row.task_id && ["done", "failed"].includes(result.task.status), "local_completion_unproven");
        const current = this.kernel.inspect(this.actor, row.task_id);
        const episode = this.kernel.db.sql.query("SELECT state FROM episodes WHERE episode_id=? AND fence=?").get(lease.episode_id, lease.fence) as { state: string } | null;
        requireThat(current.revision === result.revision && current.fence === lease.fence && current.task.status === result.task.status
          && current.active_episode === null && !current.needs_reconciliation && episode?.state === result.task.status, "local_completion_unproven");
        state = "completed"; reason = result.task.status;
      }
    } catch (error) { reason = this.reason(error); }
    if (state !== "completed") {
      // A provider may have started despite a failed callback. The kernel decides whether release is legal.
      try { this.kernel.releaseUnstarted(this.actor, `local-release-${row.run_id}`, lease, reason); state = "blocked"; }
      catch { try { this.kernel.markUnknown(this.actor, `local-unknown-${row.run_id}`, lease, reason); } catch { /* cancellation/current owner wins */ } }
      if (this.kernel.inspect(this.actor, row.task_id).task.status === "cancelled") { state = "cancelled"; reason = "task_cancelled"; }
    }
    this.kernel.db.sql.query("UPDATE local_runs SET state=?,outcome=? WHERE run_id=? AND state='running' AND owner=?")
      .run(state, canonical({ reason, retry_after: retryAfter }), row.run_id, this.owner);
  }
  async drain(): Promise<void> {
    this.tick();
    while (this.active.size) { await Promise.all([...this.active.values()].map(item => item.promise)); this.tick(); }
    if (this.persistenceFailure) throw this.persistenceFailure;
  }
  async stop(): Promise<void> {
    this.stopping = true;
    for (const item of this.active.values()) item.controller.abort();
    await Promise.allSettled([...this.active.values()].map(item => item.promise));
  }
}
