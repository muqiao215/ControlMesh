import { assertProtocolSchema, type DeviceReconciliationChallenge, type DeviceReconciliationReport, type DeviceEvidenceRef, type DeviceNativeResult } from "@controlmesh/protocol";
import type { DeviceJob } from "../device-coordinator";
import { NativeResultVerification } from "./native-result-verification";
import { isAbsolute, join, resolve } from "node:path";
import type { DeviceAdapter, DeviceAdapterContext } from "../device-worker";
import { DeviceExecutionJournal } from "../device-journal";
import { enforceLocalReadSource, enforceNativeReadSource } from "../execution-policy";
import type { Principal } from "../kernel";
import { digest, object, requireThat, type LegacyTask } from "../value";
import { OpenCodeExecution, type NativeRunner, type OpenCodeWorkerConfig, type IssuedReadAdmission } from "./opencode-execution";
import { assertReadGrantSnapshot, assertWorkspaceGrantSnapshot, readFileGrant } from "./opencode-profile";
import { NativeSessionStore } from "./native-session";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";
import { ProviderPreflightService, ProviderPreparationWait } from "./preflight-service";
import { OpenCodePreflight } from "./opencode-preflight";
import { nativeAgentTools } from "./native-agent-journal";
import { NativeAgentChannel } from "./native-agent-broker";
import { nativeAgentProof } from "./native-agent-proof";
import { assertNativeAgentConfiguration } from "./native-agent-profile";
import { WorkspaceStage } from "../workspace-stage";
import { registeredReads, writeRoots } from "./native-workspace";
import { deviceWorkspaceProof } from "./device-workspace-proof";
import type { SpecMeshPort, SpecMeshObservation } from "../specmesh-port";
import type { DeviceNativeAdoptions } from "./device-native-adoption";
import type { NativeSessionRef } from "./native-session";

export interface OpenCodeDeviceOptions {
  read_files: readonly string[];
  required_reads: readonly string[];
  binding: () => ProbeBinding;
  assertCurrent: () => void;
  timeout_ms?: number;
  write_roots?: readonly string[];
  specmesh?: SpecMeshPort;
  adoptions?: DeviceNativeAdoptions;
}

/** Native credentials, sessions, exact paths and full evidence stay on this executing device. */
export class OpenCodeDeviceAdapter implements DeviceAdapter {
  readonly dispatch_mode = "prepared" as const;
  private readonly execution: OpenCodeExecution;
  constructor(private readonly actor: Principal, private readonly cache: PreflightCache,
    private readonly journal: DeviceExecutionJournal, private readonly store: NativeSessionStore,
    private readonly config: OpenCodeWorkerConfig, private readonly options: OpenCodeDeviceOptions,
    private readonly runner?: NativeRunner, private readonly preflight = new ProviderPreflightService(cache, new OpenCodePreflight(runner))) {
    requireThat(actor.origin === "agent_message" && actor.device_id === store.deviceId && actor.device_id === journal.deviceId, "native_device_identity_mismatch");
    this.execution = new OpenCodeExecution(store, config, runner);
  }

  private registrationDigest(): string {
    return digest({ configuration: Object.fromEntries(Object.entries(this.config).filter(([, value]) => value !== undefined)), read_files: this.options.read_files, required_reads: this.options.required_reads,
      write_roots: this.options.write_roots ?? [], workflow_binding: this.options.specmesh?.binding_digest ?? null });
  }

  readiness(): Record<string, unknown> {
    const checked: unknown = this.options.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    const binding = this.options.binding(), value = this.cache.inspect(this.actor, binding);
    return { provider: binding.provider, model: binding.model, generation: value.generation ?? null,
      decision: value.decision, reason: value.reason, retry_after: value.retry_after };
  }

  retryReadiness(requestId: string, expectedGeneration: number): Record<string, unknown> {
    this.readiness();
    this.cache.retry({ ...this.actor, origin: "internal", scopes: [...this.actor.scopes, "provider:retry"] }, requestId, this.options.binding(), expectedGeneration);
    return this.readiness();
  }

