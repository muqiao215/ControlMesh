import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, parse, relative } from "node:path";
import { randomUUID } from "node:crypto";
import type { Lease, Principal, RuntimeKernel, TaskSnapshot } from "../kernel";
import { ProcessSupervisor, type ProcessSpec, type ProcessOutcome, type ProcessAdmission } from "../process-supervisor";
import { digest, object, requireThat } from "../value";
import { NativeSessionStore, type NativeSessionRef, type NativeBaseline } from "./native-session";
import { NativeSessionLease } from "./native-lease";
import { assertReadGrantSnapshot, inspectReadPermissions, readFileGrant, readOnlyEnvironment } from "./opencode-profile";
import { failureFromNativeStderr, observeOpenCode } from "./opencode-events";
import { PreflightCache, type ProbeBinding } from "./preflight-cache";

interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> }
export interface OpenCodeWorkerConfig {
  executable: string;
  native_configuration: Record<string, unknown>;
  environment: Record<string, string>;
  state_home: string;
}
export interface IssuedReadAdmission {
  // Issued by trusted local ingress. Never derive these values from transcript text or a remote body.
  source_scope: "local_foreground";
  read_files: readonly string[];
  required_reads: readonly string[];
  assertCurrent: () => void;
}

/** Concrete kernel -> native process -> kernel path for the locally issued read-only profile.
 * Other ingress/provider/write profiles remain gated until their enforcement ports are available.
 */
