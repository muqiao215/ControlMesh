import { createHash } from "node:crypto";
import type { DeviceEvidenceRef } from "@controlmesh/protocol";
import type { DeviceJob } from "./device-coordinator";
import type { Principal, RuntimeKernel } from "./kernel";
import { command } from "./commands";
import { decodeTaskCompletion, verifyDeviceCompletion, type DeviceCompletion } from "./task-completion";
import { canonical, digest, object, requireThat } from "./value";

export const artifactChunkBytes = 64 * 1024;
export const artifactFileBytes = 4 * 1024 * 1024;
export const artifactEffectBytes = 16 * 1024 * 1024;
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");
export interface ArtifactChunk { path: string; sha256: string; size: number; offset: number; content_base64: string }
interface FileRow { binding: string; sha256: string; size: number; received: number; content: Uint8Array }

/** Private durable inbox. Receiving bytes never publishes them into a project workspace. */
export class DeviceArtifactInbox {
  constructor(private readonly kernel: RuntimeKernel) {}
  private scope(actor: Principal, job: DeviceJob, manifest: DeviceEvidenceRef) {
    requireThat(job.artifact_transfer === true && ["claude", "opencode"].includes(String(job.execution?.provider)), "device_artifact_transfer_not_authorized");
    const contract = decodeTaskCompletion(job.execution?.completion_requirements);
    requireThat(contract && manifest.task_id === job.task_id && manifest.device_id === actor.device_id
      && manifest.assignment_digest === job.assignment_digest, "device_artifact_scope_changed");
    return { contract, binding: canonical({ principal: actor.id, workspace_id: job.workspace_id,
      requirements_digest: digest(contract), manifest }) };
  }
  /** Caller must hold a current execution lease or a current explicit reconciliation challenge. */
  put(actor: Principal, requestId: string, job: DeviceJob, manifest: DeviceEvidenceRef, chunk: ArtifactChunk) {
    const { contract, binding } = this.scope(actor, job, manifest), file = contract.files.find(file => file.path === chunk.path);
    requireThat(file && (file.sha256 === undefined || file.sha256 === chunk.sha256), "device_artifact_path_not_authorized");
    requireThat(/^[a-f0-9]{64}$/.test(chunk.sha256) && Number.isSafeInteger(chunk.size) && chunk.size >= 0 && chunk.size <= artifactFileBytes
      && Number.isSafeInteger(chunk.offset) && chunk.offset >= 0 && chunk.offset <= chunk.size
      && typeof chunk.content_base64 === "string" && chunk.content_base64.length <= 87384, "invalid_device_artifact_chunk");
    const bytes = Buffer.from(chunk.content_base64, "base64");
    requireThat(bytes.toString("base64") === chunk.content_base64 && bytes.length <= artifactChunkBytes
      && (bytes.length > 0 || chunk.size === 0) && chunk.offset + bytes.length <= chunk.size, "invalid_device_artifact_chunk");
    return command(this.kernel.db, actor, requestId, "device.artifact.put", { binding, chunk }, () => {
      const row = this.kernel.db.sql.query("SELECT binding,sha256,size,received,content FROM device_artifact_files WHERE effect_id=? AND path=?")
        .get(manifest.effect_id, chunk.path) as FileRow | null;
      requireThat(!row || (row.binding === binding && row.sha256 === chunk.sha256 && row.size === chunk.size), "device_artifact_transfer_changed");
      const previous = row ? Buffer.from(row.content) : Buffer.alloc(0);
      requireThat(!row || (previous.length === row.received && row.received <= row.size), "device_artifact_store_corrupted");
      const next = chunk.offset + bytes.length;
      if (row && chunk.offset < row.received) {
        requireThat(next <= row.received && previous.subarray(chunk.offset, next).equals(bytes), "device_artifact_chunk_conflict");
        return { path: chunk.path, sha256: chunk.sha256, size: chunk.size, next_offset: next };
      }
      requireThat(chunk.offset === previous.length, "device_artifact_offset_mismatch");
      if (!row) {
        const total = this.kernel.db.sql.query("SELECT COALESCE(SUM(size),0) AS size,COUNT(*) AS count FROM device_artifact_files WHERE effect_id=?")
          .get(manifest.effect_id) as { size: number; count: number };
        requireThat(total.count < contract.files.length && total.size + chunk.size <= artifactEffectBytes, "device_artifact_budget_exceeded");
      }
      const content = Buffer.concat([previous, bytes]);
      requireThat(content.length !== chunk.size || sha(content) === chunk.sha256, "device_artifact_hash_mismatch");
      this.kernel.db.sql.query("INSERT INTO device_artifact_files VALUES (?,?,?,?,?,?,?) ON CONFLICT(effect_id,path) DO UPDATE SET received=excluded.received,content=excluded.content")
        .run(manifest.effect_id, chunk.path, binding, chunk.sha256, chunk.size, content.length, content);
      return { path: chunk.path, sha256: chunk.sha256, size: chunk.size, next_offset: next };
    });
  }
  verify(actor: Principal, job: DeviceJob, manifest: DeviceEvidenceRef, proof: unknown) {
    const { contract, binding } = this.scope(actor, job, manifest);
    verifyDeviceCompletion(contract, proof);
    return contract.files.map((file, index) => {
      const row = this.kernel.db.sql.query("SELECT binding,sha256,size,received,content FROM device_artifact_files WHERE effect_id=? AND path=?")
        .get(manifest.effect_id, file.path) as FileRow | null;
      requireThat(row && row.binding === binding && row.sha256 === (proof as DeviceCompletion).sha256[index]
        && row.received === row.size && row.content.length === row.size && sha(row.content) === row.sha256, "device_artifact_delivery_incomplete");
      return { path: file.path, sha256: row.sha256, size: row.size, content: Buffer.from(row.content) };
    });
  }
  /** Only a confirmed current task result can expose inbox bytes to the local control owner. */
  read(actor: Principal, taskId: string, revision: number, effectId: string, path: string, offset: number, expectedHash?: string) {
    const effect = this.kernel.db.sql.query("SELECT episode_id FROM effects WHERE effect_id=? AND task_id=?").get(effectId, taskId) as { episode_id: string } | null;
    requireThat(effect, "device_artifact_unavailable");
    const accepted = this.kernel.inspectCompletedEffect(actor, taskId, revision, effect.episode_id, effectId), result = accepted.result;
    requireThat(result.schema_version === "controlmesh.device_native_result.v1" && result.task_failure === undefined
      && object(result.evidence), "device_artifact_unavailable");
    const stored = this.kernel.db.sql.query("SELECT binding,sha256,size,received,content FROM device_artifact_files WHERE effect_id=? AND path=?")
      .get(effectId, path) as FileRow | null;
    requireThat(stored, "device_artifact_unavailable");
    const binding = JSON.parse(stored.binding), { observation_digest: _observation, result_digest: _result, ...manifest } = result.evidence;
    const contract = decodeTaskCompletion(this.kernel.inspect(actor, taskId).task.completion_requirements);
    requireThat(contract && binding.principal === actor.id && digest(binding.manifest) === digest(manifest)
      && binding.requirements_digest === digest(contract), "device_artifact_scope_changed");
    verifyDeviceCompletion(contract, result.completion);
    const index = contract.files.findIndex(file => file.path === path);
    requireThat(index >= 0 && stored.sha256 === (result.completion as DeviceCompletion).sha256[index] && stored.received === stored.size
      && stored.content.length === stored.size && sha(stored.content) === stored.sha256, "device_artifact_delivery_incomplete");
    requireThat(Number.isSafeInteger(offset) && offset >= 0 && offset <= stored.size
      && ((offset === 0 && expectedHash === undefined) || expectedHash === stored.sha256), "device_artifact_read_changed");
    const end = Math.min(stored.size, offset + artifactChunkBytes);
    return { path, sha256: stored.sha256, size: stored.size, offset, next_offset: end, eof: end === stored.size,
      content_base64: Buffer.from(stored.content).subarray(offset, end).toString("base64") };
  }
}
