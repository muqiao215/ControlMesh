import { randomUUID } from "node:crypto";
import { assertProtocolSchema, type DeliveryReceipt, type DeliveryTarget, type TerminalDelivery } from "@controlmesh/protocol";
import { command, requireScope } from "./commands";
import { decodeExecutionContext } from "./execution-context";
import { decodeToolGrant } from "./execution-grants";
import type { Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, identifier, object, requireThat, RuntimeConflict } from "./value";

export interface DeliveryContext { signal: AbortSignal; not_before?: number; assertCurrent(): void }
export interface PreparedDelivery {
  send(envelope: TerminalDelivery, context: DeliveryContext): Promise<DeliveryReceipt>;
  inspect(envelope: TerminalDelivery, remoteMessageId: string, context: DeliveryContext): Promise<DeliveryReceipt>;
}
/** Trusted registration. prepare may obtain credentials but must not send a message. */
export interface DeliveryAdapter {
  readonly adapter_id: string; readonly transport: string; readonly binding_digest: string;
  assertCurrent(): void;
  /** Explicit operator retry may clear a credential failure latch; never invoked by drain. */
  retryPreparation?(): void;
  prepare(envelope: TerminalDelivery, context: DeliveryContext): Promise<PreparedDelivery>;
}
export interface DeliveryView {
  delivery_id: string; task_id: string; event_seq: number;
  state: "pending" | "dispatching" | "sent" | "unknown" | "blocked";
  reason: string | null; receipt: DeliveryReceipt | null; observed_receipt: DeliveryReceipt | null;
}
interface Route {
  task_id: string; principal: string; adapter_id: string; adapter_digest: string;
  binding: string; digest: string; first_event: number; active: number;
}
interface DeliveryRow extends Omit<DeliveryView, "receipt" | "observed_receipt"> {
  principal: string; route_digest: string; envelope: string; envelope_digest: string;
  attempt_id: string | null; attempt_started: number | null; attempt_until: number | null; observation: string | null; receipt: string | null;
}
interface RouteBinding {
  target: DeliveryTarget; execution_context: TerminalDelivery["execution_context"];
  authority_digest: string; output_policy: TerminalDelivery["output_policy"];
}

