import { randomUUID } from "node:crypto";
import { RuntimeDatabase } from "./database";
import { command, requireScope } from "./commands";
import { assertProtocolSchema, type ExecutionLease } from "@controlmesh/protocol";
import { canonical, digest, identifier, legacyTask, object, requireThat, terminal, type LegacyTask, type TaskStatus } from "./value";

/** Constructed by trusted ingress, never deserialized from the request body. */
export interface Principal {
  id: string;
  origin: "human_request" | "agent_message" | "schedule" | "recovery" | "internal";
  scopes: readonly string[];
  device_id?: string;
}

interface TaskRow {
  task_id: string; principal: string; revision: number; fence: number;
  active_episode: string | null; status: TaskStatus; needs_reconciliation: number; raw: string;
}
interface EpisodeRow {
  episode_id: string; task_id: string; device_id: string; fence: number;
  state: string; lease_until: number; result: string | null;
}
export interface TaskSnapshot {
  task: LegacyTask; revision: number; fence: number;
  active_episode: string | null; needs_reconciliation: boolean;
}
export type Lease = ExecutionLease;
export interface ReconciliationEvidence {
  task: TaskSnapshot;
  episode: { episode_id: string; device_id: string; fence: number };
  effect_id: string;
  manifest_digest: string;
  manifest: Record<string, unknown>;
  observation_digest: string;
  observation: Record<string, unknown>;
}
export interface ReconciliationBinding {
  episode_id: string;
  effect_id: string;
  manifest_digest: string;
  observation_digest: string;
}

export class RuntimeKernel {
  constructor(readonly db: RuntimeDatabase) {}

  private scope(actor: Principal, scope: string): void {
    requireScope(actor, scope);
  }

  private owned(actor: Principal, task: TaskRow): void {
    requireThat(task.principal === actor.id || actor.scopes.includes("task:admin"), "task_access_denied");
  }

  private row(taskId: string): TaskRow {
    identifier(taskId);
    const task = this.db.sql.query("SELECT * FROM tasks WHERE task_id=?").get(taskId) as TaskRow | null;
    requireThat(task, "task_not_found");
    return task;
  }

  private snapshot(row: TaskRow): TaskSnapshot {
    return { task: JSON.parse(row.raw), revision: row.revision, fence: row.fence,
      active_episode: row.active_episode, needs_reconciliation: Boolean(row.needs_reconciliation) };
  }

  inspect(actor: Principal, taskId: string): TaskSnapshot {
    this.scope(actor, "task:read");
    const row = this.row(taskId);
    this.owned(actor, row);
    return this.snapshot(row);
  }

  private request<T>(actor: Principal, requestId: string, operation: string, body: unknown, run: () => T, replay: (value: T) => T = value => value): T {
    return command(this.db, actor, requestId, operation, body, run, replay);
  }

  /** Composition boundary for coordinator modules; callbacks run synchronously under the lease transaction. */
  withLease<T>(actor: Principal, proof: Lease, run: () => T): T {
    this.scope(actor, "task:execute");
    return this.db.transaction(() => { this.lease(actor, proof); return run(); });
  }

  private revision(task: TaskRow, expected: number): void {
    requireThat(Number.isSafeInteger(expected) && task.revision === expected, "revision_conflict");
  }

  private event(actor: Principal, task: TaskRow, kind: string, payload: unknown): void {
    this.db.sql.query("INSERT INTO events (task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,?,?,?,?,?,?,?)")
      .run(task.task_id, kind, task.revision, task.fence, actor.id, actor.origin, this.db.now(), canonical(payload));
  }

  private save(task: TaskRow): void {
    task.revision += 1;
    const raw = JSON.parse(task.raw) as LegacyTask;
    raw.status = task.status;
    task.raw = canonical(raw);
    this.db.sql.query("UPDATE tasks SET revision=?,fence=?,active_episode=?,status=?,needs_reconciliation=?,raw=? WHERE task_id=?")
      .run(task.revision, task.fence, task.active_episode, task.status, task.needs_reconciliation, task.raw, task.task_id);
  }