  private async checkWorkflow(workspace: string, required: readonly string[], assertCurrent: () => void,
    signal?: AbortSignal, remainingMs?: () => number): Promise<SpecMeshObservation | undefined> {
    if (!this.options.specmesh) return undefined;
    this.options.specmesh.assertWorkspace(workspace);
    const observation = await this.options.specmesh.inspect("check", { assertCurrent, signal, remainingMs });
    requireThat(observation.result.status === "pass", "specmesh_device_gate_blocked");
    requireThat(observation.result.references.every(item => required.includes(join(workspace, item.path))), "specmesh_context_reads_not_issued");
    assertCurrent(); observation.assertCurrent(); return observation;
  }

  private prepare(job: DeviceJob, workspace: string, afterWrites = false) {
    requireThat(object(job.execution) && digest(job.execution) === job.execution_digest, "device_execution_projection_changed");
    const source = this.runner ? enforceNativeReadSource(job.execution.execution_context, this.runner) : enforceLocalReadSource(job.execution.execution_context);
    requireThat(typeof job.execution.prompt === "string" && job.execution.prompt.length > 0 && Buffer.byteLength(job.execution.prompt) <= 32_768, "invalid_native_task");
    const binding = structuredClone(this.options.binding());
    requireThat(binding.provider === "opencode" && binding.cli_version === "1.18.29" && binding.device_id === this.store.deviceId
      && job.execution.provider === "opencode" && job.execution.model === binding.model && digest(this.config.native_configuration) === binding.config_digest, "native_device_provider_mismatch");
    const paths = (input: readonly string[]) => input.map(path => {
      requireThat(typeof path === "string" && path.length > 0 && !isAbsolute(path) && !path.split("/").includes(".."), "device_read_requires_relative_path");
      return resolve(workspace, path);
    });
    const roots = this.options.write_roots?.length ? writeRoots(workspace, { roots: paths(this.options.write_roots) }) : [];
    const write = roots.length ? { roots, ...(this.options.specmesh ? { workflow_binding: this.options.specmesh.binding_digest } : {}) } : undefined;
    if (write) {
      WorkspaceStage.assertLocation(this.config.state_home, workspace);
      requireThat(this.runner?.forStage && this.runner.runtimeDigest?.() === binding.runtime_digest, "native_write_owner_required");
      assertWorkspaceGrantSnapshot(job.execution.tool_grant, workspace, roots, this.config.communication ? nativeAgentTools : []);
    }
    const files = write ? registeredReads(workspace, paths(this.options.read_files), roots, afterWrites) : readFileGrant(workspace, paths(this.options.read_files));
    const required = write ? registeredReads(workspace, paths(this.options.required_reads), roots, afterWrites) : readFileGrant(workspace, paths(this.options.required_reads));
    requireThat(required.every(file => files.includes(file)), "required_read_not_granted");
    if (this.config.communication) {
      assertNativeAgentConfiguration(this.config.communication);
      requireThat(this.config.communication.task_id === job.task_id && digest(this.config.communication.peer_tasks) === digest(job.peer_tasks ?? [])
        && this.config.communication.parent_task === (job.parent_task ?? null), "native_agent_assignment_changed");
    }
    assertReadGrantSnapshot(job.execution.tool_grant, files, this.config.communication ? nativeAgentTools : []);
    let native: unknown = null;
    if (job.execution.native_session) {
      const input = job.execution.native_session;
      if (object(input) && input.schema_version === "controlmesh.device_native_adoption.v1") {
        requireThat(this.options.adoptions, "native_adoption_unavailable"); native = this.options.adoptions.resolve(input, job);
      } else native = this.journal.resolveNativeSession(input, job);
      if (!afterWrites) {
        const reference = this.store.validate(native as NativeSessionRef);
        requireThat(reference.model === binding.model && reference.directory === workspace, "native_result_binding_mismatch");
        this.store.baseline(reference); // Before model preflight; recovery instead verifies the retained appended turn.
      }
    }
    const task: LegacyTask = { ...job.execution, task_id: job.task_id, chat_id: "device-execution", status: "waiting", repo_root: workspace, native_session: native };
    return { task, source, binding, files, required, write, registration: this.registrationDigest() };
  }

