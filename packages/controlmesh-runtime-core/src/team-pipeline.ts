import { exhaustedTeamBudget, type TeamStepBudgets } from "./team-budgets";
import { compactTeamText as pipelineSummary, teamResultSummary as summary, teamReducedSummary as reducedSummary } from "./team-progress";
export { compactTeamText as pipelineSummary } from "./team-progress";
import { decodeTeamResult, type StructuredTeamResult } from "./team-result-validation";
import { reducePipelineReview, reducePipelineTerminal } from "./team-results";
import { appendTopologyCheckpoint, decodeTopologyState, interruptTopology, resumeTopology, type TopologyState } from "./team-topology";
import { requireThat } from "./value";

function stateFor(state: TopologyState, substage?: string): TopologyState {
  const current = decodeTopologyState(state);
  requireThat(current.topology === "pipeline" && (!substage || current.checkpoints.at(-1)!.substage === substage), "pipeline_stage_mismatch");
  return current;
}
function planner(state: TopologyState): string { return state.checkpoints[0]!.active_roles[0] ?? "planner"; }
function completed(state: TopologyState, role: string): string[] { return [...new Set([planner(state), ...state.checkpoints.at(-1)!.completed_roles, role])]; }
export function dispatchPipelineWorker(state: TopologyState, role = "worker", latestSummary?: string, at = new Date()): TopologyState {
  const current = stateFor(state, "planning"), cp = current.checkpoints.at(-1)!;
  return appendTopologyCheckpoint(current, { substage: "worker_running", phase_status: "in_progress", active_roles: [role], completed_roles: [planner(current)],
    latest_summary: pipelineSummary(latestSummary || cp.latest_summary || "Planner dispatched worker."), artifact_count: cp.artifact_count }, at);
}
export interface PipelineResultOptions extends TeamStepBudgets { reviewer_role?: string; repair_worker_role?: string; parent_question?: string; waiting_on?: string }
export function applyPipelineResult(state: TopologyState, value: StructuredTeamResult, options: PipelineResultOptions = {}, at = new Date()): TopologyState {
  const current = stateFor(state), cp = current.checkpoints.at(-1)!, result = decodeTeamResult(value);
  requireThat(result.topology === "pipeline" && result.substage === cp.substage, "pipeline_result_stage_mismatch");
  requireThat(["worker_running", "repairing", "review_running"].includes(cp.substage), "pipeline_stage_mismatch");
  const exhausted = exhaustedTeamBudget(current, result, options, at); if (exhausted) return exhausted;
  const review = cp.substage === "review_running";
  if (!review && result.status === "completed") return appendTopologyCheckpoint(current, { substage: "review_running", phase_status: "in_progress",
    active_roles: [options.reviewer_role ?? "reviewer"], completed_roles: completed(current, result.worker_role), latest_summary: summary(result), artifact_count: result.artifacts.length, result }, at);
  if (result.status === "failed" || (review && result.status === "completed")) {
    const worker = [...current.checkpoints].reverse().map(checkpoint => checkpoint.result)
      .find(candidate => candidate !== null && ["worker_running", "repairing"].includes(candidate.substage));
    requireThat(!review || worker, "pipeline_worker_result_missing");
    const reduced = review ? reducePipelineReview(worker!, result) : reducePipelineTerminal(result);
    return appendTopologyCheckpoint(current, { substage: result.status === "completed" ? "completed" : "failed", phase_status: result.status === "completed" ? "completed" : "failed",
      active_roles: [], completed_roles: completed(current, result.worker_role), latest_summary: reducedSummary(reduced), artifact_count: reduced.selected_artifacts.length, result, reduced_result: reduced }, at);
  }
  if (review && result.status === "needs_parent_input") {
    requireThat(options.parent_question !== undefined && options.waiting_on !== undefined, "pipeline_parent_question_required");
    return interruptTopology(current, { requested_by_role: result.worker_role, question: options.parent_question, waiting_on: options.waiting_on,
      latest_summary: summary(result), completed_roles: cp.completed_roles, artifact_count: Math.max(cp.artifact_count, result.artifacts.length), result }, at);
  }
  if (review && result.status === "needs_repair") {
    const previousWorker = [...current.checkpoints].reverse().map(checkpoint => checkpoint.result)
      .find(candidate => candidate !== null && ["worker_running", "repairing"].includes(candidate.substage));
    const role = cp.result && cp.result.worker_role !== "reviewer" ? cp.result.worker_role : previousWorker?.worker_role ?? options.repair_worker_role ?? "worker";
    return appendTopologyCheckpoint(current, { substage: "repairing", phase_status: "in_progress", active_roles: [role], completed_roles: [planner(current)],
      latest_summary: summary(result), artifact_count: Math.max(cp.artifact_count, result.artifacts.length), repair_state: result.repair_hint, result }, at);
  }
  requireThat(false, "pipeline_result_status_unsupported");
}
export function resumePipeline(state: TopologyState, parentInput: string, latestSummary?: string, at = new Date()): TopologyState {
  const current = stateFor(state, "waiting_parent"), cp = current.checkpoints.at(-1)!;
  return resumeTopology(current, { parent_input: parentInput, latest_summary: latestSummary || cp.latest_summary || undefined,
    active_roles: current.interruption.requested_by_role ? [current.interruption.requested_by_role] : undefined, completed_roles: cp.completed_roles }, at);
}
