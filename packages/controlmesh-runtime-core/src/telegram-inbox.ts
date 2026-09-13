import { command, requireScope } from "./commands";
import { TelegramEventAuthenticator, assertTelegramIncoming, type TelegramIncomingMessage } from "./telegram-event-auth";
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
    this.check("telegram:ingest"); const event = this.auth.receive(headers, bytes);
    if (event.kind === "ignored") return { accepted: false, reason: event.reason };
    const message = event.message; assertTelegramIncoming(message);
    requireThat(message.bot_id === this.bot_id, "telegram_event_bot_mismatch");
    return this.kernel.db.transaction(() => {
      this.check("telegram:ingest");
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
      requireThat(count.n < 128, "telegram_inbox_full");
      const id = digest([this.bot_id, message.event_id]);
      this.kernel.db.sql.query(`INSERT INTO telegram_inbox
        (id,bot_id,principal,event_id,message_id,chat_id,conversation_id,payload,payload_digest,state,received_at) VALUES (?,?,?,?,?,?,?,?,?,'pending',?)`)
        .run(id, this.bot_id, this.actor.id, message.event_id, message.message_id, message.chat_id, this.conversationId(message), canonical(message), digest(message), this.kernel.db.now());
      this.kernel.db.sql.query("INSERT INTO telegram_event_aliases VALUES (?,?,?)").run(this.bot_id, message.event_id, id);
      return { accepted: true, receipt_id: id };
    });
  }
  status(): { pending: number; applied: number; blocked: number } {
    this.check("telegram:read"); const result = { pending: 0, applied: 0, blocked: 0 };
    for (const row of this.kernel.db.sql.query("SELECT state,COUNT(*) AS n FROM telegram_inbox WHERE principal=? AND bot_id=? GROUP BY state")
      .all(this.actor.id, this.bot_id) as { state: keyof typeof result; n: number }[]) result[row.state] = row.n;
    return result;
  }
  listBlocked(): { receipt_id: string; task_id: string | null; reason: string | null }[] {
    this.check("telegram:read");
    return (this.kernel.db.sql.query("SELECT id,task_id,reason FROM telegram_inbox WHERE principal=? AND bot_id=? AND state='blocked' ORDER BY received_at LIMIT 128")
      .all(this.actor.id, this.bot_id) as InboxRow[]).map(row => ({ receipt_id: row.id, task_id: row.task_id, reason: row.reason }));
  }
  retry(requestId: string, id: string): void {
    this.check("telegram:process"); identifier(id);
    command(this.kernel.db, this.actor, requestId, "telegram.inbox.retry", { id }, () => {
      const row = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE id=? AND principal=? AND bot_id=?").get(id, this.actor.id, this.bot_id) as InboxRow | null;
      requireThat(row && row.state === "blocked", "telegram_inbox_not_blocked");
      const message = this.load(row); requireThat(!this.auth.policy(message), "telegram_event_policy_changed");
      this.kernel.db.sql.query("UPDATE telegram_inbox SET state='pending',reason=NULL WHERE id=?").run(id);
      return { retried: true };
    }, value => { this.check("telegram:process"); return value; });
  }
  /** Synchronous effects compose inside the same transaction as marking the provider event applied. */
  applyPending(runtime: LocalTaskRuntime, deliveries: DeliveryOutbox, adapterId: string, limit = 16): number {
    this.check("telegram:process"); requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 128, "invalid_telegram_inbox_limit");
    const rows = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE principal=? AND bot_id=? AND state='pending' ORDER BY json_extract(payload,'$.created_at'),CAST(message_id AS INTEGER),rowid LIMIT ?")
      .all(this.actor.id, this.bot_id, 128) as InboxRow[];
    let applied = 0;
    for (const original of rows) {
      // Scan the bounded inbox past deferred conversations; the limit caps applied work.
      if (applied >= limit) break;
      try {
        const changed = this.kernel.db.transaction(() => {
          this.check("telegram:process");
          const row = this.kernel.db.sql.query("SELECT * FROM telegram_inbox WHERE id=?").get(original.id) as InboxRow;
          if (row.state !== "pending") return false;
          const message = this.load(row); requireThat(!this.auth.policy(message), "telegram_event_policy_changed");
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
    return applied;
  }
}
