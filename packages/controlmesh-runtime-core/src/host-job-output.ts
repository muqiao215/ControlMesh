import type { Principal, RuntimeKernel } from "./kernel";
import { digest, identifier, object, requireThat } from "./value";

export interface HostOutputPageRequest {
  stream?: "stdout" | "stderr"; offset?: number; limit?: number; effect_id?: string; observation_digest?: string;
}
/** Bounded read of retained runtime-owned output; offsets count Unicode code points. */
export function readHostOutput(kernel: RuntimeKernel, actor: Principal, taskId: string, request: HostOutputPageRequest = {}) {
  const task = kernel.inspect(actor, taskId);
  requireThat(kernel.db.sql.query("SELECT 1 FROM tasks WHERE task_id=? AND principal=?").get(taskId, actor.id), "host_output_owner_mismatch");
  requireThat(task.task.provider === "host", "host_job_task_required");
  const { stream = "stdout", offset = 0, limit = 4096, effect_id, observation_digest } = request;
  requireThat(stream === "stdout" || stream === "stderr", "invalid_host_output_stream");
  requireThat(Number.isSafeInteger(offset) && offset >= 0 && Number.isSafeInteger(limit) && limit >= 1 && limit <= 8192, "invalid_host_output_page");
  if (effect_id !== undefined) identifier(effect_id);
  requireThat(observation_digest === undefined || /^[a-f0-9]{64}$/.test(observation_digest), "invalid_host_output_digest");
  requireThat(offset === 0 || (effect_id !== undefined && observation_digest !== undefined), "host_output_cursor_binding_required");
  const row = kernel.db.sql.query(`SELECT e.effect_id,e.episode_id,e.fence,e.state,m.payload AS manifest,m.digest AS manifest_digest,
    o.payload AS observation,o.digest AS observation_digest FROM effects e
    JOIN execution_manifests m ON m.effect_id=e.effect_id LEFT JOIN effect_observations o ON o.effect_id=e.effect_id
    WHERE e.task_id=? AND (? IS NULL OR e.effect_id=?) ORDER BY e.fence DESC,e.effect_id DESC LIMIT 1`)
    .get(taskId, effect_id ?? null, effect_id ?? null) as { effect_id: string; episode_id: string; fence: number; state: string;
      manifest: string; manifest_digest: string; observation: string | null; observation_digest: string | null } | null;
  if (!row || row.observation === null) {
    requireThat(offset === 0 && observation_digest === undefined, "host_output_observation_changed");
    if (effect_id !== undefined) requireThat(row, "host_output_effect_not_found");
    return { available: false as const, task_id: taskId, task_status: task.task.status, effect_id: row?.effect_id ?? null };
  }
  requireThat(Buffer.byteLength(row.manifest) <= 2 * 1024 * 1024 && Buffer.byteLength(row.observation) <= 1024 * 1024, "host_output_evidence_too_large");
  const manifest = JSON.parse(row.manifest), outcome = JSON.parse(row.observation);
  requireThat(object(manifest) && manifest.schema_version === "controlmesh.host_step_execution.v1" && digest(manifest) === row.manifest_digest
    && object(outcome) && digest(outcome) === row.observation_digest && typeof outcome.stdout === "string" && typeof outcome.stderr === "string"
    && typeof outcome.reason === "string", "host_output_evidence_changed");
  requireThat(observation_digest === undefined || row.observation_digest === observation_digest, "host_output_observation_changed");
  const characters = Array.from(outcome[stream] as string);
  requireThat(offset <= characters.length, "invalid_host_output_page");
  const end = Math.min(offset + limit, characters.length);
  return { available: true as const, task_id: taskId, task_status: task.task.status, effect_id: row.effect_id, episode_id: row.episode_id,
    fence: row.fence, effect_state: row.state, observation_digest: row.observation_digest, reason: outcome.reason,
    exit_code: outcome.exit_code, stream, offset, text: characters.slice(offset, end).join(""),
    next_offset: end < characters.length ? end : null, total_characters: characters.length, offset_unit: "unicode_code_point" };
}
