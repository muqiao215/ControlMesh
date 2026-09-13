import { expect, test } from "bun:test";
import { sendTelegramControlReply, type TelegramControlReply } from "../src/telegram-control-reply";
import { digest } from "../src/value";

const reply: TelegramControlReply = { request_id: "a".repeat(64), bot_id: "123456", chat_id: "777", thread_id: "12", text: "No active task." };
function fixture(patch: Record<string, unknown> = {}) {
  let sends = 0, claims = 0, tokens = 0, valid = true;
  const current = () => { if (!valid) throw new Error("revoked"); };
  const config = { adapter_id: "selected", bot_id: reply.bot_id, assertCurrent: current, assertToken: current,
    async botToken() { tokens++; return "123456:fixture_token_only"; } };
  const response = { message_id: 1, date: Math.floor(Date.now() / 1000), from: { id: 123456, is_bot: true },
    chat: { id: 777 }, message_thread_id: 12, text: reply.text, ...patch };
  const request = (async (url: string | URL | Request, init?: RequestInit) => {
    sends++; expect(String(url)).toBe("https://api.telegram.org/bot123456:fixture_token_only/sendMessage");
    const body = JSON.parse(String(init?.body)); expect(body).toMatchObject({ chat_id: "777", message_thread_id: 12, text: reply.text });
    expect(body.task_id).toBeUndefined(); expect(body.parse_mode).toBeUndefined(); expect(init?.redirect).toBe("error");
    return Response.json({ ok: true, result: response });
  }) as typeof fetch;
  const context = { signal: new AbortController().signal, assertCurrent: current };
  return { config, request, context, claim: () => { claims++; }, revoke: () => { valid = false; }, counts: () => ({ sends, claims, tokens }) };
}
test("control reply verifies its independent response identity without a task envelope", async () => {
  const f = fixture(); expect(await sendTelegramControlReply(f.config, digest("adapter"), f.request, reply, f.context, f.claim))
    .toEqual({ reply_digest: digest(reply), adapter_digest: digest("adapter"), remote_message_id: "1" });
  expect(f.counts()).toEqual({ sends: 1, claims: 1, tokens: 1 });
});
for (const patch of [{ chat: { id: 888 } }, { from: { id: 222222, is_bot: true } }, { message_thread_id: 13 }, { text: "different" },
  { date: 1 }, { reply_markup: { inline_keyboard: [] } }, { edit_date: 1 }, { reply_to_message: {} }]) test(`control reply rejects mismatched acknowledgement ${JSON.stringify(patch)}`, async () => {
  const f = fixture(patch);
  await expect(sendTelegramControlReply(f.config, digest("adapter"), f.request, reply, f.context, f.claim)).rejects.toThrow("telegram_control_receipt_mismatch");
  expect(f.counts().sends).toBe(1);
});
test("invalid control target is rejected before credentials or dispatch claim", async () => {
  const f = fixture();
  await expect(sendTelegramControlReply(f.config, digest("adapter"), f.request, { ...reply, bot_id: "different" }, f.context, f.claim)).rejects.toThrow();
  expect(f.counts()).toEqual({ sends: 0, claims: 0, tokens: 0 });
});
test("revocation at durable claim prevents network dispatch", async () => {
  const f = fixture();
  await expect(sendTelegramControlReply(f.config, digest("adapter"), f.request, reply, f.context, () => { f.claim(); f.revoke(); })).rejects.toThrow("revoked");
  expect(f.counts()).toEqual({ sends: 0, claims: 1, tokens: 1 });
});
test("network uncertainty is never retried by control transport", async () => {
  const f = fixture(); let sends = 0;
  const request = (async () => { sends++; throw new Error("lost acknowledgement"); }) as unknown as typeof fetch;
  await expect(sendTelegramControlReply(f.config, digest("adapter"), request, reply, f.context, f.claim)).rejects.toThrow("telegram_control_reply_unknown");
  expect(sends).toBe(1);
});
