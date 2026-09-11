import { assertProtocolSchema, type DeviceEvidenceRef } from "@controlmesh/protocol";
import type { RuntimeDatabase } from "./database";
import type { DeviceJob } from "./device-coordinator";
import type { Lease } from "./kernel";
import { canonical, digest, identifier, object, requireThat } from "./value";

export interface DeviceExecutionRecord {
  effect_id: string; device_id: string; task_id: string; episode_id: string; fence: number;
  assignment_digest: string; workspace_id: string; phase: string; job: string;
  manifest_digest: string; manifest: string;
  observation_digest: string | null; observation: string | null;
  result_digest: string | null; result: string | null;
}

/** Device-local evidence only. This ledger never claims coordinator task or lease ownership. */
export class DeviceExecutionJournal {
  constructor(readonly db: RuntimeDatabase, readonly deviceId: string) { identifier(deviceId); }

  private row(effectId: string): DeviceExecutionRecord {
    identifier(effectId);
    const row = this.db.sql.query("SELECT * FROM device_execution_records WHERE effect_id=? AND device_id=?").get(effectId, this.deviceId) as DeviceExecutionRecord | null;
    requireThat(row, "device_evidence_unavailable");
    for (const [content, hash] of [[row.manifest, row.manifest_digest], [row.observation, row.observation_digest], [row.result, row.result_digest]]) {
      requireThat((content === null && hash === null) || (typeof content === "string" && digest(JSON.parse(content)) === hash), "device_evidence_corrupted");
    }
    const manifest = JSON.parse(row.manifest), job = JSON.parse(row.job);
    requireThat(object(manifest) && object(manifest.device_dispatch) && digest(manifest.device_dispatch) === digest({
      device_id: row.device_id, task_id: row.task_id, episode_id: row.episode_id, fence: row.fence,
      workspace_id: row.workspace_id, assignment_digest: row.assignment_digest, job_digest: digest(job),
    }), "device_evidence_binding_corrupted");
    return row;
  }
  private reference(row: DeviceExecutionRecord): DeviceEvidenceRef {
    return { schema_version: "controlmesh.device_evidence.v1", device_id: row.device_id, task_id: row.task_id, episode_id: row.episode_id,
      effect_id: row.effect_id, fence: row.fence, assignment_digest: row.assignment_digest, manifest_digest: row.manifest_digest,
      ...(row.observation_digest ? { observation_digest: row.observation_digest } : {}), ...(row.result_digest ? { result_digest: row.result_digest } : {}) };
  }
  inspect(ref: DeviceEvidenceRef): DeviceExecutionRecord {
    assertProtocolSchema<DeviceEvidenceRef>("device-evidence-ref.schema.json", ref);
    requireThat(ref.device_id === this.deviceId, "device_evidence_wrong_device");
    const row = this.row(ref.effect_id), current = this.reference(row);
    for (const [key, value] of Object.entries(ref)) requireThat((current as unknown as Record<string, unknown>)[key] === value, "device_evidence_changed");
    return row;
  }

  prepare(job: DeviceJob, lease: Lease, effectId: string, manifest: Record<string, unknown>): DeviceEvidenceRef {
    identifier(effectId);
    requireThat(lease.device_id === this.deviceId && lease.task_id === job.task_id, "device_evidence_binding_mismatch");
    const retained = { ...manifest, device_dispatch: { device_id: this.deviceId, task_id: job.task_id, episode_id: lease.episode_id, fence: lease.fence,
      workspace_id: job.workspace_id, assignment_digest: job.assignment_digest, job_digest: digest(job) } };
    const encoded = canonical(retained), input = canonical(job);
    requireThat(Buffer.byteLength(encoded) <= 16 * 1024 * 1024 && Buffer.byteLength(input) <= 128 * 1024, "device_evidence_too_large");
    return this.db.transaction(() => {
      requireThat(!this.db.sql.query("SELECT 1 FROM device_execution_records WHERE device_id=? AND episode_id=?").get(this.deviceId, lease.episode_id), "device_episode_already_prepared");
      this.db.sql.query("INSERT INTO device_execution_records (effect_id,device_id,task_id,episode_id,fence,assignment_digest,workspace_id,phase,job,manifest_digest,manifest) VALUES (?,?,?,?,?,?,?,'prepared',?,?,?)")
        .run(effectId, this.deviceId, job.task_id, lease.episode_id, lease.fence, job.assignment_digest, job.workspace_id, input, digest(retained), encoded);
      const ref = this.reference(this.row(effectId));
      assertProtocolSchema("device-evidence-ref.schema.json", ref);
      return ref;
    });
  }
  dispatching(effectId: string): void { this.transition(effectId, "prepared", "dispatching"); }
  dispatched(effectId: string): void { this.transition(effectId, "dispatching", "dispatched"); }
  completed(effectId: string): void { this.transition(effectId, "verified", "completed"); }
  unknown(effectId: string): void {
    this.db.transaction(() => {
      const row = this.row(effectId);
      if (row.phase !== "completed") this.db.sql.query("UPDATE device_execution_records SET phase='unknown' WHERE effect_id=?").run(effectId);
    });
  }
  private transition(effectId: string, from: string, to: string): void {
    this.db.transaction(() => {
      requireThat(this.row(effectId).phase === from, "device_evidence_phase_conflict");
      this.db.sql.query("UPDATE device_execution_records SET phase=? WHERE effect_id=?").run(to, effectId);
    });
  }
  observe(effectId: string, observation: Record<string, unknown>): DeviceEvidenceRef {
    return this.store(effectId, "dispatched", "observed", "observation", observation);
  }
  verify(effectId: string, result: Record<string, unknown>): DeviceEvidenceRef {
    return this.store(effectId, "observed", "verified", "result", result);
  }
  private store(effectId: string, from: string, to: string, field: "observation" | "result", value: Record<string, unknown>): DeviceEvidenceRef {
    const encoded = canonical(value);
    requireThat(Buffer.byteLength(encoded) <= 4 * 1024 * 1024, "device_evidence_too_large");
    return this.db.transaction(() => {
      const row = this.row(effectId);
      requireThat(row.phase === from && row[field] === null, "device_evidence_phase_conflict");
      this.db.sql.query(`UPDATE device_execution_records SET phase=?,${field}=?,${field}_digest=? WHERE effect_id=?`).run(to, encoded, digest(value), effectId);
      return this.reference(this.row(effectId));
    });
  }

  resolveNativeSession(value: unknown, job: DeviceJob): Record<string, unknown> {
    requireThat(object(value), "device_native_session_required");
    assertProtocolSchema("device-native-session.schema.json", value);
    requireThat(value.device_id === this.deviceId, "device_native_session_wrong_device");
    const ref = value.evidence as DeviceEvidenceRef, row = this.inspect(ref);
    requireThat(ref.result_digest && ref.observation_digest && row.result && row.task_id === job.task_id && row.workspace_id === job.workspace_id, "device_native_session_binding_mismatch");
    const result: unknown = JSON.parse(row.result);
    requireThat(object(result) && object(result.native_session), "device_native_session_unverified");
    return result.native_session;
  }
}
