import { createDecipheriv, createHash, timingSafeEqual } from "node:crypto";
import { decodeSnapshot } from "./migration";
import { object, requireThat } from "./value";

export interface FeishuEventConfiguration {
  app_id: string;
  verification_token: string;
  encrypt_key: string;
  allowed_senders: readonly string[];
  allowed_chats: readonly string[];
  bot_open_id?: string;
  require_group_mention?: boolean;
}
export interface FeishuIncomingMessage {
  schema_version: "controlmesh.feishu_incoming.v1";
  app_id: string; event_id: string; message_id: string; sender_id: string;
  chat_id: string; thread_id: string; root_id: string; text: string; created_at: number;
  source_scope: "direct_message" | "group_message";
  mentions_local_bot: boolean;
}
export type FeishuEvent = { kind: "challenge"; challenge: string } | { kind: "ignored"; reason: string }
  | { kind: "message"; message: FeishuIncomingMessage };

function equal(left: unknown, right: string): boolean {
  return typeof left === "string" && Buffer.byteLength(left) === Buffer.byteLength(right)
    && timingSafeEqual(Buffer.from(left), Buffer.from(right));
}
function ref(value: unknown, prefix: string): value is string {
  return typeof value === "string" && value.startsWith(prefix) && value.length > prefix.length
    && value.length <= prefix.length + 120 && /^[A-Za-z0-9_-]+$/.test(value);
}

