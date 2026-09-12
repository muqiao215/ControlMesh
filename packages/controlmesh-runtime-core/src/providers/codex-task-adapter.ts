import { NativeSessionLease } from "./native-lease";
import { AgentMailbox } from "../mailbox";
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

export type CodexTaskConfiguration = Omit<CodexResumeInput, "reference" | "prompt" | "execution_context" | "tool_grant">;
export interface CodexTaskReadiness {
  ensure(request: string, context: LocalExecutionContext): Promise<ProbeDecision>;
  assertReady(): void;
}
interface CodexTaskManifest extends Record<string, unknown> {
  schema_version: "controlmesh.codex_dispatch.v1";
  task_digest: string; configuration_digest: string;
  dispatch: CodexResumeDispatch;
  execution_directory: DirectoryIdentity;
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
    requireThat(task.completion_requirements === undefined, "codex_completion_profile_unavailable");
    WorkspaceStage.assertLocation(this.config.state_home, reference.directory);
    return { ...this.config, reference, prompt: task.prompt, execution_context: task.execution_context, tool_grant: task.tool_grant };
  }
  prepare(snapshot: TaskSnapshot): LocalTaskExecution {
    this.current();
    requireThat(!this.kernel.db.sql.query("SELECT 1 FROM topology_tasks WHERE child_id=?").get(snapshot.task.task_id), "codex_topology_profile_unavailable");
    requireThat(new AgentMailbox(this.kernel).pendingCount(this.actor, snapshot.task.task_id) === 0, "codex_mailbox_profile_unavailable");
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
  private result(input: CodexResumeInput, manifest: CodexTaskManifest, outcome: ProcessOutcome, current: () => void) {
    const verified = verifyRetainedCodexResume(input, manifest.dispatch, outcome, current);
    return { text: verified.observation.text, output_digest: digest(verified.observation.text), native_session: verified.evidence.reference,
      native_turn: verified.evidence.turn_id };
  }
  private async execute(snapshot: TaskSnapshot, input: CodexResumeInput, lease: Lease, context: LocalExecutionContext, configured: () => void) {
    const effect = `codex-${lease.episode_id}`, request = (op: string) => `${effect}-${op}`;
    let manifest: CodexTaskManifest | undefined, observation: Record<string, unknown> | undefined;
    const current = () => { configured(); context.assertCurrent(); this.kernel.withLease(this.actor, lease, () => {}); };
    try {
      await this.process.run(input, { signal: context.signal, remainingMs: context.remainingMs, assertCurrent: current,
        assertReady: () => this.readiness.assertReady(),
        retainDispatch: dispatch => {
          current(); const path = join(this.config.state_home, `codex-resume-${randomUUID()}`); mkdirSync(path, { mode: 0o700 });
          const issued: CodexTaskManifest = { schema_version: "controlmesh.codex_dispatch.v1", configuration_digest: digest(this.config),
            task_digest: nativeTaskDigest(snapshot.task), dispatch, execution_directory: directoryIdentity(path) };
          this.kernel.db.transaction(() => {
            current(); this.kernel.start(this.actor, request("start"), lease);
            const permit = this.kernel.dispatchEffect(this.actor, request("dispatch"), lease, effect,
              { provider: "codex", model: input.model, session_id: input.reference.session_id, prompt_digest: digest(input.prompt) }, issued);
            requireThat(permit.dispatch_permitted, "native_request_already_dispatched");
          }); manifest = issued;
        },
        retainOutcome: outcome => { requireThat(manifest, "codex_dispatch_missing"); observation = this.retain(manifest, outcome).observation; },
      });
      requireThat(manifest && observation, "codex_outcome_missing");
      return this.kernel.db.transaction(() => {
        current(); const retained = this.read(manifest!);
        requireThat(digest(retained.observation) === digest(observation), "codex_outcome_binding_changed");
        const result = this.result(input, manifest!, retained.outcome, current);
        this.kernel.recordEffectObservation(this.actor, request("observe"), lease, effect, observation!);
        this.kernel.confirmEffect(this.actor, request("confirm"), lease, effect, result);
        return this.kernel.finish(this.actor, request("finish"), lease, "done", result);
      });
    } catch (error) {
      if (manifest) { try { this.kernel.markUnknown(this.actor, request("unknown"), lease, "codex_outcome_unproven"); } catch { /* Preserve current cancellation/ownership. */ } }
      throw error;
    }
  }
  private target(taskId: string, revision: number, effect: string) {
    this.current(); const target = this.kernel.inspectReconciliationTarget(this.actor, taskId, revision, effect), raw = target.manifest;
    requireThat(object(raw) && raw.schema_version === "controlmesh.codex_dispatch.v1" && object(raw.dispatch) && object(raw.execution_directory)
      && raw.configuration_digest === digest(this.config) && raw.task_digest === nativeTaskDigest(target.task.task), "codex_dispatch_changed");
    const manifest = raw as CodexTaskManifest, retained = this.read(manifest), input = this.input(target.task);
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
      return this.kernel.db.transaction(() => {
        guarded(); this.result(value.input, value.manifest, value.retained.outcome, guarded);
        if (!value.target.observation) this.kernel.admitReconciliationObservation(this.actor, taskId, revision,
          { episode_id: binding.episode_id, effect_id: binding.effect_id, manifest_digest: binding.manifest_digest }, value.retained.observation, `codex-recovery-${digest(request)}`);
        return this.kernel.reconcileEffect(this.actor, request, taskId, revision, binding,
          () => this.result(value.input, value.manifest, value.retained.outcome, guarded));
      });
    } finally { lock.close(); }
  }
}
