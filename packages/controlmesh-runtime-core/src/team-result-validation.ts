import { text, optional, number, boolean, entries } from "./team-normalize";
import { assertProtocolSchema } from "@controlmesh/protocol";
import { object } from "./value";
import type { TeamWorkerResult } from "./team-results";

export interface StructuredTeamResult extends TeamWorkerResult {
  schema_version: 1; result_items: { kind: string; ref: string; summary: string | null }[];
  confidence: number | null; needs_parent_input: boolean; repair_hint: string | null;
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
