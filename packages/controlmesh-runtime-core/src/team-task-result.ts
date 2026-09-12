import type { Principal, RuntimeKernel } from "./kernel";
import { decodeTeamResult } from "./team-result-validation";
import { digest, requireThat } from "./value";

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

/** Reads accepted native output; evidence references inside it remain model assertions. */
export function readTeamTaskResult(kernel: RuntimeKernel, actor: Principal, binding: TeamTaskResultBinding) {
  const accepted = kernel.inspectCompletedEffect(actor, binding.task_id, binding.revision, binding.episode_id, binding.effect_id);
  const { text, output_digest } = accepted.result;
  requireThat(typeof text === "string" && Buffer.byteLength(text) <= 4 * 1024 * 1024, "team_result_text_unavailable");
  requireThat(output_digest === digest(text), "team_result_digest_mismatch");
  // A full JSON document is required. Do not select a plausible object from surrounding prose.
  const result = decodeTeamResult(JSON.parse(text));
  requireThat(result.topology === binding.topology && result.substage === binding.substage
    && result.worker_role === binding.worker_role, "team_result_assignment_mismatch");
  return { binding: { ...binding }, output_digest, result };
}
