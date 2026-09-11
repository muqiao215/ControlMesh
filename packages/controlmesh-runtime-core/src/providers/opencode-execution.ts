import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, parse, relative } from "node:path";
import { randomUUID } from "node:crypto";
import type { LegacyTask } from "../value";
import { ProcessSupervisor, type ProcessSpec, type ProcessOutcome, type ProcessAdmission } from "../process-supervisor";
import { digest, object, requireThat } from "../value";
import { enforceLocalReadSource } from "../execution-policy";
import { NativeSessionStore, type NativeSessionRef, type NativeBaseline } from "./native-session";
import { NativeSessionLease } from "./native-lease";
import { assertReadGrantSnapshot, inspectReadPermissions, readFileGrant, readOnlyEnvironment } from "./opencode-profile";
import { failureFromNativeStderr, observeOpenCode } from "./opencode-events";
import type { ProbeBinding } from "./preflight-cache";
import type { ProviderFailure } from "./opencode-events";
import { assertWorkspaceManifest, directoryIdentity, nativeReadInstructions, nativeTaskDigest, permissionEvidence, snapshotReads, type NativeManifest } from "./native-manifest";

export interface NativeRunner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome>; runtimeDigest?(): string }
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

export interface NativeExecutionHooks<T> {
  assertCurrent: () => void;
  assertReady: () => void;
  preflightGeneration: () => number;
  executionFailure: (generation: number, failure: ProviderFailure) => void;
  dispatch: (intent: Record<string, unknown>, manifest: NativeManifest) => boolean | Promise<boolean>;
  observe: (observation: Record<string, unknown>) => void | Promise<void>;
  complete: (result: Record<string, unknown>) => T | Promise<T>;
  remainingMs?: () => number;
  signal?: AbortSignal;
}

/** One native implementation shared by local and device adapters; hooks own durable authority and state. */
export class OpenCodeExecution {
  constructor(private readonly store: NativeSessionStore, private readonly config: OpenCodeWorkerConfig,
    private readonly runner: NativeRunner = new ProcessSupervisor()) {}

