import { realpathSync } from "node:fs";
import { join, relative } from "node:path";
import { digest, requireThat, type LegacyTask } from "../value";
import { enforceLocalReadSource } from "../execution-policy";
import type { IssuedReadAdmission, OpenCodeWorkerConfig } from "./opencode-worker";
import { assertWorkspaceManifest, decodeNativeManifest, nativeTaskDigest } from "./native-manifest";
import { NativeSessionLease } from "./native-lease";
import { NativeSessionStore } from "./native-session";
import { assertReadGrantSnapshot, inspectReadPermissions, readFileGrant } from "./opencode-profile";
import type { ProbeBinding } from "./preflight-cache";
import { nativeInput, nativeMailboxEvidence } from "./native-mailbox-input";
import { nativeAgentTools, type NativeAgentScope, type NativeAgentToolResult } from "./native-agent-journal";
import { assertNativeAgentConfiguration, nativeAgentScope } from "./native-agent-profile";
import { registeredReads, writeRoots, openWorkspace, verifyWorkspaceTools, type NativeWriteReceipt } from "./native-workspace";
import { inspectWorkspacePermissions } from "./opencode-profile";
import { enforceNativeReadSource } from "../execution-policy";
import type { NativeRunner } from "./opencode-execution";
import type { WorkspaceStage, WorkspaceAuthority } from "../workspace-stage";

