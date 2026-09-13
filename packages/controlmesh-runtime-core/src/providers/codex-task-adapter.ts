import { contains } from "../containers/plan";
import { writeRoots } from "./native-workspace";
import { nativeWorkspaceTools } from "./native-workspace-files";
import { decodeTaskCompletion } from "../task-completion";
import { createCodexWorkspace, verifyCodexWorkspace, codexWorkspaceBinding, type CodexWorkspaceConfiguration } from "./codex-workspace";
import { NativeAgentBroker } from "./native-agent-broker";
import { NativeAgentJournal, type NativeAgentScope } from "./native-agent-journal";
import { codexCommunicationTools, codexWorkspaceTools } from "./codex-communication";
import { assertNativeAgentConfiguration, type NativeAgentConfiguration } from "./native-agent-profile";
import { NativeSessionLease } from "./native-lease";
import { NativeMailboxDelivery } from "./native-mailbox";
import { nativeInput, nativeMailboxEvidence, type NativeMailboxBatch } from "./native-mailbox-input";
import { closeSync, constants, fsyncSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";
import type { Principal, RuntimeKernel, TaskSnapshot, Lease, ReconciliationBinding } from "../kernel";
import type { LocalTaskExecution, LocalExecutionContext } from "../local-task-runtime";
import type { ProcessOutcome } from "../process-supervisor";
import { privateFile } from "../private-runtime-file";
import { WorkspaceStage } from "../workspace-stage";
import { digest, canonical, object, requireThat } from "../value";
import { directoryIdentity, nativeTaskDigest, type DirectoryIdentity } from "./native-manifest";
import { CodexSessionStore, type CodexSessionRef } from "./codex-session";
import { CodexResumeProcess, verifyRetainedCodexResume, type CodexResumeInput, type CodexResumeDispatch } from "./codex-resume-process";
import type { ProbeDecision } from "./preflight-cache";

export type CodexTaskConfiguration = Omit<CodexResumeInput, "reference" | "prompt" | "execution_context" | "tool_grant" | "communication_command" | "workspace_command" | "workspace_tool_names"> & { communication?: NativeAgentConfiguration; workspace_files?: CodexWorkspaceConfiguration };
export interface CodexTaskReadiness {
  ensure(request: string, context: LocalExecutionContext): Promise<ProbeDecision>;
  assertReady(): void;
  captureOutcome?(): (outcome: ProcessOutcome) => void;
}
interface CodexTaskManifest extends Record<string, unknown> {
  schema_version: "controlmesh.codex_dispatch.v1";
  task_digest: string; configuration_digest: string;
  dispatch: CodexResumeDispatch;
  execution_directory: DirectoryIdentity;
  mailbox_delivery?: NativeMailboxBatch;
  communication?: NativeAgentScope;
  communication_command?: readonly string[];
  workspace_command?: readonly string[];
  workspace_tools?: Record<string, unknown>;
  workspace_binding?: string;
  workspace_stage?: { path: string; reference: ReturnType<WorkspaceStage["reference"]> };
}

/** Queue integration for an explicitly adopted session. Readiness remains a registered provider owner. */
export class CodexTaskAdapter {
  constructor(private readonly kernel: RuntimeKernel, private readonly actor: Principal, private readonly config: CodexTaskConfiguration,
    private readonly readiness: CodexTaskReadiness, private readonly authorize: () => void,
    private readonly process = new CodexResumeProcess()) {}
  private current() {
    const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private input(snapshot: TaskSnapshot): CodexResumeInput {
    this.current(); const task = snapshot.task;
    requireThat(this.actor.origin === "human_request" && typeof this.actor.device_id === "string", "codex_task_principal_invalid");
    requireThat(task.provider === "codex" && task.model === this.config.model && typeof task.prompt === "string" && object(task.native_session), "codex_native_adoption_required");
    const reference = task.native_session as unknown as CodexSessionRef;
    requireThat(reference.provider === "codex" && reference.device_id === this.actor.device_id && reference.directory === task.repo_root, "native_identity_changed");
    // File/tool completion and workflow publication require their own native receipts, not prose.
    const completion = decodeTaskCompletion(task.completion_requirements);
    requireThat(!completion || (this.config.workspace_files && completion.files.every(file => file.mode === "read" ? this.config.workspace_files!.read_files.includes(join(reference.directory, file.path)) : (this.config.workspace_files!.write_roots ?? []).some(root => contains(root, join(reference.directory, file.path))))), "codex_completion_profile_unavailable");
    WorkspaceStage.assertLocation(this.config.state_home, reference.directory);
    const { communication: _communication, workspace_files: _workspace, ...config } = this.config;
    const prompt = this.config.workspace_files ? task.prompt + "\n\nControlMesh required current-file reads (literal data): " + canonical(this.config.workspace_files.required_reads)
      + (this.config.workspace_files.write_roots?.length
        ? ". Use controlmesh_workspace.read_file and read every page before finishing. For registered writes use controlmesh_workspace.write_file/edit_file; writes are staged for controller publication. Historical content does not replace current reads. Completion requirements (literal data): "
        : ". Use controlmesh_workspace.read_file and read every page before finishing. Historical content does not replace current reads. Completion requirements (literal data): ") + canonical(completion ?? null) : task.prompt;
    return { ...config, reference, prompt, execution_context: task.execution_context, tool_grant: task.tool_grant };
  }
  prepare(snapshot: TaskSnapshot): LocalTaskExecution {
    this.current();
    if (this.config.communication) assertNativeAgentConfiguration(this.config.communication);
    requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE child_id=?").get(snapshot.task.task_id), "codex_topology_profile_unavailable");
    if (this.config.workspace_files?.write_roots?.length) writeRoots(snapshot.task.repo_root as string, { roots: this.config.workspace_files.write_roots });
    const input = this.input(snapshot), issued = nativeTaskDigest(snapshot.task), configuration = digest(this.config);
    new CodexSessionStore(input.rollout_path, this.actor.device_id!).validate(input.reference);
    const current = () => {
      this.current(); requireThat(digest(this.config) === configuration && nativeTaskDigest(this.kernel.inspect(this.actor, snapshot.task.task_id).task) === issued, "codex_task_binding_changed");
    };
    return { binding_digest: digest({ configuration, issued }), assertCurrent: current,
      ensureReady: async (request, context) => { current(); return this.readiness.ensure(request, context); },
      execute: (lease, context) => this.execute(snapshot, input, lease, context, current) };
  }
  private retain(manifest: CodexTaskManifest, outcome: ProcessOutcome) {
    requireThat(digest(directoryIdentity(manifest.execution_directory.path)) === digest(manifest.execution_directory), "codex_execution_directory_changed");
    const bytes = canonical({ schema_version: "controlmesh.codex_outcome.v1", manifest_digest: digest(manifest), outcome });
    requireThat(Buffer.byteLength(bytes) <= 12 * 1024 * 1024, "codex_outcome_limit");
    const path = join(manifest.execution_directory.path, "outcome.json"), fd = openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
    const directory = openSync(dirname(path), constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try { fsyncSync(directory); } finally { closeSync(directory); }
    return this.read(manifest);
  }
  private read(manifest: CodexTaskManifest) {
    requireThat(dirname(manifest.execution_directory.path) === this.config.state_home
      && digest(directoryIdentity(manifest.execution_directory.path)) === digest(manifest.execution_directory), "codex_execution_directory_changed");
    const file = privateFile(join(manifest.execution_directory.path, "outcome.json"), 12 * 1024 * 1024), value: unknown = JSON.parse(file.bytes.toString());
    requireThat(object(value) && value.schema_version === "controlmesh.codex_outcome.v1" && value.manifest_digest === digest(manifest) && object(value.outcome), "codex_outcome_binding_changed");
    return { outcome: value.outcome as unknown as ProcessOutcome, observation: { schema_version: "controlmesh.codex_observation.v1", record_revision: file.revision, process_digest: digest(value.outcome) } };
  }
  private stage(manifest: CodexTaskManifest, workspace: string): WorkspaceStage | undefined {
    const roots = this.config.workspace_files?.write_roots ?? [];
    requireThat(Boolean(manifest.workspace_stage) === (roots.length > 0), "codex_workspace_stage_changed");
    if (!manifest.workspace_stage) return undefined;
    requireThat(dirname(manifest.workspace_stage.path) === this.config.state_home, "codex_workspace_stage_changed");
    const stage = WorkspaceStage.open(manifest.workspace_stage.path, manifest.workspace_stage.reference);
    requireThat(manifest.workspace_stage.reference.binding_digest === manifest.workspace_binding
      && stage.fileScope().workspace === workspace
      && digest(stage.fileScope().roots) === digest(writeRoots(workspace, { roots })), "codex_workspace_stage_changed");
    return stage;
  }
  private result(input: CodexResumeInput, manifest: CodexTaskManifest, outcome: ProcessOutcome, current: () => void, completion?: unknown) {
    const verified = verifyRetainedCodexResume(input, manifest.dispatch, outcome, current);
    const communicationTools = codexCommunicationTools(outcome.stdout);
    requireThat(Boolean(manifest.communication) === Boolean(this.config.communication), "codex_communication_binding_changed");
    if (manifest.communication) new NativeAgentJournal(this.kernel).verify(`codex-${manifest.communication.episode_id}`, manifest.communication, communicationTools);
    else requireThat(communicationTools.length === 0, "codex_communication_binding_changed");
    if (!manifest.workspace_tools) requireThat(codexWorkspaceTools(outcome.stdout).length === 0, "codex_workspace_binding_changed");
    requireThat(Boolean(manifest.workspace_tools) === Boolean(this.config.workspace_files), "codex_workspace_binding_changed");
    const workspace = manifest.workspace_tools && this.config.workspace_files
      ? verifyCodexWorkspace(this.config.workspace_files, input.reference.directory, manifest.workspace_tools, manifest.workspace_binding!, outcome.stdout, current,
        completion, this.stage(manifest, input.reference.directory)) : undefined;
    const batch = manifest.mailbox_delivery;
    if (batch) requireThat(typeof verified.evidence.user_message_id === "string", "native_mailbox_delivery_unproven");
    return { ...workspace, ...(batch ? { user_message_id: verified.evidence.user_message_id!, mailbox_delivery: nativeMailboxEvidence(batch, verified.evidence.user_message_id!) } : {}), text: verified.observation.text, output_digest: digest(verified.observation.text), native_session: verified.evidence.reference,
      native_turn: verified.evidence.turn_id };
  }
  private async execute(snapshot: TaskSnapshot, input: CodexResumeInput, lease: Lease, context: LocalExecutionContext, configured: () => void) {
    const effect = `codex-${lease.episode_id}`, request = (op: string) => `${effect}-${op}`;
    let manifest: CodexTaskManifest | undefined, observation: Record<string, unknown> | undefined;
    const current = () => { configured(); context.assertCurrent(); this.kernel.withLease(this.actor, lease, () => {}); };
    const mailbox = new NativeMailboxDelivery(this.kernel);
    let communication: NativeAgentBroker | undefined;
    let workspace: ReturnType<typeof createCodexWorkspace> | undefined;
    let stage: WorkspaceStage | undefined;
    let publicationLock: NativeSessionLease | undefined;
    const authority = <T>(operation: () => T): T => this.kernel.withLease(this.actor, lease, () => { current(); publicationLock?.assertCurrent(); return operation(); });
    try {
      current();
      const delivery = mailbox.pendingCount(this.actor, lease.task_id) > 0 ? mailbox.prepare(this.actor, lease, input.prompt, 32768) : undefined;
      input = { ...input, prompt: nativeInput(input.prompt, delivery) };
      if (this.config.communication) {
        communication = new NativeAgentBroker(this.kernel, this.actor, lease, effect, this.config.communication, current);
        await communication.start();
        input = { ...input, communication_command: communication.command };
      }
      const path = join(this.config.state_home, `codex-resume-${randomUUID()}`); mkdirSync(path, { mode: 0o700 });
      const workspaceBinding = codexWorkspaceBinding(digest(this.config), nativeTaskDigest(snapshot.task), lease.episode_id);
      if (this.config.workspace_files) {
        if (this.config.workspace_files.write_roots?.length) stage = WorkspaceStage.create(this.config.state_home, input.reference.directory, this.config.workspace_files.write_roots, workspaceBinding, authority);
        workspace = createCodexWorkspace(this.config.workspace_files, input.reference.directory, path, workspaceBinding, lease, current, () => {
          current(); const row = this.kernel.db.sql.query("SELECT e.state,m.digest FROM effects e JOIN execution_manifests m ON e.effect_id=m.effect_id WHERE e.effect_id=? AND e.episode_id=? AND e.fence=?").get(effect, lease.episode_id, lease.fence) as { state: string; digest: string } | null;
          requireThat(manifest && row?.state === "dispatched" && row.digest === digest(manifest), "codex_workspace_dispatch_unavailable");
        }, stage, authority);
        await workspace.channel.start(); input = { ...input, workspace_command: workspace.channel.command, ...(stage ? { workspace_tool_names: workspace.tools } : {}) };
      }
      const observeReadiness = this.readiness.captureOutcome?.();
      await this.process.run(input, { signal: context.signal, remainingMs: context.remainingMs, assertCurrent: current,
        assertReady: () => this.readiness.assertReady(),
        retainDispatch: dispatch => {
          current();
          const issued: CodexTaskManifest = { schema_version: "controlmesh.codex_dispatch.v1", configuration_digest: digest(this.config),
            task_digest: nativeTaskDigest(snapshot.task), dispatch, ...(delivery ? { mailbox_delivery: delivery } : {}), ...(communication ? { communication: communication.scope, communication_command: communication.command } : {}), execution_directory: directoryIdentity(path), ...(workspace ? { workspace_tools: workspace.scope, workspace_command: workspace.channel.command, workspace_binding: workspaceBinding, ...(stage ? { workspace_stage: { path: stage.path, reference: stage.reference() } } : {}) } : {}) };
          this.kernel.db.transaction(() => {
            current(); this.kernel.start(this.actor, request("start"), lease);
            const permit = this.kernel.dispatchEffect(this.actor, request("dispatch"), lease, effect,
              { provider: "codex", model: input.model, session_id: input.reference.session_id, prompt_digest: digest(input.prompt) }, issued);
            requireThat(permit.dispatch_permitted, "native_request_already_dispatched");
            if (delivery) mailbox.reserve(this.actor, lease, effect, delivery);
          }); manifest = issued;
        },
        retainOutcome: outcome => { requireThat(manifest, "codex_dispatch_missing"); observation = this.retain(manifest, outcome).observation; observeReadiness?.(outcome); },
      });
      await workspace?.channel.close(); await communication?.close();
      requireThat(manifest && observation, "codex_outcome_missing");
      if (stage) publicationLock = new NativeSessionLease(this.config.state_home, this.config.rollout_path, input.reference);
      current(); const retained = this.read(manifest!);
      requireThat(digest(retained.observation) === digest(observation), "codex_outcome_binding_changed");
      this.result(input, manifest!, retained.outcome, current, snapshot.task.completion_requirements);
      if (stage) stage.seal(authority);
      this.kernel.recordEffectObservation(this.actor, request("observe"), lease, effect, observation!);
      const proposal = stage?.proposalReceipt();
      if (stage && proposal) stage.promote(authority, proposal.proposal_digest);
      return this.kernel.db.transaction(() => {
        current(); if (stage && proposal) stage.assertApplied(proposal.proposal_digest);
        const result = { ...this.result(input, manifest!, retained.outcome, current, snapshot.task.completion_requirements), ...(proposal ? { workspace_write: proposal } : {}) };
        if (delivery) mailbox.consume(this.actor, lease, effect, delivery, result);
        if (manifest!.communication) new NativeAgentJournal(this.kernel).consume(this.actor, lease, effect, manifest!.communication, codexCommunicationTools(retained.outcome.stdout));
        this.kernel.confirmEffect(this.actor, request("confirm"), lease, effect, result);
        return this.kernel.finish(this.actor, request("finish"), lease, "done", result);
      });
    } catch (error) {
      if (manifest) { try { this.kernel.markUnknown(this.actor, request("unknown"), lease, "codex_outcome_unproven"); } catch { /* Preserve current cancellation/ownership. */ } }
      throw error;
    } finally { publicationLock?.close(); await workspace?.channel.close(); await communication?.close(); }
  }
  private target(taskId: string, revision: number, effect: string) {
    this.current(); const target = this.kernel.inspectReconciliationTarget(this.actor, taskId, revision, effect), raw = target.manifest;
    requireThat(object(raw) && raw.schema_version === "controlmesh.codex_dispatch.v1" && object(raw.dispatch) && object(raw.execution_directory)
      && raw.configuration_digest === digest(this.config) && raw.task_digest === nativeTaskDigest(target.task.task), "codex_dispatch_changed");
    const manifest = raw as CodexTaskManifest, retained = this.read(manifest), base = this.input(target.task);
    const input = { ...base, prompt: nativeInput(base.prompt, manifest.mailbox_delivery), ...(manifest.communication_command ? { communication_command: manifest.communication_command } : {}), ...(manifest.workspace_command ? { workspace_command: manifest.workspace_command, ...(manifest.workspace_stage ? { workspace_tool_names: nativeWorkspaceTools } : {}) } : {}) };
    requireThat(!target.observation || digest(target.observation) === digest(retained.observation), "codex_outcome_binding_changed");
    return { target, manifest, retained, input };
  }
  inspectRecovery(taskId: string, revision: number, effect: string): ReconciliationBinding {
    const value = this.target(taskId, revision, effect);
    return { episode_id: value.target.episode.episode_id, effect_id: effect, manifest_digest: value.target.manifest_digest, observation_digest: digest(value.retained.observation) };
  }
  recover(request: string, taskId: string, revision: number, binding: ReconciliationBinding) {
    this.current(); const prior = this.kernel.reconciliationReceipt(this.actor, request, taskId, revision, binding); if (prior) return prior;
    const current = () => { this.current(); requireThat(digest(this.inspectRecovery(taskId, revision, binding.effect_id)) === digest(binding), "reconciliation_evidence_changed"); };
    current(); const value = this.target(taskId, revision, binding.effect_id);
    const lock = new NativeSessionLease(this.config.state_home, this.config.rollout_path, value.input.reference);
    try {
      const guarded = () => { lock.assertCurrent(); current(); };
      this.kernel.db.transaction(() => {
        guarded(); this.result(value.input, value.manifest, value.retained.outcome, guarded, value.target.task.task.completion_requirements);
        if (!value.target.observation) this.kernel.admitReconciliationObservation(this.actor, taskId, revision,
          { episode_id: binding.episode_id, effect_id: binding.effect_id, manifest_digest: binding.manifest_digest }, value.retained.observation, `codex-recovery-${digest(request)}`);
      });
      const stage = this.stage(value.manifest, value.input.reference.directory);
      if (stage) this.kernel.reserveReconciliation(this.actor, request, taskId, revision, binding);
      return this.kernel.db.transaction(() => {
        guarded();
        let proposal: ReturnType<WorkspaceStage["proposalReceipt"]> | undefined;
        if (stage) {
          const authority = <T>(operation: () => T): T => { guarded(); return operation(); };
          if (stage.publicationState().phase === "prepared") stage.seal(authority);
          proposal = stage.proposalReceipt();
          stage.promote(authority, proposal.proposal_digest);
          stage.assertApplied(proposal.proposal_digest);
        }
        return this.kernel.reconcileEffect(this.actor, request, taskId, revision, binding,
          original => {
            const result = { ...this.result(value.input, value.manifest, value.retained.outcome, guarded, value.target.task.task.completion_requirements), ...(proposal ? { workspace_write: proposal } : {}) };
            if (value.manifest.mailbox_delivery) new NativeMailboxDelivery(this.kernel).reconcile(this.actor, original, value.manifest.mailbox_delivery, result);
            if (value.manifest.communication) new NativeAgentJournal(this.kernel).reconcile(this.actor, original, value.manifest.communication, codexCommunicationTools(value.retained.outcome.stdout));
            return result;
          });
      });
    } finally { lock.close(); }
  }
}
