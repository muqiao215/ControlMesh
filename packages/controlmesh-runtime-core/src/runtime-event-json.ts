import { object, requireThat } from "./value";

/** Internal legacy-event codec. Never pass bigint-bearing values through ordinary JSON.stringify. */
export function parseRuntimeEventJson(text: string): unknown {
  requireThat(Buffer.byteLength(text) <= 1024 * 1024, "runtime_event_too_large");
  const parse = JSON.parse as (text: string, reviver: (key: string, value: unknown, context?: { source?: string }) => unknown) => unknown;
  return parse(text, (_key, value, context) => {
    if (typeof value === "number" && Number.isInteger(value) && !Number.isSafeInteger(value)) {
      requireThat(typeof context?.source === "string" && /^-?\d+$/.test(context.source) && context.source.length <= 4096, "runtime_event_number_unproven");
      return BigInt(context.source);
    }
    return value;
  });
}
export function runtimeEventJson(value: unknown, depth = 0): string {
  requireThat(depth <= 64, "runtime_event_depth_exceeded");
  if (typeof value === "bigint") {
    const raw = value.toString(); requireThat(raw.length <= 4096, "runtime_event_integer_too_large"); return raw;
  }
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    requireThat(Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value)), "runtime_event_number_unproven");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(item => runtimeEventJson(item, depth + 1)).join(",")}]`;
  requireThat(object(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value)), "invalid_runtime_event_json");
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${runtimeEventJson(value[key], depth + 1)}`).join(",")}}`;
}