  async reconcile(challenge: DeviceReconciliationChallenge, workspace: string, assertCurrent: () => void,
    report: (value: DeviceReconciliationReport) => Promise<unknown>, preparePublication?: () => Promise<void>): Promise<unknown> {
    assertProtocolSchema("device-reconciliation-challenge.schema.json", challenge);
    const row = this.journal.inspect(challenge.manifest), job = JSON.parse(row.job) as DeviceJob;
    requireThat(row.observation && row.observation_digest, "native_observation_unavailable");
    requireThat(job.execution_digest === challenge.execution_digest && job.workspace_id === challenge.workspace_id
      && job.capability === challenge.capability, "reconciliation_authority_changed");
    const { task, source, binding, files, required, write, registration } = this.prepare(job, workspace, true);
    const current = () => {
      assertCurrent();
      requireThat(this.registrationDigest() === registration, "native_device_registration_changed");
      requireThat(digest(this.options.binding()) === digest(binding), "native_device_binding_changed");
      const value: unknown = this.options.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      this.options.specmesh?.assertCurrent();
      const saved = this.journal.inspect(challenge.manifest);
      requireThat(saved.observation_digest === row.observation_digest, "device_evidence_changed");
    };
    current();
    requireThat(!write || preparePublication, "device_publication_authority_required");
    const verification = new NativeResultVerification(this.store, this.config, task, JSON.parse(row.manifest), JSON.parse(row.observation), binding,
      { source_scope: source.source_scope as IssuedReadAdmission["source_scope"], read_files: files, required_reads: required, assertCurrent: current,
        ...(write ? { workspace_write: write } : {}) },
      this.config.communication ? (_scope, tools) => nativeAgentProof(challenge.manifest.effect_id, tools) : undefined, this.runner);
    try {
      verification.assertCurrent();
      let publication: Record<string, unknown> = {};
      if (write) {
        await preparePublication!(); current(); verification.assertCurrent();
        verification.publish(operation => this.journal.db.transaction(() => { current(); return operation(); }));
        const assertPublished = () => { current(); verification.assertPublished(); };
        const workflow = await this.checkWorkflow(workspace, required, assertPublished);
        if (workflow) publication = { specmesh: { snapshot_digest: workflow.snapshot_digest, status: "pass", closeout_verified: false } };
        assertPublished(); workflow?.assertCurrent();
      }
      const retained = { ...publication, ...verification.result };
      const ref = this.journal.retainReconciledResult(challenge.manifest, retained);
      const { result_digest: _result, ...observationRef } = ref;
      const result = this.networkResult(retained, ref);
      const message: DeviceReconciliationReport = { schema_version: "controlmesh.device_reconciliation_report.v1",
        challenge_id: challenge.challenge_id, challenge_digest: digest(challenge),
        observation: { schema_version: "controlmesh.device_observation.v1", evidence: observationRef, terminal: true }, result };
      verification.assertCurrent();
      return await report(message);
    } finally { verification.close(); }
  }

  private networkResult(result: Record<string, unknown>, evidence: DeviceEvidenceRef): DeviceNativeResult {
    requireThat(typeof result.text === "string" && Buffer.byteLength(result.text) <= 64 * 1024 && Array.isArray(result.read_files), "native_device_result_too_large");
    const workspace = deviceWorkspaceProof(evidence.workspace_write, result);
    const value = { schema_version: "controlmesh.device_native_result.v1", text: result.text, output_digest: result.output_digest,
      read_count: result.read_files.length, evidence, ...(result.communication ? { communication: result.communication } : {}),
      ...(workspace ? { workspace_write: workspace } : {}),
      ...(result.mailbox_delivery ? { mailbox_delivery: result.mailbox_delivery } : {}),
      native_session: { schema_version: "controlmesh.device_native_session.v1", device_id: this.store.deviceId, evidence } };
    assertProtocolSchema<DeviceNativeResult>("device-native-result.schema.json", value);
    return value;
  }

