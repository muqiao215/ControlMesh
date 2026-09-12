import { exhaustedTeamBudget, type TeamStepBudgets } from "./team-budgets";
import { decodeTeamResult, type StructuredTeamResult } from "./team-result-validation";
import { compactTeamText, teamResultSummary, teamReducedSummary } from "./team-progress";
import { reduceFailedFanout, reduceFanoutResult, type TeamReducedResult } from "./team-results";
import { appendTopologyCheckpoint, decodeTopologyState, interruptTopology, resumeTopology, type TopologyState } from "./team-topology";
import { requireThat } from "./value";
function stateFor(state: TopologyState, stage: string): TopologyState {
  const current = decodeTopologyState(state);
  requireThat(current.topology === "fanout_merge" && current.checkpoints.at(-1)!.substage === stage, "fanout_stage_mismatch");
  return current;
}
const coordinator = (state: TopologyState) => state.checkpoints[0]!.active_roles[0] ?? "coordinator";
const completed = (state: TopologyState, role: string) => [...new Set([coordinator(state), ...state.checkpoints.at(-1)!.completed_roles, role])];
function resultFor(value: StructuredTeamResult, stage: string): StructuredTeamResult {
  const result = decodeTeamResult(value);
  requireThat(result.topology === "fanout_merge" && result.substage === stage, "fanout_result_stage_mismatch"); return result;
}
export function dispatchFanoutWorkers(state: TopologyState, roles: string[], limit: number, latestSummary?: string, at = new Date()): TopologyState {
  const current = stateFor(state, "planning");
  requireThat(roles.length > 0 && Number.isSafeInteger(limit) && limit >= 1 && roles.length <= limit, "fanout_parallel_limit");
  return appendTopologyCheckpoint(current, { substage: "dispatching", phase_status: "in_progress", active_roles: roles, completed_roles: [coordinator(current)],
    latest_summary: compactTeamText(latestSummary || `Dispatching ${roles.length}/${limit} bounded parallel workers: ${roles.join(", ")}.`), artifact_count: 0 }, at);
}
export function collectFanoutWorkers(state: TopologyState, values: StructuredTeamResult[], reducerRole = "reducer", at = new Date()): TopologyState {
  let current = stateFor(state, "dispatching"); requireThat(values.length > 0, "fanout_results_required");
  for (const value of values) {
    const result = resultFor(value, "collecting"), cp = current.checkpoints.at(-1)!;
    current = appendTopologyCheckpoint(current, { substage: "collecting", phase_status: "in_progress", active_roles: [result.worker_role], completed_roles: cp.completed_roles,
      latest_summary: teamResultSummary(result), artifact_count: cp.artifact_count + result.artifacts.length, result }, at);
  }
  const collected = current.checkpoints.map(cp => cp.result).filter((result): result is StructuredTeamResult => result !== null && result.substage === "collecting");
  const success = collected.filter(result => result.status === "completed"), failed = collected.filter(result => result.status === "failed");
  if (!success.length) {
    const reduced = reduceFailedFanout(failed);
    return appendTopologyCheckpoint(current, { substage: "failed", phase_status: "failed", active_roles: [], completed_roles: [coordinator(current)],
      latest_summary: teamReducedSummary(reduced), artifact_count: reduced.selected_artifacts.length, reduced_result: reduced }, at);
  }
  const summary = `${success.length} worker results ready for reduction: ${success.map(result => result.worker_role).join(", ")}.`
    + (failed.length ? ` partial failure: ${failed.length} failed (${failed.map(result => result.worker_role).join(", ")})` : "");
  return appendTopologyCheckpoint(current, { substage: "reducing", phase_status: "in_progress", active_roles: [reducerRole],
    completed_roles: [...new Set([coordinator(current), ...success.map(result => result.worker_role)])], latest_summary: summary,
    artifact_count: success.reduce((total, result) => total + result.artifacts.length, 0) }, at);
}
export interface FanoutResultOptions extends TeamStepBudgets { parent_question?: string; waiting_on?: string; repair_worker_role?: string; reducer_role?: string }
export function applyFanoutResult(state: TopologyState, value: StructuredTeamResult, options: FanoutResultOptions = {}, at = new Date()): TopologyState {
  const stage = state.checkpoints.at(-1)?.substage;
  requireThat(stage === "reducing" || stage === "repairing", "fanout_stage_mismatch");
  const current = stateFor(state, stage), cp = current.checkpoints.at(-1)!, result = resultFor(value, stage);
  const exhausted = exhaustedTeamBudget(current, result, options, at); if (exhausted) return exhausted;
  if (stage === "repairing" && result.status === "completed") return appendTopologyCheckpoint(current, { substage: "reducing", phase_status: "in_progress",
    active_roles: [options.reducer_role ?? "reducer"], completed_roles: completed(current, result.worker_role), latest_summary: teamResultSummary(result),
    artifact_count: Math.max(cp.artifact_count, result.artifacts.length), result }, at);
  if (result.status === "failed" || (stage === "reducing" && result.status === "completed")) {
    const reduced: TeamReducedResult = stage === "reducing" ? reduceFanoutResult(current.checkpoints.map(checkpoint => checkpoint.result), result)
      : { schema_version: 1, topology: "fanout_merge", final_status: "failed", reduced_summary: result.summary, selected_evidence: result.evidence, selected_artifacts: result.artifacts, next_action: result.next_action };
    return appendTopologyCheckpoint(current, { substage: result.status === "completed" ? "completed" : "failed", phase_status: result.status === "completed" ? "completed" : "failed",
      active_roles: [], completed_roles: stage === "reducing" ? completed(current, result.worker_role) : cp.completed_roles,
      latest_summary: teamReducedSummary(reduced), artifact_count: reduced.selected_artifacts.length, result, reduced_result: reduced }, at);
  }
  if (stage === "reducing" && result.status === "needs_parent_input") {
    requireThat(options.parent_question !== undefined && options.waiting_on !== undefined, "fanout_parent_question_required");
    return interruptTopology(current, { requested_by_role: result.worker_role, question: options.parent_question, waiting_on: options.waiting_on,
      latest_summary: teamResultSummary(result), completed_roles: cp.completed_roles, artifact_count: Math.max(cp.artifact_count, result.artifacts.length), result }, at);
  }
  if (stage === "reducing" && result.status === "needs_repair") return appendTopologyCheckpoint(current, { substage: "repairing", phase_status: "in_progress",
    active_roles: [options.repair_worker_role ?? "coordinator"], completed_roles: cp.completed_roles, latest_summary: teamResultSummary(result),
    artifact_count: Math.max(cp.artifact_count, result.artifacts.length), repair_state: result.repair_hint, result }, at);
  requireThat(false, "fanout_result_status_unsupported");
}
export function resumeFanout(state: TopologyState, parentInput: string, latestSummary?: string, at = new Date()): TopologyState {
  const current = stateFor(state, "waiting_parent"), cp = current.checkpoints.at(-1)!;
  return resumeTopology(current, { parent_input: parentInput, latest_summary: latestSummary || cp.latest_summary || undefined,
    active_roles: current.interruption.requested_by_role ? [current.interruption.requested_by_role] : undefined, completed_roles: cp.completed_roles }, at);
}
