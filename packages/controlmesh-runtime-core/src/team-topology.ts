import { assertProtocolSchema } from "@controlmesh/protocol";
import { requireThat } from "./value";
import type { StructuredTeamResult } from "./team-result-validation";
import type { TeamReducedResult } from "./team-results";

export interface TopologyCheckpoint {
  checkpoint_id: string; topology: string; substage: string; phase_status: string;
  active_roles: string[]; completed_roles: string[]; latest_summary: string | null;
  waiting_on: string | null; artifact_count: number; needs_parent_input: boolean;
  repair_state: string | null; round_index: number | null; round_limit: number | null;
  result: StructuredTeamResult | null; reduced_result: (Omit<TeamReducedResult, "topology"> & { topology: string }) | null; recorded_at: string | null;
}
export interface TopologyInterruption {
  status: "idle" | "waiting_parent"; requested_by_role: string | null; question: string | null;
  waiting_on: string | null; raised_at: string | null; resume_substage: string | null;
  resume_phase_status: string | null; resume_count: number; last_parent_input: string | null; last_resumed_at: string | null;
}
export interface TopologyState {
  schema_version: 1; task_id: string; execution_id: string; topology: string;
  checkpoints: TopologyCheckpoint[]; interruption: TopologyInterruption; created_at: string | null; updated_at: string | null;
}
export type CheckpointInput = Pick<TopologyCheckpoint, "substage" | "phase_status"> & Partial<Omit<TopologyCheckpoint, "checkpoint_id" | "topology" | "recorded_at">>;
const stages: Record<string, readonly string[]> = {
  pipeline: ["planning", "worker_running", "review_running", "completed", "failed", "waiting_parent", "repairing"],
  fanout_merge: ["planning", "dispatching", "collecting", "reducing", "completed", "failed", "waiting_parent", "repairing"],
  director_worker: ["planning", "dispatching", "collecting", "director_deciding", "waiting_parent", "repairing", "completed", "failed"],
  debate_judge: ["planning", "candidate_round", "collecting", "judging", "waiting_parent", "repairing", "completed", "failed"],
};
/** Strict normalized persistence boundary; this is not a general Pydantic input coercer. */
export function decodeTopologyState(value: unknown): TopologyState {
  assertProtocolSchema<TopologyState>("team-topology-state.schema.json", value);
  for (const stamp of [value.created_at, value.updated_at, value.interruption.raised_at,
    value.interruption.last_resumed_at, ...value.checkpoints.map(cp => cp.recorded_at)]) {
    if (stamp === null) continue;
    // The normalized wire uses ISO calendar timestamps, not JavaScript's permissive date grammar.
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.exec(stamp);
    requireThat(match && Number.isFinite(Date.parse(stamp)), "invalid_topology_timestamp");
    const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    requireThat(year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]!
      && Number(match[4]) < 24 && Number(match[5]) < 60 && Number(match[6]) < 60, "invalid_topology_timestamp");
  }
  for (const cp of value.checkpoints) {
    requireThat(cp.topology === value.topology && (!cp.result || cp.result.topology === value.topology)
      && (!cp.reduced_result || cp.reduced_result.topology === value.topology), "topology_checkpoint_mismatch");
    requireThat((cp.round_index === null) === (cp.round_limit === null)
      && (cp.round_index === null || cp.round_index <= cp.round_limit!), "invalid_topology_round");
  }
  const interruption = value.interruption;
  requireThat(interruption.resume_substage === null || stages[value.topology]!.includes(interruption.resume_substage), "invalid_topology_resume_substage");
  requireThat((value.checkpoints.at(-1)!.substage === "waiting_parent") === (interruption.status === "waiting_parent"), "topology_interruption_mismatch");
  return structuredClone(value);
}
const clean = (value: string): string => value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");
const optional = (value: string | null | undefined) => value == null ? null : clean(value);
const utc = (at: Date) => at.toISOString().replace(/\.000Z$/, "+00:00").replace(/\.(\d{3})Z$/, ".$1000+00:00");
function idle(): TopologyInterruption {
  return { status: "idle", requested_by_role: null, question: null, waiting_on: null, raised_at: null,
    resume_substage: null, resume_phase_status: "in_progress", resume_count: 0, last_parent_input: null, last_resumed_at: null };
}
function checkpoint(topology: string, index: number, input: CheckpointInput, now: string): TopologyCheckpoint {
  return { checkpoint_id: `cp_${String(index).padStart(4, "0")}`, topology, substage: clean(input.substage), phase_status: clean(input.phase_status),
    active_roles: (input.active_roles ?? []).map(clean), completed_roles: (input.completed_roles ?? []).map(clean),
    latest_summary: optional(input.latest_summary), waiting_on: optional(input.waiting_on), artifact_count: input.artifact_count ?? 0,
    needs_parent_input: input.needs_parent_input ?? false, repair_state: optional(input.repair_state),
    round_index: input.round_index ?? null, round_limit: input.round_limit ?? null, result: input.result ?? null,
    reduced_result: input.reduced_result ?? null, recorded_at: now };
}
export function startTopology(taskId: string, topology: string, input: Partial<Pick<CheckpointInput, "active_roles" | "latest_summary" | "round_index" | "round_limit">> = {}, at = new Date()): TopologyState {
  const now = utc(at); topology = clean(topology);
  return decodeTopologyState({ schema_version: 1, task_id: taskId, execution_id: `${taskId}-exec`, topology,
    checkpoints: [checkpoint(topology, 1, { ...input, substage: "planning", phase_status: "in_progress" }, now)],
    interruption: idle(), created_at: now, updated_at: now });
}
export function appendTopologyCheckpoint(state: TopologyState, input: CheckpointInput, at = new Date()): TopologyState {
  const current = decodeTopologyState(state), now = utc(at);
  return decodeTopologyState({ ...current, checkpoints: [...current.checkpoints, checkpoint(current.topology, current.checkpoints.length + 1, input, now)], updated_at: now });
}
export interface TopologyInterruptInput extends Partial<Omit<CheckpointInput, "substage" | "phase_status" | "active_roles" | "needs_parent_input" | "reduced_result">> {
  requested_by_role: string; question: string; waiting_on: string; resume_phase_status?: string;
}
export function interruptTopology(state: TopologyState, input: TopologyInterruptInput, at = new Date()): TopologyState {
  const current = decodeTopologyState(state), latest = current.checkpoints.at(-1)!, now = utc(at);
  const cp = checkpoint(current.topology, current.checkpoints.length + 1, { ...input,
    substage: "waiting_parent", phase_status: "blocked", active_roles: [input.requested_by_role],
    completed_roles: input.completed_roles?.length ? input.completed_roles : latest.completed_roles,
    artifact_count: input.artifact_count ?? latest.artifact_count, needs_parent_input: true,
    round_index: input.round_index ?? latest.round_index, round_limit: input.round_limit ?? latest.round_limit }, now);
  return decodeTopologyState({ ...current, checkpoints: [...current.checkpoints, cp], updated_at: now,
    interruption: { ...current.interruption, status: "waiting_parent", requested_by_role: clean(input.requested_by_role), question: clean(input.question),
      waiting_on: clean(input.waiting_on), raised_at: now, resume_substage: latest.substage, resume_phase_status: clean(input.resume_phase_status ?? "in_progress") } });
}
export interface TopologyResumeInput { parent_input: string; latest_summary?: string; active_roles?: string[]; completed_roles?: string[]; round_index?: number; round_limit?: number }
export function resumeTopology(state: TopologyState, input: TopologyResumeInput, at = new Date()): TopologyState {
  const current = decodeTopologyState(state), latest = current.checkpoints.at(-1)!, now = utc(at);
  requireThat(current.interruption.status === "waiting_parent", "topology_not_waiting_parent");
  const cp = checkpoint(current.topology, current.checkpoints.length + 1, { substage: current.interruption.resume_substage!,
    phase_status: current.interruption.resume_phase_status ?? "in_progress", latest_summary: input.latest_summary,
    active_roles: input.active_roles?.length ? input.active_roles : latest.active_roles,
    completed_roles: input.completed_roles?.length ? input.completed_roles : latest.completed_roles,
    artifact_count: latest.artifact_count, round_index: input.round_index ?? latest.round_index, round_limit: input.round_limit ?? latest.round_limit }, now);
  return decodeTopologyState({ ...current, checkpoints: [...current.checkpoints, cp], updated_at: now,
    interruption: { ...idle(), resume_count: current.interruption.resume_count + 1, last_parent_input: clean(input.parent_input), last_resumed_at: now } });
}
