import { createCipheriv, createHash } from "node:crypto";

export const eventConfig = { app_id: "cli_fixture", verification_token: "fixture_verification", encrypt_key: "fixture_encryption",
  allowed_senders: ["ou_user"], allowed_chats: ["oc_chat"], bot_open_id: "ou_bot" };
export function event(text = "Read the project", id = "one", group = false) {
  return { schema: "2.0", header: { event_id: `ev_${id}`, app_id: eventConfig.app_id, token: eventConfig.verification_token, event_type: "im.message.receive_v1" },
    event: { sender: { sender_type: "user", sender_id: { open_id: "ou_user" } }, message: { message_id: `om_${id}`, chat_id: "oc_chat",
      chat_type: group ? "group" : "p2p", create_time: String(Date.now()), message_type: "text", content: JSON.stringify({ text }),
      thread_id: "", root_id: "", mentions: [] as any[] } } };
}
export function signed(payload: unknown, encrypted = false, timestamp = String(Math.floor(Date.now() / 1000))) {
  let raw = JSON.stringify(payload, null, 2);
  if (encrypted) {
    const iv = Buffer.alloc(16, 7), cipher = createCipheriv("aes-256-cbc", createHash("sha256").update(eventConfig.encrypt_key).digest(), iv);
    raw = JSON.stringify({ encrypt: Buffer.concat([iv, cipher.update(raw), cipher.final()]).toString("base64") });
  }
  const bytes = Buffer.from(raw), nonce = "fixture_nonce";
  const signature = createHash("sha256").update(timestamp + nonce + eventConfig.encrypt_key).update(bytes).digest("hex");
  const headers = new Headers({ "content-type": "application/json", "x-lark-request-timestamp": timestamp, "x-lark-request-nonce": nonce, "x-lark-signature": signature });
  return { bytes, headers };
}
