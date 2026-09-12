import type { Principal, RuntimeKernel } from "./kernel";
import { verifiedTopologyCompletion } from "./topology-completion";
import { decodeTopologyState } from "./team-topology";
import { decodeTeamResult } from "./team-result-validation";
import { digest, requireThat } from "./value";

export interface AggregateResultBinding {
  source: "topology"; task_id: string; revision: number; execution_id: string; topology_revision: number;
  topology: string; substage: string; worker_role: string;
}
/** An aggregate is a verified topology result, never a fabricated native episode or model decision. */
export function readAggregateResult(kernel: RuntimeKernel, actor: Principal, binding: AggregateResultBinding, ancestors: ReadonlySet<string> = new Set()) {
  const child = kernel.inspect(actor, binding.task_id);
  requireThat(binding.source === "topology" && child.revision === binding.revision && !child.active_episode && !child.needs_reconciliation
    && ["done", "failed"].includes(child.task.status), "aggregate_task_changed");
  const row = kernel.db.sql.query("SELECT revision,state FROM team_topologies WHERE task_id=?").get(binding.task_id) as { revision: number; state: string } | null;
  requireThat(row && row.revision === binding.topology_revision, "aggregate_topology_changed");
  const state = decodeTopologyState(JSON.parse(row.state));
  requireThat(state.execution_id === binding.execution_id, "aggregate_execution_changed");
  const complete = verifiedTopologyCompletion(kernel, actor, binding.task_id, binding.revision - 1, binding.topology_revision, ancestors);
  requireThat(complete.outcome === child.task.status, "aggregate_status_changed");
  requireThat(!kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(binding.task_id), "aggregate_provider_queued");
  requireThat(!kernel.db.sql.query("SELECT 1 FROM effects WHERE task_id=? AND state!='confirmed'").get(binding.task_id), "aggregate_effect_uncertain");
  const reduced = state.checkpoints.at(-1)!.reduced_result!;
  const result = decodeTeamResult({ topology: binding.topology, substage: binding.substage, worker_role: binding.worker_role,
    status: complete.outcome === "done" ? "completed" : "failed", summary: reduced.reduced_summary,
    evidence: reduced.selected_evidence, artifacts: reduced.selected_artifacts, next_action: reduced.next_action });
  return { binding: { ...binding }, output_digest: digest(complete.result), result };
}