export class OpenCodeWorker {
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache,
    private readonly store: NativeSessionStore, private readonly config: OpenCodeWorkerConfig,
    private readonly runner: Runner = new ProcessSupervisor()) {}

  async execute(actor: Principal, lease: Lease, binding: ProbeBinding, admission: IssuedReadAdmission, timeoutMs = 60_000): Promise<TaskSnapshot> {
    requireThat(admission.source_scope === "local_foreground" && actor.origin === "human_request", "source_execution_floor_unavailable");
    requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 300_000, "invalid_native_timeout");
    const snapshot = this.kernel.inspect(actor, lease.task_id);
    const task = snapshot.task;
    requireThat(object(task.execution_context) && task.execution_context.source_scope === admission.source_scope && task.execution_context.origin === "user", "task_source_context_mismatch");
    requireThat(task.provider === "opencode" && task.model === binding.model && binding.device_id === this.store.deviceId, "worker_task_binding_mismatch");
    requireThat(typeof task.repo_root === "string" && typeof task.prompt === "string" && task.prompt.length > 0 && Buffer.byteLength(task.prompt) <= 32768, "invalid_native_task");
    const cwd = realpathSync(task.repo_root);
    const files = readFileGrant(cwd, admission.read_files), required = readFileGrant(cwd, admission.required_reads);
    assertReadGrantSnapshot(task.tool_grant, files);
    requireThat(required.every(file => files.includes(file)), "required_read_not_granted");
    const ref = task.native_session === undefined || task.native_session === null ? null : task.native_session as NativeSessionRef;
    if (ref) requireThat(ref.directory === cwd, "native_workspace_mismatch");
    const git = ref ? null : Bun.spawnSync(["/usr/bin/git", "-C", cwd, "rev-parse", "--show-toplevel"], { timeout: 2_000, stdout: "pipe", stderr: "pipe" });
    const worktree = ref ? this.store.worktree(ref) : git?.exitCode === 0 ? realpathSync(git.stdout.toString().trim()) : parse(cwd).root;
    // OpenCode 1.18.29 ReadTool asks permission for a path relative to its native worktree.
    const readPatterns = files.map(file => relative(worktree, file));
    const configurationDigest = digest(this.config.native_configuration);
    requireThat(configurationDigest === binding.config_digest && binding.provider === "opencode", "worker_provider_binding_mismatch");
    const stableTask = () => {
      const value = this.kernel.inspect(actor, lease.task_id).task;
      return digest({ provider: value.provider, model: value.model, repo_root: value.repo_root, prompt: value.prompt,
        native_session: value.native_session ?? null, tool_grant: value.tool_grant ?? null, execution_context: value.execution_context ?? null });
    };
    const issuedTask = stableTask(), issuedGrant = digest({ source: admission.source_scope, files, required });
    const temp = mkdtempSync(join(tmpdir(), "cm-native-worker-")), agent = `cm-worker-${randomUUID()}`;
    let lock: NativeSessionLease | null = null, baseline: NativeBaseline | null = null, dispatched = false;
    const request = (operation: string) => `native-${digest([lease.episode_id, operation])}`;
    const effect = `native-${lease.episode_id}`;
    const assertCurrent = () => {
      this.kernel.withLease(actor, lease, () => {});
      requireThat(stableTask() === issuedTask && realpathSync(String(task.repo_root)) === cwd, "worker_task_binding_changed");
      requireThat(digest(this.config.native_configuration) === configurationDigest, "native_configuration_changed");
      requireThat(digest({ source: admission.source_scope, files: readFileGrant(cwd, admission.read_files), required: readFileGrant(cwd, admission.required_reads) }) === issuedGrant, "issued_read_grant_changed");
      lock?.assertCurrent();
      return admission.assertCurrent();
    };
    try {
      assertCurrent();
      this.cache.assertReady(actor, binding);
      if (ref) {
        lock = new NativeSessionLease(this.config.state_home, this.store.path, ref);
        this.store.validate(ref);
        baseline = this.store.baseline(ref);
      }
      const env = readOnlyEnvironment(this.config.native_configuration, binding.model, this.config.environment, temp, agent, readPatterns,
        "Continue the explicitly requested task. Only the issued read permissions are available. Report observations accurately.");
      requireThat(realpathSync(join(env.XDG_DATA_HOME, "opencode/opencode.db")) === realpathSync(this.store.path), "native_environment_store_mismatch");
      const version = await this.runner.run({ command: [this.config.executable, "--version"], cwd, env, timeout_ms: 10_000, max_output_bytes: 1024 }, { assertCurrent });
      requireThat(version.reason === "exited" && version.exit_code === 0 && version.stdout.trim() === binding.cli_version, "native_cli_version_changed");
      const inspect = await this.runner.run({ command: [this.config.executable, "debug", "agent", agent, "--pure"], cwd, env, timeout_ms: 10_000, max_output_bytes: 512 * 1024 }, { assertCurrent });
      let resolved: unknown;
      try { resolved = JSON.parse(inspect.stdout); } catch { throw new Error("native_permission_inspection_failed"); }
      const permissions = inspectReadPermissions(resolved, agent, env.XDG_DATA_HOME, readPatterns, baseline?.permissions ?? []);
      requireThat(inspect.reason === "exited" && inspect.exit_code === 0 && permissions, "native_read_grant_unverified");
      assertCurrent();
      if (ref) this.store.validate(ref);
      this.cache.assertReady(actor, binding);
      const preflightGeneration = this.cache.inspect(actor, binding).generation!;
      this.kernel.start(actor, request("start"), lease);
      const permit = this.kernel.dispatchEffect(actor, request("dispatch"), lease, effect,
        { provider: "opencode", model: binding.model, native_revision: ref?.revision ?? null, prompt_digest: digest(task.prompt), grant_digest: issuedGrant, permission_digest: permissions.digest });
      requireThat(permit.dispatch_permitted, "native_request_already_dispatched");
      dispatched = true;
      const result = await this.runner.run({ command: [this.config.executable, "run", "--pure", "--format", "json", "--dir", cwd, "--agent", agent, "--model", binding.model,
        ...(ref ? ["--session", ref.session_id] : ["--title", "ControlMesh supervised task"]), "--print-logs", "--log-level", "ERROR"], cwd, env, stdin_text: task.prompt,
        timeout_ms: timeoutMs, max_output_bytes: 4 * 1024 * 1024 }, { assertCurrent, abortOnStderrLine: line => failureFromNativeStderr(line) !== null });
      const observation = observeOpenCode(result, ref?.session_id ?? null);
      if (observation.failure) this.cache.recordExecutionFailure(actor, binding, preflightGeneration, observation.failure);
      this.kernel.recordEffectObservation(actor, request("observe"), lease, effect,
        { native_session_id: observation.session_id, text: observation.text, terminal: observation.terminal, failure: observation.failure, invalid_reason: observation.invalid_reason, process_reason: result.reason, exit_code: result.exit_code });
      requireThat(observation.terminal && observation.session_id, observation.failure?.code ?? observation.invalid_reason ?? "native_completion_unproven");
      assertCurrent();
      const evidence = this.store.verifyTurn(observation.session_id, baseline, task.prompt, observation.text);
      requireThat(evidence.reference.directory === cwd && evidence.reference.model === binding.model, "native_result_binding_mismatch");
      requireThat(this.store.worktree(evidence.reference) === worktree, "native_worktree_changed");
      requireThat(required.every(file => evidence.read_files.some(read => realpathSync(read) === file)), "required_native_read_unproven");
      const accepted = { native_session: evidence.reference, user_message_id: evidence.user_message_id, assistant_message_ids: evidence.assistant_message_ids,
        text: observation.text, output_digest: digest(observation.text), permission_digest: permissions.digest, read_files: evidence.read_files };
      // Store result, effect confirmation and terminal transition together; lost acknowledgement is replay-safe.
      return this.kernel.db.transaction(() => {
        this.kernel.confirmEffect(actor, request("confirm"), lease, effect, accepted);
        return this.kernel.finish(actor, request("finish"), lease, "done", accepted);
      });
    } catch (error) {
      if (dispatched) {
        const reason = error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "native_worker_failure";
        try { this.kernel.markUnknown(actor, request("unknown"), lease, reason); } catch { /* cancellation or a newer owner remains authoritative */ }
      }
      throw error;
    } finally { lock?.close(); rmSync(temp, { recursive: true, force: true }); }
  }
}
