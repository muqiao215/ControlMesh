import { assertProtocolSchema } from "@controlmesh/protocol";
import { object } from "./value";
import { text, optional, number, entries } from "./team-normalize";
import type { TeamEvidenceRef, TeamArtifactRef } from "./team-results";
interface ControlDecision {
  schema_version: 1; round_index: number; decision: string; summary: string;
  evidence: TeamEvidenceRef[]; artifacts: TeamArtifactRef[]; confidence: number | null;
  next_action: string | null; repair_hint: string | null; stop_reason: string | null;
}
export interface DirectorDecision extends ControlDecision { topology: "director_worker"; dispatch_roles: string[] }
export interface JudgeDecision extends ControlDecision { topology: "debate_judge"; winner_role: string | null; next_candidate_roles: string[] }
function base(raw: Record<string, unknown>, topology: string) {
  return { schema_version: raw.schema_version === undefined ? 1 : number(raw.schema_version, true),
    // The Python control models require exact topology tokens instead of normalizing them.
    topology: raw.topology === undefined ? topology : raw.topology,
    round_index: number(raw.round_index, true), decision: text(raw.decision), summary: text(raw.summary),
    evidence: entries(raw.evidence, "evidence"), artifacts: entries(raw.artifacts, "artifact"),
    confidence: raw.confidence === undefined ? null : number(raw.confidence), next_action: optional(raw.next_action),
    repair_hint: optional(raw.repair_hint), stop_reason: optional(raw.stop_reason) };
}
const roles = (value: unknown) => value === undefined ? [] : Array.isArray(value) ? value.map(text) : value;
export function decodeDirectorDecision(value: unknown): DirectorDecision {
  const raw = object(value) ? value : {};
  const decision = { ...base(raw, "director_worker"), dispatch_roles: roles(raw.dispatch_roles) };
  assertProtocolSchema<DirectorDecision>("team-director-decision.schema.json", decision); return decision;
}
export function decodeJudgeDecision(value: unknown): JudgeDecision {
  const raw = object(value) ? value : {};
  const decision = { ...base(raw, "debate_judge"), winner_role: optional(raw.winner_role), next_candidate_roles: roles(raw.next_candidate_roles) };
  assertProtocolSchema<JudgeDecision>("team-judge-decision.schema.json", decision); return decision;
}
