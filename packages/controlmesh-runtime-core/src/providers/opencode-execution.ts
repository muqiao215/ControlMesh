import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, parse, relative } from "node:path";
import { randomUUID } from "node:crypto";
import type { LegacyTask } from "../value";
import { ProcessSupervisor, type ProcessSpec, type ProcessOutcome, type ProcessAdmission } from "../process-supervisor";
import { digest, object, requireThat } from "../value";
import { enforceNativeReadSource } from "../execution-policy";
import type { ExecutionContext } from "../execution-context";
import { NativeSessionStore, type NativeSessionRef, type NativeBaseline } from "./native-session";
import { NativeSessionLease } from "./native-lease";
import { assertReadGrantSnapshot, inspectReadPermissions, readFileGrant, readOnlyEnvironment } from "./opencode-profile";
import { failureFromNativeStderr, observeOpenCode } from "./opencode-events";
import type { ProbeBinding } from "./preflight-cache";
import type { ProviderFailure } from "./opencode-events";
import { assertWorkspaceManifest, directoryIdentity, nativeReadInstructions, nativeTaskDigest, permissionEvidence, snapshotReads, type NativeManifest } from "./native-manifest";
import { nativeInput, nativeMailboxEvidence, type NativeMailboxBatch } from "./native-mailbox-input";
import { nativeAgentTools, type NativeAgentScope, type NativeAgentToolResult } from "./native-agent-journal";
import { assertNativeAgentConfiguration, nativeAgentScope, type NativeAgentConfiguration } from "./native-agent-profile";
import { WorkspaceStage, type WorkspaceAuthority } from "../workspace-stage";
import { workspaceEnvironment, inspectWorkspacePermissions, assertWorkspaceGrantSnapshot } from "./opencode-profile";
import { nativeWorkspaceInstructions } from "./native-manifest";
import { registeredReads, writeRoots, workspacePatterns, workspacePermissionEvidence, verifyWorkspaceTools, type IssuedWorkspaceWrite, type NativeWriteReceipt } from "./native-workspace";

export interface NativeRunner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome>; runtimeDigest?(): string;
  forStage?(stage: WorkspaceStage): NativeRunner;
  assertSource?(context: ExecutionContext): void }
export interface OpenCodeWorkerConfig {
  executable: string;
  native_configuration: Record<string, unknown>;
  environment: Record<string, string>;
  state_home: string;
  communication?: NativeAgentConfiguration;
}
export interface IssuedReadAdmission {
  // Issued by trusted local ingress. Never derive these values from transcript text or a remote body.
  source_scope: "local_foreground" | "direct_message" | "group_message";
  read_files: readonly string[];
  required_reads: readonly string[];
  assertCurrent: () => void;
  workspace_write?: IssuedWorkspaceWrite;
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
  mailbox_delivery?: NativeMailboxBatch;
  communication?: { scope: NativeAgentScope; command: string[]; freeze: () => Promise<void>; verify: (tools: NativeAgentToolResult[]) => Record<string, unknown> };
  workspace?: { state_home: string; binding_digest: string; authority: WorkspaceAuthority; assertCurrent: () => void;
    verifyPublication?: (assertPublished: () => void) => Promise<Record<string, unknown>> };
}

/** One native implementation shared by local and device adapters; hooks own durable authority and state. */
export class OpenCodeExecution {
  constructor(private readonly store: NativeSessionStore, private readonly config: OpenCodeWorkerConfig,
    private readonly runner: NativeRunner = new ProcessSupervisor()) {}

