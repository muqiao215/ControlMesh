import { expect, test } from "bun:test";
import { TelegramEventAuthenticator } from "../src/telegram-event-auth";

const config = { bot_id: "123456", bot_username: "fixture_bot", allowed_senders: ["777"], allowed_chats: ["777", "-100123"] };
function update(): any {
  return { update_id: 31, callback_query: { id: "query_123", data: `cmc:${"a".repeat(48)}`,
    from: { id: 777, is_bot: false }, message: { message_id: 17, date: 1700000000,
      from: { id: 123456, is_bot: true }, chat: { id: -100123, type: "supergroup" }, message_thread_id: 10,
      text: "untrusted replacement", reply_markup: { inline_keyboard: [[{ text: "Cancel all", callback_data: "tsc:cancelall" }]] } } } };
}
const bytes = (body: unknown) => Buffer.from(JSON.stringify(body));

test("callback normalization keeps only selected bot, clicker, parent, topic and opaque choice identity", () => {
  const auth = new TelegramEventAuthenticator(config, () => {});
  expect(auth.callbackAuthenticated(bytes(update()))).toEqual({ kind: "callback", callback: {
    schema_version: "controlmesh.telegram_callback.v1", bot_id: "123456", event_id: "31", callback_id: "query_123",
    choice_id: `cmc:${"a".repeat(48)}`, message_id: "17", sender_id: "777", chat_id: "-100123", thread_id: "10", source_scope: "group_message",
  } });
});

for (const mode of ["sender", "chat", "bot", "human-message", "bot-clicker", "inaccessible", "inline", "control", "ambiguous", "string-id", "thread", "forwarded"]) {
  test(`callback refuses ${mode} before task execution`, () => {
    const auth = new TelegramEventAuthenticator(config, () => {}), body = update(), q = body.callback_query;
    if (mode === "sender") q.from.id = 888;
    if (mode === "chat") q.message.chat.id = -999;
    if (mode === "bot") q.message.from.id = 888;
    if (mode === "human-message") q.message.from.is_bot = false;
    if (mode === "bot-clicker") q.from.is_bot = true;
    if (mode === "inaccessible") q.message.date = 0;
    if (mode === "inline") q.inline_message_id = "inline";
    if (mode === "control") q.data = "tsc:cancelall";
    if (mode === "ambiguous") body.message = q.message;
    if (mode === "string-id") q.message.from.id = "123456";
    if (mode === "thread") q.message.message_thread_id = -1;
    if (mode === "forwarded") q.message.forward_origin = { type: "user" };
    let accepted = false;
    try { accepted = auth.callbackAuthenticated(bytes(body)).kind === "callback"; } catch {}
    expect(accepted).toBe(false);
  });
}

test("callback admission rechecks the registered policy owner and bounds raw provider input", () => {
  let revoked = false;
  const auth = new TelegramEventAuthenticator(config, () => { if (revoked) throw new Error("revoked"); });
  expect(() => auth.callbackAuthenticated(Buffer.alloc(65537))).toThrow("telegram_event_size_invalid");
  revoked = true;
  expect(() => auth.callbackAuthenticated(bytes(update()))).toThrow("revoked");
});