  async execute<T>(task: LegacyTask, binding: ProbeBinding, admission: IssuedReadAdmission, hooks: NativeExecutionHooks<T>, timeoutMs = 60_000): Promise<T> {
    requireThat(admission.source_scope === "local_foreground", "source_execution_floor_unavailable");
    requireThat(binding.cli_version === "1.18.29", "native_permission_profile_unverified");
    requireThat(binding.runtime_digest === this.runner.runtimeDigest?.(), "worker_runtime_binding_mismatch");
    requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 300_000, "invalid_native_timeout");
    enforceLocalReadSource(task.execution_context);
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
    const stableTask = () => nativeTaskDigest(task);
    const issuedTask = stableTask(), issuedGrant = digest({ source: admission.source_scope, files, required });
    const temp = mkdtempSync(join(tmpdir(), "cm-native-worker-")), agent = `cm-worker-${randomUUID()}`;
    let lock: NativeSessionLease | null = null, baseline: NativeBaseline | null = null;
    let manifest: NativeManifest | null = null;
    const assertCurrent = () => {
      hooks.assertCurrent();
      requireThat(stableTask() === issuedTask && realpathSync(String(task.repo_root)) === cwd, "worker_task_binding_changed");
      requireThat(digest(this.config.native_configuration) === configurationDigest, "native_configuration_changed");
      requireThat(binding.runtime_digest === this.runner.runtimeDigest?.(), "worker_runtime_binding_mismatch");
      requireThat(digest({ source: admission.source_scope, files: readFileGrant(cwd, admission.read_files), required: readFileGrant(cwd, admission.required_reads) }) === issuedGrant, "issued_read_grant_changed");
      lock?.assertCurrent();
      if (manifest) assertWorkspaceManifest(manifest);
      const response: unknown = admission.assertCurrent();
      if (response !== undefined) { void Promise.resolve(response).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    try {
      assertCurrent();
      hooks.assertReady();
      if (ref) {
        lock = new NativeSessionLease(this.config.state_home, this.store.path, ref);
        this.store.validate(ref);
        baseline = this.store.baseline(ref);
      }
      const instructions = nativeReadInstructions(required);
      const env = readOnlyEnvironment(this.config.native_configuration, binding.model, this.config.environment, temp, agent, readPatterns, instructions);
      requireThat(realpathSync(join(env.XDG_DATA_HOME, "opencode/opencode.db")) === realpathSync(this.store.path), "native_environment_store_mismatch");
      const version = await this.runner.run({ command: [this.config.executable, "--version"], cwd, env, timeout_ms: 10_000, max_output_bytes: 1024 }, { assertCurrent, remainingMs: hooks.remainingMs, signal: hooks.signal });
      requireThat(version.reason === "exited" && version.exit_code === 0 && version.stdout.trim() === binding.cli_version, "native_cli_version_changed");
      const inspect = await this.runner.run({ command: [this.config.executable, "debug", "agent", agent, "--pure"], cwd, env, timeout_ms: 10_000, max_output_bytes: 512 * 1024 }, { assertCurrent, remainingMs: hooks.remainingMs, signal: hooks.signal });
      let resolved: unknown;
      try { resolved = JSON.parse(inspect.stdout); } catch { throw new Error("native_permission_inspection_failed"); }
      requireThat(object(resolved) && resolved.prompt === instructions, "native_execution_instructions_changed");
      const permissions = inspectReadPermissions(resolved, agent, env.XDG_DATA_HOME, readPatterns, baseline?.permissions ?? []);
      requireThat(inspect.reason === "exited" && inspect.exit_code === 0 && permissions, "native_read_grant_unverified");
      assertCurrent();
      if (ref) this.store.validate(ref);
      hooks.assertReady();
      const preflightGeneration = hooks.preflightGeneration();
      manifest = { schema_version: "controlmesh.native_dispatch.v1", task_digest: issuedTask, binding: structuredClone(binding), native_store_id: this.store.identity(), baseline,
        directory: directoryIdentity(cwd), worktree: directoryIdentity(worktree), files: snapshotReads(cwd, files), required_reads: required,
        permission_evidence: permissionEvidence(resolved, agent, env.XDG_DATA_HOME, worktree, files, baseline) };
      assertCurrent();
      const permit = await hooks.dispatch({ provider: "opencode", model: binding.model, native_revision: ref?.revision ?? null,
        prompt_digest: digest(task.prompt), grant_digest: issuedGrant, permission_digest: permissions.digest }, manifest);
      requireThat(permit, "native_request_already_dispatched");
      assertCurrent();
      const result = await this.runner.run({ command: [this.config.executable, "run", "--pure", "--format", "json", "--dir", cwd, "--agent", agent, "--model", binding.model,
        ...(ref ? ["--session", ref.session_id] : ["--title", "ControlMesh supervised task"]), "--print-logs", "--log-level", "ERROR"], cwd, env, stdin_text: task.prompt,
        timeout_ms: timeoutMs, max_output_bytes: 4 * 1024 * 1024 }, { assertCurrent, remainingMs: hooks.remainingMs, signal: hooks.signal, abortOnStderrLine: line => failureFromNativeStderr(line) !== null });
      const observation = observeOpenCode(result, ref?.session_id ?? null);
      try {
        await hooks.observe(
          { native_session_id: observation.session_id, text: observation.text, terminal: observation.terminal, failure: observation.failure, invalid_reason: observation.invalid_reason, process_reason: result.reason, exit_code: result.exit_code });
      } finally {
        if (observation.failure) hooks.executionFailure(preflightGeneration, observation.failure);
      }
      requireThat(observation.terminal && observation.session_id, observation.failure?.code ?? observation.invalid_reason ?? "native_completion_unproven");
      assertCurrent();
      assertWorkspaceManifest(manifest, true);
      const evidence = this.store.verifyTurn(observation.session_id, baseline, task.prompt, observation.text);
      requireThat(evidence.reference.directory === cwd && evidence.reference.model === binding.model, "native_result_binding_mismatch");
      requireThat(this.store.worktree(evidence.reference) === worktree, "native_worktree_changed");
      requireThat(required.every(file => evidence.read_files.some(read => realpathSync(read) === file)), "required_native_read_unproven");
      requireThat(evidence.read_files.every(file => files.includes(realpathSync(file))), "native_ungranted_read");
      const accepted = { native_session: evidence.reference, user_message_id: evidence.user_message_id, assistant_message_ids: evidence.assistant_message_ids,
        text: observation.text, output_digest: digest(observation.text), permission_digest: permissions.digest, read_files: evidence.read_files };
      assertCurrent();
      return await hooks.complete(accepted);
    } finally { lock?.close(); rmSync(temp, { recursive: true, force: true }); }
  }
}