  async execute<T>(task: LegacyTask, binding: ProbeBinding, admission: IssuedReadAdmission, hooks: NativeExecutionHooks<T>, timeoutMs = 60_000): Promise<T> {
    requireThat(["local_foreground", "direct_message", "group_message"].includes(admission.source_scope), "source_execution_floor_unavailable");
    requireThat(binding.cli_version === "1.18.29", "native_permission_profile_unverified");
    requireThat(binding.runtime_digest === this.runner.runtimeDigest?.(), "worker_runtime_binding_mismatch");
    requireThat(Number.isSafeInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 300_000, "invalid_native_timeout");
    const source = enforceNativeReadSource(task.execution_context, this.runner);
    requireThat(source.source_scope === admission.source_scope, "source_execution_floor_unavailable");
    requireThat(task.provider === "opencode" && task.model === binding.model && binding.device_id === this.store.deviceId, "worker_task_binding_mismatch");
    requireThat(typeof task.repo_root === "string" && typeof task.prompt === "string" && task.prompt.length > 0 && Buffer.byteLength(task.prompt) <= 32768, "invalid_native_task");
    const delivery = hooks.mailbox_delivery ? structuredClone(hooks.mailbox_delivery) : undefined;
    requireThat(!delivery || delivery.task_id === task.task_id, "native_mailbox_task_mismatch");
    const input = nativeInput(task.prompt, delivery);
    const cwd = realpathSync(task.repo_root);
    const roots = admission.workspace_write ? writeRoots(cwd, admission.workspace_write) : [];
    requireThat(Boolean(admission.workspace_write) === Boolean(hooks.workspace) && (!roots.length || this.runner.forStage), "native_write_owner_required");
    requireThat(!admission.workspace_write?.workflow_binding || hooks.workspace?.verifyPublication, "native_workflow_verifier_required");
    const files = roots.length ? registeredReads(cwd, admission.read_files, roots) : readFileGrant(cwd, admission.read_files);
    const required = readFileGrant(cwd, admission.required_reads);
    const communication = hooks.communication;
    requireThat(Boolean(communication) === Boolean(this.config.communication), "native_agent_profile_required");
    const communicationIdentity = this.config.communication ? assertNativeAgentConfiguration(this.config.communication) : null;
    if (communication) {
      requireThat(communication.scope.task_id === task.task_id && digest(nativeAgentScope(this.config.communication!, communication.scope)) === digest(communication.scope), "native_agent_scope_changed");
    }
    const communicationTools = communication ? nativeAgentTools : [];
    assertReadGrantSnapshot(task.tool_grant, files, communicationTools);
    if (roots.length) assertWorkspaceGrantSnapshot(task.tool_grant, cwd, roots, communicationTools);
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
    const issuedTask = stableTask(), grantValue = (afterWrites = false) => ({ source: admission.source_scope,
      files: roots.length ? registeredReads(cwd, admission.read_files, roots, afterWrites) : readFileGrant(cwd, admission.read_files),
      required: roots.length ? registeredReads(cwd, admission.required_reads, roots, afterWrites) : readFileGrant(cwd, admission.required_reads),
      ...(admission.workspace_write ? { workspace_write: { roots: writeRoots(cwd, admission.workspace_write), workflow_binding: admission.workspace_write.workflow_binding ?? null } } : {}) });
    const issuedGrant = digest(grantValue());
    const temp = mkdtempSync(join(tmpdir(), "cm-native-worker-")), agent = `cm-worker-${randomUUID()}`;
    let lock: NativeSessionLease | null = null, baseline: NativeBaseline | null = null;
    let manifest: NativeManifest | null = null;
    let stage: WorkspaceStage | undefined, published: NativeWriteReceipt | undefined, publishing = false;
    const assertCurrent = () => {
      hooks.assertCurrent();
      enforceNativeReadSource(task.execution_context, this.runner);
      requireThat(stableTask() === issuedTask && realpathSync(String(task.repo_root)) === cwd, "worker_task_binding_changed");
      requireThat(digest(this.config.native_configuration) === configurationDigest, "native_configuration_changed");
      requireThat(binding.runtime_digest === this.runner.runtimeDigest?.(), "worker_runtime_binding_mismatch");
      if (communicationIdentity) requireThat(this.config.communication && assertNativeAgentConfiguration(this.config.communication) === communicationIdentity, "native_agent_profile_changed");
      requireThat(digest(grantValue(publishing)) === issuedGrant, "issued_read_grant_changed");
      lock?.assertCurrent();
      if (manifest) assertWorkspaceManifest(manifest, false, publishing);
      if (publishing && published) stage!.assertApplied(published.proposal_digest);
      else stage?.assertSourceCurrent();
      const response: unknown = publishing ? hooks.workspace!.assertCurrent() : admission.assertCurrent();
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
      if (hooks.workspace) stage = WorkspaceStage.create(hooks.workspace.state_home, cwd, roots, hooks.workspace.binding_digest, hooks.workspace.authority);
      const runner = stage ? this.runner.forStage!(stage) : this.runner;
      const write = stage ? { schema_version: "controlmesh.native_workspace.v1" as const, roots: roots.map(directoryIdentity), stage_path: stage.path,
        stage_reference: stage.reference(), workflow_binding: admission.workspace_write?.workflow_binding ?? null,
        ...workspacePatterns(worktree, files, roots, stage) } : undefined;
      const instructions = write ? nativeWorkspaceInstructions(required, roots, communication?.scope) : nativeReadInstructions(required, communication?.scope);
      const env = write ? workspaceEnvironment(this.config.native_configuration, binding.model, this.config.environment, temp, agent,
        write.read_patterns, write.edit_patterns, instructions, communication?.command, write.denied_patterns)
        : readOnlyEnvironment(this.config.native_configuration, binding.model, this.config.environment, temp, agent, readPatterns, instructions, communication?.command);
      requireThat(realpathSync(join(env.XDG_DATA_HOME, "opencode/opencode.db")) === realpathSync(this.store.path), "native_environment_store_mismatch");
      const version = await runner.run({ command: [this.config.executable, "--version"], cwd, env, timeout_ms: 10_000, max_output_bytes: 1024 }, { assertCurrent, remainingMs: hooks.remainingMs, signal: hooks.signal });
      requireThat(version.reason === "exited" && version.exit_code === 0 && version.stdout.trim() === binding.cli_version, "native_cli_version_changed");
      const inspect = await runner.run({ command: [this.config.executable, "debug", "agent", agent, "--pure"], cwd, env, timeout_ms: 10_000, max_output_bytes: 512 * 1024 }, { assertCurrent, remainingMs: hooks.remainingMs, signal: hooks.signal });
      let resolved: unknown;
      try { resolved = JSON.parse(inspect.stdout); } catch { throw new Error("native_permission_inspection_failed"); }
      requireThat(object(resolved) && resolved.prompt === instructions, "native_execution_instructions_changed");
      const permissions = write ? inspectWorkspacePermissions(resolved, agent, env.XDG_DATA_HOME, write.read_patterns, write.edit_patterns,
        baseline?.permissions ?? [], communicationTools, write.denied_patterns)
        : inspectReadPermissions(resolved, agent, env.XDG_DATA_HOME, readPatterns, baseline?.permissions ?? [], communicationTools);
      requireThat(inspect.reason === "exited" && inspect.exit_code === 0 && permissions, "native_read_grant_unverified");
      assertCurrent();
      if (ref) this.store.validate(ref);
      hooks.assertReady();
      const preflightGeneration = hooks.preflightGeneration();
      manifest = { schema_version: write ? "controlmesh.native_dispatch.v2" : "controlmesh.native_dispatch.v1", task_digest: issuedTask, binding: structuredClone(binding), native_store_id: this.store.identity(), baseline,
        directory: directoryIdentity(cwd), worktree: directoryIdentity(worktree), files: snapshotReads(cwd, files), required_reads: required,
        permission_evidence: write ? workspacePermissionEvidence(resolved, agent, env.XDG_DATA_HOME, write, baseline, communicationTools)
          : permissionEvidence(resolved, agent, env.XDG_DATA_HOME, worktree, files, baseline, communicationTools),
        ...(write ? { workspace_write: write } : {}),
        ...(communication ? { communication: structuredClone(communication.scope) } : {}),
        ...(delivery ? { mailbox_delivery: delivery } : {}) };
      assertCurrent();
      const permit = await hooks.dispatch({ provider: "opencode", model: binding.model, native_revision: ref?.revision ?? null,
        prompt_digest: digest(input), grant_digest: issuedGrant, permission_digest: permissions.digest }, manifest);
      requireThat(permit, "native_request_already_dispatched");
      assertCurrent();
      const result = await runner.run({ command: [this.config.executable, "run", "--pure", "--format", "json", "--dir", cwd, "--agent", agent, "--model", binding.model,
        ...(ref ? ["--session", ref.session_id] : ["--title", "ControlMesh supervised task"]), "--print-logs", "--log-level", "ERROR"], cwd, env, stdin_text: input,
        timeout_ms: timeoutMs, max_output_bytes: 4 * 1024 * 1024 }, { assertCurrent, remainingMs: hooks.remainingMs, signal: hooks.signal, abortOnStderrLine: line => failureFromNativeStderr(line) !== null });
      await communication?.freeze();
      const observation = observeOpenCode(result, ref?.session_id ?? null);
      const observed = { native_session_id: observation.session_id, text: observation.text, terminal: observation.terminal, failure: observation.failure,
        invalid_reason: observation.invalid_reason, process_reason: result.reason, exit_code: result.exit_code };
      let proposal: NativeWriteReceipt | undefined;
      try {
        if (stage && observation.terminal && observation.session_id) {
          try {
            assertCurrent(); stage.seal(hooks.workspace!.authority); proposal = stage.proposalReceipt();
            verifyWorkspaceTools(manifest, stage, this.store.verifyTurn(observation.session_id, baseline, input, observation.text), proposal);
          } catch (error) { await hooks.observe(observed); throw error; }
        }
        await hooks.observe({ ...observed, ...(proposal ? { workspace_write: proposal } : {}) });
      } finally {
        if (observation.failure) hooks.executionFailure(preflightGeneration, observation.failure);
      }
      requireThat(observation.terminal && observation.session_id, observation.failure?.code ?? observation.invalid_reason ?? "native_completion_unproven");
      assertCurrent();
      assertWorkspaceManifest(manifest, true);
      const evidence = this.store.verifyTurn(observation.session_id, baseline, input, observation.text);
      requireThat(evidence.reference.directory === cwd && evidence.reference.model === binding.model, "native_result_binding_mismatch");
      requireThat(this.store.worktree(evidence.reference) === worktree, "native_worktree_changed");
      if (stage) verifyWorkspaceTools(manifest, stage, evidence, proposal!);
      else {
        requireThat(required.every(file => evidence.read_files.some(read => realpathSync(read) === file)), "required_native_read_unproven");
        requireThat(evidence.read_files.every(file => files.includes(realpathSync(file))), "native_ungranted_read");
      }
      requireThat(communication || evidence.agent_tools.length === 0, "native_agent_scope_unavailable");
      const communicationEvidence = communication?.verify(evidence.agent_tools);
      const accepted = { native_session: evidence.reference, user_message_id: evidence.user_message_id, assistant_message_ids: evidence.assistant_message_ids,
        text: observation.text, output_digest: digest(observation.text), permission_digest: permissions.digest, read_files: evidence.read_files,
        ...(communicationEvidence ? { communication: communicationEvidence } : {}),
        ...(delivery ? { mailbox_delivery: nativeMailboxEvidence(delivery, evidence.user_message_id) } : {}) };
      assertCurrent();
      let publicationEvidence: Record<string, unknown> = {};
      if (stage) {
        publishing = true;
        published = stage.promote(hooks.workspace!.authority, proposal!.proposal_digest);
        assertCurrent();
        publicationEvidence = await hooks.workspace!.verifyPublication?.(assertCurrent) ?? {};
        assertCurrent();
      }
      return await hooks.complete({ ...publicationEvidence, ...accepted, ...(published ? { workspace_write: published } : {}) });
    } finally { lock?.close(); rmSync(temp, { recursive: true, force: true }); }
  }
}
