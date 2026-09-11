import { realpathSync } from "node:fs";
import { join, relative } from "node:path";
import type { Principal, ReconciliationBinding, RuntimeKernel, TaskSnapshot } from "../kernel";
import { digest, object, requireThat } from "../value";
import { enforceLocalReadSource } from "../execution-policy";
import type { IssuedReadAdmission, OpenCodeWorkerConfig } from "./opencode-worker";
import { assertWorkspaceManifest, decodeNativeManifest, nativeTaskDigest } from "./native-manifest";
import { NativeSessionLease } from "./native-lease";
import { NativeSessionStore } from "./native-session";
import { assertReadGrantSnapshot, inspectReadPermissions, readFileGrant } from "./opencode-profile";
import type { ProbeBinding } from "./preflight-cache";

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
    // Recheck current caller authorization even for an existing acceptance receipt.
    const authorize = () => {
      const response: unknown = admission.assertCurrent();
      if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    authorize();
    const held: { lock?: NativeSessionLease } = {};
    try {
      return this.kernel.reconcileEffect(actor, requestId, taskId, revision, candidate, evidence => {
        const manifest = decodeNativeManifest(evidence.manifest), task = evidence.task.task, observation = evidence.observation;
        requireThat(nativeTaskDigest(task) === manifest.task_digest, "reconciliation_task_changed");
        requireThat(digest(manifest.binding) === digest(binding) && digest(this.config.native_configuration) === binding.config_digest, "reconciliation_provider_changed");
        requireThat(actor.device_id === this.store.deviceId && binding.device_id === this.store.deviceId && this.store.identity() === manifest.native_store_id, "reconciliation_store_changed");
        enforceLocalReadSource(task.execution_context);
        requireThat(typeof task.repo_root === "string" && typeof task.prompt === "string" && realpathSync(task.repo_root) === manifest.directory.path, "native_workspace_mismatch");
        const files = readFileGrant(manifest.directory.path, admission.read_files), required = readFileGrant(manifest.directory.path, admission.required_reads);
        requireThat(digest(files) === digest(manifest.files.map(file => file.path)) && digest(required) === digest(manifest.required_reads), "reconciliation_grant_changed");
        assertReadGrantSnapshot(task.tool_grant, files);
        const saved = manifest.permission_evidence;
        requireThat(realpathSync(join(saved.data_home, "opencode/opencode.db")) === realpathSync(this.store.path), "native_environment_store_mismatch");
        const permissions = inspectReadPermissions(saved.resolved, saved.agent, saved.data_home,
          files.map(file => relative(manifest.worktree.path, file)), manifest.baseline?.permissions ?? []);
        requireThat(permissions?.digest === saved.digest, "native_permission_evidence_changed");
        requireThat(observation.terminal === true && typeof observation.native_session_id === "string" && typeof observation.text === "string"
          && observation.process_reason === "exited" && observation.exit_code === 0 && observation.failure === null && observation.invalid_reason === null, "native_completion_unproven");
        const current = this.store.read(observation.native_session_id);
        held.lock = new NativeSessionLease(this.config.state_home, this.store.path, current);
        requireThat(current.store_id === manifest.native_store_id, "reconciliation_store_changed");
        assertWorkspaceManifest(manifest, true);
        const verified = this.store.verifyTurn(observation.native_session_id, manifest.baseline, task.prompt, observation.text);
        requireThat(verified.reference.directory === manifest.directory.path && verified.reference.model === binding.model
          && this.store.worktree(verified.reference) === manifest.worktree.path, "native_result_binding_mismatch");
        const reads = verified.read_files.map(file => realpathSync(file));
        requireThat(required.every(file => reads.includes(file)) && reads.every(file => files.includes(file)), "required_native_read_unproven");
        authorize(); held.lock.assertCurrent();
        assertWorkspaceManifest(manifest, true);
        this.store.validate(verified.reference);
        return { native_session: verified.reference, user_message_id: verified.user_message_id, assistant_message_ids: verified.assistant_message_ids,
          text: observation.text, output_digest: digest(observation.text), permission_digest: saved.digest, read_files: verified.read_files,
          reconciliation: { schema_version: "controlmesh.native_reconciliation.v1", ...candidate } };
      });
    } finally { held.lock?.close(); }
  }
}
