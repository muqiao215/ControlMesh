import { requireThat } from "./value";

export type SessionReference = { kind: "i" | "s"; value: string };
export interface RuntimeSessionKey { transport: string; chat: SessionReference; topic: SessionReference | null }
const integer = (value: string): SessionReference => {
  requireThat(/^-?\d+$/.test(value) && value.length <= 128, "invalid_session_integer");
  return { kind: "i", value: BigInt(value).toString() };
};
function reference(kind: string, value: string): SessionReference {
  if (kind === "i") return integer(value);
  requireThat(kind === "s", "invalid_session_reference");
  try { return { kind: "s", value: decodeURIComponent(value) }; }
  catch { throw new Error("invalid_session_encoding"); }
}
/** Preserve integer identity without ever converting legacy identifiers to Number. */
export function parseRuntimeSessionKey(raw: string): RuntimeSessionKey {
  requireThat(typeof raw === "string" && raw.length > 0 && raw.length <= 8192 && !/[\x00\r\n]/.test(raw), "invalid_session_key");
  const parts = raw.split(":");
  let result: RuntimeSessionKey;
  if (parts[0] === "v2") {
    requireThat(parts.length === 4 || parts.length === 6, "invalid_session_key");
    result = { transport: parts[1]!, chat: reference(parts[2]!, parts[3]!), topic: parts.length === 6 ? reference(parts[4]!, parts[5]!) : null };
  } else if (parts.length === 1) result = { transport: "tg", chat: integer(parts[0]!), topic: null };
  else if (parts.length === 2 && /^-?\d+$/.test(parts[0]!)) result = { transport: "tg", chat: integer(parts[0]!), topic: integer(parts[1]!) };
  else {
    requireThat(parts.length === 2 || parts.length === 3, "invalid_session_key");
    result = { transport: parts[0]!, chat: integer(parts[1]!), topic: parts.length === 3 ? integer(parts[2]!) : null };
  }
  requireThat(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(result.transport), "invalid_session_transport");
  return result;
}
const quote = (value: string) => encodeURIComponent(value).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
export function runtimeSessionStorageKey(raw: string): string {
  const { transport, chat, topic } = parseRuntimeSessionKey(raw);
  if (chat.kind === "s" || topic?.kind === "s") {
    const encode = (ref: SessionReference) => `${ref.kind}:${ref.kind === "s" ? quote(ref.value) : ref.value}`;
    return `v2:${transport}:${encode(chat)}${topic ? `:${encode(topic)}` : ""}`;
  }
  return `${transport}:${chat.value}${topic ? `:${topic.value}` : ""}`;
}
