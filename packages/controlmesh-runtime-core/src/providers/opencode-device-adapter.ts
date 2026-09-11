import { assertProtocolSchema, type DeviceReconciliationChallenge, type DeviceReconciliationReport, type DeviceEvidenceRef, type DeviceNativeResult } from "@controlmesh/protocol";
import type { DeviceJob } from "../device-coordinator";
import { NativeResultVerification } from "./native-result-verification";
import { isAbsolute, resolve } from "node:path";
import type { DeviceAdapter, DeviceAdapterContext } from "../device-worker";
import { DeviceExecutionJournal } from "../device-journal";
import { enforceLocalReadSource } from "../execution-policy";
import type { Principal } from "../kernel";
import { digest, object, requireThat, type LegacyTask } from "../value";
import { OpenCodeExecution, type NativeRunner, type OpenCodeWorkerConfig } from "./opencode-execution";
import { assertReadGrantSnapshot, readFileGrant } from "./opencode-profile";
import { NativeSessionStore } from "./native-session";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";
import { ProviderPreflightService } from "./preflight-service";

export interface OpenCodeDeviceOptions {
  read_files: readonly string[];
  required_reads: readonly string[];
  binding: () => ProbeBinding;
  assertCurrent: () => void;
  timeout_ms?: number;
}

/** Native credentials, sessions, exact paths and full evidence stay on this executing device. */
export class OpenCodeDeviceAdapter implements DeviceAdapter {
  readonly dispatch_mode = "prepared" as const;
  private readonly execution: OpenCodeExecution;
  constructor(private readonly actor: Principal, private readonly cache: PreflightCache,
    private readonly journal: DeviceExecutionJournal, private readonly store: NativeSessionStore,
    private readonly config: OpenCodeWorkerConfig, private readonly options: OpenCodeDeviceOptions,
    runner?: NativeRunner, private readonly preflight = new ProviderPreflightService(cache)) {
    requireThat(actor.origin === "agent_message" && actor.device_id === store.deviceId && actor.device_id === journal.deviceId, "native_device_identity_mismatch");
    this.execution = new OpenCodeExecution(store, config, runner);
  }

  private prepare(job: DeviceJob, workspace: string) {
    requireThat(object(job.execution) && digest(job.execution) === job.execution_digest, "device_execution_projection_changed");
    const source = enforceLocalReadSource(job.execution.execution_context);
    requireThat(typeof job.execution.prompt === "string" && job.execution.prompt.length > 0 && Buffer.byteLength(job.execution.prompt) <= 32_768, "invalid_native_task");
    const binding = structuredClone(this.options.binding());
    requireThat(binding.provider === "opencode" && binding.cli_version === "1.18.29" && binding.device_id === this.store.deviceId
      && job.execution.provider === "opencode" && job.execution.model === binding.model && digest(this.config.native_configuration) === binding.config_digest, "native_device_provider_mismatch");
    const paths = (input: readonly string[]) => input.map(path => {
      requireThat(typeof path === "string" && path.length > 0 && !isAbsolute(path) && !path.split("/").includes(".."), "device_read_requires_relative_path");
      return resolve(workspace, path);
    });
    const files = readFileGrant(workspace, paths(this.options.read_files)), required = readFileGrant(workspace, paths(this.options.required_reads));
    requireThat(required.every(file => files.includes(file)), "required_read_not_granted");
    assertReadGrantSnapshot(job.execution.tool_grant, files);
    const task: LegacyTask = { ...job.execution, task_id: job.task_id, chat_id: "device-execution", status: "waiting", repo_root: workspace,
      native_session: job.execution.native_session ? this.journal.resolveNativeSession(job.execution.native_session, job) : null };
    return { task, source, binding, files, required };
  }

