import { ensureTopologyNativeInput } from "../topology-native-input";
import { AgentMailbox } from "../mailbox";
import type { RuntimeKernel, Principal, Lease, ReconciliationEvidence } from "../kernel";
import { requireScope } from "../commands";
import { digest, object, requireThat, RuntimeConflict } from "../value";
import { decodeNativeMailbox, nativeInput, nativeMailboxBinding, nativeMailboxEvidence, nativeMessage, type NativeMailboxBatch } from "./native-mailbox-input";
import { assertProtocolSchema, type NativeMailboxBinding, type NativeMailboxProof } from "@controlmesh/protocol";

/** Coordinator-owned delivery reservations. The native driver/verifier supplies confirmed input evidence. */
export class NativeMailboxDelivery {
  private readonly mailbox: AgentMailbox;
  constructor(private readonly kernel: RuntimeKernel) { this.mailbox = new AgentMailbox(kernel); }

  prepare(actor: Principal, lease: Lease, prompt: string, maxInputBytes = 65536): NativeMailboxBatch | undefined {
    requireThat(Number.isSafeInteger(maxInputBytes) && maxInputBytes > 0 && maxInputBytes <= 65536, "invalid_native_mailbox_input_limit");
    requireScope(actor, "message:ack");
    const messagesBefore = this.mailbox.pending(actor, lease);
    const required = ensureTopologyNativeInput(this.kernel, actor, lease);
    const messages = required ? this.mailbox.pending(actor, lease) : messagesBefore;
    if (!messages.length) {
      requireThat(!required, "topology_native_context_not_delivered");
      return undefined;
    }
    const batch: NativeMailboxBatch = { schema_version: "controlmesh.native_mailbox.v1", task_id: lease.task_id, messages: [] };
    for (const message of messages) {
      batch.messages.push(nativeMessage(message));
      try { requireThat(Buffer.byteLength(nativeInput(prompt, batch)) <= maxInputBytes, "native_mailbox_input_too_large"); }
      catch (error) {
        if (!(error instanceof RuntimeConflict) || !["native_mailbox_too_large", "native_mailbox_input_too_large"].includes(error.code) || batch.messages.length === 1) throw error;
        batch.messages.pop(); break; // Keep the fitting prefix; never truncate or skip a message.
      }
    }
    this.assertRequiredInput(actor, lease, batch);
    this.assertUnreserved(actor, lease, batch);
    return batch;
  }

  assertRequiredInput(actor: Principal, lease: Lease, batch?: NativeMailboxBatch): void {
    const required = ensureTopologyNativeInput(this.kernel, actor, lease);
    requireThat(!required || batch?.messages.some(message => message.message_id === required), "topology_native_context_not_delivered");
  }

  private assertUnreserved(actor: Principal, lease: Lease, batch: NativeMailboxBatch): void {
    this.kernel.withLease(actor, lease, () => {
      requireThat(batch.task_id === lease.task_id, "native_mailbox_task_mismatch");
      decodeNativeMailbox(batch);
      this.assertRequiredInput(actor, lease, batch);
      const pending = this.mailbox.pending(actor, lease, batch.messages.length);
      requireThat(digest(pending.map(nativeMessage)) === digest(batch.messages), "native_mailbox_changed");
      for (const message of batch.messages) requireThat(!this.kernel.db.sql.query("SELECT 1 FROM native_mailbox_deliveries WHERE message_id=? UNION ALL SELECT 1 FROM native_agent_deliveries WHERE message_id=?")
        .get(message.message_id, message.message_id), "native_message_already_dispatched");
    });
  }

  /** Reconstruct the exact original batch; content stays in the authoritative coordinator mailbox. */
  resolveBinding(actor: Principal, taskId: string, binding: unknown): NativeMailboxBatch {
    assertProtocolSchema<NativeMailboxBinding>("native-mailbox-binding.schema.json", binding);
    const batch: NativeMailboxBatch = { schema_version: "controlmesh.native_mailbox.v1", task_id: taskId,
      messages: binding.message_ids.map(id => nativeMessage(this.mailbox.inspect(actor, taskId, id))) };
    requireThat(digest(nativeMailboxBinding(batch)) === digest(binding), "native_mailbox_binding_changed");
    return batch;
  }

  verifyDevice(actor: Principal, taskId: string, binding: unknown, proof: unknown): { batch: NativeMailboxBatch; verified: Record<string, unknown> } {
    assertProtocolSchema<NativeMailboxProof>("native-mailbox-proof.schema.json", proof);
    const batch = this.resolveBinding(actor, taskId, binding);
    requireThat(digest(proof) === digest(nativeMailboxEvidence(batch, proof.native_user_message_id)), "native_mailbox_delivery_unproven");
    return { batch, verified: { user_message_id: proof.native_user_message_id, mailbox_delivery: proof } };
  }