  async execute(context: DeviceAdapterContext): Promise<{ observation: Record<string, unknown>; result: Record<string, unknown> }> {
    const { task, source, binding, files, required, write, registration } = this.prepare(context.job, context.workspace);
    let workflow: SpecMeshObservation | undefined, publishing = false;
    const current = () => {
      context.assertCurrent();
      requireThat(this.registrationDigest() === registration, "native_device_registration_changed");
      requireThat(digest(this.options.binding()) === digest(binding), "native_device_binding_changed");
      const value: unknown = this.options.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      this.options.specmesh?.assertCurrent();
      if (!publishing) workflow?.assertCurrent();
    };
    current();
    workflow = await this.checkWorkflow(context.workspace, required, current, context.authority.signal, context.authority.remainingMs);
    const delivery = await context.mailboxInput();
    // A different native client can append while the workflow/mailbox awaits. Recheck
    // before spending a probe; OpenCodeExecution checks again before native dispatch.
    if (task.native_session) this.store.baseline(this.store.validate(task.native_session as NativeSessionRef));
    const check = await this.preflight.ensure(this.actor, `device-probe-${digest([context.authority.lease.episode_id, binding])}`, binding,
      { executable: this.config.executable, model: binding.model, native_configuration: this.config.native_configuration, environment: this.config.environment,
        assertCurrent: current, remainingMs: context.authority.remainingMs, signal: context.authority.signal });
    if (check.decision !== "cached") throw new ProviderPreparationWait(check);
    let original: Record<string, unknown> | undefined;
    let dispatched = false;
    const channel = this.config.communication ? new NativeAgentChannel(context.authority.lease, this.config.communication, current, {
      assertDispatched: () => { current(); requireThat(dispatched, "device_native_channel_unavailable"); },
      call: (tool, input, signal) => context.nativeCall(tool, input, signal),
    }) : undefined;
    try {
      await channel?.start();
      const result = await this.execution.execute(task, binding, { source_scope: source.source_scope as IssuedReadAdmission["source_scope"], read_files: files, required_reads: required, assertCurrent: current,
        ...(write ? { workspace_write: write } : {}) }, {
        ...(write ? { workspace: { state_home: this.config.state_home,
          binding_digest: digest({ lease: context.authority.lease, task, binding, assignment: context.job.assignment_digest }), assertCurrent: current,
          preparePublication: async () => { await context.preparePublication(); current(); publishing = true; },
          authority: <R>(operation: () => R): R => this.journal.db.transaction(() => { current(); return operation(); }),
          ...(this.options.specmesh ? { verifyPublication: async (assertPublished: () => void) => {
            const checked = () => { current(); assertPublished(); };
            workflow = await this.checkWorkflow(context.workspace, required, checked, context.authority.signal, context.authority.remainingMs);
            checked(); workflow!.assertCurrent();
            return { specmesh: { snapshot_digest: workflow!.snapshot_digest, status: "pass", closeout_verified: false } };
          } } : {}) } } : {}),
        mailbox_delivery: delivery,
        ...(channel ? { communication: { scope: channel.scope, command: channel.command, freeze: () => channel.close(),
          verify: tools => nativeAgentProof(context.effect_id, tools) } } : {}),
        assertCurrent: current, remainingMs: context.authority.remainingMs, signal: context.authority.signal,
        assertReady: () => { this.cache.assertReady(this.actor, binding); },
        preflightGeneration: () => this.cache.inspect(this.actor, binding).generation!,
        executionFailure: (generation, failure) => { this.cache.recordExecutionFailure(this.actor, binding, generation, failure); },
        dispatch: async (intent, manifest) => { await context.dispatch(manifest, intent); dispatched = true; return true; },
        observe: async observation => { original = observation; await context.observe(observation); },
        complete: result => {
          const evidence = context.retainVerifiedResult(result);
          return { ...this.networkResult(result, evidence) };
        },
      }, this.options.timeout_ms ?? 60_000);
      requireThat(original, "native_device_observation_missing");
      return { observation: original, result };
    } finally { await channel?.close(); }
  }
}
