import { nativeTaskOutcome } from "../native-task-failure";
import { mkdirSync, realpathSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import type { RuntimeKernel, Principal, TaskSnapshot, Lease } from "../kernel";
import type { LocalTaskExecution, LocalExecutionContext } from "../local-task-runtime";
import { digest, requireThat } from "../value";
import { WorkspaceStage } from "../workspace-stage";
import { directoryIdentity, nativeTaskDigest } from "./native-manifest";
import { NativeSessionLease } from "./native-lease";
import { NativeMailboxDelivery } from "./native-mailbox";
import { nativeInput } from "./native-mailbox-input";
import { NativeAgentChannel, NativeAgentBroker } from "./native-agent-broker";
import { NativeAgentJournal } from "./native-agent-journal";
import { prepareNativeAgentConfiguration, type NativeAgentConfiguration } from "./native-agent-profile";
import { NativeWorkspaceFiles } from "./native-workspace-files";
import { ClaudeControlRunner } from "./claude-control-runner";
import { observeClaudeControl, validateClaudeControlInput, type ClaudeControlInput } from "./claude-control";
import { claudeTopologyOutput } from "./claude-structured-output";
import { ClaudePreflight } from "./claude-preflight";
import { PreflightCache } from "./preflight-cache";
import { ProviderPreflightService } from "./preflight-service";
import type { ClaudeNativeBaseline, ClaudeSessionRef } from "./claude-session";
import { assertClaudeTaskConfiguration, claudeContainerProfile, claudeProbeBinding, claudeTaskScope, findClaudeSession, validateClaudeTaskSession, type ClaudeTaskConfiguration } from "./claude-task-profile";
import { ClaudeTaskEvidence, claudeTaskPrompt, retainClaudeOutcome, type ClaudeDispatch } from "./claude-task-evidence";
import { ClaudeContainerProbeRunner, ClaudeContainerControlRunner } from "./claude-container";

/** Normal local queue adapter. Native history is a context source, never an alternate task writer. */
export class ClaudeTaskAdapter {
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache, private readonly actor: Principal,
    private readonly config: ClaudeTaskConfiguration, private readonly authorize: () => void,
    private readonly control?: Pick<ClaudeControlRunner, "run">, private readonly preflight?: ClaudePreflight) {}

  prepare(snapshot: TaskSnapshot): LocalTaskExecution {
    assertClaudeTaskConfiguration(this.config);
    requireThat(!this.config.container || (!this.control && !this.preflight), "claude_container_driver_override_forbidden");
    requireThat(this.actor.origin === "human_request" && typeof this.actor.device_id === "string", "source_execution_floor_unavailable");
    const task = snapshot.task, issued = nativeTaskDigest(task), configuration = digest(this.config);
    const binding = claudeProbeBinding(this.config, this.actor.device_id!);
    const initialScope = claudeTaskScope(this.config, task);
    const root = directoryIdentity(this.config.workspace), state = directoryIdentity(this.config.state_home);
    const native = directoryIdentity(this.config.environment.config_directory), home = directoryIdentity(this.config.environment.home);
    const current = (afterPublication = false) => {
      const checked: unknown = this.authorize();
      if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
      requireThat(digest(this.config) === configuration && digest(directoryIdentity(this.config.workspace)) === digest(root)
        && digest(directoryIdentity(this.config.state_home)) === digest(state) && digest(directoryIdentity(this.config.environment.config_directory)) === digest(native)
        && digest(directoryIdentity(this.config.environment.home)) === digest(home), "claude_task_configuration_changed");
      requireThat(nativeTaskDigest(this.kernel.inspect(this.actor, task.task_id).task) === issued, "worker_task_binding_changed");
      requireThat(digest(claudeTaskScope(this.config, task, afterPublication)) === digest(initialScope), "claude_task_grant_changed");
    };
    const checkSession = () => {
      if (task.native_session) validateClaudeTaskSession(this.config, this.actor.device_id!, task.native_session as ClaudeSessionRef);
    };
    current(); checkSession();
    requireThat(Buffer.byteLength(claudeTaskPrompt(task, initialScope)) <= 32768, "claude_task_input_limit");
    return { binding_digest: digest({ configuration, root, state, native, home, issued, binding, scope: initialScope }),
      assertCurrent: current, assertPublicationAuthority: () => current(true),
      ensureReady: async (requestId, context) => {
        current(); checkSession();
        let preflight = this.preflight;
        if (this.config.container) {
          const profile = claudeContainerProfile(this.config); mkdirSync(profile.container.state_root, { recursive: true, mode: 0o700 });
          preflight = new ClaudePreflight(new ClaudeContainerProbeRunner(profile));
        }
        const ready = await new ProviderPreflightService(this.cache, undefined, preflight).ensureClaude(this.actor, requestId, binding,
          { executable: this.config.executable, model: this.config.model, native_configuration: {}, environment: this.config.environment.credentials,
            signal: context.signal, remainingMs: context.remainingMs, assertCurrent: () => { context.assertCurrent(); checkSession(); } });
        context.assertCurrent(); checkSession(); return ready;
      },
      execute: (lease, context) => this.execute(snapshot, lease, context, current),
    };
  }

  private async execute(snapshot: TaskSnapshot, lease: Lease, context: LocalExecutionContext, configured: (afterPublication?: boolean) => void): Promise<TaskSnapshot> {
    const task = snapshot.task, binding = claudeProbeBinding(this.config, this.actor.device_id!), scope = claudeTaskScope(this.config, task);
    requireThat(!this.config.workflow_binding || context.verifyPublication, "native_workflow_verifier_required");
    const request = (operation: string) => `claude-${digest([lease.episode_id, operation])}`, effect = `claude-${lease.episode_id}`;
    const issued = nativeTaskDigest(task);
    let publishing = false, dispatched = false;
    const current = () => {
      this.kernel.withLease(this.actor, lease, () => {}); configured(publishing);
      if (publishing) (context.assertPublicationAuthority ?? context.assertCurrent)(); else context.assertCurrent();
      requireThat(!context.signal.aborted, "claude_task_cancelled");
    };
    const authority = <T>(operation: () => T): T => this.kernel.withLease(this.actor, lease, () => { current(); return operation(); });
    current(); this.cache.assertReady(this.actor, binding);
    const generation = this.cache.inspect(this.actor, binding).generation!;
    const reference = task.native_session ? task.native_session as ClaudeSessionRef : null;
    const sessionId = reference?.session_id ?? randomUUID();
    const lock = new NativeSessionLease(this.config.state_home, this.config.environment.config_directory, { session_id: sessionId });
    let channel: NativeAgentChannel | undefined;
    let communication: NativeAgentBroker | undefined;
    const journal = new NativeAgentJournal(this.kernel);
    try {
      const store = reference ? validateClaudeTaskSession(this.config, this.actor.device_id!, reference) : findClaudeSession(this.config, this.actor.device_id!, sessionId);
      requireThat(reference || !store, "claude_native_session_already_exists");
      const baseline: ClaudeNativeBaseline | null = reference ? store!.baseline(reference) : null;
      const runs = join(this.config.state_home, "claude-runs"); mkdirSync(runs, { recursive: true, mode: 0o700 });
      const directory = join(runs, digest(lease.episode_id)); mkdirSync(directory, { mode: 0o700 });
      const journalDirectory = join(directory, "receipts"); mkdirSync(journalDirectory, { mode: 0o700 });
      const stage = scope.roots.length ? WorkspaceStage.create(directory, this.config.workspace, scope.roots, digest({ lease, configuration: digest(this.config), task: issued }), authority) : undefined;
      const files = new NativeWorkspaceFiles({ workspace: this.config.workspace, read_files: scope.reads, tools: scope.tools,
        journal_directory: journalDirectory, binding_digest: digest({ lease, configuration: digest(this.config), task: issued }), ...(stage ? { stage } : {}) }, authority, current);
      const profile = prepareNativeAgentConfiguration(join(directory, "ipc"), this.config.node_executable, task.task_id, [], null, "workspace.v1");
      let messageProfile: NativeAgentConfiguration | undefined;
      if (scope.communication) {
        messageProfile = prepareNativeAgentConfiguration(join(directory, "message-ipc"), this.config.node_executable,
          task.task_id, scope.communication.peer_tasks, scope.communication.parent_task);
        communication = new NativeAgentBroker(this.kernel, this.actor, lease, effect, messageProfile, () => { current(); lock.assertCurrent(); });
        await communication.start();
      }
      let manifest: ClaudeDispatch | undefined;
      channel = new NativeAgentChannel(lease, profile, current, { assertDispatched: () => {
        current(); lock.assertCurrent();
        const row = this.kernel.db.sql.query("SELECT e.state,m.digest FROM effects e JOIN execution_manifests m ON e.effect_id=m.effect_id WHERE e.effect_id=? AND e.episode_id=? AND e.fence=?")
          .get(effect, lease.episode_id, lease.fence) as { state: string; digest: string } | null;
        requireThat(dispatched && manifest && row?.state === "dispatched" && row.digest === digest(manifest), "claude_tool_effect_unavailable");
      }, call: async (tool, input) => files.call(tool, input) });
      await channel.start();
      const mailbox = new NativeMailboxDelivery(this.kernel), prompt = claudeTaskPrompt(task, scope);
      const delivery = mailbox.prepare(this.actor, lease, prompt, 32768);
      const structured = claudeTopologyOutput(delivery);
      const input: ClaudeControlInput = { schema_version: "controlmesh.claude_control.v1", executable: this.config.executable, workspace: this.config.workspace,
        session_id: sessionId, resume: !!reference, model: this.config.model, prompt: nativeInput(prompt, delivery),
        max_turns: this.config.max_turns ?? 128, workspace_command: channel.command,
        ...(structured ? { structured_output: structured } : {}),
        ...(communication ? { communication_command: communication.command } : {}) };
      validateClaudeControlInput(input);
      let container: ClaudeContainerControlRunner | undefined;
      if (this.config.container) {
        const assets = join(directory, "assets"); mkdirSync(assets, { mode: 0o700 });
        container = await ClaudeContainerControlRunner.create({ ...claudeContainerProfile(this.config), workspace: this.config.workspace,
          bun_executable: realpathSync(process.execPath), asset_directory: assets, environment: this.config.environment,
          workspace_channel: profile, ...(messageProfile ? { communication_channel: messageProfile } : {}) });
      }
      manifest = { schema_version: "controlmesh.claude_dispatch.v1", task_digest: issued, configuration_digest: digest(this.config), binding, input,
        native_directory: directoryIdentity(this.config.environment.config_directory), native_path: store?.path ?? null, baseline,
        execution_directory: directoryIdentity(directory), scope, workspace_tools: files.scope,
        stage: stage ? { path: stage.path, reference: stage.reference() } : null, ...(delivery ? { mailbox_delivery: delivery } : {}),
        ...(communication ? { communication: communication.scope } : {}), ...(container ? { container: container.execution() } : {}) };
      current(); lock.assertCurrent(); if (reference) store!.validate(reference); this.cache.assertReady(this.actor, binding);
      this.kernel.db.transaction(() => {
        current(); this.kernel.start(this.actor, request("start"), lease);
        const permit = this.kernel.dispatchEffect(this.actor, request("dispatch"), lease, effect, { provider: "claude", model: binding.model,
          prompt_digest: digest(input.prompt), session_id: sessionId, resumed: !!reference }, manifest);
        requireThat(permit.dispatch_permitted, "native_request_already_dispatched");
        if (delivery) mailbox.reserve(this.actor, lease, effect, delivery);
        dispatched = true;
      });
      const outcome = await (container ?? this.control ?? new ClaudeControlRunner()).run(input, this.config.environment, { signal: context.signal, remainingMs: context.remainingMs,
        assertCurrent: () => { current(); lock.assertCurrent(); } }, this.config.timeout_ms ?? 60000);
      await channel.close(); await communication?.close();
      // Keep the original result even if its lease expired before the coordinator can acknowledge it.
      const observation = retainClaudeOutcome(manifest, outcome), observed = observeClaudeControl(outcome, input);
      if (observed.failure) this.cache.recordExecutionFailure(this.actor, binding, generation, observed.failure);
      this.kernel.recordEffectObservation(this.actor, request("observe"), lease, effect, observation);
      const evidence = new ClaudeTaskEvidence(this.config, this.actor.device_id!, task, manifest, observation, current,
        (scope, tools) => journal.verify(effect, scope, tools));
      evidence.verify(); publishing = true;
      const result = evidence.publish(authority);
      const publication = nativeTaskOutcome(result) === "failed" ? {} : await context.verifyPublication?.(() => { current(); evidence.assertPublished(); }) ?? {};
      return this.kernel.db.transaction(() => {
        current(); evidence.assertPublished();
        if (delivery) mailbox.consume(this.actor, lease, effect, delivery, result);
        if (communication) journal.consume(this.actor, lease, effect, communication.scope, evidence.communicationTools);
        const accepted = { ...publication, ...result, mailbox_pending_count: mailbox.pendingCount(this.actor, task.task_id) };
        this.kernel.confirmEffect(this.actor, request("confirm"), lease, effect, accepted);
        return this.kernel.finish(this.actor, request("finish"), lease, nativeTaskOutcome(accepted), accepted);
      });
    } catch (error) {
      if (dispatched) {
        const reason = error instanceof Error && /^[a-z0-9_]{1,96}$/.test(error.message) ? error.message : "claude_worker_failed";
        try { this.kernel.markUnknown(this.actor, request("unknown"), lease, reason); } catch { /* current cancellation/new ownership remains authoritative */ }
      }
      throw error;
    } finally { await Promise.allSettled([channel?.close(), communication?.close()]); lock.close(); }
  }
}
