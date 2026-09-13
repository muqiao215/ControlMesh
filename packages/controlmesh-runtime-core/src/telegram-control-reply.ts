import type { DeliveryContext } from "./delivery-outbox";
import type { TelegramDeliveryConfiguration } from "./telegram-delivery";
import { digest, object, requireThat } from "./value";

/** Private runtime response, bound to an authenticated inbox request rather than a task. */
export interface TelegramControlReply { request_id: string; bot_id: string; chat_id: string; thread_id: string; text: string }
export interface TelegramControlReceipt { reply_digest: string; adapter_digest: string; remote_message_id: string }

export async function sendTelegramControlReply(config: TelegramDeliveryConfiguration, adapterDigest: string, request: typeof fetch,
  reply: TelegramControlReply, context: DeliveryContext, beforeDispatch: () => void): Promise<TelegramControlReceipt> {
  const issued = digest(reply), target = structuredClone(reply);
  requireThat(/^[a-f0-9]{64}$/.test(reply.request_id) && reply.bot_id === config.bot_id && /^-?[1-9][0-9]*$/.test(reply.chat_id)
    && Number.isSafeInteger(Number(reply.chat_id)) && (reply.thread_id === "" || /^[1-9][0-9]*$/.test(reply.thread_id) && Number.isSafeInteger(Number(reply.thread_id)))
    && typeof reply.text === "string" && reply.text.length > 0 && reply.text.length <= 4096, "telegram_control_reply_invalid");
  context.assertCurrent();
  const token = await config.botToken(context);
  const current = () => {
    context.assertCurrent();
    for (const checked of [config.assertCurrent(), config.assertToken(token)] as unknown[]) {
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    }
    requireThat(digest(reply) === issued && config.bot_id === target.bot_id
      && typeof token === "string" && /^[1-9][0-9]*:[A-Za-z0-9_-]{16,256}$/.test(token)
      && token.split(":")[0] === target.bot_id, "telegram_control_reply_changed");
  };
  current(); const started = Date.now();
  const claimed: unknown = beforeDispatch();
  if (claimed !== undefined) { void Promise.resolve(claimed).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  current();
  let response: Response;
  try { response = await request(`https://api.telegram.org/bot${token}/sendMessage`, { method: "POST", redirect: "error", signal: context.signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chat_id: target.chat_id, text: target.text,
      link_preview_options: { is_disabled: true }, ...(target.thread_id ? { message_thread_id: Number(target.thread_id) } : {}) }) }); }
  catch { requireThat(false, "telegram_control_reply_unknown"); }
  requireThat(response.body, "telegram_control_reply_unknown");
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) { const next = await reader.read(); if (next.done) break;
      size += next.value.length; requireThat(size <= 65536, "telegram_control_reply_oversized"); chunks.push(next.value); }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  current(); let data: unknown;
  try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks))); }
  catch { requireThat(false, "telegram_control_reply_unknown"); }
  requireThat(response.ok && object(data) && data.ok === true && object(data.result), "telegram_control_reply_rejected");
  const value = data.result;
  requireThat(Number.isSafeInteger(value.message_id) && Number(value.message_id) > 0 && object(value.chat)
    && String(value.chat.id) === target.chat_id && Number.isSafeInteger(value.chat.id) && object(value.from)
    && value.from.is_bot === true && String(value.from.id) === target.bot_id && Number.isSafeInteger(value.from.id)
    && String(value.message_thread_id ?? "") === target.thread_id && value.text === target.text
    && Number.isSafeInteger(value.date) && Number(value.date) * 1000 >= started - 5000
    && !value.reply_markup && !value.reply_to_message && !value.external_reply && !value.forward_origin && !value.sender_chat
    && !value.business_connection_id && !value.edit_date && !value.is_ephemeral && !value.is_from_offline && !value.is_paid_post
    && !value.direct_messages_topic, "telegram_control_receipt_mismatch");
  return { reply_digest: issued, adapter_digest: adapterDigest, remote_message_id: String(value.message_id) };
}
