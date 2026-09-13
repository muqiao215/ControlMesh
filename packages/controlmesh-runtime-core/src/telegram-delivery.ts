import { assertProtocolSchema, type DeliveryReceipt, type TerminalDelivery } from "@controlmesh/protocol";
import type { DeliveryAdapter, DeliveryContext, PreparedDelivery } from "./delivery-outbox";
import { digest, identifier, object, requireThat } from "./value";

export interface TelegramDeliveryConfiguration {
  adapter_id: string; bot_id: string;
  /** Explicit selected bot credential owner; no discovery from other accounts. */
  botToken(context: DeliveryContext): Promise<string>;
  assertToken(token: string): void;
  assertCurrent(): void;
}
function numericId(value: unknown, positive = false): value is string {
  return typeof value === "string" && (positive ? /^[1-9][0-9]*$/ : /^-?[1-9][0-9]*$/).test(value)
    && Number.isSafeInteger(Number(value));
}
export function telegramDeliveryText(envelope: TerminalDelivery): string {
  const scope = envelope.execution_context.source_scope;
  const label = scope === "cron" ? "Scheduled task" : scope === "heartbeat" ? "Heartbeat task"
    : scope === "bot_handoff" ? "Agent task" : scope === "webhook" ? "Webhook task" : "Task";
  return `${label} ${envelope.task_id}: ${envelope.status === "done" ? "completed" : envelope.status}\n\n${envelope.text}`;
}
/** Plain text, numeric chat/forum target. Unknown sends are never retried here. */
export class TelegramTextDelivery implements DeliveryAdapter {
  readonly adapter_id: string; readonly transport = "telegram"; readonly binding_digest: string;
  private readonly botId: string;
  constructor(private readonly config: TelegramDeliveryConfiguration, private readonly request: typeof fetch = fetch) {
    identifier(config.adapter_id); requireThat(numericId(config.bot_id, true), "invalid_telegram_bot_id");
    this.adapter_id = config.adapter_id; this.botId = config.bot_id;
    this.binding_digest = digest({ adapter: "telegram_text.v1", adapter_id: this.adapter_id, bot_id: this.botId, transport: this.transport });
  }
  assertCurrent() {
    const result: unknown = this.config.assertCurrent();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(this.config.bot_id === this.botId && this.config.adapter_id === this.adapter_id, "telegram_registration_changed");
  }
  submissionIdentity(_taskId: string, chatId: string): { chat_id: string } {
    this.assertCurrent(); requireThat(numericId(chatId), "telegram_target_unqualified"); return { chat_id: chatId };
  }
  async recoverAcknowledgement(envelope: TerminalDelivery, receipt: DeliveryReceipt, context: DeliveryContext): Promise<DeliveryReceipt> {
    context.assertCurrent(); this.assertCurrent();
    assertProtocolSchema("delivery-receipt.schema.json", receipt);
    requireThat(envelope.target.transport === this.transport && numericId(envelope.target.chat_id)
      && receipt.delivery_id === envelope.delivery_id && receipt.envelope_digest === digest(envelope)
      && receipt.target_digest === digest(envelope.target) && receipt.adapter_digest === this.binding_digest
      && numericId(receipt.remote_message_id, true), "telegram_acknowledgement_mismatch");
    // No credential access or remote call: this accepts the already verified original send,
    // not a claim that its content still exists remotely. The outbox binds the stored observation.
    return structuredClone(receipt);
  }
  async prepare(original: TerminalDelivery, context: DeliveryContext): Promise<PreparedDelivery> {
    context.assertCurrent(); this.assertCurrent(); const issued = digest(original), text = telegramDeliveryText(original);
    const target = (value: TerminalDelivery) => {
      requireThat(digest(value) === issued && value.target.transport === this.transport && numericId(value.target.chat_id), "telegram_target_unqualified");
      requireThat(value.target.topic_id === "" && (value.target.thread_id === "" || numericId(value.target.thread_id, true)), "telegram_thread_unqualified");
      // Multipart delivery needs per-part receipts; never silently truncate task output.
      requireThat(text.length > 0 && text.length <= 4096, "telegram_text_requires_multipart");
    };
    target(original);
    const token = await this.config.botToken(context);
    const current = (control: DeliveryContext) => {
      control.assertCurrent(); this.assertCurrent();
      const checked: unknown = this.config.assertToken(token);
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(typeof token === "string" && /^[1-9][0-9]*:[A-Za-z0-9_-]{16,256}$/.test(token) && token.split(":")[0] === this.botId, "telegram_token_identity_mismatch");
    };
    current(context);
    return {
      send: async (envelope, control) => {
        target(envelope); current(control);
        let response: Response;
        try { response = await this.request(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", redirect: "error", signal: control.signal,
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chat_id: envelope.target.chat_id, text,
            link_preview_options: { is_disabled: true }, ...(envelope.target.thread_id ? { message_thread_id: Number(envelope.target.thread_id) } : {}) }) }); }
        catch { requireThat(false, "telegram_delivery_outcome_unknown"); }
        requireThat(response.body, "telegram_delivery_response_missing");
        const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
        try {
          while (true) { const item = await reader.read(); if (item.done) break;
            size += item.value.length; requireThat(size <= 256 * 1024, "telegram_response_too_large"); chunks.push(item.value); }
        } catch { requireThat(false, "telegram_delivery_response_unproven"); }
        finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
        current(control);
        let data: unknown; try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks))); }
        catch { requireThat(false, "telegram_delivery_response_unproven"); }
        requireThat(response.ok && object(data) && data.ok === true && object(data.result), "telegram_delivery_api_rejected");
        const value = data.result;
        requireThat(Number.isSafeInteger(value.message_id) && Number(value.message_id) > 0 && object(value.chat)
          && Number.isSafeInteger(value.chat.id) && String(value.chat.id) === envelope.target.chat_id
          && object(value.from) && value.from.is_bot === true && Number.isSafeInteger(value.from.id) && String(value.from.id) === this.botId, "telegram_message_identity_mismatch");
        requireThat(String(value.message_thread_id ?? "") === envelope.target.thread_id && !value.reply_to_message && !value.external_reply
          && !value.business_connection_id && !value.sender_chat && !value.forward_origin && !value.is_ephemeral && !value.edit_date
          && !value.direct_messages_topic && !value.is_from_offline && !value.is_paid_post, "telegram_message_context_mismatch");
        requireThat(value.text === text, "telegram_message_content_mismatch");
        requireThat(Number.isSafeInteger(value.date) && Number(value.date) > 0 && typeof control.not_before === "number"
          && Number(value.date) * 1000 >= control.not_before - 5000, "telegram_message_predates_attempt");
        const receipt: DeliveryReceipt = { schema_version: "controlmesh.delivery_receipt.v1", delivery_id: envelope.delivery_id,
          envelope_digest: issued, target_digest: digest(envelope.target), adapter_digest: this.binding_digest, remote_message_id: String(value.message_id) };
        return receipt;
      },
      inspect: async (envelope, _messageId, control) => {
        target(envelope); current(control);
        // No Bot API getMessage readback. Do not send/edit/forward as a substitute.
        throw new Error("telegram_readback_unavailable");
      },
    };
  }
}