  /** Must run in the same transaction as dispatchEffect, before the native command is issued. */
  reserve(actor: Principal, lease: Lease, effectId: string, batch: NativeMailboxBatch): void {
    requireScope(actor, "message:ack");
    this.kernel.withLease(actor, lease, () => {
      this.assertUnreserved(actor, lease, batch);
      this.assertEffect(effectId, lease.task_id, lease.episode_id, lease.fence, batch, "dispatched");
      for (const message of batch.messages) {
        this.mailbox.acknowledge(actor, `native-receive-${digest([effectId, message.message_id])}`, lease, message.message_id, "received", null);
        this.kernel.db.sql.query("INSERT INTO native_mailbox_deliveries VALUES (?,?,?,?)")
          .run(message.message_id, effectId, digest(message), digest(batch));
      }
    });
  }

  private assertEffect(effectId: string, taskId: string, episodeId: string, fence: number, batch: NativeMailboxBatch, state: string): void {
    const effect = this.kernel.db.sql.query("SELECT e.state,m.payload,m.digest FROM effects e JOIN execution_manifests m ON m.effect_id=e.effect_id WHERE e.effect_id=? AND e.task_id=? AND e.episode_id=? AND e.fence=?")
      .get(effectId, taskId, episodeId, fence) as { state: string; payload: string; digest: string } | null;
    requireThat(effect && effect.state === state, "native_mailbox_effect_mismatch");
    const manifest = JSON.parse(effect.payload);
    const bound = manifest.schema_version === "controlmesh.device_evidence.v1" ? nativeMailboxBinding(batch) : batch;
    requireThat(digest(manifest) === effect.digest && digest(manifest.mailbox_delivery) === digest(bound), "native_mailbox_manifest_changed");
  }

  /** Called only after actual native input verification, inside the task completion/reconciliation transaction. */
  consume(actor: Principal, lease: Lease, effectId: string, batch: NativeMailboxBatch, verified: Record<string, unknown>): void {
    requireThat(this.kernel.db.sql.inTransaction, "native_mailbox_transaction_required");
    this.kernel.withLease(actor, lease, () => this.apply(actor, effectId, lease.task_id, lease.episode_id, lease.fence, batch, verified, "dispatched"));
  }

  reconcile(actor: Principal, original: ReconciliationEvidence, batch: NativeMailboxBatch, verified: Record<string, unknown>): void {
    requireThat(this.kernel.db.sql.inTransaction, "native_mailbox_transaction_required");
    const current = this.kernel.inspectReconciliation(actor, original.task.task.task_id, original.task.revision, original.effect_id);
    requireThat(current.manifest_digest === original.manifest_digest && current.observation_digest === original.observation_digest,
      "reconciliation_evidence_changed");
    this.apply(actor, current.effect_id, current.task.task.task_id, current.episode.episode_id, current.episode.fence, batch, verified, "unknown");
  }

  private apply(actor: Principal, effectId: string, taskId: string, episodeId: string, fence: number,
    batch: NativeMailboxBatch, verified: Record<string, unknown>, state: "dispatched" | "unknown"): void {
    requireScope(actor, "message:ack"); this.kernel.inspect(actor, taskId);
    requireThat(this.kernel.db.sql.inTransaction, "native_mailbox_transaction_required");
    requireThat(batch.task_id === taskId && typeof verified.user_message_id === "string" && object(verified.mailbox_delivery)
      && digest(verified.mailbox_delivery) === digest(nativeMailboxEvidence(batch, verified.user_message_id)), "native_mailbox_delivery_unproven");
    this.assertEffect(effectId, taskId, episodeId, fence, batch, state);
    for (const message of batch.messages) {
      const current = this.mailbox.inspect(actor, taskId, message.message_id);
      requireThat(current.status === "received" && digest(nativeMessage(current)) === digest(message), "native_mailbox_changed");
      const saved = this.kernel.db.sql.query("SELECT d.*,m.receipt_episode,m.receipt_fence FROM native_mailbox_deliveries d JOIN messages m ON m.message_id=d.message_id WHERE d.message_id=?")
        .get(message.message_id) as { effect_id: string; message_digest: string; delivery_digest: string; receipt_episode: string; receipt_fence: number } | null;
      requireThat(saved && saved.effect_id === effectId && saved.message_digest === digest(message) && saved.delivery_digest === digest(batch)
        && saved.receipt_episode === episodeId && saved.receipt_fence === fence, "native_mailbox_receipt_changed");
      const gap = this.kernel.db.sql.query("SELECT 1 FROM messages WHERE recipient_task=? AND sequence<? AND status IN ('pending','received') LIMIT 1").get(taskId, message.sequence);
      requireThat(!gap, "message_sequence_gap");
      const evidence = `native-mailbox:${digest({ effect_id: effectId, ...verified.mailbox_delivery })}`;
      this.kernel.db.sql.query("UPDATE messages SET status='consumed',consumed_evidence=? WHERE message_id=?")
        .run(evidence, message.message_id);
    }
  }

  pendingCount(actor: Principal, taskId: string): number { return this.mailbox.pendingCount(actor, taskId); }
}
