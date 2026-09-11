import { expect, test } from "bun:test";
import { fileURLToPath } from "node:url";
import { FeishuEventAuthenticator } from "../src";
import { event, eventConfig, signed } from "./helpers/feishu-events";

const auth = () => new FeishuEventAuthenticator(eventConfig, () => {});
for (const encrypted of [false, true]) test(`signed ${encrypted ? "encrypted" : "plain"} event keeps provider identity and exact text`, () => {
  const packet = signed(event("你好，retain all context"), encrypted);
  expect(auth().receive(packet.headers, packet.bytes)).toMatchObject({ kind: "message", message: {
    app_id: "cli_fixture", event_id: "ev_one", message_id: "om_one", sender_id: "ou_user", source_scope: "direct_message", text: "你好，retain all context" } });
});
test("signature covers the original whitespace and body bytes", () => {
  const packet = signed(event());
  expect(auth().receive(packet.headers, packet.bytes).kind).toBe("message");
  expect(() => auth().receive(packet.headers, Buffer.from(JSON.stringify(JSON.parse(packet.bytes.toString()))))).toThrow("feishu_event_unauthenticated");
});
for (const kind of ["missing", "forged", "expired", "future", "token", "app"] as const) test(`event ${kind} authentication failure cannot become user input`, () => {
  const body = event(); if (kind === "token") body.header.token = "not_the_token"; if (kind === "app") body.header.app_id = "cli_other";
  const packet = signed(body, false, String(Math.floor(Date.now() / 1000) + (kind === "expired" ? -360 : kind === "future" ? 360 : 0)));
  if (kind === "missing") packet.headers.delete("x-lark-signature"); if (kind === "forged") packet.headers.set("x-lark-signature", "0".repeat(64));
  expect(() => auth().receive(packet.headers, packet.bytes)).toThrow();
});
test("URL challenge requires the configured token even when no signature headers are supplied", () => {
  for (const encrypted of [false, true]) {
    const packet = signed({ type: "url_verification", token: eventConfig.verification_token, challenge: "fixture_challenge" }, encrypted);
    expect(auth().receive(new Headers(), packet.bytes)).toEqual({ kind: "challenge", challenge: "fixture_challenge" });
  }
  expect(() => auth().receive(new Headers(), Buffer.from('{"type":"url_verification","challenge":"untrusted"}'))).toThrow("feishu_event_unauthenticated");
});
test("encrypted envelopes cannot overlay authenticated plaintext fields", () => {
  const packet = signed(event(), true), outer = JSON.parse(packet.bytes.toString()); outer.header = { app_id: "cli_other" };
  expect(() => auth().receive(packet.headers, Buffer.from(JSON.stringify(outer)))).toThrow("feishu_event_ciphertext_invalid");
});
test("a group needs an actual configured bot mention; missing identifiers never count as a mention", () => {
  const body = event("@_user_1 inspect this", "one", true);
  let packet = signed(body); expect(auth().receive(packet.headers, packet.bytes)).toEqual({ kind: "ignored", reason: "feishu_mention_required" });
  body.event.message.mentions = [{ id: { open_id: "ou_bot" }, key: "@_user_1" }]; packet = signed(body);
  expect(auth().receive(packet.headers, packet.bytes)).toMatchObject({ kind: "message", message: { text: "inspect this", source_scope: "group_message" } });
  body.event.message.mentions = [{ id: {}, key: "@_user_1" }]; packet = signed(body);
  const noBot = new FeishuEventAuthenticator({ ...eventConfig, bot_open_id: undefined }, () => {});
  expect(noBot.receive(packet.headers, packet.bytes)).toEqual({ kind: "ignored", reason: "feishu_mention_required" });
});
for (const field of ["sender", "chat", "bot", "type"] as const) test(`unauthorized or unsupported ${field} is not admitted`, () => {
  const body = event();
  if (field === "sender") body.event.sender.sender_id.open_id = "ou_other";
  if (field === "chat") body.event.message.chat_id = "oc_other";
  if (field === "bot") body.event.sender.sender_type = "app";
  if (field === "type") body.event.message.message_type = "interactive";
  const packet = signed(body); expect(auth().receive(packet.headers, packet.bytes).kind).toBe("ignored");
});
test("live official Python SDK decrypts the same AES/PKCS7 event bytes", () => {
  const original = event("独立 SDK 解密校验"), packet = signed(original, true);
  const child = Bun.spawnSync(["uv", "run", "python", "-c",
    "import json,sys; from lark_oapi.core.utils.decryptor import AESCipher; value=json.load(sys.stdin); print(AESCipher('fixture_encryption').decrypt_str(value['encrypt']))"],
    { cwd: fileURLToPath(new URL("../../..", import.meta.url)), stdin: packet.bytes, stdout: "pipe", stderr: "pipe", timeout: 10_000 });
  expect(child.exitCode).toBe(0); expect(JSON.parse(child.stdout.toString())).toEqual(original);
});
