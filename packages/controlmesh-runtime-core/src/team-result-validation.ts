import { assertProtocolSchema } from "@controlmesh/protocol";
import { object } from "./value";
import type { TeamWorkerResult } from "./team-results";

export interface StructuredTeamResult extends TeamWorkerResult {
  schema_version: 1; result_items: { kind: string; ref: string; summary: string | null }[];
  confidence: number | null; needs_parent_input: boolean; repair_hint: string | null;
}
// Python str.strip includes U+001C–U+001F and U+0085 but does not strip U+FEFF.
const pythonWhitespace = "[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]";
const strip = new RegExp(`^${pythonWhitespace}+|${pythonWhitespace}+$`, "g");
function text(value: unknown): unknown { return typeof value === "string" ? value.replace(strip, "") : value; }
function optional(value: unknown): unknown { return value === undefined ? null : text(value); }
function number(value: unknown, integer = false): unknown {
  if (typeof value === "boolean") return Number(value);
  if (typeof value !== "string") return value;
  const normalized = value.trim();
  const decimal = integer ? /^[+-]?\d+(?:\.0+)?$/ : /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
  return decimal.test(normalized) && Number.isFinite(Number(normalized)) ? Number(normalized) : value;
}
function boolean(value: unknown): unknown {
  if (value === undefined) return false;
  if (value === 1 || value === 0) return Boolean(value);
  if (typeof value === "string") {
    const lower = value.toLowerCase();
    if (["1", "true", "t", "yes", "y", "on"].includes(lower)) return true;
    if (["0", "false", "f", "no", "n", "off"].includes(lower)) return false;
  }
  return value;
}
function entries(value: unknown, kind: "item" | "evidence" | "artifact"): unknown {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return value;
  return value.map(item => !object(item) ? item : {
    ref: text(item.ref), kind: text(item.kind === undefined ? (kind === "artifact" ? "file" : kind === "evidence" ? "event" : undefined) : item.kind),
    summary: optional(item.summary), ...(kind === "artifact" ? { label: optional(item.label) } : {}),
  });
}
/** Normalize JSON model output, then enforce the shared normalized wire contract. No authority is issued. */
export function decodeTeamResult(value: unknown): StructuredTeamResult {
  const raw = object(value) ? value : {};
  const result = {
    schema_version: raw.schema_version === undefined ? 1 : number(raw.schema_version, true), status: text(raw.status), topology: text(raw.topology),
    substage: text(raw.substage), worker_role: text(raw.worker_role), summary: text(raw.summary),
    result_items: entries(raw.result_items, "item"), evidence: entries(raw.evidence, "evidence"), artifacts: entries(raw.artifacts, "artifact"),
    confidence: raw.confidence === undefined ? null : number(raw.confidence), next_action: optional(raw.next_action),
    needs_parent_input: boolean(raw.needs_parent_input), repair_hint: optional(raw.repair_hint),
  };
  assertProtocolSchema<StructuredTeamResult>("team-structured-result.schema.json", result);
  return result;
}
