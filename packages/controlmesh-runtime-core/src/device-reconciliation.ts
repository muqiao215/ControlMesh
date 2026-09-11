import { randomUUID } from "node:crypto";
import { assertProtocolSchema, type DeviceEvidenceRef, type DeviceReconciliationChallenge, type DeviceReconciliationReport } from "@controlmesh/protocol";
import { command, requireScope } from "./commands";
import type { DeviceJob, DeviceRegistration } from "./device-coordinator";
import type { Principal, RuntimeKernel } from "./kernel";
import { canonical, digest, identifier, requireThat } from "./value";

interface RecoveryRow {
  challenge_id: string; principal: string; device_id: string; registration_digest: string; task_id: string;
  challenge_digest: string; challenge: string; report_digest: string | null; response: string | null;
}
export interface ReconciliationReceipt { task_id: string; status: "done"; revision: number; challenge_id: string; evidence: DeviceEvidenceRef }

/** A trusted request authorizes one bounded result verification, never another provider execution. */
export class DeviceReconciliation {
  constructor(private readonly kernel: RuntimeKernel,
    private readonly registration: (deviceId: string, principalId: string) => DeviceRegistration,
    private readonly assignment: (device: DeviceRegistration, taskId: string) => DeviceJob) {}

  request(actor: Principal, requestId: string, taskId: string, revision: number, effectId: string, ttlMs = 30_000): DeviceReconciliationChallenge {
    requireScope(actor, "task:reconcile");
    requireThat(["human_request", "recovery", "internal"].includes(actor.origin), "trusted_reconciliation_required");
    identifier(actor.device_id);
    const device = this.registration(actor.device_id, actor.id);
    this.kernel.inspect(actor, taskId);
    requireThat(Number.isSafeInteger(ttlMs) && ttlMs >= 500 && ttlMs <= 30_000, "invalid_reconciliation_ttl");
    return command(this.kernel.db, actor, requestId, "device.reconciliation.request", { taskId, revision, effectId, ttlMs }, () => {
      const target = this.kernel.inspectReconciliationTarget(actor, taskId, revision, effectId);
      const job = this.assignment(device, taskId);
      const manifest: unknown = target.manifest;
      assertProtocolSchema<DeviceReconciliationChallenge["manifest"]>("device-evidence-ref.schema.json", manifest);
      requireThat(job.execution?.provider === "opencode" && job.execution_digest, "device_reconciliation_profile_unavailable");
      requireThat(manifest.device_id === device.device_id && manifest.task_id === taskId && manifest.effect_id === effectId
        && manifest.episode_id === target.episode.episode_id && manifest.fence === target.episode.fence
        && manifest.assignment_digest === job.assignment_digest && !manifest.observation_digest && !manifest.result_digest, "device_manifest_binding_mismatch");
      const challenge: DeviceReconciliationChallenge = { schema_version: "controlmesh.device_reconciliation_challenge.v1", challenge_id: randomUUID(),
        task_revision: revision, task_fence: target.task.fence, manifest, execution_digest: job.execution_digest,
        workspace_id: job.workspace_id, capability: job.capability, expires_at: this.kernel.db.now() + ttlMs };
      assertProtocolSchema("device-reconciliation-challenge.schema.json", challenge);
      this.kernel.db.sql.query("INSERT INTO device_reconciliations (challenge_id,principal,device_id,registration_digest,task_id,challenge_digest,challenge) VALUES (?,?,?,?,?,?,?)")
        .run(challenge.challenge_id, actor.id, device.device_id, digest(device), taskId, digest(challenge), canonical(challenge));
      this.event(actor, challenge, "device.reconciliation_requested", { challenge_digest: digest(challenge) });
      return challenge;
    });
  }

  private event(actor: Principal, challenge: DeviceReconciliationChallenge, kind: string, payload: unknown): void {
    this.kernel.db.sql.query("INSERT INTO events (task_id,kind,revision,fence,principal,origin,at,payload) VALUES (?,?,?,?,?,?,?,?)")
      .run(challenge.manifest.task_id, kind, challenge.task_revision, challenge.task_fence, actor.id, actor.origin, this.kernel.db.now(),
        canonical({ challenge_id: challenge.challenge_id, device_id: challenge.manifest.device_id, detail: payload }));
  }

