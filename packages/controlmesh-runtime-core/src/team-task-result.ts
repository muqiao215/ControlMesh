import { ProtocolValidationError } from "@controlmesh/protocol";
import type { Principal, RuntimeKernel } from "./kernel";
import { decodeTeamResult } from "./team-result-validation";
import { decodeDirectorDecision, decodeJudgeDecision } from "./team-control-decision";
import { digest, requireThat, RuntimeConflict } from "./value";

/** Only errors attributable to verified model output permit explicit regeneration. */
export class TeamOutputError extends RuntimeConflict {}
function decodeOutput<T>(decode: () => T): T {
  try { return decode(); }
  catch (error) {
    if (error instanceof SyntaxError) throw new TeamOutputError("team_result_invalid_json");
    if (error instanceof ProtocolValidationError) throw new TeamOutputError("team_result_invalid_schema");
    throw error;
  }
}

/** Supplied by trusted topology scheduling state, never inferred from model output. */
export interface TeamTaskResultBinding {
  task_id: string;
  revision: number;
  episode_id: string;
  effect_id: string;
  topology: string;
  substage: string;
  worker_role: string;
}

/** Read one accepted full JSON document without granting its contents execution authority. */
function acceptedJSON(kernel: RuntimeKernel, actor: Principal, binding: TeamTaskResultBinding) {
  const accepted = kernel.inspectCompletedEffect(actor, binding.task_id, binding.revision, binding.episode_id, binding.effect_id);
  const { text, output_digest } = accepted.result;
  requireThat(typeof text === "string" && Buffer.byteLength(text) <= 4 * 1024 * 1024, "team_result_text_unavailable");
  requireThat(output_digest === digest(text), "team_result_digest_mismatch");
  return { output_digest, raw: decodeOutput(() => JSON.parse(text) as unknown) };
}
/** Reads accepted native output; evidence references inside it remain model assertions. */
export function readTeamTaskResult(kernel: RuntimeKernel, actor: Principal, binding: TeamTaskResultBinding) {
  const accepted = acceptedJSON(kernel, actor, binding), result = decodeOutput(() => decodeTeamResult(accepted.raw));
  if (result.topology !== binding.topology || result.substage !== binding.substage || result.worker_role !== binding.worker_role)
    throw new TeamOutputError("team_result_assignment_mismatch");
  return { binding: { ...binding }, output_digest: accepted.output_digest, result };
}
/** Round and role are supplied by the persisted assignment, not inferred from model claims. */
export function readTeamControlDecision(kernel: RuntimeKernel, actor: Principal, binding: TeamTaskResultBinding & { round_index: number }) {
  requireThat(Number.isSafeInteger(binding.round_index) && binding.round_index >= 1, "control_round_required");
  const director = binding.topology === "director_worker";
  requireThat(director ? ["planning", "director_deciding", "repairing"].includes(binding.substage)
    : binding.topology === "debate_judge" && binding.substage === "judging", "control_decision_stage_mismatch");
  const accepted = acceptedJSON(kernel, actor, binding);
  const result = decodeOutput(() => director ? decodeDirectorDecision(accepted.raw) : decodeJudgeDecision(accepted.raw));
  const round = binding.round_index + (director && result.decision === "dispatch_workers" && binding.substage !== "planning" ? 1 : 0);
  if (result.topology !== binding.topology || result.round_index !== round) throw new TeamOutputError("control_decision_assignment_mismatch");
  return { binding: { ...binding }, output_digest: accepted.output_digest, result };
}

/** Worker envelope stage is independent of the stable parent dispatch checkpoint. */
export function teamWorkerSubstage(topology: string, substage: string): string {
  return ((topology === "fanout_merge" || topology === "director_worker") && substage === "dispatching")
    || (topology === "debate_judge" && substage === "candidate_round") ? "collecting" : substage;
}
