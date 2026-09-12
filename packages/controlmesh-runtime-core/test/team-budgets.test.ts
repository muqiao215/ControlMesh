import { expect, test } from "bun:test";
import { startTopology, decodeTopologyState, type TopologyState } from "../src/team-topology";
import { applyPipelineResult, dispatchPipelineWorker, resumePipeline } from "../src/team-pipeline";
import { applyFanoutResult, dispatchFanoutWorkers, collectFanoutWorkers, resumeFanout } from "../src/team-fanout";
import { decodeTeamResult } from "../src/team-result-validation";
import type { TeamStepBudgets } from "../src/team-budgets";

for (const topology of ["pipeline", "fanout_merge"] as const) {
  const result = (state: TopologyState, status: string) => decodeTeamResult({ topology,
    substage: state.checkpoints.at(-1)!.substage, worker_role: state.checkpoints.at(-1)!.active_roles[0], status,
    summary: "observed result", evidence: [{ ref: "event:observed" }], artifacts: [{ ref: "file:observed" }],
    repair_hint: status === "needs_repair" ? "correct output" : null, needs_parent_input: status === "needs_parent_input" });
  const apply = (state: TopologyState, status: string, budget: TeamStepBudgets = {}) =>
    (topology === "pipeline" ? applyPipelineResult : applyFanoutResult)(state, result(state, status), { ...budget, parent_question: "choose", waiting_on: "user" });
  const start = () => {
    const planning = startTopology("parent", topology);
    if (topology === "pipeline") return apply(dispatchPipelineWorker(planning), "completed");
    const dispatched = dispatchFanoutWorkers(planning, ["a", "b"], 2);
    const workers = ["a", "b"].map(worker_role => decodeTeamResult({ topology, substage: "collecting", worker_role, status: "completed", summary: "observed worker" }));
    return collectFanoutWorkers(dispatched, workers);
  };
  test(`${topology} repair cap survives serialized state and terminates with actual evidence`, () => {
    let state = apply(start(), "needs_repair", { max_repair_cycles: 1 });
    expect(state.checkpoints.at(-1)!.substage).toBe("repairing");
    state = apply(state, "completed", { max_repair_cycles: 1 });
    state = apply(decodeTopologyState(JSON.parse(JSON.stringify(state))), "needs_repair", { max_repair_cycles: 1 });
    const cp = state.checkpoints.at(-1)!;
    expect(cp.substage).toBe("failed"); expect(cp.reduced_result?.final_status).toBe("failed");
    expect(cp.reduced_result?.selected_evidence).toEqual(cp.result?.evidence);
    expect(cp.reduced_result?.selected_artifacts).toEqual(cp.result?.artifacts);
    expect(cp.artifact_count).toBe(1);
    expect(state.checkpoints.filter(cp => cp.substage === "repairing")).toHaveLength(1);
  });
  test(`${topology} parent cap stops a second interruption after explicit answer`, () => {
    let state = apply(start(), "needs_parent_input", { max_parent_interruptions: 1 });
    expect(state.checkpoints.at(-1)!.substage).toBe("waiting_parent");
    state = (topology === "pipeline" ? resumePipeline : resumeFanout)(state, "answer");
    state = apply(decodeTopologyState(JSON.parse(JSON.stringify(state))), "needs_parent_input", { max_parent_interruptions: 1 });
    expect(state.checkpoints.at(-1)!.substage).toBe("failed");
    expect(state.checkpoints.filter(cp => cp.substage === "waiting_parent")).toHaveLength(1);
  });
  test(`${topology} zero caps stop review requests without accepting unsupported worker statuses`, () => {
    const caps = { max_parent_interruptions: 0, max_repair_cycles: 0 };
    expect(apply(start(), "needs_repair", caps).checkpoints.at(-1)!.substage).toBe("failed");
    expect(apply(start(), "needs_parent_input", caps).checkpoints.at(-1)!.substage).toBe("failed");
    expect(apply(start(), "completed", caps).checkpoints.at(-1)!.substage).toBe("completed");
    const repairing = apply(start(), "needs_repair");
    for (const status of ["needs_repair", "needs_parent_input"])
      expect(() => apply(repairing, status, caps)).toThrow(`${topology === "pipeline" ? "pipeline" : "fanout"}_result_status_unsupported`);
    if (topology === "pipeline") expect(() => apply(dispatchPipelineWorker(startTopology("parent", topology)), "needs_repair", caps)).toThrow("pipeline_result_status_unsupported");
  });
  test(`${topology} rejects malformed configured caps`, () => {
    for (const cap of [-1, 1.5, NaN, Infinity, 101, null, "1"]) {
      expect(() => apply(start(), "completed", { max_repair_cycles: cap as number })).toThrow("invalid_team_step_budget");
      expect(() => apply(start(), "completed", { max_parent_interruptions: cap as number })).toThrow("invalid_team_step_budget");
    }
  });
}
