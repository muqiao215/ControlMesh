import { mkdirSync, realpathSync, statSync, existsSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { RuntimeDatabase } from "./database";
import { RuntimeKernel, type Principal } from "./kernel";
import { LocalTaskRuntime } from "./local-task-runtime";
import { PreflightCache } from "./providers/preflight-cache";
import { OpenCodeReadContainerRunner, type OpenCodeContainerProfile } from "./providers/opencode-container";
import { OpenCodeTaskAdapter } from "./providers/opencode-task-adapter";
import { NativeSessionStore } from "./providers/native-session";
import { directoryIdentity } from "./providers/native-manifest";
import { decodeSnapshot } from "./migration";
import { digest, identifier, object, requireThat, type LegacyTask } from "./value";
import { prepareNativeAgentConfiguration } from "./providers/native-agent-profile";
import { DeliveryOutbox } from "./delivery-outbox";
import { openFeishuDelivery } from "./feishu-delivery-profile";
import { privateFile } from "./private-runtime-file";
import type { SubmissionIdentity } from "./task-ingress";

/** Explicit isolated candidate configuration. Reading task state does not inspect or probe any provider. */
export function openLocalRuntime(path: string): { runtime: LocalTaskRuntime; deliveries?: DeliveryOutbox;
  submissionIdentity: (task: LegacyTask) => SubmissionIdentity; stop: () => Promise<void>; close: () => Promise<void> } {
  const loaded = privateFile(path), config = decodeSnapshot(loaded.bytes).source;
  requireThat(object(config) && config.schema_version === "controlmesh.local_runtime.v1" && config.mode === "candidate", "unsupported_local_runtime_config");
  requireThat(typeof config.state_root === "string" && isAbsolute(config.state_root) && realpathSync(config.state_root) === config.state_root, "private_runtime_state_required");
  const root = config.state_root, state = statSync(root);
  requireThat(state.isDirectory() && state.uid === process.getuid?.() && (state.mode & 0o077) === 0, "private_runtime_state_required");
  requireThat(!["tasks.json", "config.json", "controlmesh_state"].some(name => existsSync(join(root, name))), "legacy_runtime_state_forbidden");
  identifier(config.principal_id); identifier(config.device_id);
  requireThat(object(config.source) && config.source.command_origin === "human_request" && config.source.origin === "user"
    && config.source.source_scope === "local_foreground" && typeof config.source.transport === "string", "local_source_profile_unqualified");
  requireThat(object(config.opencode) && typeof config.opencode.model === "string" && config.opencode.cli_version === "1.18.29"
    && object(config.opencode.native_configuration) && object(config.opencode.environment) && Object.values(config.opencode.environment).every(value => typeof value === "string")
    && object(config.opencode.container) && typeof config.opencode.executable === "string", "invalid_local_provider_profile");
  requireThat(object(config.workspace) && typeof config.workspace.directory === "string" && Array.isArray(config.workspace.read_files)
    && config.workspace.read_files.every(value => typeof value === "string") && Array.isArray(config.workspace.required_reads)
    && config.workspace.required_reads.every(value => typeof value === "string"), "invalid_local_workspace_profile");
  const provider = config.opencode, workspace = config.workspace;
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
  const timeoutMs = provider.timeout_ms ?? 60_000;
  requireThat(Number.isSafeInteger(timeoutMs) && Number(timeoutMs) >= 1000 && Number(timeoutMs) <= 300_000, "invalid_native_timeout");
  const environment = provider.environment as Record<string, string>;
  requireThat(typeof environment.XDG_DATA_HOME === "string" && typeof environment.XDG_CACHE_HOME === "string", "explicit_native_state_required");
  const native = provider.native_configuration as Record<string, unknown>;
  const initialRoot = digest(directoryIdentity(root));
  const current = () => {
    requireThat(privateFile(path).revision === loaded.revision && digest(directoryIdentity(root)) === initialRoot, "runtime_configuration_changed");
  };
  const actor: Principal = { id: config.principal_id, device_id: config.device_id, origin: "human_request",
    scopes: ["task:create", "task:read", "task:execute", "task:resume", "task:cancel", "task:reconcile", "task:admin", "message:send", "message:read", "message:ack", "provider:probe",
      "delivery:read", "delivery:configure", "delivery:project", "delivery:send", "delivery:reconcile"] };
  const db = new RuntimeDatabase(join(root, "runtime.sqlite")), kernel = new RuntimeKernel(db), cache = new PreflightCache(db);
  try {
    const runtime = new LocalTaskRuntime(kernel, actor, { command_origin: "human_request", origin: "user", source_scope: "local_foreground", transport: config.source.transport }, task => {
      current();
      const control = join(root, "containers"); mkdirSync(control, { recursive: true, mode: 0o700 });
      const taskId = task.task.task_id;
      const peers = object(communication) && object(communication.tasks) && Object.hasOwn(communication.tasks, taskId) ? communication.tasks[taskId] as Record<string, unknown> : undefined;
      const channel = peers ? prepareNativeAgentConfiguration(join(root, "task-channels", digest(taskId)),
        (communication as Record<string, unknown>).node_executable as string, taskId, peers.peer_tasks as string[], peers.parent_task as string | null) : undefined;
      const profile: OpenCodeContainerProfile = { container: { ...provider.container as OpenCodeContainerProfile["container"], state_root: control },
        executable: provider.executable as string, data_home: environment.XDG_DATA_HOME, cache_home: environment.XDG_CACHE_HOME,
        ...(channel ? { communication: channel } : {}) };
      const runner = new OpenCodeReadContainerRunner(profile), store = new NativeSessionStore(join(profile.data_home, "opencode/opencode.db"), actor.device_id!);
      const registration = { workspace: workspace.directory as string, timeout_ms: Number(timeoutMs),
        binding: () => ({ provider: "opencode", model: provider.model as string, cli_version: "1.18.29", device_id: actor.device_id!,
          config_digest: digest(native), credential_revision: privateFile(join(profile.data_home, "opencode/auth.json")).revision,
          permission_profile: "opencode-native-read-v1", runtime_digest: runner.runtimeDigest() }),
        admission: { source_scope: "local_foreground" as const, read_files: workspace.read_files as string[], required_reads: workspace.required_reads as string[], assertCurrent: current } };
      return new OpenCodeTaskAdapter(kernel, cache, actor, store, { executable: profile.executable, native_configuration: native,
        environment, state_home: root, ...(channel ? { communication: channel } : {}) }, runner, registration).prepare(task);
    }, current, object(config.limits) ? config.limits : {});
    const delivery = config.delivery === undefined ? undefined : openFeishuDelivery(config.delivery, config.source.transport, current);
    const deliveries = delivery ? new DeliveryOutbox(kernel, actor, [delivery.adapter], current) : undefined;
    const submissionIdentity = (task: LegacyTask): SubmissionIdentity => {
      current();
      return delivery ? delivery.adapter.submissionIdentity(task.task_id, String(task.chat_id)) : { chat_id: String(task.chat_id) };
    };
    let stopping: Promise<void> | undefined, closing: Promise<void> | undefined;
    const stop = () => stopping ??= Promise.all([runtime.stop(), deliveries?.stop(), delivery?.close()]).then(() => {});
    const close = () => closing ??= stop().then(() => db.close());
    return { runtime, submissionIdentity, stop, close, ...(deliveries ? { deliveries } : {}) };
  } catch (error) { db.close(); throw error; }
}
