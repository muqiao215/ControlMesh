import { timingSafeEqual } from "node:crypto";
import { decodeSnapshot } from "./migration";
import { object, requireThat } from "./value";

export interface TelegramEventConfiguration {
  bot_id: string; bot_username: string; secret_token?: string;
  allowed_senders: readonly string[]; allowed_chats: readonly string[]; require_group_mention?: boolean;
}
export interface TelegramIncomingMessage {
  schema_version: "controlmesh.telegram_incoming.v1";
  bot_id: string; event_id: string; message_id: string; sender_id: string;
  chat_id: string; thread_id: string; text: string; created_at: number;
  source_scope: "direct_message" | "group_message"; mentions_local_bot: boolean;
}
function id(value: unknown, signed = false): value is string {
  return typeof value === "string" && (signed ? /^-?[1-9][0-9]*$/ : /^[1-9][0-9]*$/).test(value) && Number.isSafeInteger(Number(value));
}
export function assertTelegramIncoming(value: unknown): asserts value is TelegramIncomingMessage {
  requireThat(object(value) && value.schema_version === "controlmesh.telegram_incoming.v1" && id(value.bot_id)
    && typeof value.event_id === "string" && /^(0|[1-9][0-9]*)$/.test(value.event_id) && Number.isSafeInteger(Number(value.event_id))
    && id(value.message_id) && id(value.sender_id) && id(value.chat_id, true) && (value.thread_id === "" || id(value.thread_id))
    && typeof value.text === "string" && value.text.length > 0 && Buffer.byteLength(value.text) <= 65536
    && Number.isSafeInteger(value.created_at) && Number(value.created_at) > 0
    && ["direct_message", "group_message"].includes(String(value.source_scope)) && typeof value.mentions_local_bot === "boolean",
    "telegram_incoming_invalid");
}

/** Secret-authenticated provider bytes; body fields cannot issue runtime permissions. */
export class TelegramEventAuthenticator {
  private readonly config: TelegramEventConfiguration;
  constructor(config: TelegramEventConfiguration, private readonly current: () => void) {
    this.config = structuredClone(config);
    requireThat(id(config.bot_id) && typeof config.bot_username === "string" && /^[A-Za-z0-9_]{5,32}$/.test(config.bot_username)
      && (config.secret_token === undefined || (typeof config.secret_token === "string" && /^[A-Za-z0-9_-]{1,256}$/.test(config.secret_token))), "telegram_webhook_credentials_required");
    requireThat(Array.isArray(config.allowed_senders) && config.allowed_senders.length <= 128 && config.allowed_senders.every(value => id(value))
      && Array.isArray(config.allowed_chats) && config.allowed_chats.length <= 128 && config.allowed_chats.every(value => id(value, true))
      && (config.require_group_mention === undefined || typeof config.require_group_mention === "boolean"), "invalid_telegram_event_policy");
  }
  assertCurrent(): void {
    const result: unknown = this.current();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  policy(message: TelegramIncomingMessage): string | null {
    this.assertCurrent();
    if (message.bot_id !== this.config.bot_id) return "telegram_event_bot_mismatch";
    if (!this.config.allowed_senders.includes(message.sender_id)) return "telegram_sender_denied";
    if (!this.config.allowed_chats.includes(message.chat_id)) return "telegram_chat_denied";
    if (message.source_scope === "group_message" && this.config.require_group_mention !== false && !message.mentions_local_bot) return "telegram_mention_required";
    return null;
  }
  receive(headers: Headers, bytes: Uint8Array): { kind: "ignored"; reason: string } | { kind: "message"; message: TelegramIncomingMessage } {
    this.assertCurrent();
    const supplied = headers.get("x-telegram-bot-api-secret-token"), secret = this.config.secret_token;
    requireThat(typeof secret === "string" && typeof supplied === "string" && Buffer.byteLength(supplied) === Buffer.byteLength(secret)
      && timingSafeEqual(Buffer.from(supplied), Buffer.from(secret)), "telegram_event_auth_failed");
    return this.receiveAuthenticated(bytes);
  }
  /** Trusted polling transport only, after validating the selected HTTPS bot response. */
  receiveAuthenticated(bytes: Uint8Array): { kind: "ignored"; reason: string } | { kind: "message"; message: TelegramIncomingMessage } {
    this.assertCurrent();
    requireThat(bytes.byteLength > 0 && bytes.byteLength <= 65536, "telegram_event_size_invalid");
    const update = decodeSnapshot(bytes).source;
    requireThat(object(update) && Number.isSafeInteger(update.update_id) && Number(update.update_id) >= 0, "telegram_update_invalid");
    if (!object(update.message)) return { kind: "ignored", reason: "telegram_update_type_unsupported" };
    requireThat(Object.keys(update).every(key => key === "update_id" || key === "message"), "telegram_update_ambiguous");
    const value = update.message;
    if (!object(value.from) || value.from.is_bot !== false || value.sender_chat || value.business_connection_id || value.guest_query_id
      || !object(value.chat) || !["private", "group", "supergroup"].includes(String(value.chat.type)) || typeof value.text !== "string")
      return { kind: "ignored", reason: "telegram_message_type_unsupported" };
    requireThat(Number.isSafeInteger(value.from.id) && Number.isSafeInteger(value.chat.id) && Number.isSafeInteger(value.message_id)
      && Number.isSafeInteger(value.date) && Number(value.date) > 0 && Number(value.date) <= Number.MAX_SAFE_INTEGER / 1000
      && (value.message_thread_id === undefined || (Number.isSafeInteger(value.message_thread_id) && Number(value.message_thread_id) > 0)), "telegram_message_identity_invalid");
    const text = value.text, username = `@${this.config.bot_username.toLowerCase()}`;
    let mentioned = false;
    if (value.entities !== undefined) {
      requireThat(Array.isArray(value.entities) && value.entities.length <= 256, "telegram_entities_invalid");
      for (const entity of value.entities) {
        requireThat(object(entity) && Number.isSafeInteger(entity.offset) && Number(entity.offset) >= 0 && Number.isSafeInteger(entity.length)
          && Number(entity.length) > 0 && Number(entity.offset) + Number(entity.length) <= text.length, "telegram_entity_range_invalid");
        const content = text.slice(Number(entity.offset), Number(entity.offset) + Number(entity.length)).toLowerCase();
        if (entity.type === "mention" && content === username) mentioned = true;
        if (entity.type === "bot_command" && /^\/[a-z0-9_]+@[a-z0-9_]+$/.test(content) && content.endsWith(username)) mentioned = true;
      }
    }
    if (object(value.reply_to_message) && object(value.reply_to_message.from) && value.reply_to_message.from.is_bot === true
      && Number.isSafeInteger(value.reply_to_message.from.id) && String(value.reply_to_message.from.id) === this.config.bot_id) mentioned = true;
    const message: TelegramIncomingMessage = { schema_version: "controlmesh.telegram_incoming.v1", bot_id: this.config.bot_id,
      event_id: String(update.update_id), message_id: String(value.message_id), sender_id: String(value.from.id), chat_id: String(value.chat.id),
      thread_id: value.message_thread_id === undefined ? "" : String(value.message_thread_id), text, created_at: Number(value.date) * 1000,
      source_scope: value.chat.type === "private" ? "direct_message" : "group_message", mentions_local_bot: mentioned };
    assertTelegramIncoming(message); const reason = this.policy(message);
    return reason ? { kind: "ignored", reason } : { kind: "message", message };
  }
}
