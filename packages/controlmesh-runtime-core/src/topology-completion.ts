import { readAggregateResult, type AggregateResultBinding } from "./topology-aggregate";
import type { TopologyArtifactGate } from "./topology-artifacts";
import { command, requireScope } from "./commands";
import type { Principal, RuntimeKernel, TaskSnapshot } from "./kernel";
import type { TopologySnapshot } from "./runtime-topology";
import { decodeTopologyState } from "./team-topology";
import { compactTeamText } from "./team-progress";
import { readTeamControlDecision, readTeamTaskResult, teamWorkerSubstage } from "./team-task-result";
import { canonical, digest, object, requireThat } from "./value";

interface CompletionRow {
  task_id: string; parent_revision: number; topology_revision: number; checkpoint_id: string;
  state_digest: string; inputs_digest: string; result: string;
}
function terminalState(kernel: RuntimeKernel, taskId: string, revision: number) {
  const row = kernel.db.sql.query("SELECT revision,state FROM team_topologies WHERE task_id=?").get(taskId) as { revision: number; state: string } | null;
  requireThat(row && Number.isSafeInteger(revision) && row.revision === revision, "topology_completion_revision_conflict");
  const state = decodeTopologyState(JSON.parse(row.state)), cp = state.checkpoints.at(-1)!;
  requireThat(state.task_id === taskId && ["completed", "failed"].includes(cp.substage) && cp.substage === cp.phase_status
    && cp.active_roles.length === 0 && state.interruption.status === "idle" && cp.reduced_result?.final_status === cp.substage, "topology_completion_not_terminal");
  return { state, cp };
}
/** Revalidate current generations against authoritative task results; older generations remain audit history. */
function acceptedInputs(kernel: RuntimeKernel, actor: Principal, taskId: string, revision: number, ancestors: ReadonlySet<string> = new Set([taskId])) {
  const { state } = terminalState(kernel, taskId, revision);
  const rows = kernel.db.sql.query("SELECT child_id,parent_id,topology,substage,worker_role,checkpoint_id,run_id,accepted,generation FROM topology_tasks WHERE parent_id=? AND execution_id=? ORDER BY child_id").all(taskId, state.execution_id) as {
    child_id: string; parent_id: string; topology: string; substage: string; worker_role: string;
    checkpoint_id: string; run_id: string; accepted: string | null; generation: number;
  }[];
  requireThat(rows.length > 0, "topology_completion_inputs_missing");
  for (const row of rows) {
    requireThat(row.accepted !== null, "topology_completion_input_unresolved");
    const original = state.checkpoints.find(cp => cp.checkpoint_id === row.checkpoint_id), stored = JSON.parse(row.accepted);
    requireThat(original && original.substage === row.substage && row.topology === state.topology
      && original.active_roles.includes(row.worker_role) && object(stored) && object(stored.binding), "topology_completion_assignment_changed");
    const binding = stored.binding;
    const kind = (kernel.db.sql.query("SELECT kind FROM topology_tasks WHERE child_id=?").get(row.child_id) as { kind: string }).kind;
    if (kind === "aggregate") {
      requireThat(binding.source === "topology" && binding.task_id === row.child_id && binding.execution_id === row.run_id
        && binding.topology === row.topology && binding.substage === teamWorkerSubstage(row.topology, row.substage) && binding.worker_role === row.worker_role, "aggregate_assignment_changed");
      const checked = readAggregateResult(kernel, actor, binding as unknown as AggregateResultBinding, ancestors);
      requireThat(canonical(checked) === row.accepted, "topology_completion_result_changed"); continue;
    }
    const run = kernel.db.sql.query("SELECT state,task_id,lease FROM local_runs WHERE run_id=?").get(row.run_id) as { state: string; task_id: string; lease: string | null } | null;
    requireThat(run?.state === "completed" && run.task_id === row.child_id && run.lease, "topology_completion_run_unresolved");
    const lease = JSON.parse(run.lease);
    requireThat(binding.task_id === row.child_id && binding.episode_id === lease.episode_id, "topology_completion_execution_changed");
    const base = { task_id: row.child_id, revision: binding.revision as number, episode_id: lease.episode_id as string,
      effect_id: binding.effect_id as string, topology: row.topology, substage: row.substage, worker_role: row.worker_role };
    const control = (row.topology === "director_worker" && ["planning", "director_deciding", "repairing"].includes(row.substage))
      || (row.topology === "debate_judge" && row.substage === "judging");
    const checked = control ? readTeamControlDecision(kernel, actor, { ...base, round_index: original.round_index! })
      : readTeamTaskResult(kernel, actor, { ...base, substage: teamWorkerSubstage(row.topology, row.substage) });
    requireThat(canonical(checked) === row.accepted, "topology_completion_result_changed");
    requireThat(!kernel.db.sql.query("SELECT 1 FROM local_runs WHERE task_id=? AND state IN ('queued','running')").get(row.child_id), "topology_completion_input_queued");
    requireThat(!kernel.db.sql.query("SELECT 1 FROM effects WHERE task_id=? AND state!='confirmed'").get(row.child_id), "topology_completion_input_uncertain");
  }
  const history = kernel.db.sql.query("SELECT h.child_id,h.generation,h.assignment FROM topology_task_history h JOIN topology_tasks t ON t.child_id=h.child_id WHERE t.parent_id=? ORDER BY h.child_id,h.generation").all(taskId);
  return { digest: digest({ current: rows, history }), inputs: rows.map(row => ({ child_id: row.child_id, generation: row.generation, accepted_digest: digest(JSON.parse(row.accepted!)) })) };
}
/** Only accepted queue compositions mint this proof; the kernel refuses bare checkpoint completion. */
export function completeTopologyStep(kernel: RuntimeKernel, actor: Principal, requestId: string, parentRevision: number, snapshot: TopologySnapshot, gate?: TopologyArtifactGate): TaskSnapshot | null {
  const cp = snapshot.state.checkpoints.at(-1)!;
  if (!["completed", "failed"].includes(cp.phase_status)) return null;
  requireScope(actor, "team:write"); requireScope(actor, "task:execute"); kernel.inspect(actor, snapshot.task_id);
  return command(kernel.db, actor, requestId, "topology.complete_step", { parentRevision, taskId: snapshot.task_id, revision: snapshot.revision, state_digest: digest(snapshot.state) }, () => {
    const current = terminalState(kernel, snapshot.task_id, snapshot.revision);
    requireThat(canonical(current.state) === canonical(snapshot.state), "topology_completion_state_changed");
    const inputs = acceptedInputs(kernel, actor, snapshot.task_id, snapshot.revision);
    requireThat(!gate || gate.kernel === kernel, "topology_artifact_kernel_mismatch");
    const permit = current.cp.substage === "completed" ? gate?.issue(actor, parentRevision, snapshot) : undefined;
    const reduced = current.cp.reduced_result!, text = canonical(reduced);
    const result = { ...(permit ? { completion: permit.evidence } : {}), schema_version: "controlmesh.topology_result.v1", source: "topology_reduction", topology: current.state.topology,
      topology_revision: snapshot.revision, checkpoint_id: current.cp.checkpoint_id, state_digest: digest(current.state),
      inputs_digest: inputs.digest, inputs: inputs.inputs, reduced_result: reduced, text, output_digest: digest(text), delivery_text: compactTeamText(reduced.reduced_summary, 4000) };
    kernel.db.sql.query("INSERT INTO topology_completions VALUES (?,?,?,?,?,?,?)").run(snapshot.task_id, parentRevision, snapshot.revision,
      current.cp.checkpoint_id, result.state_digest, inputs.digest, canonical(result));
    return kernel.completeTopology(actor, `topology-finish-${digest(requestId)}`, snapshot.task_id, parentRevision, snapshot.revision, permit);
  }, value => { requireScope(actor, "team:write"); requireScope(actor, "task:execute"); kernel.inspect(actor, snapshot.task_id); return value; });
}
/** Kernel-side verification of the privately issued proof. Does not accept caller-supplied result text. */
export function verifiedTopologyCompletion(kernel: RuntimeKernel, actor: Principal, taskId: string, parentRevision: number, revision: number, ancestors: ReadonlySet<string> = new Set()) {
  requireThat(ancestors.size < 32 && !ancestors.has(taskId), "topology_cycle_or_depth_limit");
  const lineage = new Set(ancestors); lineage.add(taskId);
  const proof = kernel.db.sql.query("SELECT * FROM topology_completions WHERE task_id=?").get(taskId) as CompletionRow | null;
  requireThat(proof && proof.parent_revision === parentRevision && proof.topology_revision === revision, "topology_completion_proof_missing");
  const { state, cp } = terminalState(kernel, taskId, revision);
  requireThat(proof.checkpoint_id === cp.checkpoint_id && proof.state_digest === digest(state)
    && proof.inputs_digest === acceptedInputs(kernel, actor, taskId, revision, lineage).digest, "topology_completion_proof_changed");
  const result = JSON.parse(proof.result);
  requireThat(object(result) && result.source === "topology_reduction" && result.state_digest === proof.state_digest && result.inputs_digest === proof.inputs_digest
    && result.schema_version === "controlmesh.topology_result.v1" && result.topology === state.topology && result.topology_revision === revision
    && result.text === canonical(cp.reduced_result) && result.output_digest === digest(result.text) && canonical(result.reduced_result) === canonical(cp.reduced_result), "topology_completion_result_changed");
  return { outcome: cp.substage === "completed" ? "done" as const : "failed" as const, topology: state.topology, result };
}
