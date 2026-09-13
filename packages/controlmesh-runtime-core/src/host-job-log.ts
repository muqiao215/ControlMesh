import type { Lease, Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, identifier, requireThat } from "./value";

export function appendHostLog(kernel: RuntimeKernel, actor: Principal, lease: Lease, effectId: string, stream: "stdout" | "stderr", text: string): void {
  kernel.db.transaction(() => {
    requireThat(kernel.db.sql.query(`SELECT 1 FROM effects e JOIN tasks t ON t.task_id=e.task_id
      JOIN execution_manifests m ON m.effect_id=e.effect_id
      WHERE e.effect_id=? AND e.task_id=? AND e.episode_id=? AND e.fence=? AND t.principal=?
      AND e.state IN ('dispatched','unknown') AND e.result IS NULL
      AND json_extract(m.payload,'$.schema_version')='controlmesh.host_step_execution.v1'`)
      .get(effectId, lease.task_id, lease.episode_id, lease.fence, actor.id), "host_log_execution_unproven");
    const prior = kernel.db.sql.query("SELECT COUNT(*) AS count,COALESCE(SUM(bytes),0) AS bytes FROM process_output_chunks WHERE effect_id=?").get(effectId) as { count: number; bytes: number };
    const characters = Array.from(text), count = Math.ceil(characters.length / 4096);
    requireThat(prior.bytes + Buffer.byteLength(text) <= 1024 * 1024 && prior.count + count <= 4096, "host_log_limit_exceeded");
    for (let index = 0; index < characters.length; index += 4096) {
      const chunk = characters.slice(index, index + 4096).join("");
      const inserted = kernel.db.sql.query("INSERT INTO process_output_chunks(effect_id,stream,text,digest,bytes) VALUES(?,?,?,?,?)")
        .run(effectId, stream, chunk, "", Buffer.byteLength(chunk));
      const seq = Number(inserted.lastInsertRowid); requireThat(Number.isSafeInteger(seq), "host_log_sequence_exhausted");
      kernel.db.sql.query("UPDATE process_output_chunks SET digest=? WHERE seq=?")
        .run(digest({ seq, effect_id: effectId, stream, text: chunk }), seq);
    }
  });
}
export function readHostLog(kernel: RuntimeKernel, actor: Principal, taskId: string, effectId?: string, after = 0, limit = 32) {
  const task = kernel.inspect(actor, taskId);
  requireThat(kernel.db.sql.query("SELECT 1 FROM tasks WHERE task_id=? AND principal=?").get(taskId, actor.id), "host_output_owner_mismatch");
  requireThat(task.task.provider === "host", "host_job_task_required");
  if (effectId !== undefined) identifier(effectId);
  requireThat(Number.isSafeInteger(after) && after >= 0 && Number.isSafeInteger(limit) && limit > 0 && limit <= 64, "invalid_host_log_page");
  requireThat(after === 0 || effectId !== undefined, "host_log_cursor_binding_required");
  const effect = kernel.db.sql.query("SELECT effect_id,state FROM effects WHERE task_id=? AND (? IS NULL OR effect_id=?) ORDER BY fence DESC,effect_id DESC LIMIT 1")
    .get(taskId, effectId ?? null, effectId ?? null) as { effect_id: string; state: string } | null;
  if (!effect) { requireThat(effectId === undefined, "host_output_effect_not_found"); return { task_id: taskId, effect_id: null, chunks: [], next_after: after, has_more: false, task_status: task.task.status }; }
  const rows = kernel.db.sql.query("SELECT seq,stream,text,digest,bytes FROM process_output_chunks WHERE effect_id=? AND seq>? ORDER BY seq LIMIT ?")
    .all(effect.effect_id, after, limit + 1) as { seq: number; stream: string; text: string; digest: string; bytes: number }[];
  const chunks: typeof rows = []; let bytes = 0;
  for (const row of rows.slice(0, limit)) {
    requireThat(row.bytes === Buffer.byteLength(row.text) && row.digest === digest({ seq: row.seq, effect_id: effect.effect_id, stream: row.stream, text: row.text }), "host_log_evidence_changed");
    const size = Buffer.byteLength(canonical(row)); if (bytes + size > 262144) break;
    chunks.push(row); bytes += size;
  }
  return { task_id: taskId, effect_id: effect.effect_id, task_status: task.task.status, effect_state: effect.state,
    chunks, next_after: chunks.at(-1)?.seq ?? after, has_more: rows.length > chunks.length };
}