  private load(device: DeviceRegistration, id: string): { row: RecoveryRow; challenge: DeviceReconciliationChallenge } {
    identifier(id);
    const current = this.registration(device.device_id, device.principal_id);
    const row = this.kernel.db.sql.query("SELECT * FROM device_reconciliations WHERE challenge_id=? AND device_id=? AND principal=?")
      .get(id, device.device_id, device.principal_id) as RecoveryRow | null;
    requireThat(row && row.registration_digest === digest(current), "reconciliation_authority_unavailable");
    const challenge: unknown = JSON.parse(row.challenge);
    assertProtocolSchema<DeviceReconciliationChallenge>("device-reconciliation-challenge.schema.json", challenge);
    requireThat(digest(challenge) === row.challenge_digest && challenge.challenge_id === id && challenge.manifest.task_id === row.task_id
      && challenge.manifest.device_id === row.device_id, "reconciliation_challenge_corrupted");
    this.kernel.inspect(this.recoveryActor(row), row.task_id);
    return { row, challenge };
  }

  private recoveryActor(row: RecoveryRow): Principal {
    // Derived from a persisted, scope-checked local request. The reporting device remains agent-origin.
    return { id: row.principal, device_id: row.device_id, origin: "recovery", scopes: ["task:read", "task:reconcile"] };
  }

  private current(device: DeviceRegistration, row: RecoveryRow, challenge: DeviceReconciliationChallenge): void {
    requireThat(this.kernel.db.now() < challenge.expires_at, "reconciliation_expired");
    const job = this.assignment(device, row.task_id);
    const target = this.kernel.inspectReconciliationTarget(this.recoveryActor(row), row.task_id, challenge.task_revision, challenge.manifest.effect_id);
    requireThat(target.task.fence === challenge.task_fence && digest(target.manifest) === digest(challenge.manifest)
      && job.assignment_digest === challenge.manifest.assignment_digest && job.execution_digest === challenge.execution_digest
      && job.workspace_id === challenge.workspace_id && job.capability === challenge.capability, "reconciliation_authority_changed");
  }

  inspect(device: DeviceRegistration, id: string): unknown {
    return this.kernel.db.transaction(() => {
      const { row, challenge } = this.load(device, id);
      if (row.response) return { state: "accepted", receipt: JSON.parse(row.response) };
      this.current(device, row, challenge);
      return { state: "pending", challenge, remaining_ms: Math.min(30_000, challenge.expires_at - this.kernel.db.now()) };
    });
  }

  report(device: DeviceRegistration, requestId: string, report: DeviceReconciliationReport): ReconciliationReceipt {
    assertProtocolSchema("device-reconciliation-report.schema.json", report);
    const actor: Principal = { id: device.principal_id, device_id: device.device_id, origin: "agent_message", scopes: ["task:read"] };
    this.load(device, report.challenge_id); // Current authorization is required even for an idempotent receipt.
    return command(this.kernel.db, actor, requestId, "device.reconciliation.report", report, () => {
      const { row, challenge } = this.load(device, report.challenge_id);
      requireThat(report.challenge_digest === row.challenge_digest, "reconciliation_challenge_changed");
      if (row.response) {
        requireThat(row.report_digest === digest(report), "reconciliation_report_conflict");
        return JSON.parse(row.response) as ReconciliationReceipt;
      }
      this.current(device, row, challenge);
      const { observation, result } = report;
      for (const ref of [observation.evidence, result.evidence]) {
        const { observation_digest: _observation, result_digest: _result, ...base } = ref;
        requireThat(digest(base) === digest(challenge.manifest), "device_evidence_reference_mismatch");
      }
      requireThat(observation.terminal && observation.evidence.observation_digest && !observation.evidence.result_digest
        && result.evidence.observation_digest === observation.evidence.observation_digest && result.evidence.result_digest
        && digest(result.text) === result.output_digest && result.native_session.device_id === device.device_id
        && digest(result.native_session.evidence) === digest(result.evidence), "device_reconciliation_result_mismatch");
      const recovery = this.recoveryActor(row), binding = { episode_id: challenge.manifest.episode_id, effect_id: challenge.manifest.effect_id,
        manifest_digest: digest(challenge.manifest), observation_digest: digest(observation) };
      this.event(actor, challenge, "device.reconciliation_reported", { report_digest: digest(report) });
      this.kernel.admitReconciliationObservation(recovery, row.task_id, challenge.task_revision, binding, { ...observation }, challenge.challenge_id);
      const done = this.kernel.reconcileEffect(recovery, `reconcile-${challenge.challenge_id}`, row.task_id, challenge.task_revision, binding, () => {
        this.current(device, row, challenge);
        return { ...result, reconciliation: { schema_version: "controlmesh.device_reconciliation.v1", challenge_id: challenge.challenge_id,
          challenge_digest: row.challenge_digest, report_digest: digest(report) } };
      });
      const receipt: ReconciliationReceipt = { task_id: row.task_id, status: "done", revision: done.revision, challenge_id: challenge.challenge_id, evidence: result.evidence };
      this.kernel.db.sql.query("UPDATE device_reconciliations SET report_digest=?,response=? WHERE challenge_id=?")
        .run(digest(report), canonical(receipt), challenge.challenge_id);
      return receipt;
    });
  }
}
