import type { Principal, ReconciliationBinding, RuntimeKernel, TaskSnapshot } from "../kernel";
import { digest, requireThat } from "../value";
import type { IssuedReadAdmission, OpenCodeWorkerConfig } from "./opencode-worker";
import { decodeNativeManifest } from "./native-manifest";
import { NativeSessionStore } from "./native-session";
import { NativeResultVerification } from "./native-result-verification";
import type { ProbeBinding } from "./preflight-cache";
import { NativeMailboxDelivery } from "./native-mailbox";
import { NativeAgentJournal, type NativeAgentToolResult } from "./native-agent-journal";
import type { NativeRunner } from "./opencode-execution";

/** Native evidence verification and owned proposal recovery before the outcome decision. No model/probe/CLI invocation. */
export class NativeReconciler {
  constructor(private readonly kernel: RuntimeKernel, private readonly store: NativeSessionStore,
    private readonly config: OpenCodeWorkerConfig, private readonly runner?: NativeRunner) {}

  inspect(actor: Principal, taskId: string, revision: number, effectId: string): ReconciliationBinding {
    const evidence = this.kernel.inspectReconciliation(actor, taskId, revision, effectId);
    decodeNativeManifest(evidence.manifest);
    return { episode_id: evidence.episode.episode_id, effect_id: effectId, manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest };
  }

  accept(actor: Principal, requestId: string, taskId: string, revision: number, candidate: ReconciliationBinding,
    binding: ProbeBinding, admission: IssuedReadAdmission): TaskSnapshot {
    requireThat(this.runner || admission.source_scope === "local_foreground", "source_execution_floor_unavailable");
    requireThat(actor.device_id === this.store.deviceId, "reconciliation_store_changed");
    const response: unknown = admission.assertCurrent();
    if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    let verification: NativeResultVerification | undefined;
    try {
      return this.kernel.reconcileEffect(actor, requestId, taskId, revision, candidate, evidence => {
        requireThat(!decodeNativeManifest(evidence.manifest).workspace_write, "native_write_recovery_requires_publication");
        const journal = new NativeAgentJournal(this.kernel);
        let tools: NativeAgentToolResult[] = [];
        verification = new NativeResultVerification(this.store, this.config, evidence.task.task, evidence.manifest, evidence.observation, binding, admission,
          (scope, actual) => { tools = actual; return journal.verify(evidence.effect_id, scope, actual); }, this.runner);
        verification.assertCurrent();
        const delivery = decodeNativeManifest(evidence.manifest).mailbox_delivery;
        let pending: number | undefined;
        if (delivery) {
          const mailbox = new NativeMailboxDelivery(this.kernel);
          mailbox.reconcile(actor, evidence, delivery, verification.result);
          pending = mailbox.pendingCount(actor, taskId);
        }
        const communication = decodeNativeManifest(evidence.manifest).communication;
        if (communication) {
          journal.reconcile(actor, evidence, communication, tools);
          pending = new NativeMailboxDelivery(this.kernel).pendingCount(actor, taskId);
        }
        verification.assertCurrent();
        return { ...verification.result, ...(pending !== undefined ? { mailbox_pending_count: pending } : {}),
          reconciliation: { schema_version: "controlmesh.native_reconciliation.v1", ...candidate } };
      });
    } finally { verification?.close(); }
  }

  /** Resume only the retained proposal. Native execution is unavailable during recovery. */
  async acceptWorkspace(actor: Principal, requestId: string, taskId: string, revision: number, candidate: ReconciliationBinding,
    binding: ProbeBinding, admission: IssuedReadAdmission,
    verifyPublication?: (assertPublished: () => void) => Promise<Record<string, unknown>>): Promise<TaskSnapshot> {
    requireThat(actor.device_id === this.store.deviceId, "reconciliation_store_changed");
    const authorize = () => { const checked: unknown = admission.assertCurrent();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); } };
    authorize();
    const previous = this.kernel.reconciliationReceipt(actor, requestId, taskId, revision, candidate);
    if (previous) return previous;
    const evidence = this.kernel.inspectReconciliation(actor, taskId, revision, candidate.effect_id), manifest = decodeNativeManifest(evidence.manifest);
    if (!manifest.workspace_write) return this.accept(actor, requestId, taskId, revision, candidate, binding, admission);
    requireThat(!manifest.workspace_write.workflow_binding || verifyPublication, "native_workflow_verifier_required");
    const selected = { episode_id: evidence.episode.episode_id, effect_id: evidence.effect_id,
      manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest };
    requireThat(digest(selected) === digest(candidate), "reconciliation_evidence_changed");
    const journal = new NativeAgentJournal(this.kernel); let tools: NativeAgentToolResult[] = [];
    const verification = new NativeResultVerification(this.store, this.config, evidence.task.task, manifest, evidence.observation, binding, admission,
      (scope, actual) => { tools = actual; return journal.verify(evidence.effect_id, scope, actual); }, this.runner);
    const current = () => {
      authorize(); const fresh = this.kernel.inspectReconciliation(actor, taskId, revision, candidate.effect_id);
      requireThat(fresh.manifest_digest === candidate.manifest_digest && fresh.observation_digest === candidate.observation_digest
        && fresh.episode.episode_id === candidate.episode_id, "reconciliation_evidence_changed"); verification.assertCurrent();
    };
    try {
      this.kernel.reserveReconciliation(actor, requestId, taskId, revision, candidate);
      verification.publish(operation => this.kernel.db.transaction(() => { current(); return operation(); }));
      const assertPublished = () => { current(); verification.assertPublished(); };
      const publication = await verifyPublication?.(assertPublished) ?? {};
      assertPublished();
      return this.kernel.reconcileEffect(actor, requestId, taskId, revision, candidate, saved => {
        assertPublished(); const mailbox = new NativeMailboxDelivery(this.kernel);
        if (manifest.mailbox_delivery) mailbox.reconcile(actor, saved, manifest.mailbox_delivery, verification.result);
        if (manifest.communication) journal.reconcile(actor, saved, manifest.communication, tools);
        assertPublished();
        return { ...publication, ...verification.result, mailbox_pending_count: mailbox.pendingCount(actor, taskId),
          reconciliation: { schema_version: "controlmesh.native_reconciliation.v1", ...candidate } };
      });
    } finally { verification.close(); }
  }
}
