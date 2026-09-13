import { command, requireScope } from "./commands";
import { TelegramEventAuthenticator, assertTelegramIncoming, type TelegramIncomingMessage, type TelegramIncomingCallback } from "./telegram-event-auth";
import { TaskIngress } from "./task-ingress";
import type { LocalTaskRuntime } from "./local-task-runtime";
import type { Principal, RuntimeKernel } from "./kernel";
import type { DeliveryOutbox } from "./delivery-outbox";
import { ToolGrantDenied } from "./execution-grants";
import { ExecutionPolicyDenied } from "./execution-policy";
import { canonical, digest, identifier, requireThat, RuntimeConflict, terminal } from "./value";

interface InboxRow {
  id: string; bot_id: string; principal: string; event_id: string; message_id: string; chat_id: string;
  conversation_id: string; received_at: number; payload: string; payload_digest: string;
  state: "pending" | "applied" | "blocked"; task_id: string | null; reason: string | null;
}
interface CallbackRow { id: string; bot_id: string; principal: string; event_id: string; callback_id: string; payload: string; payload_digest: string; state: string; received_at: number }
interface Conversation { id: string; bot_id: string; principal: string; task_id: string; first_event: string }
export interface TelegramTaskTemplate { provider: string; model: string; repo_root: string }

/** Verified provider events and their one canonical task/conversation mapping. */
export class TelegramInbox {
  private readonly actor: Principal;
  readonly binding_digest: string;
  private readonly template: TelegramTaskTemplate;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, readonly bot_id: string,
    private readonly auth: TelegramEventAuthenticator, template: TelegramTaskTemplate,
    private readonly current: () => void) {
    this.actor = structuredClone(actor); this.template = structuredClone(template); identifier(bot_id);
    requireThat(actor.origin === "human_request", "telegram_ingress_origin_denied");
    for (const scope of ["telegram:ingest", "telegram:read", "telegram:process"]) this.check(scope);
    this.binding_digest = digest({ kind: "telegram_inbox.v1", bot_id, principal: actor.id, template });
  }
  private check(scope: string): void {
    requireScope(this.actor, scope); this.auth.assertCurrent();
    const checked: unknown = this.current();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private sourceId(message: TelegramIncomingMessage): string { return `telegram:${message.bot_id}:${message.chat_id}:${message.message_id}`; }
  private load(row: InboxRow): TelegramIncomingMessage {
    requireThat(row.principal === this.actor.id && row.bot_id === this.bot_id, "telegram_inbox_owner_mismatch");
    const value = JSON.parse(row.payload) as TelegramIncomingMessage;
    assertTelegramIncoming(value);
    requireThat(digest(value) === row.payload_digest && value.bot_id === row.bot_id && value.event_id === row.event_id
      && value.message_id === row.message_id && value.chat_id === row.chat_id && this.conversationId(value) === row.conversation_id, "telegram_inbox_corrupted");
    return value;
  }
  private conversationId(message: TelegramIncomingMessage): string {
    return digest([this.actor.id, message.bot_id, message.chat_id, message.thread_id, message.source_scope]);
  }
  receive(headers: Headers, bytes: Uint8Array): { challenge: string } | { accepted: boolean; reason?: string; receipt_id?: string } {
    this.check("telegram:ingest"); return this.store(this.auth.receive(headers, bytes));
  }
  /** Caller is the registered polling transport; a remote body never selects this path. */
  receivePolled(bytes: Uint8Array, assertTransport: () => void): { accepted: boolean; reason?: string; receipt_id?: string } {
    this.check("telegram:ingest"); const result: unknown = assertTransport();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    return this.store(this.auth.receiveAuthenticated(bytes));
  }
  private store(event: ReturnType<TelegramEventAuthenticator["receive"]>): { accepted: boolean; reason?: string; receipt_id?: string } {
    if (event.kind === "ignored") return { accepted: false, reason: event.reason };
    if (event.kind === "callback") return this.storeCallback(event.callback);
    const message = event.message; assertTelegramIncoming(message);
    requireThat(message.bot_id === this.bot_id, "telegram_event_bot_mismatch");
    return this.kernel.db.transaction(() => {
      this.check("telegram:ingest");
      requireThat(!this.kernel.db.sql.query("SELECT 1 FROM telegram_callbacks WHERE bot_id=? AND event_id=?").get(this.bot_id, message.event_id), "telegram_event_identity_conflict");
      const prior = this.kernel.db.sql.query(`SELECT * FROM telegram_inbox WHERE bot_id=? AND
        (id IN (SELECT receipt_id FROM telegram_event_aliases WHERE bot_id=? AND event_id=?) OR (chat_id=? AND message_id=?))`)
        .all(this.bot_id, this.bot_id, message.event_id, message.chat_id, message.message_id) as InboxRow[];
      if (prior.length) {
        requireThat(prior.length === 1, "telegram_event_identity_conflict"); const old = this.load(prior[0]);
        const { event_id: _oldId, ...oldMessage } = old, { event_id: _newId, ...newMessage } = message;
        requireThat(digest(oldMessage) === digest(newMessage), "telegram_event_identity_conflict");
        this.kernel.db.sql.query("INSERT OR IGNORE INTO telegram_event_aliases VALUES (?,?,?)").run(this.bot_id, message.event_id, prior[0].id);
        return { accepted: true, receipt_id: prior[0].id };
      }
      const count = this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM telegram_inbox WHERE principal=? AND bot_id=? AND state!='applied'")
        .get(this.actor.id, this.bot_id) as { n: number };
      // One reserved control slot keeps a full ordinary inbox stoppable.
      requireThat(count.n < 128 || (count.n === 128 && this.auth.controlCommand(message) === "stop"), "telegram_inbox_full");
      const id = digest([this.bot_id, message.event_id]);
      this.kernel.db.sql.query(`INSERT INTO telegram_inbox
        (id,bot_id,principal,event_id,message_id,chat_id,conversation_id,payload,payload_digest,state,received_at) VALUES (?,?,?,?,?,?,?,?,?,'pending',?)`)
        .run(id, this.bot_id, this.actor.id, message.event_id, message.message_id, message.chat_id, this.conversationId(message), canonical(message), digest(message), this.kernel.db.now());
      this.kernel.db.sql.query("INSERT INTO telegram_event_aliases VALUES (?,?,?)").run(this.bot_id, message.event_id, id);
      return { accepted: true, receipt_id: id };
    });
  }
  private storeCallback(callback: TelegramIncomingCallback): { accepted: boolean; receipt_id: string } {
    return this.kernel.db.transaction(() => {
      this.check("telegram:ingest");
      requireThat(callback.bot_id === this.bot_id && !this.kernel.db.sql.query("SELECT 1 FROM telegram_event_aliases WHERE bot_id=? AND event_id=?")
        .get(this.bot_id, callback.event_id), "telegram_event_identity_conflict");
      const prior = this.kernel.db.sql.query("SELECT * FROM telegram_callbacks WHERE bot_id=? AND (event_id=? OR callback_id=?)")
        .all(this.bot_id, callback.event_id, callback.callback_id) as CallbackRow[];
      if (prior.length) {
        requireThat(prior.length === 1 && prior[0].principal === this.actor.id, "telegram_callback_identity_conflict");
        const old = this.loadCallback(prior[0]);
        requireThat(digest(old) === digest(callback), "telegram_callback_identity_conflict");
        return { accepted: true, receipt_id: prior[0].id };
      }
      const count = this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM telegram_callbacks WHERE bot_id=? AND principal=? AND state!='applied'")
        .get(this.bot_id, this.actor.id) as { n: number };
      requireThat(count.n < 128, "telegram_inbox_full");
      const id = digest(["callback", this.bot_id, callback.callback_id]);
      this.kernel.db.sql.query(`INSERT INTO telegram_callbacks
        (id,bot_id,principal,event_id,callback_id,payload,payload_digest,state,received_at) VALUES (?,?,?,?,?,?,?,'pending',?)`)
        .run(id, this.bot_id, this.actor.id, callback.event_id, callback.callback_id, canonical(callback), digest(callback), this.kernel.db.now());
      return { accepted: true, receipt_id: id };
    });
  }
  private loadCallback(row: CallbackRow): TelegramIncomingCallback {
    const callback = JSON.parse(row.payload) as TelegramIncomingCallback;
    requireThat(row.bot_id === this.bot_id && row.principal === this.actor.id && digest(callback) === row.payload_digest
      && callback.bot_id === row.bot_id && callback.callback_id === row.callback_id && callback.event_id === row.event_id,
      "telegram_callback_corrupted");
    return callback;
  }
  private applyCallbacks(runtime: LocalTaskRuntime, deliveries: DeliveryOutbox, adapterId: string, limit: number): number {
    const rows = this.kernel.db.sql.query("SELECT * FROM telegram_callbacks WHERE bot_id=? AND principal=? AND state='pending' ORDER BY received_at,rowid LIMIT ?")
      .all(this.bot_id, this.actor.id, limit) as CallbackRow[];
    let applied = 0;
    for (const original of rows) {
      try {
        const changed = this.kernel.db.transaction(() => {
          this.check("telegram:process");
          const row = this.kernel.db.sql.query("SELECT * FROM telegram_callbacks WHERE id=?").get(original.id) as CallbackRow;
          if (row.state !== "pending") return false;
          const callback = this.loadCallback(row);
          requireThat(!this.auth.policy({ ...callback, schema_version: "controlmesh.telegram_incoming.v1", text: callback.choice_id,
            created_at: row.received_at, mentions_local_bot: true }), "telegram_event_policy_changed");
          if (this.kernel.db.sql.query(`SELECT 1 FROM telegram_inbox WHERE bot_id=? AND principal=? AND chat_id=?
            AND json_extract(payload,'$.thread_id')=? AND state!='applied'
            AND (reason IS NULL OR reason NOT IN ('telegram_event_order_requires_review','telegram_input_predates_cancellation'))
            AND (received_at<? OR (received_at=? AND CAST(event_id AS INTEGER)<?)) LIMIT 1`)
            .get(this.bot_id, this.actor.id, callback.chat_id, callback.thread_id, row.received_at, row.received_at, Number(callback.event_id))) return false;
          const choice = deliveries.resolveTelegramChoice(adapterId, callback);
          runtime.resume(`tg-callback-resume-${row.id}`, choice.task_id, choice.revision, choice.text);
          const task = this.kernel.inspect(this.actor, choice.task_id);
          runtime.enqueue(`tg-callback-enqueue-${row.id}`, choice.task_id, task.revision);
          this.kernel.db.sql.query("UPDATE telegram_callbacks SET state='applied',task_id=?,reason=NULL WHERE id=?").run(choice.task_id, row.id);
          return true;
        });
        if (changed) applied++;
      } catch (error) {
        const reason = error instanceof RuntimeConflict ? error.code : error instanceof ToolGrantDenied ? error.reason_code
          : error instanceof ExecutionPolicyDenied ? error.decision.reason_code : "telegram_callback_application_failed";
        this.kernel.db.sql.query("UPDATE telegram_callbacks SET state='blocked',reason=? WHERE id=? AND state='pending'").run(reason, original.id);
      }
    }
    return applied;
  }
  /** UI acknowledgement is independent of execution; unknown HTTP outcomes never requeue an Agent. */
  async confirmCallbacks(deliveries: DeliveryOutbox, adapterId: string): Promise<boolean> {
    this.check("telegram:process");
    const rows = this.kernel.db.sql.query("SELECT * FROM telegram_callbacks WHERE bot_id=? AND principal=? AND state!='pending' AND ack_state='pending' ORDER BY received_at LIMIT 4")
      .all(this.bot_id, this.actor.id) as CallbackRow[];
    await Promise.all(rows.map(async row => {
      const callback = this.loadCallback(row);
      const claimed = this.kernel.db.transaction(() => {
        this.check("telegram:process");
        return this.kernel.db.sql.query("UPDATE telegram_callbacks SET ack_state='unknown',ack_reason='telegram_callback_ack_interrupted' WHERE id=? AND ack_state='pending'")
          .run(row.id).changes > 0;
      });
      if (!claimed) return;
      try {
        await deliveries.answerTelegramCallback(adapterId, callback, row.state === "applied");
        this.check("telegram:process");
        this.kernel.db.sql.query("UPDATE telegram_callbacks SET ack_state='sent',ack_reason=NULL WHERE id=?").run(row.id);
      } catch (error) {
        const reason = error instanceof RuntimeConflict ? error.code : "telegram_callback_ack_unknown";
        this.kernel.db.sql.query("UPDATE telegram_callbacks SET ack_reason=? WHERE id=?").run(reason, row.id);
      }
    }));
    return Boolean(this.kernel.db.sql.query("SELECT 1 FROM telegram_callbacks WHERE bot_id=? AND principal=? AND state!='pending' AND ack_state='pending' LIMIT 1")
      .get(this.bot_id, this.actor.id));
  }
  status(): { pending: number; applied: number; blocked: number } {
    this.check("telegram:read"); const result = { pending: 0, applied: 0, blocked: 0 };
    for (const row of this.kernel.db.sql.query("SELECT state,COUNT(*) AS n FROM telegram_inbox WHERE principal=? AND bot_id=? GROUP BY state")
      .all(this.actor.id, this.bot_id) as { state: keyof typeof result; n: number }[]) result[row.state] = row.n;
    for (const row of this.kernel.db.sql.query("SELECT state,COUNT(*) AS n FROM telegram_callbacks WHERE principal=? AND bot_id=? GROUP BY state")
      .all(this.actor.id, this.bot_id) as { state: keyof typeof result; n: number }[]) result[row.state] += row.n;
    return result;
  }
  listBlocked(): { receipt_id: string; task_id: string | null; reason: string | null }[] {
    this.check("telegram:read");
    return (this.kernel.db.sql.query("SELECT id,task_id,reason FROM telegram_inbox WHERE principal=? AND bot_id=? AND state='blocked' ORDER BY received_at LIMIT 128")
      .all(this.actor.id, this.bot_id) as InboxRow[]).concat(this.kernel.db.sql.query("SELECT id,task_id,reason FROM telegram_callbacks WHERE principal=? AND bot_id=? AND state='blocked' ORDER BY received_at LIMIT 128")
        .all(this.actor.id, this.bot_id) as InboxRow[]).map(row => ({ receipt_id: row.id, task_id: row.task_id, reason: row.reason }));
  }
  retry(requestId: string, id: string): void {
    this.check("telegram:process"); identifier(id);
    command(this.kernel.db, this.actor, requestId, "telegram.inbox.retry", { id }, () => {
      const callback = this.kernel.db.sql.query("SELECT * FROM telegram_callbacks WHERE id=? AND principal=? AND bot_id=?").get(id, this.actor.id, this.bot_id) as CallbackRow | null;
      if (callback) {
        requireThat(callback.state === "blocked", "telegram_inbox_not_blocked"); this.loadCallback(callback);
        this.kernel.db.sql.query("UPDATE telegram_callbacks SET state='pending',reason=NULL WHERE id=?").run(id);
        return { retried: true };
      }
      const row = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE id=? AND principal=? AND bot_id=?").get(id, this.actor.id, this.bot_id) as InboxRow | null;
      requireThat(row && row.state === "blocked", "telegram_inbox_not_blocked");
      const message = this.load(row); requireThat(!this.auth.policy(message), "telegram_event_policy_changed");
      this.kernel.db.sql.query("UPDATE telegram_inbox SET state='pending',reason=NULL WHERE id=?").run(id);
      return { retried: true };
    }, value => { this.check("telegram:process"); return value; });
  }
  /** The ingress pump may call this while it is awaiting a native execution. */
  applyControl(runtime: LocalTaskRuntime, limit = 16): number {
    this.check("telegram:process");
    requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 128, "invalid_telegram_inbox_limit");
    return this.applyStops(runtime, limit);
  }
  /** Stop bypasses a blocked execution lane but never supersedes newer applied input. */
  private applyStops(runtime: LocalTaskRuntime, limit: number): number {
    const rows = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE principal=? AND bot_id=? AND state='pending' ORDER BY json_extract(payload,'$.created_at'),CAST(message_id AS INTEGER),rowid LIMIT 129")
      .all(this.actor.id, this.bot_id) as InboxRow[];
    let applied = 0;
    for (const original of rows) {
      if (applied >= limit) break;
      if (this.auth.controlCommand(this.load(original)) !== "stop") continue;
      try {
        const changed = this.kernel.db.transaction(() => {
          this.check("telegram:process");
          const row = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE id=?").get(original.id) as InboxRow;
          if (row.state !== "pending") return false;
          const message = this.load(row); requireThat(!this.auth.policy(message), "telegram_event_policy_changed");
          requireScope(this.actor, "task:cancel");
          requireThat(!this.kernel.db.sql.query(`SELECT 1 FROM telegram_inbox WHERE conversation_id=? AND state='applied'
            AND (json_extract(payload,'$.created_at')>? OR (json_extract(payload,'$.created_at')=? AND CAST(message_id AS INTEGER)>?)) LIMIT 1`)
            .get(row.conversation_id, message.created_at, message.created_at, Number(message.message_id)), "telegram_event_order_requires_review");
          requireThat(!this.kernel.db.sql.query(`SELECT 1 FROM telegram_callbacks WHERE bot_id=? AND principal=? AND state='applied'
            AND json_extract(payload,'$.chat_id')=? AND json_extract(payload,'$.thread_id')=? AND CAST(event_id AS INTEGER)>? LIMIT 1`)
            .get(this.bot_id, this.actor.id, message.chat_id, message.thread_id, Number(message.event_id)), "telegram_event_order_requires_review");
          const conversation = this.kernel.db.sql.query("SELECT * FROM telegram_conversations WHERE id=?").get(row.conversation_id) as Conversation | null;
          if (conversation) {
            requireThat(conversation.bot_id === this.bot_id && conversation.principal === this.actor.id
              && conversation.task_id === `tg-${row.conversation_id}`, "telegram_conversation_corrupted");
            const task = this.kernel.inspect(this.actor, conversation.task_id);
            if (!terminal.has(task.task.status)) runtime.cancel(`tg-stop-${row.id}`, conversation.task_id, task.revision);
          }
          this.kernel.db.sql.query(`UPDATE telegram_inbox SET state='blocked',reason='telegram_input_predates_cancellation'
            WHERE conversation_id=? AND state!='applied' AND id!=?
            AND (json_extract(payload,'$.created_at')<? OR (json_extract(payload,'$.created_at')=? AND CAST(message_id AS INTEGER)<?))`)
            .run(row.conversation_id, row.id, message.created_at, message.created_at, Number(message.message_id));
          this.kernel.db.sql.query(`UPDATE telegram_callbacks SET state='blocked',reason='telegram_input_predates_cancellation'
            WHERE bot_id=? AND principal=? AND state='pending' AND json_extract(payload,'$.chat_id')=?
            AND json_extract(payload,'$.thread_id')=? AND received_at<=?`)
            .run(this.bot_id, this.actor.id, message.chat_id, message.thread_id, row.received_at);
          this.kernel.db.sql.query("UPDATE telegram_inbox SET state='applied',task_id=?,reason=NULL WHERE id=?")
            .run(conversation?.task_id ?? null, row.id);
          return true;
        });
        if (changed) applied++;
      } catch (error) {
        const reason = error instanceof RuntimeConflict ? error.code : "telegram_stop_failed";
        this.kernel.db.sql.query("UPDATE telegram_inbox SET state='blocked',reason=? WHERE id=? AND state='pending'").run(reason, original.id);
      }
    }
    return applied;
  }
  /** Synchronous effects compose inside the same transaction as marking the provider event applied. */
  applyPending(runtime: LocalTaskRuntime, deliveries: DeliveryOutbox, adapterId: string, limit = 16): number {
    this.check("telegram:process"); requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 128, "invalid_telegram_inbox_limit");
    const stopped = this.applyStops(runtime, limit);
    const rows = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE principal=? AND bot_id=? AND state='pending' ORDER BY json_extract(payload,'$.created_at'),CAST(message_id AS INTEGER),rowid LIMIT ?")
      .all(this.actor.id, this.bot_id, 128) as InboxRow[];
    let applied = stopped;
    for (const original of rows) {
      // Scan the bounded inbox past deferred conversations; the limit caps applied work.
      if (applied >= limit) break;
      try {
        const changed = this.kernel.db.transaction(() => {
          this.check("telegram:process");
          const row = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE id=?").get(original.id) as InboxRow;
          if (row.state !== "pending") return false;
          const message = this.load(row); requireThat(!this.auth.policy(message), "telegram_event_policy_changed");
          if (this.kernel.db.sql.query(`SELECT 1 FROM telegram_callbacks WHERE bot_id=? AND principal=? AND state='pending'
            AND json_extract(payload,'$.chat_id')=? AND json_extract(payload,'$.thread_id')=?
            AND (received_at<? OR (received_at=? AND CAST(event_id AS INTEGER)<?)) LIMIT 1`)
            .get(this.bot_id, this.actor.id, message.chat_id, message.thread_id, row.received_at, row.received_at, Number(message.event_id))) return false;
          const laterApplied = this.kernel.db.sql.query(`SELECT 1 FROM telegram_inbox WHERE conversation_id=? AND state='applied'
            AND (json_extract(payload,'$.created_at')>? OR (json_extract(payload,'$.created_at')=? AND CAST(message_id AS INTEGER)>?)) LIMIT 1`)
            .get(row.conversation_id, message.created_at, message.created_at, Number(message.message_id));
          requireThat(!laterApplied, "telegram_event_order_requires_review");
          if (this.kernel.db.sql.query(`SELECT 1 FROM telegram_inbox WHERE conversation_id=? AND state!='applied' AND (reason IS NULL OR reason NOT IN ('telegram_event_order_requires_review','telegram_input_predates_cancellation'))
            AND (json_extract(payload,'$.created_at')<? OR (json_extract(payload,'$.created_at')=? AND CAST(message_id AS INTEGER)<?)) LIMIT 1`)
            .get(row.conversation_id, message.created_at, message.created_at, Number(message.message_id))) return false;
          const conversation = this.kernel.db.sql.query("SELECT * FROM telegram_conversations WHERE id=?").get(row.conversation_id) as Conversation | null;
          const taskId = `tg-${row.conversation_id}`;
          const key = (op: string) => `tg-${op}-${row.id}`;
          if (!conversation) {
            new TaskIngress(this.kernel, { command_origin: "human_request", origin: "user", source_scope: message.source_scope, transport: "telegram" }, () => this.check("telegram:process"))
              .submit(this.actor, key("create"), { task_id: taskId, chat_id: message.chat_id, thread_id: message.thread_id, status: "waiting",
                prompt: message.text, ...this.template }, { chat_id: message.chat_id, thread_id: message.thread_id, source_id: this.sourceId(message) });
            this.kernel.db.sql.query("INSERT INTO telegram_conversations VALUES (?,?,?,?,?)").run(row.conversation_id, this.bot_id, this.actor.id, taskId, row.id);
            deliveries.bindTask(key("bind"), taskId, 1, adapterId);
          } else {
            requireThat(conversation.bot_id === this.bot_id && conversation.principal === this.actor.id && conversation.task_id === taskId, "telegram_conversation_corrupted");
            const task = this.kernel.inspect(this.actor, taskId);
            requireThat(!task.needs_reconciliation, "task_reconciliation_required");
            if (task.task.status === "cancelled") {
              const cancelled = this.kernel.db.sql.query("SELECT at FROM events WHERE task_id=? AND kind='task.cancelled' ORDER BY seq DESC LIMIT 1")
                .get(taskId) as { at: number } | null;
              requireThat(cancelled && row.received_at > cancelled.at, "telegram_input_predates_cancellation");
            }
            const latestRun = this.kernel.db.sql.query("SELECT state FROM local_runs WHERE task_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1")
              .get(taskId) as { state: string } | null;
            if (task.task.status === "waiting" && latestRun?.state === "blocked") return false;
            if (task.active_episode || this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(taskId)) return false;
            if (terminal.has(task.task.status)) runtime.resume(key("resume"), taskId, task.revision, message.text);
            else if (task.task.status === "waiting") runtime.tell(key("tell"), taskId, message.text);
            else throw new RuntimeConflict("telegram_task_not_resumable");
          }
          const task = this.kernel.inspect(this.actor, taskId); runtime.enqueue(key("enqueue"), taskId, task.revision);
          this.kernel.db.sql.query("UPDATE telegram_inbox SET state='applied',task_id=?,reason=NULL WHERE id=?").run(taskId, row.id);
          return true;
        });
        if (changed) applied++;
      } catch (error) {
        // Preserve authenticated input for explicit operator action; a retry never re-authors its contents.
        const reason = error instanceof RuntimeConflict ? error.code : error instanceof ToolGrantDenied ? error.reason_code
          : error instanceof ExecutionPolicyDenied ? error.decision.reason_code : "telegram_event_application_failed";
        this.kernel.db.sql.query("UPDATE telegram_inbox SET state='blocked',reason=? WHERE id=? AND state='pending'").run(reason, original.id);
      }
    }
    return applied + this.applyCallbacks(runtime, deliveries, adapterId, limit - applied);
  }
}
