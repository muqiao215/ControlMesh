import { deviceCompletionProof } from "../task-completion";
import { mkdirSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { assertProtocolSchema, type DeviceEvidenceRef, type DeviceNativeResult, type DeviceReconciliationChallenge, type DeviceReconciliationReport } from "@controlmesh/protocol";
import type { Principal } from "../kernel";
import type { DeviceJob } from "../device-coordinator";
import type { DeviceAdapter, DeviceAdapterContext } from "../device-worker";
import { DeviceExecutionJournal } from "../device-journal";
import { digest, object, requireThat, type LegacyTask } from "../value";
import { WorkspaceStage } from "../workspace-stage";
import type { SpecMeshPort, SpecMeshObservation } from "../specmesh-port";
import { PreflightCache } from "./preflight-cache";
import { ProviderPreflightService, ProviderPreparationWait } from "./preflight-service";
import { ClaudePreflight } from "./claude-preflight";
import { ClaudeContainerControlRunner, ClaudeContainerProbeRunner } from "./claude-container";
import { assertClaudeTaskConfiguration, claudeContainerProfile, claudeProbeBinding, claudeTaskScope, findClaudeSession, validateClaudeTaskSession, type ClaudeTaskConfiguration } from "./claude-task-profile";
import { ClaudeTaskEvidence, claudeTaskPrompt, decodeClaudeDispatch, retainClaudeOutcome, type ClaudeDispatch } from "./claude-task-evidence";
import { observeClaudeControl, type ClaudeControlInput } from "./claude-control";
import { directoryIdentity, nativeTaskDigest } from "./native-manifest";
import { NativeSessionLease } from "./native-lease";
import type { ClaudeSessionRef } from "./claude-session";
import { NativeAgentChannel } from "./native-agent-broker";
import { prepareNativeAgentConfiguration } from "./native-agent-profile";
import { NativeWorkspaceFiles } from "./native-workspace-files";
import { nativeInput } from "./native-mailbox-input";
import { nativeAgentProof } from "./native-agent-proof";
import { deviceWorkspaceProof } from "./device-workspace-proof";
import type { DeviceNativeAdoptions } from "./device-native-adoption";

export interface ClaudeDeviceOptions {
  assertCurrent(): void;
  specmesh?: SpecMeshPort;
  adoptions?: DeviceNativeAdoptions<"claude">;
}

/** Provider state stays on the worker; the existing device journal and remote lease own dispatch. */
export class ClaudeDeviceAdapter implements DeviceAdapter {
  readonly dispatch_mode = "prepared" as const;
  private readonly probe: ClaudeContainerProbeRunner;
  constructor(private readonly actor: Principal, private readonly cache: PreflightCache, private readonly journal: DeviceExecutionJournal,
    private readonly config: ClaudeTaskConfiguration, private readonly options: ClaudeDeviceOptions) {
    requireThat(actor.origin === "agent_message" && actor.device_id === journal.deviceId && config.container, "claude_device_container_required");
    assertClaudeTaskConfiguration(config);
    requireThat((config.workflow_binding ?? null) === (config.write_roots.length ? options.specmesh?.binding_digest ?? null : null), "claude_workflow_binding_changed");
    this.probe = new ClaudeContainerProbeRunner(claudeContainerProfile(config));
  }
  private current(): void {
    const checked: unknown = this.options.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    this.options.specmesh?.assertCurrent();
  }
  readiness(): Record<string, unknown> {
    this.current(); const binding = claudeProbeBinding(this.config, this.journal.deviceId), value = this.cache.inspect(this.actor, binding);
    return { provider: binding.provider, model: binding.model, generation: value.generation ?? null,
      decision: value.decision, reason: value.reason, retry_after: value.retry_after };
  }
  retryReadiness(requestId: string, expectedGeneration: number): Record<string, unknown> {
    this.readiness(); this.cache.retry({ ...this.actor, origin: "internal", scopes: [...this.actor.scopes, "provider:retry"] }, requestId,
      claudeProbeBinding(this.config, this.journal.deviceId), expectedGeneration); return this.readiness();
  }
  private prepare(job: DeviceJob, workspace: string, afterWrites = false) {
    this.current();
    requireThat(object(job.execution) && digest(job.execution) === job.execution_digest && job.execution.provider === "claude"
      && job.execution.model === this.config.model && workspace === this.config.workspace, "claude_device_execution_changed");
    requireThat(typeof job.execution.prompt === "string" && job.execution.prompt.length > 0 && Buffer.byteLength(job.execution.prompt) <= 32768, "invalid_native_task");
    requireThat(this.config.communication || (!(job.peer_tasks?.length) && !job.parent_task), "native_communication_not_configured");
    if (this.config.communication) requireThat(digest(this.config.communication.peer_tasks) === digest(job.peer_tasks ?? [])
      && this.config.communication.parent_task === (job.parent_task ?? null), "native_agent_assignment_changed");
    let native: unknown = null;
    if (job.execution.native_session) {
      const value = job.execution.native_session;
      if (object(value) && value.schema_version === "controlmesh.device_native_adoption.v1") {
        requireThat(this.options.adoptions, "native_adoption_unavailable"); native = this.options.adoptions.resolve(value, job);
      } else native = this.journal.resolveNativeSession(value, job);
      if (!afterWrites) validateClaudeTaskSession(this.config, this.journal.deviceId, native as ClaudeSessionRef).baseline(native as ClaudeSessionRef);
    }
    const task: LegacyTask = { ...job.execution, task_id: job.task_id, chat_id: "device-execution", status: "waiting", repo_root: workspace, native_session: native };
    const scope = claudeTaskScope(this.config, task, afterWrites, this.probe), binding = claudeProbeBinding(this.config, this.journal.deviceId);
    return { task, scope, binding, registration: digest(this.config) };
  }
  private async workflow(required: readonly string[], current: () => void, signal?: AbortSignal, remainingMs?: () => number): Promise<SpecMeshObservation | undefined> {
    if (!this.options.specmesh) return undefined;
    const observation = await this.options.specmesh.inspect("check", { assertCurrent: current, signal, remainingMs });
    requireThat(observation.result.status === "pass" && observation.result.references.every(item => required.includes(join(this.config.workspace, item.path))), "specmesh_device_gate_blocked");
    current(); observation.assertCurrent(); return observation;
  }
  private networkResult(result: Record<string, unknown>, evidence: DeviceEvidenceRef, task: LegacyTask): DeviceNativeResult {
    requireThat(typeof result.text === "string" && Buffer.byteLength(result.text) <= 65536 && Array.isArray(result.read_files), "native_device_result_too_large");
    const workspace = deviceWorkspaceProof(evidence.workspace_write, result);
    const completion = deviceCompletionProof(task.completion_requirements, result.completion);
    const value = { schema_version: "controlmesh.device_native_result.v1", text: result.text, output_digest: result.output_digest, read_count: result.read_files.length, evidence,
      ...(completion ? { completion } : {}), ...(workspace ? { workspace_write: workspace } : {}), ...(result.communication ? { communication: result.communication } : {}),
      ...(result.mailbox_delivery ? { mailbox_delivery: result.mailbox_delivery } : {}),
      native_session: { schema_version: "controlmesh.device_native_session.v1", device_id: this.journal.deviceId, evidence } };
    assertProtocolSchema<DeviceNativeResult>("device-native-result.schema.json", value); return value;
  }
  private evidence(task: LegacyTask, manifest: ClaudeDispatch, observation: Record<string, unknown>, current: () => void, effectId: string) {
    requireThat(observation.schema_version === "controlmesh.claude_device_observation.v1" && typeof observation.terminal === "boolean"
      && object(observation.native), "invalid_claude_device_observation");
    return new ClaudeTaskEvidence(this.config, this.journal.deviceId, task, manifest, observation.native, current,
      (_scope, tools) => nativeAgentProof(effectId, tools), this.probe);
  }

  async execute(context: DeviceAdapterContext): Promise<{ observation: Record<string, unknown>; result: Record<string, unknown> }> {
    const { task, scope, binding, registration } = this.prepare(context.job, context.workspace);
    let publishing = false, dispatched = false, workflow: SpecMeshObservation | undefined;
    const current = () => {
      context.assertCurrent(); this.current();
      requireThat(digest(this.config) === registration && digest(claudeProbeBinding(this.config, this.journal.deviceId)) === digest(binding), "claude_device_registration_changed");
      requireThat(digest(claudeTaskScope(this.config, task, publishing, this.probe)) === digest(scope), "claude_task_grant_changed");
      if (!publishing) workflow?.assertCurrent();
    };
    current(); workflow = await this.workflow(scope.required, current, context.authority.signal, context.authority.remainingMs);
    const delivery = await context.mailboxInput();
    const reference = task.native_session as ClaudeSessionRef | null;
    if (reference) validateClaudeTaskSession(this.config, this.journal.deviceId, reference).baseline(reference);
    const profile = claudeContainerProfile(this.config); mkdirSync(profile.container.state_root, { recursive: true, mode: 0o700 });
    const ready = await new ProviderPreflightService(this.cache, undefined, new ClaudePreflight(this.probe)).ensureClaude(this.actor,
      `claude-device-probe-${digest([context.authority.lease.episode_id, binding])}`, binding,
      { executable: this.config.executable, model: this.config.model, native_configuration: {}, environment: this.config.environment.credentials,
        assertCurrent: current, signal: context.authority.signal, remainingMs: context.authority.remainingMs });
    if (ready.decision !== "cached") throw new ProviderPreparationWait(ready);
    const generation = this.cache.inspect(this.actor, binding).generation!, sessionId = reference?.session_id ?? randomUUID();
    const lock = new NativeSessionLease(this.config.state_home, this.config.environment.config_directory, { session_id: sessionId });
    const authorized = () => { current(); lock.assertCurrent(); }, authority = <T>(run: () => T): T => this.journal.db.transaction(() => { authorized(); return run(); });
    let channel: NativeAgentChannel | undefined, messages: NativeAgentChannel | undefined;
    try {
      const store = reference ? validateClaudeTaskSession(this.config, this.journal.deviceId, reference) : findClaudeSession(this.config, this.journal.deviceId, sessionId);
      requireThat(reference || !store, "claude_native_session_already_exists");
      const runs = join(this.config.state_home, "claude-runs"); mkdirSync(runs, { recursive: true, mode: 0o700 });
      const directory = join(runs, digest(context.authority.lease.episode_id)); mkdirSync(directory, { mode: 0o700 });
      const receipts = join(directory, "receipts"), assets = join(directory, "assets"); mkdirSync(receipts, { mode: 0o700 }); mkdirSync(assets, { mode: 0o700 });
      const grant = digest({ lease: context.authority.lease, task: nativeTaskDigest(task), registration, assignment: context.job.assignment_digest });
      const stage = scope.roots.length ? WorkspaceStage.create(directory, this.config.workspace, scope.roots, grant, authority) : undefined;
      const files = new NativeWorkspaceFiles({ workspace: this.config.workspace, read_files: scope.reads, tools: scope.tools, journal_directory: receipts, binding_digest: grant, ...(stage ? { stage } : {}) }, authority, authorized);
      const fileProfile = prepareNativeAgentConfiguration(join(directory, "ipc"), this.config.node_executable, task.task_id, [], null, "workspace.v1");
      const assertDispatched = () => { authorized(); requireThat(dispatched, "device_native_channel_unavailable"); };
      channel = new NativeAgentChannel(context.authority.lease, fileProfile, authorized, { assertDispatched, call: async (tool, input) => files.call(tool, input) });
      const messageProfile = scope.communication ? prepareNativeAgentConfiguration(join(directory, "message-ipc"), this.config.node_executable,
        task.task_id, scope.communication.peer_tasks, scope.communication.parent_task) : undefined;
      if (messageProfile) messages = new NativeAgentChannel(context.authority.lease, messageProfile, authorized, { assertDispatched, call: context.nativeCall });
      await channel.start(); await messages?.start();
      const runner = await ClaudeContainerControlRunner.create({ ...profile, workspace: this.config.workspace, bun_executable: realpathSync(process.execPath),
        asset_directory: assets, environment: this.config.environment, workspace_channel: fileProfile, ...(messageProfile ? { communication_channel: messageProfile } : {}) });
      const input: ClaudeControlInput = { schema_version: "controlmesh.claude_control.v1", executable: this.config.executable, workspace: this.config.workspace, model: this.config.model,
        session_id: sessionId, resume: !!reference, max_turns: this.config.max_turns ?? 128, prompt: nativeInput(claudeTaskPrompt(task, scope), delivery),
        workspace_command: channel.command, ...(messages ? { communication_command: messages.command } : {}) };
      const manifest: ClaudeDispatch = { schema_version: "controlmesh.claude_dispatch.v1", task_digest: nativeTaskDigest(task), configuration_digest: registration, binding, input,
        native_directory: directoryIdentity(this.config.environment.config_directory), native_path: store?.path ?? null, baseline: reference ? store!.baseline(reference) : null,
        execution_directory: directoryIdentity(directory), scope, workspace_tools: files.scope, stage: stage ? { path: stage.path, reference: stage.reference() } : null,
        container: runner.execution(), workflow_binding: this.config.workflow_binding ?? null,
        ...(delivery ? { mailbox_delivery: delivery } : {}), ...(messages ? { communication: messages.scope } : {}) };
      authorized(); if (reference) store!.validate(reference); this.cache.assertReady(this.actor, binding);
      const dispatchedRef = await context.dispatch(manifest, { provider: "claude", model: binding.model, session_id: sessionId, prompt_digest: digest(input.prompt), resumed: !!reference });
      dispatched = true;
      const retained = decodeClaudeDispatch(JSON.parse(this.journal.inspect(dispatchedRef).manifest));
      const outcome = await runner.run(input, this.config.environment, { assertCurrent: authorized, signal: context.authority.signal, remainingMs: context.authority.remainingMs }, this.config.timeout_ms ?? 60000);
      await channel.close(); await messages?.close();
      const native = retainClaudeOutcome(retained, outcome), observed = observeClaudeControl(outcome, input);
      const observation = { schema_version: "controlmesh.claude_device_observation.v1", terminal: observed.terminal, native };
      if (observed.failure) this.cache.recordExecutionFailure(this.actor, binding, generation, observed.failure);
      await context.observe(observation);
      const evidence = this.evidence(task, retained, observation, authorized, context.effect_id); evidence.verify();
      if (stage) { await context.preparePublication(); publishing = true; evidence.publish(authority); }
      workflow = await this.workflow(scope.required, () => { authorized(); evidence.assertPublished(); }, context.authority.signal, context.authority.remainingMs);
      const result = { ...evidence.verify(), ...(workflow ? { specmesh: { snapshot_digest: workflow.snapshot_digest, status: "pass", closeout_verified: false } } : {}) };
      authorized(); evidence.assertPublished();
      return { observation, result: { ...this.networkResult(result, context.retainVerifiedResult(result), task) } };
    } finally { await Promise.allSettled([channel?.close(), messages?.close()]); lock.close(); }
  }

  async reconcile(challenge: DeviceReconciliationChallenge, workspace: string, assertCurrent: () => void,
    report: (value: DeviceReconciliationReport) => Promise<unknown>, preparePublication?: () => Promise<void>): Promise<unknown> {
    assertProtocolSchema("device-reconciliation-challenge.schema.json", challenge);
    const saved = this.journal.inspect(challenge.manifest), job = JSON.parse(saved.job) as DeviceJob;
    requireThat(saved.observation && saved.observation_digest && job.execution_digest === challenge.execution_digest
      && job.workspace_id === challenge.workspace_id && job.capability === challenge.capability, "claude_device_reconciliation_changed");
    const { task, scope, binding, registration } = this.prepare(job, workspace, true), manifest = decodeClaudeDispatch(JSON.parse(saved.manifest));
    const lock = new NativeSessionLease(this.config.state_home, this.config.environment.config_directory, { session_id: manifest.input.session_id });
    const current = () => { assertCurrent(); this.current(); lock.assertCurrent();
      requireThat(digest(this.config) === registration && digest(claudeProbeBinding(this.config, this.journal.deviceId)) === digest(binding)
        && this.journal.inspect(challenge.manifest).observation_digest === saved.observation_digest, "claude_device_reconciliation_changed"); };
    try {
      const evidence = this.evidence(task, manifest, JSON.parse(saved.observation), current, saved.effect_id); evidence.verify();
      if (manifest.stage) {
        requireThat(preparePublication, "device_publication_authority_required"); await preparePublication(); current();
        evidence.publish(run => this.journal.db.transaction(() => { current(); return run(); }));
      }
      const workflow = await this.workflow(scope.required, () => { current(); evidence.assertPublished(); });
      const result = { ...evidence.verify(), ...(workflow ? { specmesh: { snapshot_digest: workflow.snapshot_digest, status: "pass", closeout_verified: false } } : {}) };
      current(); evidence.assertPublished();
      const reference = this.journal.retainReconciledResult(challenge.manifest, result), { result_digest: _result, ...observationRef } = reference;
      const response: DeviceReconciliationReport = { schema_version: "controlmesh.device_reconciliation_report.v1", challenge_id: challenge.challenge_id,
        challenge_digest: digest(challenge), observation: { schema_version: "controlmesh.device_observation.v1", evidence: observationRef, terminal: true }, result: this.networkResult(result, reference, task) };
      current(); return await report(response);
    } finally { lock.close(); }
  }
}