  submit(actor: Principal, requestId: string, task: LegacyTask): TaskSnapshot {
    this.scope(actor, "task:create");
    legacyTask(task);
    requireThat(task.status === "waiting", "new_task_must_wait_for_admission");
    return this.request(actor, requestId, "submit", task, () => {
      requireThat(!this.db.sql.query("SELECT 1 FROM tasks WHERE task_id=?").get(task.task_id), "task_id_conflict");
      this.db.sql.query("INSERT INTO tasks (task_id,principal,revision,status,raw) VALUES (?,?,1,?,?)")
        .run(task.task_id, actor.id, task.status, canonical(task));
      const row = this.row(task.task_id);
      this.event(actor, row, "task.created", {});
      return this.snapshot(row);
    });
  }

  claim(actor: Principal, requestId: string, taskId: string, expectedRevision: number, ttlMs: number): Lease {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(taskId));
    identifier(actor.device_id);
    requireThat(Number.isSafeInteger(ttlMs) && ttlMs >= 100 && ttlMs <= 300_000, "invalid_lease_ttl");
    return this.request(actor, requestId, "claim", { taskId, expectedRevision, ttlMs }, () => {
      const task = this.row(taskId);
      this.owned(actor, task);
      this.revision(task, expectedRevision);
      requireThat(!terminal.has(task.status) && !task.needs_reconciliation, "task_not_admitted");
      const now = this.db.now();
      if (task.active_episode) {
        const previous = this.db.sql.query("SELECT * FROM episodes WHERE episode_id=?").get(task.active_episode) as EpisodeRow;
        requireThat(previous.lease_until <= now, "lease_busy");
        requireThat(previous.state === "leased", "reconciliation_required");
        this.db.sql.query("UPDATE episodes SET state='expired' WHERE episode_id=?").run(previous.episode_id);
      }
      task.fence += 1;
      task.active_episode = randomUUID();
      task.status = "running";
      const lease: Lease = { schema_version: "controlmesh.execution_lease.v1", task_id: taskId, episode_id: task.active_episode, device_id: actor.device_id!, fence: task.fence, lease_until: now + ttlMs };
      assertProtocolSchema<Lease>("execution-lease.schema.json", lease);
      this.db.sql.query("INSERT INTO episodes (episode_id,task_id,device_id,fence,state,lease_until) VALUES (?,?,?,?,'leased',?)")
        .run(lease.episode_id, taskId, lease.device_id, lease.fence, lease.lease_until);
      this.save(task);
      this.event(actor, task, "episode.claimed", lease);
      return lease;
    });
  }

  private lease(actor: Principal, proof: Lease): { task: TaskRow; episode: EpisodeRow } {
    assertProtocolSchema<Lease>("execution-lease.schema.json", proof);
    requireThat(actor.device_id === proof.device_id, "device_mismatch");
    const task = this.row(proof.task_id);
    this.owned(actor, task);
    requireThat(!terminal.has(task.status) && !task.needs_reconciliation, "task_not_executable");
    requireThat(task.active_episode === proof.episode_id && task.fence === proof.fence, "stale_fence");
    const episode = this.db.sql.query("SELECT * FROM episodes WHERE episode_id=?").get(proof.episode_id) as EpisodeRow | null;
    requireThat(episode && episode.device_id === actor.device_id && episode.fence === proof.fence, "lease_mismatch");
    requireThat(episode.lease_until > this.db.now(), "lease_expired");
    requireThat(episode.state === "leased" || episode.state === "running", "episode_not_executable");
    return { task, episode };
  }

  start(actor: Principal, requestId: string, proof: Lease): TaskSnapshot {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    return this.request(actor, requestId, "start", proof, () => {
      const { task, episode } = this.lease(actor, proof);
      requireThat(episode.state === "leased", "episode_already_started");
      this.db.sql.query("UPDATE episodes SET state='running' WHERE episode_id=?").run(proof.episode_id);
      this.save(task);
      this.event(actor, task, "episode.started", { episode_id: proof.episode_id });
      return this.snapshot(task);
    });
  }

  renew(actor: Principal, requestId: string, proof: Lease, ttlMs: number): Lease {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    requireThat(Number.isSafeInteger(ttlMs) && ttlMs >= 100 && ttlMs <= 300_000, "invalid_lease_ttl");
    return this.request(actor, requestId, "renew", { proof, ttlMs }, () => {
      this.lease(actor, proof);
      const until = this.db.now() + ttlMs;
      this.db.sql.query("UPDATE episodes SET lease_until=MAX(lease_until,?) WHERE episode_id=?").run(until, proof.episode_id);
      const row = this.db.sql.query("SELECT lease_until FROM episodes WHERE episode_id=?").get(proof.episode_id) as { lease_until: number };
      return { ...proof, lease_until: row.lease_until };
    });
  }

  finish(actor: Principal, requestId: string, proof: Lease, outcome: "done" | "failed", result: Record<string, unknown>): TaskSnapshot {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    requireThat(outcome === "done" || outcome === "failed", "invalid_outcome");
    return this.request(actor, requestId, "finish", { proof, outcome, result }, () => {
      const { task, episode } = this.lease(actor, proof);
      requireThat(episode.state === "running", "episode_not_started");
      requireThat(!this.db.sql.query("SELECT 1 FROM effects WHERE episode_id=? AND state!='confirmed'").get(proof.episode_id), "unresolved_effects");
      this.db.sql.query("UPDATE episodes SET state=?,result=? WHERE episode_id=?").run(outcome, canonical(result), proof.episode_id);
      task.status = outcome;
      task.active_episode = null;
      const raw = JSON.parse(task.raw) as LegacyTask;
      raw.completed_at = this.db.now() / 1000;
      task.raw = canonical(raw);
      this.save(task);
      this.event(actor, task, `task.${outcome}`, { episode_id: proof.episode_id, result });
      return this.snapshot(task);
    });
  }

  cancel(actor: Principal, requestId: string, taskId: string, expectedRevision: number): TaskSnapshot {
    this.scope(actor, "task:cancel");
    this.owned(actor, this.row(taskId));
    return this.request(actor, requestId, "cancel", { taskId, expectedRevision }, () => {
      const task = this.row(taskId);
      this.owned(actor, task);
      this.revision(task, expectedRevision);
      requireThat(!terminal.has(task.status), "task_already_terminal");
      if (task.active_episode) {
        this.db.sql.query("UPDATE episodes SET state='cancelled',lease_until=0 WHERE episode_id=?").run(task.active_episode);
        this.db.sql.query("UPDATE effects SET state='unknown' WHERE episode_id=? AND state='dispatched'").run(task.active_episode);
      }
      task.status = "cancelled";
      task.fence += 1;
      task.active_episode = null;
      this.save(task);
      this.event(actor, task, "task.cancelled", {});
      return this.snapshot(task);
    });
  }

  resume(actor: Principal, requestId: string, taskId: string, expectedRevision: number, prompt: string): TaskSnapshot {
    this.scope(actor, "task:resume");
    this.owned(actor, this.row(taskId));
    requireThat(typeof prompt === "string" && prompt.length > 0 && Buffer.byteLength(prompt) <= 32_768, "invalid_resume_prompt");
    return this.request(actor, requestId, "resume", { taskId, expectedRevision, prompt }, () => {
      const task = this.row(taskId);
      this.owned(actor, task);
      this.revision(task, expectedRevision);
      requireThat((task.status === "done" || task.status === "failed") && !task.needs_reconciliation, "task_not_resumable");
      requireThat(!this.db.sql.query("SELECT 1 FROM effects WHERE task_id=? AND state!='confirmed'").get(taskId), "unresolved_effects");
      const episode = this.db.sql.query("SELECT episode_id,result FROM episodes WHERE task_id=? ORDER BY fence DESC LIMIT 1").get(taskId) as { episode_id: string; result: string | null } | null;
      const raw = JSON.parse(task.raw) as LegacyTask;
      const result = episode?.result ? JSON.parse(episode.result) : {};
      // Native evidence is issued by the trusted worker; its current revision is revalidated at the next dispatch.
      if (result.native_session) raw.native_session = result.native_session;
      raw.prompt = prompt;
      raw.completed_at = null;
      task.raw = canonical(raw);
      task.status = "waiting";
      task.active_episode = null;
      this.save(task);
      this.event(actor, task, "task.resumed", { previous_episode: episode?.episode_id ?? null, prompt_digest: digest(prompt) });
      return this.snapshot(task);
    });
  }

  markUnknown(actor: Principal, requestId: string, proof: Lease, reason: string): TaskSnapshot {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    requireThat(/^[a-z0-9_]{1,96}$/.test(reason), "invalid_unknown_reason");
    return this.request(actor, requestId, "outcome_unknown", { proof, reason }, () => {
      const { task, episode } = this.lease(actor, proof);
      requireThat(episode.state === "running", "episode_not_started");
      this.db.sql.query("UPDATE episodes SET state='unknown',lease_until=0 WHERE episode_id=?").run(proof.episode_id);
      this.db.sql.query("UPDATE effects SET state='unknown' WHERE episode_id=? AND state='dispatched'").run(proof.episode_id);
      task.status = "stale";
      task.needs_reconciliation = 1;
      task.fence += 1;
      this.save(task);
      this.event(actor, task, "episode.outcome_unknown", { episode_id: proof.episode_id, reason });
      return this.snapshot(task);
    });
  }

  /** A preparation failure can release only an unstarted lease with no external effect. */
  releaseUnstarted(actor: Principal, requestId: string, proof: Lease, reason = "admission_unavailable"): TaskSnapshot {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    requireThat(/^[a-z0-9_]{1,96}$/.test(reason), "invalid_admission_reason");
    return this.request(actor, requestId, "release_unstarted", { proof, reason }, () => {
      const { task, episode } = this.lease(actor, proof);
      requireThat(episode.state === "leased" && !this.db.sql.query("SELECT 1 FROM effects WHERE episode_id=?").get(proof.episode_id), "started_episode_cannot_release");
      this.db.sql.query("UPDATE episodes SET state='released' WHERE episode_id=?").run(proof.episode_id);
      task.active_episode = null; task.status = "waiting"; task.fence += 1;
      this.save(task); this.event(actor, task, "episode.admission_released", { episode_id: proof.episode_id, reason });
      return this.snapshot(task);
    });
  }

  recoverExpired(actor: Principal): string[] {
    this.scope(actor, "task:reconcile");
    requireThat(actor.scopes.includes("task:admin"), "scope_denied");
    return this.db.transaction(() => {
      const now = this.db.now();
      const idle = this.db.sql.query("SELECT t.* FROM tasks t JOIN episodes e ON t.active_episode=e.episode_id WHERE e.lease_until<=? AND e.state='leased'").all(now) as TaskRow[];
      for (const task of idle) {
        requireThat(!this.db.sql.query("SELECT 1 FROM effects WHERE episode_id=?").get(task.active_episode), "unstarted_episode_has_effects");
        const episode = task.active_episode;
        this.db.sql.query("UPDATE episodes SET state='expired' WHERE episode_id=?").run(episode);
        task.active_episode = null; task.status = "waiting"; task.fence += 1;
        this.save(task); this.event(actor, task, "episode.admission_expired", { episode_id: episode });
      }
      const rows = this.db.sql.query("SELECT t.* FROM tasks t JOIN episodes e ON t.active_episode=e.episode_id WHERE e.lease_until<=? AND e.state='running'").all(now) as TaskRow[];
      for (const task of rows) {
        this.db.sql.query("UPDATE episodes SET state='unknown' WHERE episode_id=?").run(task.active_episode);
        this.db.sql.query("UPDATE effects SET state='unknown' WHERE episode_id=? AND state='dispatched'").run(task.active_episode);
        task.status = "stale";
        task.needs_reconciliation = 1;
        task.fence += 1;
        this.save(task);
        this.event(actor, task, "episode.outcome_unknown", { episode_id: task.active_episode });
      }
      return [...idle, ...rows].map(row => row.task_id);
    });
  }

  /** Recorded BEFORE handing an operation to an external provider. This is not a distributed exactly-once guarantee. */
  dispatchEffect(actor: Principal, requestId: string, proof: Lease, effectId: string, intent: unknown, manifest?: Record<string, unknown>): { effect_id: string; dispatch_permitted: boolean } {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    identifier(effectId);
    const manifestText = manifest === undefined ? null : canonical(manifest);
    requireThat(manifestText === null || Buffer.byteLength(manifestText) <= 16 * 1024 * 1024, "execution_manifest_too_large");
    // Omitted manifests preserve pre-v5 request identity; old receipts are never retrofitted as evidence.
    return this.request<{ effect_id: string; dispatch_permitted: boolean }>(actor, requestId, "dispatch_effect", { proof, effectId, intent,
      ...(manifest === undefined ? {} : { manifest_digest: digest(manifest) }) }, () => {
      const { task, episode } = this.lease(actor, proof);
      requireThat(episode.state === "running", "episode_not_started");
      requireThat(!this.db.sql.query("SELECT 1 FROM effects WHERE effect_id=?").get(effectId), "effect_id_conflict");
      this.db.sql.query("INSERT INTO effects (effect_id,task_id,episode_id,fence,digest,state) VALUES (?,?,?,?,?,'dispatched')")
        .run(effectId, proof.task_id, proof.episode_id, proof.fence, digest(intent));
      if (manifestText !== null) this.db.sql.query("INSERT INTO execution_manifests VALUES (?,?,?)").run(effectId, digest(manifest), manifestText);
      this.event(actor, task, "effect.dispatched", { effect_id: effectId, intent_digest: digest(intent) });
      return { effect_id: effectId, dispatch_permitted: true };
    }, value => ({ ...value, dispatch_permitted: false }));
  }

  confirmEffect(actor: Principal, requestId: string, proof: Lease, effectId: string, result: unknown): { effect_id: string } {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    return this.request(actor, requestId, "confirm_effect", { proof, effectId, result }, () => {
      const { task } = this.lease(actor, proof);
      const changed = this.db.sql.query("UPDATE effects SET state='confirmed',result=? WHERE effect_id=? AND episode_id=? AND fence=? AND state='dispatched'")
        .run(canonical(result), effectId, proof.episode_id, proof.fence);
      requireThat(changed.changes === 1, "effect_not_pending");
      this.event(actor, task, "effect.confirmed", { effect_id: effectId, result });
      return { effect_id: effectId };
    });
  }

  recordEffectObservation(actor: Principal, requestId: string, proof: Lease, effectId: string, observation: unknown): { effect_id: string } {
    this.scope(actor, "task:execute");
    this.owned(actor, this.row(proof.task_id));
    requireThat(Buffer.byteLength(canonical(observation)) <= 4 * 1024 * 1024, "effect_observation_too_large");
    return this.request(actor, requestId, "observe_effect", { proof, effectId, observation }, () => {
      const { task } = this.lease(actor, proof);
      const changed = this.db.sql.query("UPDATE effects SET result=? WHERE effect_id=? AND episode_id=? AND fence=? AND state='dispatched' AND result IS NULL")
        .run(canonical(observation), effectId, proof.episode_id, proof.fence);
      requireThat(changed.changes === 1, "effect_observation_not_pending");
      this.db.sql.query("INSERT INTO effect_observations VALUES (?,?,?)").run(effectId, digest(observation), canonical(observation));
      this.event(actor, task, "effect.observed", { effect_id: effectId, observation_digest: digest(observation), accepted: false });
      return { effect_id: effectId };
    });
  }

  private reconcileScope(actor: Principal, taskId: string): void {
    this.scope(actor, "task:reconcile");
    requireThat(["human_request", "recovery", "internal"].includes(actor.origin), "trusted_reconciliation_required");
    identifier(actor.device_id);
    this.owned(actor, this.row(taskId));
  }

  inspectReconciliation(actor: Principal, taskId: string, expectedRevision: number, effectId: string): ReconciliationEvidence {
    this.reconcileScope(actor, taskId);
    identifier(effectId);
    return this.db.transaction(() => {
      const task = this.row(taskId);
      this.revision(task, expectedRevision);
      requireThat(task.status === "stale" && task.needs_reconciliation && task.active_episode, "task_not_reconcilable");
      const episode = this.db.sql.query("SELECT * FROM episodes WHERE episode_id=?").get(task.active_episode) as EpisodeRow | null;
      requireThat(episode && episode.state === "unknown" && episode.device_id === actor.device_id && task.fence > episode.fence, "reconciliation_episode_mismatch");
      const effect = this.db.sql.query("SELECT state FROM effects WHERE effect_id=? AND episode_id=? AND task_id=? AND fence=?").get(effectId, episode.episode_id, taskId, episode.fence) as { state: string } | null;
      requireThat(effect?.state === "unknown", "effect_not_reconcilable");
      const row = (table: string, missing: string): { digest: string; payload: Record<string, unknown> } => {
        const value = this.db.sql.query(`SELECT digest,payload FROM ${table} WHERE effect_id=?`).get(effectId) as { digest: string; payload: string } | null;
        requireThat(value && Buffer.byteLength(value.payload) <= 16 * 1024 * 1024, missing);
        const payload = JSON.parse(value.payload) as Record<string, unknown>;
        requireThat(digest(payload) === value.digest, "reconciliation_evidence_corrupt");
        return { digest: value.digest, payload };
      };
      const manifest = row("execution_manifests", "dispatch_manifest_unavailable");
      const observation = row("effect_observations", "native_observation_unavailable");
      return { task: this.snapshot(task), episode: { episode_id: episode.episode_id, device_id: episode.device_id, fence: episode.fence }, effect_id: effectId,
        manifest_digest: manifest.digest, manifest: manifest.payload, observation_digest: observation.digest, observation: observation.payload };
    });
  }

  /** Trusted verifier runs synchronously in the acceptance transaction. No worker/body can submit a done flag here. */
  reconcileEffect(actor: Principal, requestId: string, taskId: string, expectedRevision: number, binding: ReconciliationBinding,
    verify: (evidence: ReconciliationEvidence) => Record<string, unknown>): TaskSnapshot {
    this.reconcileScope(actor, taskId);
    return this.request(actor, requestId, "reconcile_effect", { taskId, expectedRevision, binding }, () => {
      const evidence = this.inspectReconciliation(actor, taskId, expectedRevision, binding.effect_id);
      requireThat(evidence.episode.episode_id === binding.episode_id && evidence.manifest_digest === binding.manifest_digest && evidence.observation_digest === binding.observation_digest, "reconciliation_evidence_changed");
      requireThat(!this.db.sql.query("SELECT 1 FROM effects WHERE episode_id=? AND effect_id!=? AND state!='confirmed'").get(binding.episode_id, binding.effect_id), "other_effects_unresolved");
      const accepted = verify(evidence);
      if (accepted && typeof accepted.then === "function") { void Promise.resolve(accepted).catch(() => {}); requireThat(false, "verifier_must_be_synchronous"); }
      requireThat(object(accepted), "invalid_reconciled_result");
      const result = canonical(accepted);
      requireThat(Buffer.byteLength(result) <= 4 * 1024 * 1024, "reconciled_result_too_large");
      // A trusted verifier may call other state APIs; it cannot override cancellation or replace the reviewed inputs.
      const current = this.inspectReconciliation(actor, taskId, expectedRevision, binding.effect_id);
      requireThat(current.manifest_digest === binding.manifest_digest && current.observation_digest === binding.observation_digest, "reconciliation_evidence_changed");
      this.db.sql.query("UPDATE effects SET state='confirmed',result=? WHERE effect_id=?").run(result, binding.effect_id);
      this.db.sql.query("UPDATE episodes SET state='done',lease_until=0,result=? WHERE episode_id=?").run(result, binding.episode_id);
      const task = this.row(taskId);
      task.status = "done"; task.needs_reconciliation = 0; task.active_episode = null;
      const raw = JSON.parse(task.raw) as LegacyTask;
      raw.completed_at = this.db.now() / 1000; task.raw = canonical(raw);
      this.save(task);
      this.event(actor, task, "effect.reconciled", { ...binding, acceptance_digest: digest(accepted) });
      this.event(actor, task, "task.done", { episode_id: binding.episode_id, reconciled: true, result: accepted });
      return this.snapshot(task);
    });
  }
}
