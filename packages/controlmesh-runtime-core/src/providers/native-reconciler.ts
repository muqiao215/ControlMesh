import type { Principal, ReconciliationBinding, RuntimeKernel, TaskSnapshot } from "../kernel";
import { requireThat } from "../value";
import type { IssuedReadAdmission, OpenCodeWorkerConfig } from "./opencode-worker";
import { decodeNativeManifest } from "./native-manifest";
import { NativeSessionStore } from "./native-session";
import { NativeResultVerification } from "./native-result-verification";
import type { ProbeBinding } from "./preflight-cache";
import { NativeMailboxDelivery } from "./native-mailbox";

/** Read-only native verification followed by an explicit transactional outcome decision. No model/probe/CLI invocation. */
export class NativeReconciler {
  constructor(private readonly kernel: RuntimeKernel, private readonly store: NativeSessionStore,
    private readonly config: OpenCodeWorkerConfig) {}

  inspect(actor: Principal, taskId: string, revision: number, effectId: string): ReconciliationBinding {
    const evidence = this.kernel.inspectReconciliation(actor, taskId, revision, effectId);
    decodeNativeManifest(evidence.manifest);
    return { episode_id: evidence.episode.episode_id, effect_id: effectId, manifest_digest: evidence.manifest_digest, observation_digest: evidence.observation_digest };
  }

  accept(actor: Principal, requestId: string, taskId: string, revision: number, candidate: ReconciliationBinding,
    binding: ProbeBinding, admission: IssuedReadAdmission): TaskSnapshot {
    requireThat(admission.source_scope === "local_foreground", "source_execution_floor_unavailable");
    requireThat(actor.device_id === this.store.deviceId, "reconciliation_store_changed");
    const response: unknown = admission.assertCurrent();
    if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    let verification: NativeResultVerification | undefined;
    try {
      return this.kernel.reconcileEffect(actor, requestId, taskId, revision, candidate, evidence => {
        verification = new NativeResultVerification(this.store, this.config, evidence.task.task, evidence.manifest, evidence.observation, binding, admission);
        verification.assertCurrent();
        const delivery = decodeNativeManifest(evidence.manifest).mailbox_delivery;
        let pending: number | undefined;
        if (delivery) {
          const mailbox = new NativeMailboxDelivery(this.kernel);
          mailbox.reconcile(actor, evidence, delivery, verification.result);
          pending = mailbox.pendingCount(actor, taskId);
        }
        verification.assertCurrent();
        return { ...verification.result, ...(pending !== undefined ? { mailbox_pending_count: pending } : {}),
          reconciliation: { schema_version: "controlmesh.native_reconciliation.v1", ...candidate } };
      });
    } finally { verification?.close(); }
  }
}
