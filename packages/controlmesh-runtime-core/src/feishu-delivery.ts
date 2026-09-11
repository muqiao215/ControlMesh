import type { DeliveryReceipt, TerminalDelivery } from "@controlmesh/protocol";
import type { DeliveryAdapter, DeliveryContext, PreparedDelivery } from "./delivery-outbox";
import { digest, identifier, object, requireThat } from "./value";

function visibleText(envelope: TerminalDelivery): string {
  const scope = envelope.execution_context.source_scope;
  const label = scope === "cron" ? "Scheduled task" : scope === "heartbeat" ? "Heartbeat task"
    : scope === "bot_handoff" ? "Agent task" : scope === "webhook" ? "Webhook task" : "Task";
  const state = envelope.status === "done" ? "completed" : envelope.status;
  return `${label} ${envelope.task_id}: ${state}\n\n${envelope.text}`;
}

export interface FeishuDeliveryConfiguration {
  adapter_id: string;
  transport: string;
  app_id: string;
  domain?: "https://open.feishu.cn" | "https://open.larksuite.com";
  /** Issued by the selected account's credential owner. Never infer an app from available credentials. */
  tenantAccessToken(context: DeliveryContext): Promise<string>;
  assertAccessToken?(token: string): void;
  retryAuthentication?(): void;
  replies?: Record<string, FeishuReplyTarget>;
  reply_source?: FeishuReplySource;
  assertCurrent(): void;
}

export interface FeishuReplyTarget {
  chat_id: string;
  message_id: string;
  thread_id: string;
  reply_in_thread: boolean;
}
export interface FeishuReplySource {
  binding_digest: string;
  resolve(envelope: TerminalDelivery): FeishuReplyTarget | undefined;
}

function validateReply(reply: FeishuReplyTarget): void {
  requireThat(object(reply) && Object.keys(reply).every(key => ["chat_id", "message_id", "thread_id", "reply_in_thread"].includes(key))
    && typeof reply.chat_id === "string" && /^oc_[A-Za-z0-9_-]{1,120}$/.test(reply.chat_id)
    && typeof reply.message_id === "string" && /^om_[A-Za-z0-9_-]{1,120}$/.test(reply.message_id)
    && typeof reply.thread_id === "string" && typeof reply.reply_in_thread === "boolean"
    && (reply.reply_in_thread ? /^th_[A-Za-z0-9_-]{1,120}$/.test(reply.thread_id) : reply.thread_id === ""), "invalid_feishu_reply_profile");
}

