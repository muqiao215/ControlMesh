import type { Principal, ReconciliationBinding, RuntimeKernel, TaskSnapshot } from "../kernel";
import { digest, requireThat } from "../value";
import { NativeSessionLease } from "./native-lease";
import { NativeMailboxDelivery } from "./native-mailbox";
import { claudeTaskScope, type ClaudeTaskConfiguration } from "./claude-task-profile";
import { ClaudeTaskEvidence, decodeClaudeDispatch, readClaudeOutcome } from "./claude-task-evidence";

/** Current owner may recover retained output/publication. No provider runner is reachable here. */
export class ClaudeTaskReconciler {
  constructor(private readonly kernel: RuntimeKernel, private readonly config: ClaudeTaskConfiguration, private readonly authorize: () => void) {}
  private current(): void {
    const checked: unknown = this.authorize();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  inspect(actor: Principal, taskId: string, revision: number, effectId: string): ReconciliationBinding {
    this.current();
    const target = this.kernel.inspectReconciliationTarget(actor, taskId, revision, effectId), manifest = decodeClaudeDispatch(target.manifest);
    claudeTaskScope(this.config, target.task.task, true);
    requireThat(manifest.configuration_digest === digest(this.config), "claude_task_configuration_changed");
    const observation = target.observation ?? readClaudeOutcome(manifest).observation;
    return { episode_id: target.episode.episode_id, effect_id: effectId, manifest_digest: target.manifest_digest, observation_digest: digest(observation) };
  }
  async accept(actor: Principal, requestId: string, taskId: string, revision: number, binding: ReconciliationBinding,
    verifyPublication?: (assertPublished: () => void) => Promise<Record<string, unknown>>): Promise<TaskSnapshot> {
    this.current();
    const previous = this.kernel.reconciliationReceipt(actor, requestId, taskId, revision, binding); if (previous) return previous;
    const selected = this.inspect(actor, taskId, revision, binding.effect_id);
    requireThat(digest(selected) === digest(binding), "reconciliation_evidence_changed");
    const target = this.kernel.inspectReconciliationTarget(actor, taskId, revision, binding.effect_id), manifest = decodeClaudeDispatch(target.manifest);
    requireThat(!this.config.workflow_binding || verifyPublication, "native_workflow_verifier_required");
    const lock = new NativeSessionLease(this.config.state_home, this.config.environment.config_directory, { session_id: manifest.input.session_id });
    try {
      const current = () => {
        this.current(); lock.assertCurrent();
        requireThat(digest(this.inspect(actor, taskId, revision, binding.effect_id)) === digest(binding), "reconciliation_evidence_changed");
      };
      const observation = target.observation ?? readClaudeOutcome(manifest).observation;
      const verifier = new ClaudeTaskEvidence(this.config, actor.device_id!, target.task.task, manifest, observation, current);
      verifier.verify();
      if (!target.observation) this.kernel.admitReconciliationObservation(actor, taskId, revision,
        { episode_id: binding.episode_id, effect_id: binding.effect_id, manifest_digest: binding.manifest_digest }, observation, `claude-recovery-${digest(requestId)}`);
      this.kernel.reserveReconciliation(actor, requestId, taskId, revision, binding);
      const result = verifier.publish(operation => this.kernel.db.transaction(() => { current(); return operation(); }));
      const assertPublished = () => { current(); verifier.assertPublished(); };
      const publication = await verifyPublication?.(assertPublished) ?? {};
      assertPublished();
      return this.kernel.reconcileEffect(actor, requestId, taskId, revision, binding, saved => {
        assertPublished(); const mailbox = new NativeMailboxDelivery(this.kernel);
        if (manifest.mailbox_delivery) mailbox.reconcile(actor, saved, manifest.mailbox_delivery, result);
        return { ...publication, ...result, mailbox_pending_count: mailbox.pendingCount(actor, taskId),
          reconciliation: { schema_version: "controlmesh.claude_reconciliation.v1", ...binding } };
      });
    } finally { lock.close(); }
  }
}
