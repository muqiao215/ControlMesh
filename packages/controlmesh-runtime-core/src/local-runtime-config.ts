import { TopologyScheduler } from "./topology-scheduler";
import { TopologyArtifactGate } from "./topology-artifacts";
import { mkdirSync, realpathSync, statSync, existsSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { RuntimeDatabase } from "./database";
import { RuntimeKernel, type Principal, type TaskSnapshot } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { PreflightCache } from "./providers/preflight-cache";
import { OpenCodeReadContainerRunner, OpenCodeStagedContainerRunner, type OpenCodeContainerProfile } from "./providers/opencode-container";
import { OpenCodeTaskAdapter } from "./providers/opencode-task-adapter";
import { NativeSessionStore } from "./providers/native-session";
import { decodeNativeManifest, directoryIdentity } from "./providers/native-manifest";
import { decodeSnapshot } from "./migration";
import { digest, identifier, object, requireThat, type LegacyTask } from "./value";
import { prepareNativeAgentConfiguration } from "./providers/native-agent-profile";
import { DeliveryOutbox } from "./delivery-outbox";
import { openFeishuDelivery } from "./feishu-delivery-profile";
import { privateFile } from "./private-runtime-file";
import type { SubmissionIdentity } from "./task-ingress";
import { decodeExecutionContext } from "./execution-context";
import type { IssuedReadAdmission } from "./providers/opencode-execution";
import { FeishuEventAuthenticator } from "./feishu-event-auth";
import { FeishuInbox } from "./feishu-inbox";
import { FeishuInboundRuntime } from "./feishu-inbound-runtime";
import { decodeToolGrant, enforceProviderConfirmation } from "./execution-grants";
import { SpecMeshPort, type SpecMeshConfiguration } from "./specmesh-port";
import { writeRoots } from "./providers/native-workspace";
import { NativeReconciler } from "./providers/native-reconciler";
import type { LocalRuntimeRecovery } from "./local-runtime-control";
import { ClaudeTaskAdapter } from "./providers/claude-task-adapter";
import { ClaudeTaskReconciler } from "./providers/claude-task-reconciler";
import type { ClaudeTaskConfiguration } from "./providers/claude-task-profile";
import { LocalNativeHistory, type LocalNativeHistoryPort } from "./providers/local-native-history";

/** Explicit isolated candidate configuration. Reading task state does not inspect or probe any provider. */
export interface LocalRuntimeDescription {
  mode: "candidate"; workspace: string;
  providers: { provider: "opencode" | "claude"; model: string }[];
  registered_write_roots: string[];
  integrations: { history: boolean; specmesh: boolean };
}
export function openLocalRuntime(path: string): { runtime: LocalTaskRuntime; deliveries?: DeliveryOutbox; inbound?: FeishuInboundRuntime;
  scheduler?: TopologyScheduler; keep_alive?: boolean; specmesh?: SpecMeshPort; recovery: LocalRuntimeRecovery; history?: LocalNativeHistoryPort;
  describe: () => LocalRuntimeDescription; submissionIdentity: (task: LegacyTask) => SubmissionIdentity; stop: () => Promise<void>; close: () => Promise<void> } {
  const loaded = privateFile(path), config = decodeSnapshot(loaded.bytes).source;
  requireThat(object(config) && config.schema_version === "controlmesh.local_runtime.v1" && config.mode === "candidate", "unsupported_local_runtime_config");
  requireThat(typeof config.state_root === "string" && isAbsolute(config.state_root) && realpathSync(config.state_root) === config.state_root, "private_runtime_state_required");
  const root = config.state_root, state = statSync(root);
  requireThat(state.isDirectory() && state.uid === process.getuid?.() && (state.mode & 0o077) === 0, "private_runtime_state_required");
  requireThat(!["tasks.json", "config.json", "controlmesh_state"].some(name => existsSync(join(root, name))), "legacy_runtime_state_forbidden");
  identifier(config.principal_id); identifier(config.device_id);
  requireThat(object(config.source) && config.source.command_origin === "human_request" && config.source.origin === "user"
    && config.source.source_scope === "local_foreground" && typeof config.source.transport === "string", "local_source_profile_unqualified");
  requireThat(config.opencode !== undefined || config.claude !== undefined, "local_provider_required");
  requireThat(config.opencode === undefined || (object(config.opencode) && typeof config.opencode.model === "string" && config.opencode.cli_version === "1.18.29"
    && object(config.opencode.native_configuration) && object(config.opencode.environment) && Object.values(config.opencode.environment).every(value => typeof value === "string")
    && object(config.opencode.container) && typeof config.opencode.executable === "string"), "invalid_local_provider_profile");
  requireThat(config.claude === undefined || (object(config.claude) && typeof config.claude.model === "string" && config.claude.cli_version === "2.1.263"
    && typeof config.claude.executable === "string" && typeof config.claude.node_executable === "string"
    && typeof config.claude.home === "string" && typeof config.claude.config_directory === "string"
    && object(config.claude.environment) && Object.values(config.claude.environment).every(value => typeof value === "string")
    && (config.claude.container === undefined || object(config.claude.container))), "invalid_local_claude_profile");
  requireThat(object(config.workspace) && typeof config.workspace.directory === "string" && Array.isArray(config.workspace.read_files)
    && config.workspace.read_files.every(value => typeof value === "string") && Array.isArray(config.workspace.required_reads)
    && config.workspace.required_reads.every(value => typeof value === "string"), "invalid_local_workspace_profile");
  const provider = config.opencode as Record<string, unknown> | undefined, workspace = config.workspace;
  requireThat(workspace.write_roots === undefined || (Array.isArray(workspace.write_roots) && workspace.write_roots.length <= 64
    && workspace.write_roots.every(value => typeof value === "string")), "invalid_local_write_profile");
  const roots = Array.isArray(workspace.write_roots) && workspace.write_roots.length
    ? writeRoots(workspace.directory as string, { roots: workspace.write_roots as string[] }) : [];
  const communication = config.communication;
  if (communication !== undefined) {
    requireThat(object(communication) && typeof communication.node_executable === "string" && object(communication.tasks)
      && Object.keys(communication.tasks).length <= 128, "invalid_local_communication_profile");
    for (const [taskId, item] of Object.entries(communication.tasks)) {
      identifier(taskId);
      requireThat(object(item) && Array.isArray(item.peer_tasks) && item.peer_tasks.length <= 16
        && item.peer_tasks.every(peer => typeof peer === "string") && (item.parent_task === null || typeof item.parent_task === "string"), "invalid_local_communication_profile");
    }
  }
  const timeoutMs = provider?.timeout_ms ?? 60_000;
  requireThat(Number.isSafeInteger(timeoutMs) && Number(timeoutMs) >= 1000 && Number(timeoutMs) <= 300_000, "invalid_native_timeout");
  const environment = provider?.environment as Record<string, string> | undefined;
  requireThat(!provider || (typeof environment?.XDG_DATA_HOME === "string" && typeof environment.XDG_CACHE_HOME === "string"), "explicit_native_state_required");
  const native = provider?.native_configuration as Record<string, unknown>;
  const initialRoot = digest(directoryIdentity(root));
  const current = () => {
    requireThat(privateFile(path).revision === loaded.revision && digest(directoryIdentity(root)) === initialRoot, "runtime_configuration_changed");
  };
  const schedule = config.topology_scheduler;
  requireThat(schedule === undefined || (object(schedule) && Object.keys(schedule).every(key => ["auto_start", "keep_alive", "interval_ms", "lease_ms", "max_steps", "artifact_files"].includes(key))
    && typeof schedule.auto_start === "boolean" && typeof schedule.keep_alive === "boolean"
    && (schedule.artifact_files === undefined || (Array.isArray(schedule.artifact_files) && schedule.artifact_files.every(file => typeof file === "string")))), "invalid_topology_scheduler_profile");
  const actor: Principal = { id: config.principal_id, device_id: config.device_id, origin: "human_request",
    scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "message:send", "message:read", "message:ack", "provider:probe",
      "delivery:read", "delivery:configure", "delivery:project", "delivery:send", "delivery:reconcile", "feishu:ingest", "feishu:read", "feishu:process", "history:read", "history:adopt", ...(schedule ? ["team:write"] : [])] };
  const db = new RuntimeDatabase(join(root, "runtime.sqlite")), kernel = new RuntimeKernel(db), cache = new PreflightCache(db);
  try {
    requireThat(config.specmesh === undefined || object(config.specmesh), "invalid_specmesh_profile");
    const specmesh = config.specmesh === undefined ? undefined : new SpecMeshPort(config.specmesh as unknown as SpecMeshConfiguration, workspace.directory as string, current);
    const claudeConfiguration = (taskId: string): ClaudeTaskConfiguration => {
      current(); const selected = config.claude;
      requireThat(object(selected), "claude_not_registered");
      const peers = object(communication) && object(communication.tasks) ? communication.tasks[taskId] : undefined;
      requireThat(peers === undefined || (object(peers) && communication!.node_executable === selected.node_executable), "claude_communication_node_mismatch");
      return { executable: selected.executable as string, node_executable: selected.node_executable as string,
        state_home: root, environment: { home: selected.home as string, config_directory: selected.config_directory as string, credentials: selected.environment as Record<string, string> },
        model: selected.model as string, workspace: workspace.directory as string, read_files: workspace.read_files as string[], required_reads: workspace.required_reads as string[],
        write_roots: roots, ...(peers ? { communication: structuredClone(peers) as { peer_tasks: string[]; parent_task: string | null } } : {}),
        ...(selected.container ? { container: structuredClone(selected.container) as ClaudeTaskConfiguration["container"] } : {}),
        ...(specmesh && roots.length ? { workflow_binding: specmesh.binding_digest } : {}),
        ...(selected.timeout_ms !== undefined ? { timeout_ms: selected.timeout_ms as number } : {}), ...(selected.max_turns !== undefined ? { max_turns: selected.max_turns as number } : {}) };
    };
    requireThat(config.history === undefined || (object(config.history) && typeof config.history.directory === "string" && typeof config.history.python === "string"), "invalid_native_history_profile");
    const history = config.history === undefined ? undefined : new LocalNativeHistory(db, actor, config.history as { directory: string; python: string }, root, claudeConfiguration, current);
    const registered = (task: TaskSnapshot) => {
      current();
      requireThat(provider && environment, "opencode_not_registered");
      enforceProviderConfirmation("opencode", decodeToolGrant(task.task.tool_grant));
      const control = join(root, "containers"); mkdirSync(control, { recursive: true, mode: 0o700 });
      const taskId = task.task.task_id;
      const peers = object(communication) && object(communication.tasks) && Object.hasOwn(communication.tasks, taskId) ? communication.tasks[taskId] as Record<string, unknown> : undefined;
      const channel = peers ? prepareNativeAgentConfiguration(join(root, "task-channels", digest(taskId)),
        (communication as Record<string, unknown>).node_executable as string, taskId, peers.peer_tasks as string[], peers.parent_task as string | null) : undefined;
      const profile: OpenCodeContainerProfile = { container: { ...provider.container as OpenCodeContainerProfile["container"], state_root: control },
        executable: provider.executable as string, data_home: environment.XDG_DATA_HOME, cache_home: environment.XDG_CACHE_HOME,
        ...(channel ? { communication: channel } : {}) };
      const runner = roots.length ? new OpenCodeStagedContainerRunner(profile, { directory: workspace.directory as string, write_roots: roots }) : new OpenCodeReadContainerRunner(profile);
      const store = new NativeSessionStore(join(profile.data_home, "opencode/opencode.db"), actor.device_id!);
      const registration = { workspace: workspace.directory as string, timeout_ms: Number(timeoutMs),
        binding: () => ({ provider: "opencode", model: provider.model as string, cli_version: "1.18.29", device_id: actor.device_id!,
          config_digest: digest(native), credential_revision: privateFile(join(profile.data_home, "opencode/auth.json")).revision,
          permission_profile: roots.length ? "opencode-native-workspace-v1" : "opencode-native-read-v1", runtime_digest: runner.runtimeDigest() }),
        admission: { source_scope: decodeExecutionContext(task.task.execution_context).source_scope as IssuedReadAdmission["source_scope"],
          read_files: workspace.read_files as string[], required_reads: workspace.required_reads as string[], assertCurrent: current,
          ...(roots.length ? { workspace_write: { roots, ...(specmesh ? { workflow_binding: specmesh.binding_digest } : {}) } } : {}) } };
      const worker = { executable: profile.executable, native_configuration: native, environment, state_home: root, ...(channel ? { communication: channel } : {}) };
      return { runner, store, registration, worker };
    };
    const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: config.source.transport }, task => {
      if (task.task.provider === "claude") {
        const selected = claudeConfiguration(task.task.task_id), execution = new ClaudeTaskAdapter(kernel, cache, actor, selected, current).prepare(task);
        return specmesh ? specmesh.bind(execution, selected.required_reads) : execution;
      }
      const { runner, store, registration, worker } = registered(task);
      const execution = new OpenCodeTaskAdapter(kernel, cache, actor, store, worker, runner, registration).prepare(task);
      return specmesh ? specmesh.bind(execution, registration.admission.required_reads) : execution;
    }, current, object(config.limits) ? config.limits : {});
    const recovery: LocalRuntimeRecovery = {
      inspect: (taskId, revision, effectId) => {
        current(); runtime.queueStatus();
        if (kernel.inspect(actor, taskId).task.provider === "claude") return new ClaudeTaskReconciler(kernel, claudeConfiguration(taskId), current).inspect(actor, taskId, revision, effectId);
        const saved = kernel.inspectReconciliation(actor, taskId, revision, effectId);
        decodeNativeManifest(saved.manifest);
        return { episode_id: saved.episode.episode_id, effect_id: effectId, manifest_digest: saved.manifest_digest, observation_digest: saved.observation_digest };
      },
      accept: async (requestId, taskId, revision, candidate) => {
        if (kernel.inspect(actor, taskId).task.provider === "claude") {
          runtime.queueStatus(); const selected = claudeConfiguration(taskId);
          const result = await new ClaudeTaskReconciler(kernel, selected, () => { current(); runtime.queueStatus(); }).accept(actor, requestId, taskId, revision, candidate,
            specmesh ? async assertPublished => {
              const authorize = () => { current(); runtime.queueStatus(); assertPublished(); };
              const checked = await specmesh.inspect("check", { assertCurrent: authorize });
              requireThat(checked.result.status === "pass" && checked.result.references.every(item => selected.required_reads.includes(join(selected.workspace, item.path))), "specmesh_publication_gate_blocked");
              authorize(); checked.assertCurrent(); return { specmesh: { snapshot_digest: checked.snapshot_digest, status: "pass", closeout_verified: false } };
            } : undefined);
          runtime.recover(); return result;
        }
        runtime.queueStatus(); const selected = registered(kernel.inspect(actor, taskId)), binding = selected.registration.binding();
        const authorize = () => { current(); runtime.queueStatus();
          requireThat(digest(selected.registration.binding()) === digest(binding), "native_recovery_profile_changed"); };
        const result = await new NativeReconciler(kernel, selected.store, selected.worker, selected.runner).acceptWorkspace(actor, requestId, taskId, revision, candidate,
          binding, { ...selected.registration.admission, assertCurrent: authorize }, specmesh ? async assertPublished => {
            const assertCurrent = () => { authorize(); assertPublished(); };
            const checked = await specmesh.inspect("check", { assertCurrent });
            requireThat(checked.result.status === "pass", "specmesh_publication_gate_blocked");
            requireThat(checked.result.references.every(item => selected.registration.admission.required_reads.includes(join(workspace.directory as string, item.path))), "specmesh_context_reads_not_issued");
            assertCurrent(); checked.assertCurrent();
            return { specmesh: { snapshot_digest: checked.snapshot_digest, status: "pass", closeout_verified: false } };
          } : undefined);
        runtime.recover(); return result;
      },
    };
    let inbox: FeishuInbox | undefined;
    if (config.inbound !== undefined) {
      const inbound = config.inbound;
      requireThat(object(inbound) && typeof inbound.credentials_file === "string" && config.source.transport === "fs"
        && object(config.delivery) && typeof config.delivery.app_id === "string"
        && (inbound.port === undefined || (Number.isInteger(inbound.port) && Number(inbound.port) >= 0 && Number(inbound.port) <= 65535))
        && (inbound.path === undefined || typeof inbound.path === "string"), "invalid_feishu_inbound_profile");
      const loadedVerification = privateFile(inbound.credentials_file), verification = decodeSnapshot(loadedVerification.bytes).source;
      requireThat(object(verification) && verification.app_id === config.delivery.app_id && typeof verification.verification_token === "string"
        && typeof verification.encrypt_key === "string", "feishu_event_credentials_required");
      const currentInbound = () => {
        current(); requireThat(privateFile(inbound.credentials_file as string).revision === loadedVerification.revision, "feishu_event_configuration_changed");
      };
      const auth = new FeishuEventAuthenticator({ app_id: config.delivery.app_id, verification_token: verification.verification_token,
        encrypt_key: verification.encrypt_key, allowed_chats: inbound.allowed_chats as string[], allowed_senders: inbound.allowed_senders as string[],
        bot_open_id: inbound.bot_open_id as string | undefined, require_group_mention: inbound.require_group_mention as boolean | undefined }, currentInbound);
      const inboundProvider = inbound.provider ?? (config.opencode && !config.claude ? "opencode" : config.claude && !config.opencode ? "claude" : null);
      requireThat(inboundProvider === "opencode" || inboundProvider === "claude", "inbound_provider_selection_required");
      const inboundProfile = config[inboundProvider]; requireThat(object(inboundProfile), "inbound_provider_not_registered");
      inbox = new FeishuInbox(kernel, actor, config.delivery.app_id, auth,
        { provider: inboundProvider, model: inboundProfile.model as string, repo_root: workspace.directory as string }, currentInbound);
    }
    const delivery = config.delivery === undefined ? undefined : openFeishuDelivery(config.delivery, config.source.transport, current, fetch,
      inbox ? { binding_digest: inbox.binding_digest, resolve: envelope => inbox!.replyTarget(envelope) } : undefined);
    const deliveries = delivery ? new DeliveryOutbox(kernel, actor, [delivery.adapter], current) : undefined;
    const inboundConfig = config.inbound as Record<string, unknown> | undefined;
    const inbound = inbox ? new FeishuInboundRuntime(inbox, runtime, deliveries!, delivery!.adapter.adapter_id,
      inboundConfig?.path as string | undefined, inboundConfig?.port as number | undefined) : undefined;
    const submissionIdentity = (task: LegacyTask): SubmissionIdentity => {
      current();
      return delivery ? delivery.adapter.submissionIdentity(task.task_id, String(task.chat_id)) : { chat_id: String(task.chat_id) };
    };
    const scheduler = !object(schedule) ? undefined : new TopologyScheduler(kernel, runtime, actor, {
      interval_ms: schedule.interval_ms as number | undefined, lease_ms: schedule.lease_ms as number | undefined, max_steps: schedule.max_steps as number | undefined,
    }, Array.isArray(schedule.artifact_files) && schedule.artifact_files.length > 0 ? new TopologyArtifactGate(kernel,
      { workspace: workspace.directory as string, allowed_files: schedule.artifact_files as string[] }, current, specmesh) : undefined);
    if (scheduler && schedule!.auto_start) scheduler.start();
    let stopping: Promise<void> | undefined, closing: Promise<void> | undefined;
    const stop = () => stopping ??= Promise.all([scheduler?.stop(), runtime.stop(), deliveries?.stop(), delivery?.close(), inbound?.stop(), specmesh?.stop(), history?.stop()]).then(() => {});
    const close = () => closing ??= stop().then(() => db.close());
    const describe = (): LocalRuntimeDescription => {
      current();
      return { mode: "candidate", workspace: workspace.directory as string,
        providers: (["opencode", "claude"] as const).filter(name => object(config[name])).map(name => ({ provider: name, model: (config[name] as Record<string, unknown>).model as string })),
        registered_write_roots: [...roots], integrations: { history: Boolean(history), specmesh: Boolean(specmesh) } };
    };
    return { runtime, recovery, describe, submissionIdentity, stop, close, ...(scheduler ? { scheduler, keep_alive: schedule!.keep_alive === true } : {}), ...(history ? { history } : {}), ...(deliveries ? { deliveries } : {}), ...(inbound ? { inbound } : {}), ...(specmesh ? { specmesh } : {}) };
  } catch (error) { db.close(); throw error; }
}