/** Keeps the native lock while callers retain/report the verified result. No provider command is available here. */
export class NativeResultVerification {
  readonly result: Record<string, unknown>;
  private lock?: NativeSessionLease;
  private recheck: () => void;
  private closed = false;
  private stage?: WorkspaceStage;
  private proposal?: NativeWriteReceipt;
  constructor(private readonly store: NativeSessionStore, private readonly config: OpenCodeWorkerConfig,
    task: LegacyTask, manifestValue: unknown, observation: Record<string, unknown>, binding: ProbeBinding, admission: IssuedReadAdmission,
    verifyCommunication?: (scope: NativeAgentScope, tools: NativeAgentToolResult[]) => Record<string, unknown>, runner?: NativeRunner) {
    const source = runner ? enforceNativeReadSource(task.execution_context, runner) : enforceLocalReadSource(task.execution_context);
    requireThat(admission.source_scope === source.source_scope, "source_execution_floor_unavailable");
    // Recheck current caller authorization even for an existing acceptance receipt.
    const issuedAdmission = () => digest({ source_scope: admission.source_scope, read_files: admission.read_files,
      required_reads: admission.required_reads, workspace_write: admission.workspace_write ?? null });
    const admissionDigest = issuedAdmission();
    const authorize = () => {
      requireThat(issuedAdmission() === admissionDigest, "native_recovery_grant_changed");
      const response: unknown = admission.assertCurrent();
      if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    this.recheck = authorize;
    authorize();
    try {
      const manifest = decodeNativeManifest(manifestValue);
      requireThat(Boolean(manifest.workspace_write) === Boolean(admission.workspace_write), "native_write_grant_changed");
      if (manifest.workspace_write) requireThat(runner?.forStage && runner.runtimeDigest?.() === binding.runtime_digest, "native_write_owner_required");
      requireThat(Boolean(manifest.communication) === Boolean(this.config.communication), "native_agent_profile_required");
      const communicationIdentity = this.config.communication ? assertNativeAgentConfiguration(this.config.communication) : null;
      if (manifest.communication) {
        requireThat(verifyCommunication && manifest.communication.task_id === task.task_id
          && digest(nativeAgentScope(this.config.communication!, manifest.communication)) === digest(manifest.communication), "native_agent_scope_changed");
      }
      requireThat(nativeTaskDigest(task) === manifest.task_digest, "reconciliation_task_changed");
      requireThat(digest(manifest.binding) === digest(binding) && digest(this.config.native_configuration) === binding.config_digest, "reconciliation_provider_changed");
      requireThat(binding.device_id === this.store.deviceId && this.store.identity() === manifest.native_store_id, "reconciliation_store_changed");
      requireThat(typeof task.repo_root === "string" && typeof task.prompt === "string" && realpathSync(task.repo_root) === manifest.directory.path, "native_workspace_mismatch");
      requireThat(!manifest.mailbox_delivery || manifest.mailbox_delivery.task_id === task.task_id, "native_mailbox_task_mismatch");
      const input = nativeInput(task.prompt, manifest.mailbox_delivery);
      const roots = admission.workspace_write ? writeRoots(manifest.directory.path, admission.workspace_write) : [];
      const files = roots.length ? registeredReads(manifest.directory.path, admission.read_files, roots, true) : readFileGrant(manifest.directory.path, admission.read_files);
      const required = roots.length ? registeredReads(manifest.directory.path, admission.required_reads, roots, true) : readFileGrant(manifest.directory.path, admission.required_reads);
      requireThat(digest(files) === digest(manifest.files.map(file => file.path)) && digest(required) === digest(manifest.required_reads), "reconciliation_grant_changed");
      const communicationTools = manifest.communication ? nativeAgentTools : [];
      assertReadGrantSnapshot(task.tool_grant, files, communicationTools);
      const saved = manifest.permission_evidence;
      requireThat(realpathSync(join(saved.data_home, "opencode/opencode.db")) === realpathSync(this.store.path), "native_environment_store_mismatch");
      const write = manifest.workspace_write;
      const permissions = write ? inspectWorkspacePermissions(saved.resolved, saved.agent, saved.data_home, write.read_patterns, write.edit_patterns,
        manifest.baseline?.permissions ?? [], communicationTools, write.denied_patterns) : inspectReadPermissions(saved.resolved, saved.agent, saved.data_home,
        files.map(file => relative(manifest.worktree.path, file)), manifest.baseline?.permissions ?? [], communicationTools);
      requireThat(permissions?.digest === saved.digest, "native_permission_evidence_changed");
      requireThat(observation.terminal === true && typeof observation.native_session_id === "string" && typeof observation.text === "string"
        && observation.process_reason === "exited" && observation.exit_code === 0 && observation.failure === null && observation.invalid_reason === null, "native_completion_unproven");
      const current = this.store.read(observation.native_session_id);
      this.lock = new NativeSessionLease(this.config.state_home, this.store.path, current);
      requireThat(current.store_id === manifest.native_store_id, "reconciliation_store_changed");
      assertWorkspaceManifest(manifest, true, Boolean(write));
      const verified = this.store.verifyTurn(observation.native_session_id, manifest.baseline, input, observation.text);
      requireThat(verified.reference.directory === manifest.directory.path && verified.reference.model === binding.model
        && this.store.worktree(verified.reference) === manifest.worktree.path, "native_result_binding_mismatch");
      if (write) {
        this.stage = openWorkspace(manifest, this.config.state_home, admission.workspace_write!, task.tool_grant);
        this.proposal = observation.workspace_write as NativeWriteReceipt;
        verifyWorkspaceTools(manifest, this.stage, verified, this.proposal);
      } else {
        const reads = verified.read_files.map(file => realpathSync(file));
        requireThat(required.every(file => reads.includes(file)) && reads.every(file => files.includes(file)), "required_native_read_unproven");
      }
      requireThat(manifest.communication || verified.agent_tools.length === 0, "native_agent_scope_unavailable");
      const communication = manifest.communication ? verifyCommunication!(manifest.communication, verified.agent_tools) : undefined;
      this.assertCurrent(); this.lock.assertCurrent();
      assertWorkspaceManifest(manifest, true, Boolean(write));
      this.store.validate(verified.reference);
      this.recheck = () => {
        authorize(); this.lock!.assertCurrent(); assertWorkspaceManifest(manifest, true, Boolean(write)); this.store.validate(verified.reference);
        if (write) {
          requireThat(runner?.runtimeDigest?.() === binding.runtime_digest, "native_write_owner_required");
          openWorkspace(manifest, this.config.state_home, admission.workspace_write!, task.tool_grant);
          this.stage!.assertProposal(this.proposal!.proposal_digest);
        }
        if (communicationIdentity) requireThat(this.config.communication && assertNativeAgentConfiguration(this.config.communication) === communicationIdentity, "native_agent_profile_changed");
      };
      this.result = { native_session: verified.reference, user_message_id: verified.user_message_id, assistant_message_ids: verified.assistant_message_ids,
        text: observation.text, output_digest: digest(observation.text), permission_digest: saved.digest, read_files: verified.read_files,
        ...(communication ? { communication } : {}),
        ...(this.proposal ? { workspace_write: this.proposal } : {}),
        ...(manifest.mailbox_delivery ? { mailbox_delivery: nativeMailboxEvidence(manifest.mailbox_delivery, verified.user_message_id) } : {}) };
    } catch (error) { this.close(); throw error; }
  }
  assertCurrent = (): void => { requireThat(!this.closed, "native_verification_closed"); this.recheck(); };
  publish(authority: WorkspaceAuthority): void {
    this.assertCurrent(); requireThat(this.stage && this.proposal, "native_write_manifest_required");
    this.stage.promote(authority, this.proposal.proposal_digest); this.assertPublished();
  }
  assertPublished = (): void => {
    this.assertCurrent(); requireThat(this.stage && this.proposal, "native_write_manifest_required");
    this.stage.assertApplied(this.proposal.proposal_digest);
  };
  close(): void { this.closed = true; this.lock?.close(); }
}