/** Feishu plain-text, chat-addressed API port. HTTP acknowledgement is not end-user read status. */
export class FeishuTextDelivery implements DeliveryAdapter {
  readonly adapter_id: string;
  readonly transport: string;
  readonly binding_digest: string;
  private readonly domain: string;
  private readonly replies: Record<string, FeishuReplyTarget>;
  private readonly replySource: FeishuReplySource | undefined;
  constructor(private readonly config: FeishuDeliveryConfiguration, private readonly request: typeof fetch = fetch) {
    identifier(config.adapter_id); identifier(config.app_id);
    requireThat(/^[a-z0-9_-]{1,32}$/.test(config.transport), "invalid_delivery_transport");
    this.domain = config.domain ?? "https://open.feishu.cn";
    requireThat(["https://open.feishu.cn", "https://open.larksuite.com"].includes(this.domain), "untrusted_feishu_endpoint");
    this.adapter_id = config.adapter_id; this.transport = config.transport;
    this.replies = structuredClone(config.replies ?? {});
    this.replySource = config.reply_source ? { ...config.reply_source } : undefined;
    requireThat(!this.replySource || (/^[a-f0-9]{64}$/.test(this.replySource.binding_digest)
      && typeof this.replySource.resolve === "function"), "invalid_feishu_reply_source");
    requireThat(object(this.replies) && Object.keys(this.replies).length <= 128, "invalid_feishu_reply_profile");
    for (const [taskId, reply] of Object.entries(this.replies)) {
      identifier(taskId);
      validateReply(reply);
    }
    this.binding_digest = digest({ adapter: "feishu_text.v1", adapter_id: this.adapter_id, transport: this.transport, domain: this.domain,
      app_id: config.app_id, ...(Object.keys(this.replies).length ? { replies: this.replies } : {}),
      ...(this.replySource ? { reply_source: this.replySource.binding_digest } : {}) });
  }
  assertCurrent(): void {
    const result: unknown = this.config.assertCurrent();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  retryPreparation(): void {
    this.assertCurrent(); const result: unknown = this.config.retryAuthentication?.();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  submissionIdentity(taskId: string, chatId: string): { chat_id: string; thread_id?: string } {
    this.assertCurrent();
    const reply = Object.hasOwn(this.replies, taskId) ? this.replies[taskId] : undefined;
    requireThat(!reply || reply.chat_id === chatId, "feishu_reply_chat_mismatch");
    return { chat_id: chatId, ...(reply ? { thread_id: reply.thread_id } : {}) };
  }
  private replyFor(envelope: TerminalDelivery): FeishuReplyTarget | undefined {
    const fixed = Object.hasOwn(this.replies, envelope.task_id) ? this.replies[envelope.task_id] : undefined;
    const dynamic = this.replySource?.resolve(structuredClone(envelope));
    if (dynamic !== undefined) validateReply(dynamic);
    requireThat(!fixed || !dynamic || digest(fixed) === digest(dynamic), "feishu_reply_source_conflict");
    return dynamic ?? fixed;
  }
  async prepare(original: TerminalDelivery, context: DeliveryContext): Promise<PreparedDelivery> {
    context.assertCurrent(); this.assertCurrent();
    const inputDigest = digest(original);
    const reply = this.replyFor(original), replyDigest = digest(reply ?? null);
    const target = (envelope: TerminalDelivery) => {
      requireThat(digest(envelope) === inputDigest, "feishu_prepared_input_changed");
      requireThat(digest(this.replyFor(envelope) ?? null) === replyDigest, "feishu_reply_source_changed");
      requireThat(envelope.target.transport === this.transport && /^oc_[A-Za-z0-9_-]{1,120}$/.test(envelope.target.chat_id), "feishu_target_unqualified");
      requireThat(envelope.target.topic_id === "" && envelope.target.thread_id === (reply?.thread_id ?? ""), "feishu_thread_profile_unqualified");
      requireThat(!reply || reply.chat_id === envelope.target.chat_id, "feishu_reply_chat_mismatch");
    };
    target(original);
    const token = await this.config.tenantAccessToken(context);
    context.assertCurrent(); this.assertCurrent();
    requireThat(typeof token === "string" && /^[A-Za-z0-9_.~+/=-]{1,4096}$/.test(token), "feishu_token_unavailable");
    const call = async (path: string, method: "GET" | "POST", body: unknown, control: DeliveryContext): Promise<Record<string, unknown>> => {
      control.assertCurrent(); this.assertCurrent();
      const checked: unknown = this.config.assertAccessToken?.(token);
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      const response = await this.request(`${this.domain}/open-apis/im/v1/messages${path}`, { method, redirect: "error", signal: control.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, ...(method === "POST" ? { body: JSON.stringify(body) } : {}) });
      // Bound every response and never include provider bodies or credentials in thrown errors/logs.
      if (!response.ok) { await response.body?.cancel(); requireThat(false, "feishu_delivery_http_rejected"); }
      requireThat(response.body, "feishu_delivery_http_rejected");
      const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
      try {
        while (true) { const item = await reader.read(); if (item.done) break; size += item.value.byteLength;
          requireThat(size <= 256 * 1024, "feishu_response_too_large"); chunks.push(item.value); }
      } finally { await reader.cancel(); reader.releaseLock(); }
      control.assertCurrent(); this.assertCurrent();
      const data: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
      requireThat(object(data) && data.code === 0 && object(data.data), "feishu_delivery_api_rejected");
      return data.data;
    };
    let rootId = "";
    if (reply) {
      const parent = await call(`/${encodeURIComponent(reply.message_id)}`, "GET", undefined, context);
      requireThat(Array.isArray(parent.items) && parent.items.length === 1 && object(parent.items[0]), "feishu_reply_parent_unavailable");
      const message = parent.items[0];
      requireThat(message.message_id === reply.message_id && message.chat_id === original.target.chat_id && !message.deleted
        && (message.thread_id ?? "") === reply.thread_id, "feishu_reply_parent_mismatch");
      rootId = typeof message.root_id === "string" && message.root_id ? message.root_id : reply.message_id;
      requireThat(/^om_[A-Za-z0-9_-]{1,120}$/.test(rootId), "feishu_reply_parent_mismatch");
    }
    const receipt = (envelope: TerminalDelivery, value: unknown, control: DeliveryContext): DeliveryReceipt => {
      requireThat(object(value) && value.msg_type === "text" && typeof value.message_id === "string", "feishu_message_unverified");
      identifier(value.message_id);
      requireThat(value.chat_id === envelope.target.chat_id && !value.deleted && !value.updated
        && object(value.sender) && value.sender.sender_type === "app" && value.sender.id === this.config.app_id,
      "feishu_message_identity_mismatch");
      requireThat(reply ? value.parent_id === reply.message_id && value.root_id === rootId && (value.thread_id ?? "") === reply.thread_id
        : !value.parent_id && !value.thread_id && !value.root_id, "feishu_message_thread_mismatch");
      requireThat(object(value.body) && typeof value.body.content === "string", "feishu_message_content_unavailable");
      const content: unknown = JSON.parse(value.body.content);
      requireThat(object(content) && content.text === visibleText(envelope), "feishu_message_content_mismatch");
      const created = Number(value.create_time);
      requireThat(Number.isSafeInteger(created) && typeof control.not_before === "number" && created >= control.not_before - 5000,
        "feishu_message_predates_attempt");
      return { schema_version: "controlmesh.delivery_receipt.v1", delivery_id: envelope.delivery_id, envelope_digest: digest(envelope),
        target_digest: digest(envelope.target), adapter_digest: this.binding_digest, remote_message_id: value.message_id };
    };
    return {
      send: async (envelope, control) => {
        target(envelope);
        const body = { msg_type: "text", content: JSON.stringify({ text: visibleText(envelope) }), uuid: envelope.delivery_id.slice(0, 32) };
        const data = await call(reply ? `/${encodeURIComponent(reply.message_id)}/reply` : "?receive_id_type=chat_id", "POST",
          reply ? { ...body, reply_in_thread: reply.reply_in_thread } : { ...body, receive_id: envelope.target.chat_id }, control);
        return receipt(envelope, data, control);
      },
      inspect: async (envelope, messageId, control) => {
        target(envelope); identifier(messageId);
        const data = await call(`/${encodeURIComponent(messageId)}`, "GET", undefined, control);
        requireThat(Array.isArray(data.items) && data.items.length === 1 && object(data.items[0]) && data.items[0].message_id === messageId,
          "feishu_message_unavailable");
        return receipt(envelope, data.items[0], control);
      },
    };
  }
}