  async reconcile(challenge: DeviceReconciliationChallenge, workspace: string, assertCurrent: () => void,
    report: (value: DeviceReconciliationReport) => Promise<unknown>): Promise<unknown> {
    assertProtocolSchema("device-reconciliation-challenge.schema.json", challenge);
    const row = this.journal.inspect(challenge.manifest), job = JSON.parse(row.job) as DeviceJob;
    requireThat(row.observation && row.observation_digest, "native_observation_unavailable");
    requireThat(job.execution_digest === challenge.execution_digest && job.workspace_id === challenge.workspace_id
      && job.capability === challenge.capability, "reconciliation_authority_changed");
    const { task, source, binding, files, required } = this.prepare(job, workspace);
    const current = () => {
      assertCurrent();
      requireThat(digest(this.options.binding()) === digest(binding), "native_device_binding_changed");
      const value: unknown = this.options.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      const saved = this.journal.inspect(challenge.manifest);
      requireThat(saved.observation_digest === row.observation_digest, "device_evidence_changed");
    };
    current();
    const verification = new NativeResultVerification(this.store, this.config, task, JSON.parse(row.manifest), JSON.parse(row.observation), binding,
      { source_scope: source.source_scope as "local_foreground", read_files: files, required_reads: required, assertCurrent: current });
    try {
      verification.assertCurrent();
      const ref = this.journal.retainReconciledResult(challenge.manifest, verification.result);
      const { result_digest: _result, ...observationRef } = ref;
      const result = this.networkResult(verification.result, ref);
      const message: DeviceReconciliationReport = { schema_version: "controlmesh.device_reconciliation_report.v1",
        challenge_id: challenge.challenge_id, challenge_digest: digest(challenge),
        observation: { schema_version: "controlmesh.device_observation.v1", evidence: observationRef, terminal: true }, result };
      verification.assertCurrent();
      return await report(message);
    } finally { verification.close(); }
  }

  private networkResult(result: Record<string, unknown>, evidence: DeviceEvidenceRef): DeviceNativeResult {
    requireThat(typeof result.text === "string" && Buffer.byteLength(result.text) <= 64 * 1024 && Array.isArray(result.read_files), "native_device_result_too_large");
    const value = { schema_version: "controlmesh.device_native_result.v1", text: result.text, output_digest: result.output_digest,
      read_count: result.read_files.length, evidence,
      native_session: { schema_version: "controlmesh.device_native_session.v1", device_id: this.store.deviceId, evidence } };
    assertProtocolSchema<DeviceNativeResult>("device-native-result.schema.json", value);
    return value;
  }

  async execute(context: DeviceAdapterContext): Promise<{ observation: Record<string, unknown>; result: Record<string, unknown> }> {
    const { task, source, binding, files, required } = this.prepare(context.job, context.workspace);
    const current = () => {
      context.assertCurrent();
      requireThat(digest(this.options.binding()) === digest(binding), "native_device_binding_changed");
      const value: unknown = this.options.assertCurrent();
      if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    current();
    const check = await this.preflight.ensure(this.actor, `device-probe-${digest([context.authority.lease.episode_id, binding])}`, binding,
      { executable: this.config.executable, model: binding.model, native_configuration: this.config.native_configuration, environment: this.config.environment,
        assertCurrent: current, remainingMs: context.authority.remainingMs, signal: context.authority.signal });
    requireThat(check.decision === "cached", "provider_preflight_not_ready");
    let original: Record<string, unknown> | undefined;
    const result = await this.execution.execute(task, binding, { source_scope: source.source_scope as "local_foreground", read_files: files, required_reads: required, assertCurrent: current }, {
      assertCurrent: current, remainingMs: context.authority.remainingMs, signal: context.authority.signal,
      assertReady: () => { this.cache.assertReady(this.actor, binding); },
      preflightGeneration: () => this.cache.inspect(this.actor, binding).generation!,
      executionFailure: (generation, failure) => { this.cache.recordExecutionFailure(this.actor, binding, generation, failure); },
      dispatch: async (intent, manifest) => { await context.dispatch(manifest, intent); return true; },
      observe: async observation => { original = observation; await context.observe(observation); },
      complete: result => {
        const evidence = context.retainVerifiedResult(result);
        return { ...this.networkResult(result, evidence) };
      },
    }, this.options.timeout_ms ?? 60_000);
    requireThat(original, "native_device_observation_missing");
    return { observation: original, result };
  }
}
