import { decodeDirectorDecision, type DirectorDecision } from "./team-control-decision";
import { decodeTeamResult, type StructuredTeamResult } from "./team-result-validation";
import { compactTeamText, teamResultSummary, teamReducedSummary } from "./team-progress";
import type { TeamReducedResult } from "./team-results";
import { startTopology, appendTopologyCheckpoint, decodeTopologyState, interruptTopology, resumeTopology, type TopologyState } from "./team-topology";
import { requireThat } from "./value";
export interface DirectorLimits {
  max_rounds: number; max_parent_interruptions: number; max_repair_cycles_per_run: number;
  max_parallel_workers_per_round: number; max_total_worker_dispatches: number;
}
export type DirectorOptions = Partial<Omit<DirectorLimits, "max_parallel_workers_per_round" | "max_total_worker_dispatches">> & {
  max_parallel_workers_per_round?: number | null; max_total_worker_dispatches?: number | null;
};
/** Pure policy port. The eventual task owner must persist these limits with the task. */
export class DirectorPolicy {
  readonly limits: Readonly<DirectorLimits>;
  constructor(parallelLimit: number, options: DirectorOptions = {}) {
    const rounds = options.max_rounds ?? 3, interruptions = options.max_parent_interruptions ?? 1, repairs = options.max_repair_cycles_per_run ?? 1;
    // Existing Python config treats zero like the omitted value for these two options.
    const parallel = options.max_parallel_workers_per_round || parallelLimit, total = options.max_total_worker_dispatches || rounds * parallel;
    requireThat([rounds, interruptions, repairs, parallel, total, parallelLimit].every(Number.isSafeInteger)
      && rounds >= 1 && interruptions >= 0 && repairs >= 0 && parallel >= 1 && parallel <= parallelLimit && total >= 1, "invalid_director_limits");
    this.limits = Object.freeze({ max_rounds: rounds, max_parent_interruptions: interruptions, max_repair_cycles_per_run: repairs,
      max_parallel_workers_per_round: parallel, max_total_worker_dispatches: total });
  }
  private state(value: TopologyState, stages: string[]): TopologyState {
    const state = decodeTopologyState(value);
    requireThat(state.topology === "director_worker" && stages.includes(state.checkpoints.at(-1)!.substage), "director_stage_mismatch"); return state;
  }
  private director(state: TopologyState): string { return state.checkpoints[0]!.active_roles[0] ?? "director"; }
  private round(state: TopologyState): number { return state.checkpoints.at(-1)!.round_index || 1; }
  private roundLimit(state: TopologyState): number { return state.checkpoints.at(-1)!.round_limit || this.limits.max_rounds; }
  private completed(state: TopologyState): string[] { return [...new Set([this.director(state), ...state.checkpoints.at(-1)!.completed_roles])]; }
  private summary(decision: DirectorDecision): string {
    const parts = [`director: ${compactTeamText(decision.summary, 96)}`];
    if (decision.decision === "dispatch_workers") parts.push(`${decision.dispatch_roles.length} workers`);
    if (decision.repair_hint !== null) parts.push(`repair: ${compactTeamText(decision.repair_hint, 40)}`);
    else if (decision.next_action !== null) parts.push(compactTeamText(decision.next_action, 40));
    return parts.join(" | ");
  }
  private terminal(state: TopologyState, decision: DirectorDecision, status: "completed" | "failed", summary: string, at: Date): TopologyState {
    const results = state.checkpoints.map(cp => cp.result).filter((result): result is StructuredTeamResult => result !== null && result.substage === "collecting");
    const success = results.filter(result => result.status === "completed"), preferred = success.length ? success : results;
    const reduced: TeamReducedResult = { schema_version: 1, topology: "director_worker", final_status: status, reduced_summary: summary,
      selected_evidence: decision.evidence.length ? decision.evidence : preferred.flatMap(result => result.evidence),
      selected_artifacts: decision.artifacts.length ? decision.artifacts : preferred.flatMap(result => result.artifacts), next_action: decision.next_action };
    return appendTopologyCheckpoint(state, { substage: status, phase_status: status, active_roles: [], completed_roles: this.completed(state),
      latest_summary: teamReducedSummary(reduced), artifact_count: reduced.selected_artifacts.length, round_index: this.round(state), round_limit: this.roundLimit(state), reduced_result: reduced }, at);
  }
  start(taskId: string, planningSummary: string, directorRole = "director", roundLimit?: number, at = new Date()): TopologyState {
    const limit = roundLimit || this.limits.max_rounds;
    requireThat(Number.isSafeInteger(limit) && limit >= 1 && limit <= this.limits.max_rounds, "invalid_director_round_limit");
    return startTopology(taskId, "director_worker", { active_roles: [directorRole], latest_summary: compactTeamText(planningSummary), round_index: 1, round_limit: limit }, at);
  }
  decide(value: TopologyState, raw: DirectorDecision, parent: { question?: string; waiting_on?: string } = {}, at = new Date()): TopologyState {
    const state = this.state(value, ["planning", "director_deciding", "repairing"]), decision = decodeDirectorDecision(raw), cp = state.checkpoints.at(-1)!;
    const currentRound = this.round(state), roundLimit = this.roundLimit(state);
    const budget = (reason: string) => this.terminal(state, decision, "failed", `director_worker failed with budget_exhausted: ${reason}`, at);
    if (decision.decision === "dispatch_workers") {
      const target = cp.substage === "planning" ? currentRound : currentRound + 1;
      requireThat(decision.round_index === target, "director_dispatch_round_mismatch");
      if (target > roundLimit || target > this.limits.max_rounds) return budget(`round ${target} exceeds the frozen limit of ${roundLimit}.`);
      requireThat(decision.dispatch_roles.length <= this.limits.max_parallel_workers_per_round, "director_parallel_limit");
      const dispatched = state.checkpoints.filter(item => item.substage === "dispatching").reduce((n, item) => n + item.active_roles.length, 0);
      if (dispatched + decision.dispatch_roles.length > this.limits.max_total_worker_dispatches) return budget("max_total_worker_dispatches was exceeded.");
      return appendTopologyCheckpoint(state, { substage: "dispatching", phase_status: "in_progress", active_roles: decision.dispatch_roles, completed_roles: [this.director(state)],
        latest_summary: this.summary(decision), artifact_count: cp.artifact_count, round_index: target, round_limit: roundLimit }, at);
    }
    requireThat(decision.round_index === currentRound, "director_current_round_mismatch");
    if (decision.decision === "complete" || decision.decision === "failed") return this.terminal(state, decision, decision.decision === "complete" ? "completed" : "failed", decision.summary, at);
    if (decision.decision === "needs_parent_input") {
      requireThat(parent.question !== undefined && parent.waiting_on !== undefined, "director_parent_question_required");
      if (state.checkpoints.filter(item => item.substage === "waiting_parent").length >= this.limits.max_parent_interruptions) return budget("max_parent_interruptions was exceeded.");
      return interruptTopology(state, { requested_by_role: this.director(state), question: parent.question, waiting_on: parent.waiting_on,
        latest_summary: this.summary(decision), completed_roles: cp.completed_roles, artifact_count: cp.artifact_count, repair_state: cp.repair_state,
        round_index: currentRound, round_limit: roundLimit }, at);
    }
    requireThat(decision.decision === "needs_repair" && cp.substage === "director_deciding", "director_repair_stage_mismatch");
    if (state.checkpoints.filter(item => item.substage === "repairing").length >= this.limits.max_repair_cycles_per_run) return budget("max_repair_cycles_per_run was exceeded.");
    return appendTopologyCheckpoint(state, { substage: "repairing", phase_status: "in_progress", active_roles: [this.director(state)], completed_roles: [this.director(state)],
      latest_summary: this.summary(decision), artifact_count: cp.artifact_count, repair_state: decision.repair_hint, round_index: currentRound, round_limit: roundLimit }, at);
  }
  collect(value: TopologyState, raw: StructuredTeamResult[], directorRole?: string, at = new Date()): TopologyState {
    let state = this.state(value, ["dispatching"]);
    const results = raw.map(decodeTeamResult), dispatched = state.checkpoints.at(-1)!.active_roles, submitted = results.map(result => result.worker_role);
    requireThat(results.length > 0 && new Set(submitted).size === results.length && JSON.stringify([...submitted].sort()) === JSON.stringify([...dispatched].sort()), "director_complete_batch_required");
    const round = this.round(state), limit = this.roundLimit(state), director = directorRole || this.director(state);
    for (const result of results) {
      requireThat(result.topology === "director_worker" && result.substage === "collecting", "director_result_stage_mismatch");
      const cp = state.checkpoints.at(-1)!;
      state = appendTopologyCheckpoint(state, { substage: "collecting", phase_status: "in_progress", active_roles: [result.worker_role], completed_roles: cp.completed_roles,
        latest_summary: teamResultSummary(result), artifact_count: cp.artifact_count + result.artifacts.length, round_index: round, round_limit: limit, result }, at);
    }
    const parts = [`${results.length} director_worker results collected for the director.`];
    for (const [status, label] of [["completed", "completed"], ["needs_repair", "repair"], ["failed", "failed"]]) {
      const roles = results.filter(result => result.status === status).map(result => result.worker_role);
      if (roles.length) parts.push(`${label}: ${roles.join(", ")}`);
    }
    return appendTopologyCheckpoint(state, { substage: "director_deciding", phase_status: "in_progress", active_roles: [director],
      completed_roles: [...new Set([director, ...results.filter(result => result.status !== "failed").map(result => result.worker_role)])], latest_summary: parts.join(" | "),
      artifact_count: state.checkpoints.at(-1)!.artifact_count, round_index: round, round_limit: limit }, at);
  }
  resume(value: TopologyState, parentInput: string, latestSummary?: string, at = new Date()): TopologyState {
    const state = this.state(value, ["waiting_parent"]), cp = state.checkpoints.at(-1)!;
    return resumeTopology(state, { parent_input: parentInput, latest_summary: latestSummary || cp.latest_summary || undefined,
      active_roles: state.interruption.requested_by_role ? [state.interruption.requested_by_role] : undefined, completed_roles: cp.completed_roles,
      round_index: cp.round_index ?? undefined, round_limit: cp.round_limit ?? undefined }, at);
  }
}
