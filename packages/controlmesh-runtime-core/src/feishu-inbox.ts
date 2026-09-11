import { assertProtocolSchema, type TerminalDelivery } from "@controlmesh/protocol";
import { command, requireScope } from "./commands";
import { FeishuEventAuthenticator, type FeishuIncomingMessage } from "./feishu-event-auth";
import { TaskIngress } from "./task-ingress";
import type { LocalTaskRuntime } from "./local-task-runtime";
import type { Principal, RuntimeKernel } from "./kernel";
import type { DeliveryOutbox } from "./delivery-outbox";
import type { FeishuReplyTarget } from "./feishu-delivery";
import { issueExecutionContext } from "./execution-context";
import { ToolGrantDenied } from "./execution-grants";
import { ExecutionPolicyDenied } from "./execution-policy";
import { canonical, digest, identifier, requireThat, RuntimeConflict, terminal } from "./value";

interface InboxRow {
  id: string; app_id: string; principal: string; event_id: string; message_id: string;
  conversation_id: string; payload: string; payload_digest: string;
  state: "pending" | "applied" | "blocked"; task_id: string | null; reason: string | null;
}
interface Conversation { id: string; app_id: string; principal: string; task_id: string; first_event: string }
export interface FeishuTaskTemplate { provider: string; model: string; repo_root: string }