/** Authenticates provider bytes; this object never accepts a principal or permissions from an event. */
export class FeishuEventAuthenticator {
  private readonly config: FeishuEventConfiguration;
  constructor(config: FeishuEventConfiguration, private readonly current: () => void, private readonly now = Date.now) {
    this.config = structuredClone(config);
    requireThat(ref(config.app_id, "cli_") && typeof config.verification_token === "string" && config.verification_token.length >= 1
      && config.verification_token.length <= 256 && typeof config.encrypt_key === "string" && config.encrypt_key.length >= 1
      && config.encrypt_key.length <= 256, "feishu_event_credentials_required");
    requireThat(Array.isArray(config.allowed_senders) && config.allowed_senders.length <= 128 && config.allowed_senders.every(id => ref(id, "ou_"))
      && Array.isArray(config.allowed_chats) && config.allowed_chats.length <= 128 && config.allowed_chats.every(id => ref(id, "oc_"))
      && (config.bot_open_id === undefined || ref(config.bot_open_id, "ou_"))
      && (config.require_group_mention === undefined || typeof config.require_group_mention === "boolean"), "invalid_feishu_event_policy");
  }
  assertCurrent(): void {
    const checked: unknown = this.current();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  policy(message: FeishuIncomingMessage): string | null {
    this.assertCurrent();
    if (message.app_id !== this.config.app_id) return "feishu_event_app_mismatch";
    if (!this.config.allowed_senders.includes(message.sender_id)) return "feishu_sender_denied";
    if (!this.config.allowed_chats.includes(message.chat_id)) return "feishu_chat_denied";
    if (message.source_scope === "group_message" && this.config.require_group_mention !== false && !message.mentions_local_bot) return "feishu_mention_required";
    return null;
  }
  receive(headers: Headers, bytes: Uint8Array): FeishuEvent {
    this.assertCurrent(); requireThat(bytes.byteLength > 0 && bytes.byteLength <= 65_536, "feishu_event_size_invalid");
    const outer = decodeSnapshot(bytes).source;
    requireThat(object(outer), "feishu_event_invalid");
    let payload = outer;
    if (Object.hasOwn(outer, "encrypt")) {
      requireThat(Object.keys(outer).length === 1 && typeof outer.encrypt === "string"
        && /^[A-Za-z0-9+/]+={0,2}$/.test(outer.encrypt) && outer.encrypt.length % 4 === 0, "feishu_event_ciphertext_invalid");
      const encrypted = Buffer.from(outer.encrypt, "base64");
      requireThat(encrypted.length >= 32 && encrypted.length % 16 === 0 && encrypted.toString("base64") === outer.encrypt, "feishu_event_ciphertext_invalid");
      const decipher = createDecipheriv("aes-256-cbc", createHash("sha256").update(this.config.encrypt_key).digest(), encrypted.subarray(0, 16));
      const decoded = Buffer.concat([decipher.update(encrypted.subarray(16)), decipher.final()]);
      const plaintext = decodeSnapshot(decoded).source; requireThat(object(plaintext), "feishu_event_invalid"); payload = plaintext;
    }
    const header = object(payload.header) ? payload.header : {};
    requireThat(equal(payload.type === "url_verification" ? payload.token : header.token, this.config.verification_token), "feishu_event_unauthenticated");
    // Official URL verification may omit signature headers; a valid secret token is still mandatory.
    if (payload.type === "url_verification") {
      requireThat(typeof payload.challenge === "string" && payload.challenge.length > 0 && payload.challenge.length <= 512, "feishu_challenge_invalid");
      return { kind: "challenge", challenge: payload.challenge };
    }
    const timestamp = headers.get("x-lark-request-timestamp"), nonce = headers.get("x-lark-request-nonce"), signature = headers.get("x-lark-signature");
    requireThat(timestamp && /^\d{1,12}$/.test(timestamp) && Number.isSafeInteger(Number(timestamp))
      && Math.abs(this.now() - Number(timestamp) * 1000) <= 300_000 && nonce && nonce.length <= 128
      && signature && /^[a-f0-9]{64}$/i.test(signature), "feishu_event_unauthenticated");
    const expected = createHash("sha256").update(timestamp + nonce + this.config.encrypt_key).update(bytes).digest("hex");
    requireThat(equal(signature.toLowerCase(), expected), "feishu_event_unauthenticated");
    requireThat(payload.schema === "2.0" && header.app_id === this.config.app_id, "feishu_event_app_mismatch");
    if (header.event_type !== "im.message.receive_v1") return { kind: "ignored", reason: "feishu_event_type_unsupported" };
    requireThat(typeof header.event_id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(header.event_id)
      && object(payload.event) && object(payload.event.message) && object(payload.event.sender), "feishu_event_invalid");
    const event = payload.event, message = event.message as Record<string, unknown>, sender = event.sender as Record<string, unknown>;
    if (sender.sender_type !== "user") return { kind: "ignored", reason: "feishu_sender_type_unsupported" };
    requireThat(object(sender.sender_id) && ref(sender.sender_id.open_id, "ou_") && ref(message.chat_id, "oc_")
      && ref(message.message_id, "om_") && ["p2p", "group"].includes(String(message.chat_type)), "feishu_event_identity_invalid");
    if (message.message_type !== "text") return { kind: "ignored", reason: "feishu_message_type_unsupported" };
    requireThat(typeof message.content === "string" && Buffer.byteLength(message.content) <= 40_000, "feishu_event_content_invalid");
    const content = decodeSnapshot(Buffer.from(message.content)).source;
    requireThat(object(content) && typeof content.text === "string" && content.text.trim() && Buffer.byteLength(content.text) <= 32_768, "feishu_event_content_invalid");
    const thread = message.thread_id ?? "", root = message.root_id ?? "", created = Number(message.create_time);
    requireThat((thread === "" || ref(thread, "th_")) && (root === "" || ref(root, "om_")) && Number.isSafeInteger(created)
      && created > 0 && created <= this.now() + 300_000, "feishu_event_identity_invalid");
    if (created < this.now() - 86_400_000) return { kind: "ignored", reason: "feishu_event_expired" };
    requireThat(message.mentions === undefined || (Array.isArray(message.mentions) && message.mentions.length <= 128), "feishu_event_mentions_invalid");
    const mentions = (message.mentions ?? []) as unknown[];
    const local = mentions.filter(item => typeof this.config.bot_open_id === "string" && object(item) && object(item.id) && item.id.open_id === this.config.bot_open_id);
    let text = content.text;
    for (const mention of local) if (object(mention) && typeof mention.key === "string" && /^@_user_\d+$/.test(mention.key)) text = text.replaceAll(mention.key, "");
    const normalized: FeishuIncomingMessage = { schema_version: "controlmesh.feishu_incoming.v1", app_id: this.config.app_id,
      event_id: header.event_id, message_id: message.message_id, sender_id: sender.sender_id.open_id, chat_id: message.chat_id,
      thread_id: thread as string, root_id: root as string, text: text.trim(), created_at: created,
      source_scope: message.chat_type === "group" ? "group_message" : "direct_message", mentions_local_bot: local.length > 0 };
    const denied = this.policy(normalized);
    if (denied || !normalized.text) return { kind: "ignored", reason: denied ?? "feishu_message_empty" };
    return { kind: "message", message: normalized };
  }
}
