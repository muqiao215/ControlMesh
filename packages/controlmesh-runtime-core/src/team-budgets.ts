import type { StructuredTeamResult } from "./team-result-validation";
import { appendTopologyCheckpoint, type TopologyState } from "./team-topology";
import { requireThat } from "./value";
export interface TeamStepBudgets { max_repair_cycles?: number; max_parent_interruptions?: number }
/** Optional host budgets leave the existing pure Python parity defaults unchanged. */
export function exhaustedTeamBudget(state: TopologyState, result: StructuredTeamResult, budget: TeamStepBudgets, at: Date): TopologyState | null {
  for (const value of [budget.max_repair_cycles, budget.max_parent_interruptions])
    requireThat(value === undefined || (Number.isSafeInteger(value) && value >= 0 && value <= 100), "invalid_team_step_budget");
  // A budget must not turn a worker's unsupported control request into an accepted result.
  const currentStage = state.checkpoints.at(-1)!.substage;
  if (!((state.topology === "pipeline" && currentStage === "review_running")
    || (state.topology === "fanout_merge" && currentStage === "reducing"))) return null;
  const stage = result.status === "needs_repair" ? "repairing" : result.status === "needs_parent_input" ? "waiting_parent" : null;
  const limit = stage === "repairing" ? budget.max_repair_cycles : stage === "waiting_parent" ? budget.max_parent_interruptions : undefined;
  if (stage === null || limit === undefined || state.checkpoints.filter(cp => cp.substage === stage).length < limit) return null;
  const cp = state.checkpoints.at(-1)!, summary = `${state.topology} stopped: ${stage === "repairing" ? "max_repair_cycles" : "max_parent_interruptions"} exhausted (${limit}).`;
  return appendTopologyCheckpoint(state, { substage: "failed", phase_status: "failed", active_roles: [], completed_roles: [...new Set([...cp.completed_roles, result.worker_role])],
    latest_summary: summary, artifact_count: result.artifacts.length, result, reduced_result: { schema_version: 1, topology: state.topology, final_status: "failed", reduced_summary: summary,
      selected_evidence: result.evidence, selected_artifacts: result.artifacts, next_action: null } }, at);
}