/** Verified provider events and their one canonical task/conversation mapping. */
export class FeishuInbox {
  private readonly actor: Principal;
  readonly binding_digest: string;
  private readonly template: FeishuTaskTemplate;
  constructor(private readonly kernel: RuntimeKernel, actor: Principal, readonly app_id: string,
    private readonly auth: FeishuEventAuthenticator, template: FeishuTaskTemplate,
    private readonly current: () => void) {
    this.actor = structuredClone(actor); this.template = structuredClone(template); identifier(app_id);
    requireThat(actor.origin === "human_request", "feishu_ingress_origin_denied");
    for (const scope of ["feishu:ingest", "feishu:read", "feishu:process"]) this.check(scope);
    this.binding_digest = digest({ kind: "feishu_inbox.v1", app_id, principal: actor.id, template });
  }
  private check(scope: string): void {
    requireScope(this.actor, scope); this.auth.assertCurrent();
    const checked: unknown = this.current();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private sourceId(message: FeishuIncomingMessage): string { return `feishu:${message.app_id}:${message.message_id}`; }
  private load(row: InboxRow): FeishuIncomingMessage {
    requireThat(row.principal === this.actor.id && row.app_id === this.app_id, "feishu_inbox_owner_mismatch");
    const value = JSON.parse(row.payload) as FeishuIncomingMessage;
    assertProtocolSchema("feishu-incoming.schema.json", value);
    requireThat(digest(value) === row.payload_digest && value.app_id === row.app_id && value.event_id === row.event_id
      && value.message_id === row.message_id && this.conversationId(value) === row.conversation_id, "feishu_inbox_corrupted");
    return value;
  }
  private conversationId(message: FeishuIncomingMessage): string {
    return digest([this.actor.id, message.app_id, message.chat_id, message.thread_id, message.source_scope]);
  }
  receive(headers: Headers, bytes: Uint8Array): { challenge: string } | { accepted: boolean; reason?: string; receipt_id?: string } {
    this.check("feishu:ingest"); const event = this.auth.receive(headers, bytes);
    if (event.kind === "challenge") return { challenge: event.challenge };
    if (event.kind === "ignored") return { accepted: false, reason: event.reason };
    const message = event.message; assertProtocolSchema("feishu-incoming.schema.json", message);
    requireThat(message.app_id === this.app_id, "feishu_event_app_mismatch");
    return this.kernel.db.transaction(() => {
      this.check("feishu:ingest");
      const prior = this.kernel.db.sql.query(`SELECT * FROM feishu_inbox WHERE app_id=? AND
        (id IN (SELECT receipt_id FROM feishu_event_aliases WHERE app_id=? AND event_id=?) OR message_id=?)`)
        .all(this.app_id, this.app_id, message.event_id, message.message_id) as InboxRow[];
      if (prior.length) {
        requireThat(prior.length === 1, "feishu_event_identity_conflict"); const old = this.load(prior[0]);
        const { event_id: _oldId, ...oldMessage } = old, { event_id: _newId, ...newMessage } = message;
        requireThat(digest(oldMessage) === digest(newMessage), "feishu_event_identity_conflict");
        this.kernel.db.sql.query("INSERT OR IGNORE INTO feishu_event_aliases VALUES (?,?,?)").run(this.app_id, message.event_id, prior[0].id);
        return { accepted: true, receipt_id: prior[0].id };
      }
      const count = this.kernel.db.sql.query("SELECT COUNT(*) AS n FROM feishu_inbox WHERE principal=? AND app_id=? AND state!='applied'")
        .get(this.actor.id, this.app_id) as { n: number };
      requireThat(count.n < 128, "feishu_inbox_full");
      const id = digest([this.app_id, message.event_id]);
      this.kernel.db.sql.query(`INSERT INTO feishu_inbox
        (id,app_id,principal,event_id,message_id,conversation_id,payload,payload_digest,state,received_at) VALUES (?,?,?,?,?,?,?,?,'pending',?)`)
        .run(id, this.app_id, this.actor.id, message.event_id, message.message_id, this.conversationId(message), canonical(message), digest(message), this.kernel.db.now());
      this.kernel.db.sql.query("INSERT INTO feishu_event_aliases VALUES (?,?,?)").run(this.app_id, message.event_id, id);
      return { accepted: true, receipt_id: id };
    });
  }
  status(): { pending: number; applied: number; blocked: number } {
    this.check("feishu:read"); const result = { pending: 0, applied: 0, blocked: 0 };
    for (const row of this.kernel.db.sql.query("SELECT state,COUNT(*) AS n FROM feishu_inbox WHERE principal=? AND app_id=? GROUP BY state")
      .all(this.actor.id, this.app_id) as { state: keyof typeof result; n: number }[]) result[row.state] = row.n;
    return result;
  }
  listBlocked(): { receipt_id: string; task_id: string | null; reason: string | null }[] {
    this.check("feishu:read");
    return (this.kernel.db.sql.query("SELECT id,task_id,reason FROM feishu_inbox WHERE principal=? AND app_id=? AND state='blocked' ORDER BY received_at LIMIT 128")
      .all(this.actor.id, this.app_id) as InboxRow[]).map(row => ({ receipt_id: row.id, task_id: row.task_id, reason: row.reason }));
  }
  retry(requestId: string, id: string): void {
    this.check("feishu:process"); identifier(id);
    command(this.kernel.db, this.actor, requestId, "feishu.inbox.retry", { id }, () => {
      const row = this.kernel.db.sql.query("SELECT * FROM feishu_inbox WHERE id=? AND principal=? AND app_id=?").get(id, this.actor.id, this.app_id) as InboxRow | null;
      requireThat(row && row.state === "blocked", "feishu_inbox_not_blocked");
      const message = this.load(row); requireThat(!this.auth.policy(message), "feishu_event_policy_changed");
      this.kernel.db.sql.query("UPDATE feishu_inbox SET state='pending',reason=NULL WHERE id=?").run(id);
      return { retried: true };
    }, value => { this.check("feishu:process"); return value; });
  }
  /** Dynamic reply identity comes only from the immutable, verified conversation-opening event. */
  replyTarget(envelope: TerminalDelivery): FeishuReplyTarget | undefined {
    this.check("feishu:read");
    const conversation = this.kernel.db.sql.query("SELECT * FROM feishu_conversations WHERE task_id=? AND app_id=? AND principal=?")
      .get(envelope.task_id, this.app_id, this.actor.id) as Conversation | null;
    if (!conversation) return undefined;
    const row = this.kernel.db.sql.query("SELECT * FROM feishu_inbox WHERE id=?").get(conversation.first_event) as InboxRow;
    requireThat(row, "feishu_conversation_corrupted"); const first = this.load(row);
    const context = issueExecutionContext({ origin: "user", source_scope: first.source_scope, transport: "fs", source_id: this.sourceId(first) });
    requireThat(conversation.id === row.conversation_id && row.task_id === conversation.task_id
      && envelope.target.chat_id === first.chat_id && envelope.target.thread_id === first.thread_id
      && envelope.execution_context.source_ref === context.source_ref && envelope.execution_context.source_scope === first.source_scope,
      "feishu_conversation_corrupted");
    return { chat_id: first.chat_id, message_id: first.message_id, thread_id: first.thread_id, reply_in_thread: Boolean(first.thread_id) };
  }
  /** Synchronous effects compose inside the same transaction as marking the provider event applied. */
  applyPending(runtime: LocalTaskRuntime, deliveries: DeliveryOutbox, adapterId: string, limit = 16): number {
    this.check("feishu:process"); requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= 128, "invalid_feishu_inbox_limit");
    const rows = this.kernel.db.sql.query("SELECT * FROM feishu_inbox WHERE principal=? AND app_id=? AND state='pending' ORDER BY received_at,rowid LIMIT ?")
      .all(this.actor.id, this.app_id, 128) as InboxRow[];
    let applied = 0;
    for (const original of rows) {
      // Scan the bounded inbox past deferred conversations; the limit caps applied work.
      if (applied >= limit) break;
      try {
        const changed = this.kernel.db.transaction(() => {
          this.check("feishu:process");
          const row = this.kernel.db.sql.query("SELECT * FROM feishu_inbox WHERE id=?").get(original.id) as InboxRow;
          if (row.state !== "pending") return false;
          const message = this.load(row); requireThat(!this.auth.policy(message), "feishu_event_policy_changed");
          if (this.kernel.db.sql.query("SELECT 1 FROM feishu_inbox WHERE conversation_id=? AND rowid < (SELECT rowid FROM feishu_inbox WHERE id=?) AND state!='applied' LIMIT 1")
            .get(row.conversation_id, row.id)) return false;
          const conversation = this.kernel.db.sql.query("SELECT * FROM feishu_conversations WHERE id=?").get(row.conversation_id) as Conversation | null;
          const taskId = `fs-${row.conversation_id}`;
          const key = (op: string) => `fs-${op}-${row.id}`;
          if (!conversation) {
            new TaskIngress(this.kernel, { command_origin: "human_request", origin: "user", source_scope: message.source_scope, transport: "fs" }, () => this.check("feishu:process"))
              .submit(this.actor, key("create"), { task_id: taskId, chat_id: message.chat_id, thread_id: message.thread_id, status: "waiting",
                prompt: message.text, ...this.template }, { chat_id: message.chat_id, thread_id: message.thread_id, source_id: this.sourceId(message) });
            this.kernel.db.sql.query("INSERT INTO feishu_conversations VALUES (?,?,?,?,?)").run(row.conversation_id, this.app_id, this.actor.id, taskId, row.id);
            deliveries.bindTask(key("bind"), taskId, 1, adapterId);
          } else {
            requireThat(conversation.app_id === this.app_id && conversation.principal === this.actor.id && conversation.task_id === taskId, "feishu_conversation_corrupted");
            const task = this.kernel.inspect(this.actor, taskId);
            requireThat(!task.needs_reconciliation, "task_reconciliation_required");
            if (task.active_episode || this.kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(taskId)) return false;
            if (terminal.has(task.task.status)) runtime.resume(key("resume"), taskId, task.revision, message.text);
            else if (task.task.status === "waiting") runtime.tell(key("tell"), taskId, message.text);
            else throw new RuntimeConflict("feishu_task_not_resumable");
          }
          const task = this.kernel.inspect(this.actor, taskId); runtime.enqueue(key("enqueue"), taskId, task.revision);
          this.kernel.db.sql.query("UPDATE feishu_inbox SET state='applied',task_id=?,reason=NULL WHERE id=?").run(taskId, row.id);
          return true;
        });
        if (changed) applied++;
      } catch (error) {
        // Preserve authenticated input for explicit operator action; a retry never re-authors its contents.
        const reason = error instanceof RuntimeConflict ? error.code : error instanceof ToolGrantDenied ? error.reason_code
          : error instanceof ExecutionPolicyDenied ? error.decision.reason_code : "feishu_event_application_failed";
        this.kernel.db.sql.query("UPDATE feishu_inbox SET state='blocked',reason=? WHERE id=? AND state='pending'").run(reason, original.id);
      }
    }
    return applied;
  }
}