/** Durable terminal-event projection and transport outcome owner. Never invokes an Agent. */
export class DeliveryOutbox {
  private readonly actor: Principal;
  private readonly adapters = new Map<string, DeliveryAdapter>();
  private stopping = false;
  private readonly active = new Map<AbortController, Promise<void>>();
  constructor(readonly kernel: RuntimeKernel, actor: Principal, adapters: readonly DeliveryAdapter[],
    private readonly authorize: () => void, private readonly timeoutMs = 30_000) {
    this.actor = structuredClone(actor);
    requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 100 && timeoutMs <= 60_000, "invalid_delivery_timeout");
    for (const adapter of adapters) {
      identifier(adapter.adapter_id);
      requireThat(!this.adapters.has(adapter.adapter_id) && /^[a-f0-9]{64}$/.test(adapter.binding_digest)
        && /^[a-z0-9_-]{1,32}$/.test(adapter.transport), "invalid_delivery_adapter");
      this.adapters.set(adapter.adapter_id, adapter);
    }
    this.current("delivery:read");
  }
  private current(scope: string): void {
    requireThat(!this.stopping, "delivery_stopping");
    requireScope(this.actor, scope);
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private track(controller: AbortController): () => void {
    let finish!: () => void;
    this.active.set(controller, new Promise<void>(resolve => { finish = resolve; }));
    return () => { this.active.delete(controller); finish(); };
  }
  async stop(): Promise<void> {
    this.stopping = true;
    const active = [...this.active];
    for (const [controller] of active) controller.abort();
    await Promise.all(active.map(([, done]) => done));
  }
  private adapterCurrent(adapter: DeliveryAdapter): void {
    const checked: unknown = adapter.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private authority(taskId: string): Omit<RouteBinding, "output_policy"> {
    const { task } = this.kernel.inspect(this.actor, taskId);
    const grant = decodeToolGrant(task.tool_grant), source = decodeExecutionContext(task.execution_context);
    requireThat(source.source_scope !== "legacy_compat", "delivery_source_unclassified");
    const target = { transport: grant.reply_transport, chat_id: grant.reply_chat, topic_id: grant.reply_topic, thread_id: grant.reply_thread };
    assertProtocolSchema<DeliveryTarget>("delivery-target.schema.json", target);
    requireThat(target.chat_id === String(task.chat_id) && target.transport === source.transport, "delivery_target_changed");
    return { target, execution_context: { ...source }, authority_digest: digest({ grant, source }) };
  }
  private route(taskId: string): Route {
    const row = this.kernel.db.sql.query("SELECT * FROM delivery_routes WHERE task_id=? AND principal=?").get(taskId, this.actor.id) as Route | null;
    requireThat(row, "delivery_route_unavailable"); return row;
  }
  private routeBinding(taskId: string): { row: Route; binding: RouteBinding } {
    const row = this.route(taskId), binding = JSON.parse(row.binding) as RouteBinding;
    requireThat(row.active === 1, "delivery_route_revoked");
    requireThat(digest({ adapter_id: row.adapter_id, adapter_digest: row.adapter_digest, binding }) === row.digest, "delivery_route_corrupted");
    const { output_policy: _policy, ...authority } = binding;
    requireThat(digest(authority) === digest(this.authority(taskId)), "delivery_authority_changed");
    return { row, binding };
  }
  private checkedRoute(taskId: string): { row: Route; binding: RouteBinding; adapter: DeliveryAdapter } {
    const { row, binding } = this.routeBinding(taskId);
    const adapter = this.adapters.get(row.adapter_id);
    requireThat(adapter && adapter.binding_digest === row.adapter_digest && adapter.transport === binding.target.transport, "delivery_adapter_changed");
    this.adapterCurrent(adapter);
    return { row, binding, adapter };
  }
  bindTask(requestId: string, taskId: string, expectedRevision: number, adapterId: string,
    outputPolicy: TerminalDelivery["output_policy"] = "summarized_only"): void {
    this.current("delivery:configure");
    requireThat(this.actor.origin === "human_request" || this.actor.origin === "internal", "delivery_configuration_origin_denied");
    identifier(taskId); identifier(adapterId);
    requireThat(["summarized_only", "full"].includes(outputPolicy), "invalid_delivery_output_policy");
    command(this.kernel.db, this.actor, requestId, "delivery.bind", { taskId, expectedRevision, adapterId, outputPolicy }, () => {
      this.current("delivery:configure");
      const task = this.kernel.inspect(this.actor, taskId), adapter = this.adapters.get(adapterId);
      requireThat(task.revision === expectedRevision && task.task.status === "waiting" && !task.active_episode, "delivery_binding_requires_waiting_task");
      requireThat(adapter, "delivery_adapter_unavailable"); this.adapterCurrent(adapter);
      const binding = { ...this.authority(taskId), output_policy: outputPolicy };
      requireThat(binding.target.transport === adapter.transport, "delivery_transport_mismatch");
      const hash = digest({ adapter_id: adapterId, adapter_digest: adapter.binding_digest, binding });
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM delivery_routes WHERE task_id=?").get(taskId), "delivery_route_already_bound");
      const last = this.kernel.db.sql.query("SELECT COALESCE(MAX(seq),0) AS n FROM events").get() as { n: number };
      this.kernel.db.sql.query("INSERT INTO delivery_routes VALUES (?,?,?,?,?,?,?,1)")
        .run(taskId, this.actor.id, adapterId, adapter.binding_digest, canonical(binding), hash, last.n + 1);
      return { bound: true };
    }, value => { this.current("delivery:configure"); this.checkedRoute(taskId); return value; });
  }
  revokeTask(requestId: string, taskId: string): void {
    this.current("delivery:configure");
    command(this.kernel.db, this.actor, requestId, "delivery.revoke", { taskId }, () => {
      this.kernel.inspect(this.actor, taskId); this.route(taskId);
      this.kernel.db.sql.query("UPDATE delivery_routes SET active=0 WHERE task_id=?").run(taskId); return { revoked: true };
    });
  }
  /** An accepted event is already durable; projection can safely catch up after any restart. */
  project(limit = 32): number {
    this.current("delivery:project");
    requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 128, "invalid_delivery_limit");
    return this.kernel.db.transaction(() => {
      const open = this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM delivery_outbox WHERE principal=? AND state!='sent'").get(this.actor.id) as { n: number };
      limit = Math.min(limit, Math.max(0, 128 - open.n));
      if (limit === 0) return 0;
      const events = this.kernel.db.sql.query(`SELECT e.* FROM events e JOIN delivery_routes r ON r.task_id=e.task_id
        WHERE r.principal=? AND r.active=1 AND e.seq>=r.first_event AND e.kind IN ('task.done','task.failed','task.cancelled')
        AND NOT EXISTS (SELECT 1 FROM delivery_outbox d WHERE d.event_seq=e.seq) ORDER BY e.seq LIMIT ?`).all(this.actor.id, limit) as
        { seq: number; task_id: string; revision: number; fence: number; origin: Principal["origin"]; at: number; kind: string; payload: string }[];
      for (const event of events) {
        const { row, binding } = this.routeBinding(event.task_id), payload = JSON.parse(event.payload);
        const result = object(payload.result) ? payload.result : {};
        const status = event.kind.slice(5) as TerminalDelivery["status"];
        const fallback = status === "failed" ? `Background task \`${event.task_id}\` failed. Check task artifacts for details.`
          : status === "cancelled" ? `Background task \`${event.task_id}\` was cancelled.`
          : `Background task \`${event.task_id}\` completed. Check task artifacts for details.`;
        const summary = typeof result.delivery_text === "string" ? result.delivery_text : "";
        const raw = typeof result.text === "string" ? result.text : typeof result.result_text === "string" ? result.result_text : "";
        const envelope: TerminalDelivery = { schema_version: "controlmesh.terminal_delivery.v1", delivery_id: digest([event.seq, row.digest]),
          task_id: event.task_id, event_seq: event.seq, task_revision: event.revision, fence: event.fence, status, origin: "task_result",
          command_origin: event.origin, execution_context: binding.execution_context, target: binding.target,
          text: summary || (binding.output_policy === "full" ? raw : "") || fallback, output_policy: binding.output_policy, created_at: event.at };
        assertProtocolSchema("terminal-delivery.schema.json", envelope);
        requireThat(Buffer.byteLength(envelope.text) <= 65536, "delivery_text_too_large");
        this.kernel.db.sql.query(`INSERT INTO delivery_outbox
          (delivery_id,event_seq,task_id,principal,route_digest,envelope,envelope_digest,state,created_at) VALUES (?,?,?,?,?,?,?,'pending',?)`)
          .run(envelope.delivery_id, event.seq, event.task_id, this.actor.id, row.digest, canonical(envelope), digest(envelope), this.kernel.db.now());
      }
      return events.length;
    });
  }
  private row(id: string): DeliveryRow {
    identifier(id);
    const row = this.kernel.db.sql.query("SELECT * FROM delivery_outbox WHERE delivery_id=? AND principal=?").get(id, this.actor.id) as DeliveryRow | null;
    requireThat(row, "delivery_not_found"); this.kernel.inspect(this.actor, row.task_id); return row;
  }
  inspect(id: string): DeliveryView {
    this.current("delivery:read"); const row = this.row(id);
    return { delivery_id: id, task_id: row.task_id, event_seq: row.event_seq, state: row.state, reason: row.reason,
      receipt: row.receipt ? JSON.parse(row.receipt) : null, observed_receipt: row.observation ? JSON.parse(row.observation) : null };
  }
  status(): Record<DeliveryView["state"], number> {
    this.current("delivery:read");
    const counts = { pending: 0, dispatching: 0, sent: 0, unknown: 0, blocked: 0 };
    for (const row of this.kernel.db.sql.query("SELECT state,COUNT(*) AS n FROM delivery_outbox WHERE principal=? GROUP BY state")
      .all(this.actor.id) as { state: DeliveryView["state"]; n: number }[]) counts[row.state] = row.n;
    return counts;
  }
  list(taskId: string): DeliveryView[] {
    this.current("delivery:read"); this.kernel.inspect(this.actor, taskId);
    return (this.kernel.db.sql.query("SELECT delivery_id FROM delivery_outbox WHERE task_id=? AND principal=? ORDER BY event_seq LIMIT 128")
      .all(taskId, this.actor.id) as { delivery_id: string }[]).map(row => this.inspect(row.delivery_id));
  }
  private evidence(row: DeliveryRow): { envelope: TerminalDelivery; adapter: DeliveryAdapter } {
    const { row: route, adapter } = this.checkedRoute(row.task_id);
    requireThat(route.digest === row.route_digest, "delivery_route_changed");
    const envelope = JSON.parse(row.envelope) as TerminalDelivery;
    assertProtocolSchema("terminal-delivery.schema.json", envelope);
    requireThat(digest(envelope) === row.envelope_digest && envelope.delivery_id === row.delivery_id
      && envelope.task_id === row.task_id && envelope.event_seq === row.event_seq, "delivery_evidence_corrupted");
    return { envelope, adapter };
  }
  private accept(row: DeliveryRow, receipt: DeliveryReceipt): void {
    const { envelope, adapter } = this.evidence(row);
    assertProtocolSchema("delivery-receipt.schema.json", receipt);
    requireThat(receipt.delivery_id === row.delivery_id && receipt.envelope_digest === row.envelope_digest
      && receipt.target_digest === digest(envelope.target) && receipt.adapter_digest === adapter.binding_digest, "delivery_receipt_mismatch");
    if (row.state === "sent") { requireThat(digest(JSON.parse(row.receipt!)) === digest(receipt), "delivery_receipt_conflict"); return; }
    requireThat(["dispatching", "unknown"].includes(row.state), "delivery_not_dispatched");
    requireThat(row.observation && digest(JSON.parse(row.observation)) === digest(receipt), "delivery_observation_required");
    this.kernel.db.sql.query("INSERT INTO transport_receipts VALUES (?,?,?)")
      .run(receipt.adapter_digest, receipt.remote_message_id, row.delivery_id);
    this.kernel.db.sql.query("UPDATE delivery_outbox SET state='sent',receipt=?,reason=NULL WHERE delivery_id=?").run(canonical(receipt), row.delivery_id);
  }
  recover(): number {
    this.current("delivery:send");
    return this.kernel.db.transaction(() => this.kernel.db.sql.query(`UPDATE delivery_outbox SET state='unknown',reason='delivery_acknowledgement_missing'
      WHERE principal=? AND state='dispatching' AND attempt_until<=?`).run(this.actor.id, this.kernel.db.now()).changes);
  }
  async deliver(id: string): Promise<DeliveryView> {
    this.current("delivery:send"); const original = this.row(id);
    if (original.state !== "pending") return this.inspect(id);
    const prior = () => this.kernel.db.sql.query("SELECT 1 FROM delivery_outbox WHERE task_id=? AND event_seq<? AND state!='sent' LIMIT 1")
      .get(original.task_id, original.event_seq);
    const capacity = () => (this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM delivery_outbox WHERE state='dispatching'").get() as { n: number }).n < 4;
    if (prior() || !capacity()) return this.inspect(id);
    let attempted = false;
    let started = 0;
    const attempt = randomUUID(), abort = new AbortController(), timeout = setTimeout(() => abort.abort(), this.timeoutMs);
    const finished = this.track(abort);
    const current = () => { this.current("delivery:send"); requireThat(!abort.signal.aborted, "delivery_interrupted"); this.evidence(this.row(id)); };
    const timer = setInterval(() => { try { current(); } catch { abort.abort(); } }, 50);
    try {
      current(); const { envelope, adapter } = this.evidence(original);
      const prepared = await adapter.prepare(structuredClone(envelope), { signal: abort.signal, assertCurrent: current });
      const admitted = this.kernel.db.transaction(() => {
        current(); if (this.row(id).state !== "pending" || prior() || !capacity()) return false;
        started = this.kernel.db.now();
        this.kernel.db.sql.query("UPDATE delivery_outbox SET state='dispatching',attempt_id=?,attempt_started=?,attempt_until=?,reason=NULL WHERE delivery_id=?")
          .run(attempt, started, started + this.timeoutMs, id); return true;
      });
      if (!admitted) return this.inspect(id);
      attempted = true; current();
      const receipt = await prepared.send(structuredClone(envelope), { signal: abort.signal, not_before: started, assertCurrent: current });
      assertProtocolSchema("delivery-receipt.schema.json", receipt);
      requireThat(receipt.delivery_id === id && receipt.envelope_digest === original.envelope_digest
        && receipt.target_digest === digest(envelope.target) && receipt.adapter_digest === adapter.binding_digest, "delivery_receipt_mismatch");
      // Preserve the original remote acknowledgement separately from accepting the outcome.
      this.kernel.db.sql.query("UPDATE delivery_outbox SET observation=? WHERE delivery_id=? AND attempt_id=? AND observation IS NULL")
        .run(canonical(receipt), id, attempt);
      this.kernel.db.transaction(() => { current(); const row = this.row(id); requireThat(row.attempt_id === attempt, "delivery_attempt_changed"); this.accept(row, receipt); });
    } catch (error) {
      const reason = error instanceof RuntimeConflict ? error.code : "delivery_unavailable";
      this.kernel.db.sql.query(`UPDATE delivery_outbox SET state=?,reason=? WHERE delivery_id=? AND principal=?
        AND ${attempted ? "state IN ('dispatching','unknown') AND attempt_id=?" : "state='pending'"}`)
        .run(attempted ? "unknown" : "blocked", reason, id, this.actor.id, ...(attempted ? [attempt] : []));
    } finally { clearTimeout(timeout); clearInterval(timer); finished(); }
    return this.inspect(id);
  }
  async drain(): Promise<void> {
    this.current("delivery:send"); this.project(); this.recover();
    const rows = this.kernel.db.sql.query("SELECT delivery_id FROM delivery_outbox WHERE principal=? AND state='pending' ORDER BY event_seq LIMIT 32")
      .all(this.actor.id) as { delivery_id: string }[];
    for (const row of rows) await this.deliver(row.delivery_id);
  }
  retryBlocked(requestId: string, id: string): DeliveryView {
    this.current("delivery:send");
    requireThat(this.actor.origin === "human_request" || this.actor.origin === "internal", "delivery_retry_origin_denied");
    command(this.kernel.db, this.actor, requestId, "delivery.retry_blocked", { id }, () => {
      const row = this.row(id), { adapter } = this.evidence(row);
      requireThat(row.state === "blocked" && row.attempt_id === null, "delivery_retry_not_safe");
      const retried: unknown = adapter.retryPreparation?.();
      if (retried !== undefined) { void Promise.resolve(retried).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      this.kernel.db.sql.query("UPDATE delivery_outbox SET state='pending',reason=NULL WHERE delivery_id=?").run(id);
      return { reset: true };
    }, value => { this.evidence(this.row(id)); return value; });
    return this.inspect(id);
  }
  async reconcile(id: string, remoteMessageId: string): Promise<DeliveryView> {
    this.current("delivery:reconcile"); requireThat(this.actor.origin !== "agent_message" && this.actor.origin !== "schedule", "delivery_recovery_origin_denied");
    const row = this.row(id);
    if (row.state === "sent") { requireThat(JSON.parse(row.receipt!).remote_message_id === remoteMessageId, "delivery_receipt_conflict"); this.evidence(row); return this.inspect(id); }
    requireThat(row.state === "unknown", "delivery_not_reconcilable"); identifier(remoteMessageId);
    requireThat(row.observation && JSON.parse(row.observation).remote_message_id === remoteMessageId, "delivery_original_acknowledgement_required");
    const controller = new AbortController(), signal = controller.signal, finished = this.track(controller);
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    const current = () => { this.current("delivery:reconcile"); requireThat(!signal.aborted, "delivery_interrupted"); this.evidence(this.row(id)); };
    try {
    current(); const { envelope, adapter } = this.evidence(row), prepared = await adapter.prepare(structuredClone(envelope), { signal, assertCurrent: current });
    requireThat(row.attempt_started !== null, "delivery_attempt_missing");
    current(); const receipt = await prepared.inspect(structuredClone(envelope), remoteMessageId,
      { signal, not_before: row.attempt_started, assertCurrent: current });
    this.kernel.db.transaction(() => { current(); this.accept(this.row(id), receipt); });
    return this.inspect(id);
    } finally { clearTimeout(timeout); finished(); }
  }
}
