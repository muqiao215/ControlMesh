import { randomUUID } from "node:crypto";
import { closeSync, constants, fsyncSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { RuntimeKernel, Principal, TaskSnapshot, Lease, ReconciliationBinding } from "../kernel";
import type { LocalTaskExecution, LocalExecutionContext } from "../local-task-runtime";
import type { ProcessOutcome } from "../process-supervisor";
import { privateFile } from "../private-runtime-file";
import { canonical, digest, object, requireThat } from "../value";
import { directoryIdentity, nativeTaskDigest, type DirectoryIdentity } from "./native-manifest";
import { GeminiSessionStore, type GeminiNativeBaseline } from "./gemini-session";
import { GeminiResumeProcess, verifyRetainedGeminiResume, type GeminiResumeInput, type GeminiResumeDispatch } from "./gemini-resume-process";
import type { ProbeDecision } from "./preflight-cache";
import { NativeMailboxDelivery } from "./native-mailbox";
import { assertTopologyNativeInput } from "../topology-native-input";
import { NativeSessionLease } from "./native-lease";

export interface GeminiTaskReference extends GeminiNativeBaseline { provider: "gemini"; device_id: string; directory: string; model: string }
export type GeminiTaskConfiguration = Omit<GeminiResumeInput, "baseline" | "session_id" | "device_id" | "prompt" | "execution_context" | "tool_grant">;
export interface GeminiTaskReadiness {
  ensure(request: string, context: LocalExecutionContext): Promise<ProbeDecision>;
  assertReady(): void;
  captureOutcome?(): (outcome: ProcessOutcome) => void;
}
interface Manifest extends Record<string, unknown> {
  schema_version: "controlmesh.gemini_dispatch.v1"; configuration_digest: string; task_digest: string;
  dispatch: GeminiResumeDispatch; directory: DirectoryIdentity;
}
/** Persistent task ownership for the Gemini text continuation process. */
export class GeminiTaskAdapter {
  constructor(private readonly kernel: RuntimeKernel, private readonly actor: Principal, private readonly config: GeminiTaskConfiguration,
    private readonly readiness: GeminiTaskReadiness, private readonly authorize: () => void,
    private readonly process: Pick<GeminiResumeProcess, "run"> = new GeminiResumeProcess()) {}
  private current() {
    const value: unknown = this.authorize();
    if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private input(snapshot: TaskSnapshot): GeminiResumeInput {
    this.current(); const task = snapshot.task, ref = task.native_session;
    requireThat(this.actor.origin === "human_request" && typeof this.actor.device_id === "string", "gemini_task_principal_invalid");
    requireThat(task.provider === "gemini" && task.model === this.config.model && typeof task.prompt === "string" && object(ref)
      && ref.provider === "gemini" && ref.device_id === this.actor.device_id && ref.directory === task.repo_root
      && ref.directory === this.config.settings.workspace && ref.model === this.config.model, "gemini_native_adoption_required");
    requireThat(!task.completion_requirements, "gemini_text_completion_profile_required");
    requireThat(!assertTopologyNativeInput(this.kernel, task.task_id)
      && new NativeMailboxDelivery(this.kernel).pendingCount(this.actor, task.task_id) === 0, "gemini_mailbox_profile_required");
    const reference = ref as unknown as GeminiTaskReference;
    const { provider: _provider, device_id: _device, directory: _directory, model: _model, ...baseline } = reference;
    return { ...this.config, device_id: this.actor.device_id, session_id: reference.session_id, baseline,
      prompt: task.prompt, execution_context: task.execution_context, tool_grant: task.tool_grant };
  }
  prepare(snapshot: TaskSnapshot): LocalTaskExecution {
    const input = this.input(snapshot), issued = nativeTaskDigest(snapshot.task), config = digest(this.config);
    requireThat(digest(new GeminiSessionStore(input.session_path, input.device_id, input.settings.workspace).baseline(input.session_id)) === digest(input.baseline), "gemini_adoption_changed");
    const current = () => { this.current(); requireThat(digest(this.config) === config
      && nativeTaskDigest(this.kernel.inspect(this.actor, snapshot.task.task_id).task) === issued, "gemini_task_binding_changed"); };
    return { binding_digest: digest({ issued, config }), assertCurrent: current,
      ensureReady: async (request, context) => { current(); return this.readiness.ensure(request, context); },
      execute: (lease, context) => this.execute(snapshot, input, lease, context, current) };
  }
  private read(manifest: Manifest) {
    requireThat(dirname(manifest.directory.path) === this.config.state_home
      && digest(directoryIdentity(manifest.directory.path)) === digest(manifest.directory), "gemini_outcome_directory_changed");
    const file = privateFile(join(manifest.directory.path, "outcome.json"), 12 * 1024 * 1024), value: unknown = JSON.parse(file.bytes.toString());
    requireThat(object(value) && value.schema_version === "controlmesh.gemini_outcome.v1" && value.manifest_digest === digest(manifest) && object(value.outcome), "gemini_outcome_changed");
    return { outcome: value.outcome as unknown as ProcessOutcome, observation: { schema_version: "controlmesh.gemini_observation.v1", record_revision: file.revision, process_digest: digest(value.outcome) } };
  }
  private retain(manifest: Manifest, outcome: ProcessOutcome) {
    requireThat(digest(directoryIdentity(manifest.directory.path)) === digest(manifest.directory), "gemini_outcome_directory_changed");
    const bytes = canonical({ schema_version: "controlmesh.gemini_outcome.v1", manifest_digest: digest(manifest), outcome });
    requireThat(Buffer.byteLength(bytes) <= 12 * 1024 * 1024, "gemini_outcome_limit");
    const fd = openSync(join(manifest.directory.path, "outcome.json"), constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
    const directory = openSync(manifest.directory.path, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try { fsyncSync(directory); } finally { closeSync(directory); }
    return this.read(manifest);
  }
  private result(input: GeminiResumeInput, manifest: Manifest, outcome: ProcessOutcome, current: () => void) {
    const verified = verifyRetainedGeminiResume(input, manifest.dispatch, outcome, current);
    const baseline = new GeminiSessionStore(input.session_path, input.device_id, input.settings.workspace).baseline(input.session_id);
    requireThat(baseline.revision === verified.evidence.revision, "gemini_outcome_changed");
    return { text: verified.evidence.text, output_digest: digest(verified.evidence.text), native_turn: verified.evidence.user_message_id,
      native_session: { ...baseline, provider: "gemini", device_id: input.device_id, directory: input.settings.workspace, model: input.model } };
  }
  private async execute(snapshot: TaskSnapshot, input: GeminiResumeInput, lease: Lease, context: LocalExecutionContext, configured: () => void) {
    const effect = `gemini-${lease.episode_id}`, request = (op: string) => `${effect}-${op}`;
    let manifest: Manifest | undefined;
    const current = () => { configured(); context.assertCurrent(); this.kernel.withLease(this.actor, lease, () => {}); };
    try {
      current();
      const path = join(this.config.state_home, `gemini-${randomUUID()}`); mkdirSync(path, { mode: 0o700 });
      const capture = this.readiness.captureOutcome?.();
      await this.process.run(input, { ...context, assertCurrent: current, assertReady: () => this.readiness.assertReady(),
        retainDispatch: dispatch => {
          current(); const issued: Manifest = { schema_version: "controlmesh.gemini_dispatch.v1", configuration_digest: digest(this.config),
            task_digest: nativeTaskDigest(snapshot.task), dispatch, directory: directoryIdentity(path) };
          this.kernel.db.transaction(() => {
            current(); this.kernel.start(this.actor, request("start"), lease);
            requireThat(this.kernel.dispatchEffect(this.actor, request("dispatch"), lease, effect,
              { provider: "gemini", session_id: input.session_id, model: input.model, prompt_digest: digest(input.prompt) }, issued).dispatch_permitted, "native_request_already_dispatched");
          }); manifest = issued;
        }, retainOutcome: outcome => { requireThat(manifest, "gemini_dispatch_missing"); this.retain(manifest, outcome); capture?.(outcome); } });
      requireThat(manifest, "gemini_dispatch_missing");
      const lock = new NativeSessionLease(this.config.state_home, input.session_path, input.baseline);
      try {
        return this.kernel.db.transaction(() => {
          current(); lock.assertCurrent(); const retained = this.read(manifest!);
          const result = this.result(input, manifest!, retained.outcome, current);
          this.kernel.recordEffectObservation(this.actor, request("observe"), lease, effect, retained.observation);
          this.kernel.confirmEffect(this.actor, request("confirm"), lease, effect, result);
          return this.kernel.finish(this.actor, request("finish"), lease, "done", result);
        });
      } finally { lock.close(); }
    } catch (error) {
      if (manifest) try { this.kernel.markUnknown(this.actor, request("unknown"), lease, "gemini_outcome_unproven"); } catch { /* Preserve cancellation or a newer owner. */ }
      throw error;
    }
  }
  private target(taskId: string, revision: number, effect: string) {
    this.current(); const target = this.kernel.inspectReconciliationTarget(this.actor, taskId, revision, effect), raw = target.manifest;
    requireThat(object(raw) && raw.schema_version === "controlmesh.gemini_dispatch.v1" && object(raw.dispatch) && object(raw.directory)
      && raw.configuration_digest === digest(this.config) && raw.task_digest === nativeTaskDigest(target.task.task), "gemini_dispatch_changed");
    const manifest = raw as Manifest, retained = this.read(manifest);
    requireThat(!target.observation || digest(target.observation) === digest(retained.observation), "gemini_outcome_changed");
    return { target, manifest, retained, input: this.input(target.task) };
  }
  inspectRecovery(taskId: string, revision: number, effect: string): ReconciliationBinding {
    const value = this.target(taskId, revision, effect);
    return { episode_id: value.target.episode.episode_id, effect_id: effect, manifest_digest: value.target.manifest_digest, observation_digest: digest(value.retained.observation) };
  }
  recover(request: string, taskId: string, revision: number, binding: ReconciliationBinding) {
    this.current(); const prior = this.kernel.reconciliationReceipt(this.actor, request, taskId, revision, binding); if (prior) return prior;
    const value = this.target(taskId, revision, binding.effect_id);
    const current = () => { this.current(); requireThat(digest(this.inspectRecovery(taskId, revision, binding.effect_id)) === digest(binding), "reconciliation_evidence_changed"); };
    const lock = new NativeSessionLease(this.config.state_home, value.input.session_path, value.input.baseline);
    try { return this.kernel.db.transaction(() => {
      current(); lock.assertCurrent(); const result = this.result(value.input, value.manifest, value.retained.outcome, current);
      if (!value.target.observation) this.kernel.admitReconciliationObservation(this.actor, taskId, revision,
        { episode_id: binding.episode_id, effect_id: binding.effect_id, manifest_digest: binding.manifest_digest }, value.retained.observation, `gemini-recovery-${digest(request)}`);
      return this.kernel.reconcileEffect(this.actor, request, taskId, revision, binding, () => result);
    }); } finally { lock.close(); }
  }
}
