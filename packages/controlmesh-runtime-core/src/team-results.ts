/** Internal normalized worker results; input validation/admission remains owned by topology execution. */
export interface TeamEvidenceRef { ref: string; kind: string; summary: string | null }
export interface TeamArtifactRef extends TeamEvidenceRef { label: string | null }
export interface TeamWorkerResult {
  status: string; topology: string; substage: string; worker_role: string; summary: string;
  evidence: TeamEvidenceRef[]; artifacts: TeamArtifactRef[]; next_action: string | null;
}
export interface TeamReducedResult {
  schema_version: 1; topology: "pipeline" | "fanout_merge" | "director_worker" | "debate_judge"; final_status: string; reduced_summary: string;
  selected_evidence: TeamEvidenceRef[]; selected_artifacts: TeamArtifactRef[]; next_action: string | null;
}
function reduced(topology: TeamReducedResult["topology"], result: TeamWorkerResult,
  evidence: TeamEvidenceRef[], artifacts: TeamArtifactRef[]): TeamReducedResult {
  return structuredClone({ schema_version: 1, topology, final_status: result.status, reduced_summary: result.summary,
    selected_evidence: evidence, selected_artifacts: artifacts, next_action: result.next_action });
}
/** Review selections independently override each worker collection, matching Python pipeline behavior. */
export function reducePipelineReview(worker: TeamWorkerResult, review: TeamWorkerResult): TeamReducedResult {
  return reduced("pipeline", review, review.evidence.length ? review.evidence : worker.evidence,
    review.artifacts.length ? review.artifacts : worker.artifacts);
}
export function reducePipelineTerminal(result: TeamWorkerResult): TeamReducedResult {
  return reduced("pipeline", result, result.evidence, result.artifacts);
}
/** Callers supply checkpoint results; only completed collecting entries participate in fallback. */
export function reduceFanoutResult(checkpoints: readonly (TeamWorkerResult | null)[], reducer: TeamWorkerResult): TeamReducedResult {
  const completed = checkpoints.filter((value): value is TeamWorkerResult => value !== null && value.substage === "collecting" && value.status === "completed");
  return reduced("fanout_merge", reducer, reducer.evidence.length ? reducer.evidence : completed.flatMap(value => value.evidence),
    reducer.artifacts.length ? reducer.artifacts : completed.flatMap(value => value.artifacts));
}
export function reduceFailedFanout(failed: readonly TeamWorkerResult[]): TeamReducedResult {
  return structuredClone({ schema_version: 1, topology: "fanout_merge", final_status: "failed",
    reduced_summary: failed.length ? `All fanout workers failed before reduction: ${failed.map(value => value.worker_role).join(", ")}.`
      : "All fanout workers failed before reduction.",
    selected_evidence: failed.flatMap(value => value.evidence), selected_artifacts: failed.flatMap(value => value.artifacts), next_action: null });
}
