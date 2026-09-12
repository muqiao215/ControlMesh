import { decodeJudgeDecision, type JudgeDecision } from "./team-control-decision";
import { decodeTeamResult, type StructuredTeamResult } from "./team-result-validation";
import { compactTeamText, teamResultSummary, teamReducedSummary } from "./team-progress";
import { text } from "./team-normalize";
import type { TeamReducedResult } from "./team-results";
import { startTopology, appendTopologyCheckpoint, decodeTopologyState, interruptTopology, resumeTopology, type TopologyState } from "./team-topology";
import { requireThat } from "./value";
/** Pure debate policy. Exactly two candidates; no task/permission authority is issued here. */
export class JudgePolicy {
  constructor(private readonly parallelLimit: number) { requireThat(Number.isSafeInteger(parallelLimit) && parallelLimit >= 1, "invalid_judge_parallel_limit"); }
  private state(value: TopologyState, stages?: string[]): TopologyState {
    const state = decodeTopologyState(value);
    requireThat(state.topology === "debate_judge" && (!stages || stages.includes(state.checkpoints.at(-1)!.substage)), "judge_stage_mismatch"); return state;
  }
  private judge(state: TopologyState): string { return state.checkpoints[0]!.active_roles[0] ?? "judge"; }
  private roles(values: string[]): string[] {
    const roles = values.map(role => text(role) as string).filter(Boolean);
    requireThat(roles.length === 2 && new Set(roles).size === 2 && roles.length <= this.parallelLimit, "judge_two_distinct_candidates_required"); return roles;
  }
  private roundResults(state: TopologyState, round: number): StructuredTeamResult[] {
    let start = -1;
    for (let index = state.checkpoints.length - 1; index >= 0; index--) {
      const cp = state.checkpoints[index]!;
      if (cp.substage === "candidate_round" && cp.round_index === round) { start = index; break; }
    }
    return state.checkpoints.slice(start + 1).filter(cp => cp.substage === "collecting" && cp.round_index === round && cp.result !== null).map(cp => cp.result!);
  }
  private summary(decision: JudgeDecision): string {
    const parts = [compactTeamText(decision.summary, 104)];
    if (decision.evidence.length) parts.push(`${decision.evidence.length} evidence`);
    if (decision.artifacts.length) parts.push(`${decision.artifacts.length} artifacts`);
    if (decision.decision === "needs_repair" && decision.repair_hint !== null) parts.push(`repair: ${compactTeamText(decision.repair_hint, 40)}`);
    else if (decision.next_action !== null) parts.push(compactTeamText(decision.next_action, 40));
    return parts.join(" | ");
  }
  start(taskId: string, planningSummary: string, roundLimit: number, judgeRole = "judge", at = new Date()): TopologyState {
    requireThat(Number.isSafeInteger(roundLimit) && roundLimit > 0, "invalid_judge_round_limit");
    return startTopology(taskId, "debate_judge", { active_roles: [judgeRole], latest_summary: compactTeamText(planningSummary), round_index: 1, round_limit: roundLimit }, at);
  }
  candidates(value: TopologyState, roles: string[], latestSummary?: string, at = new Date()): TopologyState {
    const state = this.state(value, ["planning", "repairing"]), cp = state.checkpoints.at(-1)!, normalized = this.roles(roles), round = cp.round_index || 1;
    const summary = latestSummary || `Starting candidate round ${round}${cp.round_limit === null ? "" : `/${cp.round_limit}`}: ${normalized.join(", ")}.`;
    return appendTopologyCheckpoint(state, { substage: "candidate_round", phase_status: "in_progress", active_roles: normalized, completed_roles: [this.judge(state)],
      latest_summary: compactTeamText(summary), round_index: round, round_limit: cp.round_limit }, at);
  }
  collect(value: TopologyState, raw: StructuredTeamResult[], judgeRole = "judge", at = new Date()): TopologyState {
    let state = this.state(value, ["candidate_round"]); const cp = state.checkpoints.at(-1)!, round = cp.round_index!, limit = cp.round_limit;
    const results = raw.map(decodeTeamResult), roles = results.map(result => result.worker_role);
    requireThat(results.length > 0 && new Set(roles).size === roles.length && roles.length === cp.active_roles.length
      && roles.every(role => cp.active_roles.includes(role)), "judge_complete_batch_required");
    for (const result of results) {
      requireThat(result.topology === "debate_judge" && result.substage === "collecting", "judge_candidate_stage_mismatch");
      const last = state.checkpoints.at(-1)!;
      state = appendTopologyCheckpoint(state, { substage: "collecting", phase_status: "in_progress", active_roles: [result.worker_role],
        completed_roles: [...new Set([...last.completed_roles, result.worker_role])], latest_summary: teamResultSummary(result),
        artifact_count: last.artifact_count + result.artifacts.length, round_index: round, round_limit: limit, result }, at);
    }
    const current = this.roundResults(state, round), parts = [`Round ${round} collected ${current.length} candidate envelopes.`];
    for (const [status, label] of [["completed", "completed"], ["failed", "failed"], ["needs_repair", "repair"]]) {
      const roles = current.filter(result => result.status === status).map(result => result.worker_role);
      if (roles.length) parts.push(`${label}: ${roles.join(", ")}`);
    }
    return appendTopologyCheckpoint(state, { substage: "judging", phase_status: "in_progress", active_roles: [judgeRole], completed_roles: cp.active_roles,
      latest_summary: compactTeamText(parts.join(" ")), artifact_count: current.reduce((n, result) => n + result.artifacts.length, 0), round_index: round, round_limit: limit }, at);
  }
  decide(value: TopologyState, raw: JudgeDecision, parent: { question?: string; waiting_on?: string } = {}, at = new Date()): TopologyState {
    const state = this.state(value, ["judging"]), cp = state.checkpoints.at(-1)!, decision = decodeJudgeDecision(raw), round = cp.round_index, limit = cp.round_limit;
    requireThat(round !== null && limit !== null && decision.round_index === round, "judge_round_mismatch");
    const results = this.roundResults(state, round), roles = results.map(result => result.worker_role);
    requireThat(results.length > 0, "judge_current_round_results_required");
    if (decision.decision === "select_winner" || decision.decision === "failed") {
      const winner = results.find(result => result.worker_role === decision.winner_role);
      requireThat(decision.decision === "failed" || winner, "judge_winner_not_in_current_batch");
      const source = decision.decision === "failed" ? results : [winner!], status = decision.decision === "failed" ? "failed" : "completed";
      const reduced: TeamReducedResult = { schema_version: 1, topology: "debate_judge", final_status: status, reduced_summary: decision.summary,
        selected_evidence: decision.evidence.length ? decision.evidence : source.flatMap(result => result.evidence),
        selected_artifacts: decision.artifacts.length ? decision.artifacts : source.flatMap(result => result.artifacts), next_action: decision.next_action };
      return appendTopologyCheckpoint(state, { substage: status, phase_status: status, active_roles: [], completed_roles: [...new Set([...roles, this.judge(state)])],
        latest_summary: teamReducedSummary(reduced), artifact_count: reduced.selected_artifacts.length, round_index: round, round_limit: limit, reduced_result: reduced }, at);
    }
    if (decision.decision === "advance_round") {
      requireThat(round < limit, "judge_final_round_requires_escalation");
      return appendTopologyCheckpoint(state, { substage: "candidate_round", phase_status: "in_progress", active_roles: this.roles(decision.next_candidate_roles),
        completed_roles: [this.judge(state)], latest_summary: this.summary(decision), round_index: round + 1, round_limit: limit }, at);
    }
    const count = decision.artifacts.length || results.reduce((n, result) => n + result.artifacts.length, 0);
    if (decision.decision === "needs_parent_input") {
      requireThat(parent.question !== undefined && parent.waiting_on !== undefined, "judge_parent_question_required");
      requireThat(decision.stop_reason !== "final_round_tie" || round === limit, "judge_not_final_round");
      return interruptTopology(state, { requested_by_role: this.judge(state), question: parent.question, waiting_on: parent.waiting_on,
        latest_summary: this.summary(decision), completed_roles: roles, artifact_count: count, round_index: round, round_limit: limit }, at);
    }
    requireThat(decision.decision === "needs_repair", "judge_decision_unsupported");
    return appendTopologyCheckpoint(state, { substage: "repairing", phase_status: "in_progress", active_roles: roles, completed_roles: [this.judge(state)],
      latest_summary: this.summary(decision), artifact_count: count, repair_state: decision.repair_hint, round_index: round, round_limit: limit }, at);
  }
  resume(value: TopologyState, parentInput: string, latestSummary?: string, at = new Date()): TopologyState {
    const state = this.state(value, ["waiting_parent"]), cp = state.checkpoints.at(-1)!;
    return resumeTopology(state, { parent_input: parentInput, latest_summary: latestSummary || cp.latest_summary || undefined,
      active_roles: [state.interruption.requested_by_role || this.judge(state)], completed_roles: cp.completed_roles,
      round_index: cp.round_index ?? undefined, round_limit: cp.round_limit ?? undefined }, at);
  }
}
