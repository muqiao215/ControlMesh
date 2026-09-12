import { existsSync, lstatSync, mkdirSync, realpathSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { RuntimeDatabase } from "./database";
import { RuntimeKernel, type Principal } from "./kernel";
import { DeviceCoordinator, type DeviceRegistration } from "./device-coordinator";
import { DeviceClient } from "./device-client";
import { DeviceWorker, type DeviceWorkerOptions } from "./device-worker";
import { DeviceExecutionJournal } from "./device-journal";
import { DeviceCoordinatorControl, DeviceWorkerControl, type RuntimeControl } from "./device-runtime-control";
import { privateFile } from "./private-runtime-file";
import { decodeSnapshot } from "./migration";
import { digest, identifier, object, requireThat } from "./value";
import { PreflightCache } from "./providers/preflight-cache";
import { NativeSessionStore } from "./providers/native-session";
import { OpenCodeDeviceAdapter } from "./providers/opencode-device-adapter";
import { OpenCodeReadContainerRunner, OpenCodeStagedContainerRunner, type OpenCodeContainerProfile } from "./providers/opencode-container";
import { prepareNativeAgentConfiguration } from "./providers/native-agent-profile";
import { directoryIdentity } from "./providers/native-manifest";
import { decodeToolGrant, enforceProviderConfirmation } from "./execution-grants";
import { decodeExecutionContext } from "./execution-context";
import { SpecMeshPort, type SpecMeshConfiguration } from "./specmesh-port";
import { WorkspaceStage } from "./workspace-stage";
import { writeRoots } from "./providers/native-workspace";
import { HistoryClient } from "./providers/history-client";
import { DeviceNativeAdoptions } from "./providers/device-native-adoption";
import { DeviceScheduler, type DeviceSchedulerOptions } from "./device-scheduler";

export interface DeviceRuntime {
  control: RuntimeControl;
  startDaemon(): void;
  stop(): Promise<void>;
  close(): Promise<void>;
}

function fields(value: unknown, allowed: readonly string[], code: string): asserts value is Record<string, unknown> {
  requireThat(object(value) && Object.keys(value).every(key => allowed.includes(key)), code);
}
function integer(value: unknown, low: number, high: number, code: string): number {
  requireThat(Number.isSafeInteger(value) && Number(value) >= low && Number(value) <= high, code); return Number(value);
}
function relativeList(value: unknown, limit: number): string[] {
  requireThat(Array.isArray(value) && value.length <= limit && new Set(value).size === value.length
    && value.every(path => typeof path === "string" && path.length > 0 && !isAbsolute(path) && !/[\x00\r\n]/.test(path)
      && !path.split("/").includes("..")), "invalid_device_workspace_profile");
  return value as string[];
}

/** A normal private startup path. Opening/status never probes a model or starts a network listener. */
export function openDeviceRuntime(path: string): DeviceRuntime {
  const loaded = privateFile(path), config = decodeSnapshot(loaded.bytes).source;
  requireThat(object(config) && config.schema_version === "controlmesh.device_runtime.v1" && config.mode === "candidate"
    && ["coordinator", "worker"].includes(String(config.role)), "unsupported_device_runtime_config");
  const common = ["schema_version", "mode", "role", "state_root", "principal_id", "device_id"];
  fields(config, [...common, ...(config.role === "coordinator" ? ["devices", "listen_port"]
    : ["coordinator", "opencode", "workspaces", "capabilities", "communication", "history", "max_parallel", "scheduler"])], "invalid_device_runtime_config");
  identifier(config.principal_id); identifier(config.device_id);
  requireThat(typeof config.state_root === "string" && isAbsolute(config.state_root), "private_runtime_state_required");
  const root = config.state_root;
  const rootIdentity = () => {
    const stat = lstatSync(root);
    requireThat(stat.isDirectory() && !stat.isSymbolicLink() && realpathSync(root) === root && stat.uid === process.getuid?.()
      && (stat.mode & 0o077) === 0, "private_runtime_state_required");
    requireThat(!["tasks.json", "config.json", "controlmesh_state"].some(name => existsSync(join(root, name))), "legacy_runtime_state_forbidden");
    return digest(directoryIdentity(root));
  };
  const originalRoot = rootIdentity();
  let closed = false, stopping = false;
  const current = () => {
    requireThat(!closed && !stopping && privateFile(path).revision === loaded.revision && rootIdentity() === originalRoot, "runtime_configuration_changed");
  };
  let db: RuntimeDatabase | undefined;
  const database = () => {
    current();
    db = new RuntimeDatabase(join(root, "runtime.sqlite"));
    const identity = digest({ role: config.role, principal_id: config.principal_id, device_id: config.device_id });
    db.transaction(() => {
      const old = db!.sql.query("SELECT value FROM meta WHERE key='device_runtime_identity'").get() as { value: string } | null;
      requireThat(!old || old.value === identity, "device_runtime_identity_changed");
      if (!old) {
        // An unbound pre-existing candidate database needs an explicit migration, not implicit adoption.
        requireThat(!db!.sql.query("SELECT 1 FROM tasks UNION ALL SELECT 1 FROM device_execution_records LIMIT 1").get(), "device_runtime_adoption_required");
        db!.sql.query("INSERT INTO meta VALUES ('device_runtime_identity',?)").run(identity);
      }
    });
    return db;
  };
  try {
    let control: DeviceCoordinatorControl | DeviceWorkerControl;
    if (config.role === "coordinator") {
      requireThat(Array.isArray(config.devices), "invalid_device_catalog");
      for (const entry of config.devices) {
        fields(entry, ["device_id", "principal_id", "token_sha256", "capabilities", "workspace_ids"], "invalid_device_catalog");
        requireThat(entry.principal_id === config.principal_id && Array.isArray(entry.capabilities) && Array.isArray(entry.workspace_ids), "invalid_device_catalog");
      }
      const devices = config.devices as unknown as DeviceRegistration[];
      const port = integer(config.listen_port ?? 0, 0, 65535, "invalid_device_port");
      const kernel = new RuntimeKernel(database());
      const actor: Principal = { id: config.principal_id, device_id: config.device_id, origin: "human_request",
        scopes: ["task:create", "task:read", "task:resume", "task:cancel", "task:reconcile", "task:admin", "device:assign", "device:revoke"] };
      control = new DeviceCoordinatorControl(kernel, actor, new DeviceCoordinator(kernel, devices, current), devices, current, port);
    } else {
      fields(config.coordinator, ["endpoint", "token"], "invalid_device_coordinator_profile");
      requireThat(typeof config.coordinator.endpoint === "string" && typeof config.coordinator.token === "string", "invalid_device_coordinator_profile");
      const client = new DeviceClient({ endpoint: config.coordinator.endpoint, token: config.coordinator.token, device_id: config.device_id });
      fields(config.opencode, ["model", "cli_version", "executable", "environment", "native_configuration", "container", "timeout_ms"], "invalid_device_provider_profile");
      const provider = config.opencode;
      requireThat(typeof provider.model === "string" && provider.model.length > 0 && provider.cli_version === "1.18.29"
        && typeof provider.executable === "string" && isAbsolute(provider.executable) && object(provider.native_configuration)
        && object(provider.environment) && Object.values(provider.environment).every(value => typeof value === "string")
        && object(provider.container), "invalid_device_provider_profile");
      const environment = provider.environment as Record<string, string>, native = provider.native_configuration;
      requireThat(typeof environment.XDG_DATA_HOME === "string" && isAbsolute(environment.XDG_DATA_HOME)
        && typeof environment.XDG_CACHE_HOME === "string" && isAbsolute(environment.XDG_CACHE_HOME), "explicit_native_state_required");
      const timeout = integer(provider.timeout_ms ?? 60_000, 1000, 300_000, "invalid_native_timeout");
      const parallel = integer(config.max_parallel ?? 4, 1, 8, "invalid_device_concurrency");
      requireThat(object(config.workspaces) && Object.keys(config.workspaces).length > 0 && Object.keys(config.workspaces).length <= 128
        && object(config.capabilities) && Object.keys(config.capabilities).length > 0 && Object.keys(config.capabilities).length <= 128, "invalid_device_catalog");
      const workspaces: Record<string, string> = {};
      const profiles = new Map<string, { directory: string; read_files: string[]; required_reads: string[]; write_roots: string[]; specmesh?: SpecMeshConfiguration }>();
      for (const [id, source] of Object.entries(config.workspaces)) {
        identifier(id); fields(source, ["directory", "read_files", "required_reads", "write_roots", "specmesh"], "invalid_device_workspace_profile");
        requireThat(typeof source.directory === "string" && isAbsolute(source.directory) && realpathSync(source.directory) === source.directory
          && lstatSync(source.directory).isDirectory(), "workspace_must_be_canonical");
        const read = relativeList(source.read_files, 80), required = relativeList(source.required_reads, 80), writes = relativeList(source.write_roots ?? [], 64);
        requireThat(required.every(file => read.includes(file)), "required_read_not_granted");
        if (writes.length) { WorkspaceStage.assertLocation(root, source.directory); writeRoots(source.directory, { roots: writes.map(item => resolve(source.directory as string, item)) }); }
        requireThat(source.specmesh === undefined || object(source.specmesh), "invalid_specmesh_profile");
        workspaces[id] = source.directory;
        profiles.set(id, { directory: source.directory, read_files: read, required_reads: required, write_roots: writes,
          ...(source.specmesh ? { specmesh: source.specmesh as unknown as SpecMeshConfiguration } : {}) });
      }
      const capabilities = new Map<string, { workspace_ids: string[]; writable: boolean }>();
      for (const [id, source] of Object.entries(config.capabilities)) {
        identifier(id); fields(source, ["workspace_ids", "writable"], "invalid_device_capability_profile");
        requireThat(Array.isArray(source.workspace_ids) && source.workspace_ids.length > 0 && source.workspace_ids.length <= 128
          && new Set(source.workspace_ids).size === source.workspace_ids.length && source.workspace_ids.every(item => typeof item === "string" && profiles.has(item))
          && typeof source.writable === "boolean", "invalid_device_capability_profile");
        requireThat(!source.writable || source.workspace_ids.every(id => profiles.get(id as string)!.write_roots.length > 0), "invalid_device_write_profile");
        capabilities.set(id, { workspace_ids: source.workspace_ids as string[], writable: source.writable });
      }
      const communication = config.communication;
      if (communication !== undefined) {
        fields(communication, ["node_executable"], "invalid_device_communication_profile");
        requireThat(typeof communication.node_executable === "string" && isAbsolute(communication.node_executable), "invalid_device_communication_profile");
      }
      const historyConfig = config.history;
      if (historyConfig !== undefined) {
        fields(historyConfig, ["python", "directory", "environment"], "invalid_device_history_profile");
        requireThat(typeof historyConfig.python === "string" && isAbsolute(historyConfig.python)
          && typeof historyConfig.directory === "string" && isAbsolute(historyConfig.directory)
          && (historyConfig.environment === undefined || (object(historyConfig.environment)
            && Object.values(historyConfig.environment).every(value => typeof value === "string"))), "invalid_device_history_profile");
      }
      const local = database(), cache = new PreflightCache(local), journal = new DeviceExecutionJournal(local, config.device_id);
      const actor: Principal = { id: config.principal_id, device_id: config.device_id, origin: "agent_message", scopes: ["provider:probe", "history:read", "history:adopt", "device:schedule"] };
      const nativeStore = new NativeSessionStore(join(environment.XDG_DATA_HOME, "opencode/opencode.db"), actor.device_id!);
      const history = historyConfig ? new DeviceNativeAdoptions(local, actor, nativeStore, new HistoryClient({ python: historyConfig.python as string,
        viewer_directory: historyConfig.directory as string,
        environment: { PATH: "/usr/bin:/bin", PYTHONUTF8: "1", PYTHONNOUSERSITE: "1", PYTHONDONTWRITEBYTECODE: "1", ...historyConfig.environment as Record<string, string> | undefined } }, nativeStore),
        workspaceId => { current(); const selected = profiles.get(workspaceId); requireThat(selected, "local_capability_unavailable"); return selected.directory; },
        (workspaceId, capability) => {
          current(); const selected = profiles.get(workspaceId), permission = capabilities.get(capability);
          requireThat(selected && permission?.workspace_ids.includes(workspaceId), "local_capability_unavailable");
          return { directory: selected.directory, model: provider.model as string, digest: digest({ principal: actor.id, device: actor.device_id,
            provider, selected, directory_identity: directoryIdentity(selected.directory), permission, communication: communication ?? null, history: historyConfig }) };
        }, current) : undefined;
      const abort = new AbortController(), adapters: Record<string, DeviceWorkerOptions["adapters"][string]> = {};
      for (const [capability, selection] of capabilities) adapters[capability] = (job, workspace) => {
        current(); requireThat(selection.workspace_ids.includes(job.workspace_id) && job.execution, "local_capability_unavailable");
        const selected = profiles.get(job.workspace_id)!;
        requireThat(workspace === selected.directory && job.execution.provider === "opencode" && job.execution.model === provider.model, "native_device_provider_mismatch");
        const context = decodeExecutionContext(job.execution.execution_context);
        requireThat(context.origin === "user" && ["local_foreground", "direct_message", "group_message"].includes(context.source_scope), "source_execution_floor_unavailable");
        enforceProviderConfirmation("opencode", decodeToolGrant(job.execution.tool_grant));
        requireThat(communication || (!(job.peer_tasks?.length) && !job.parent_task), "native_communication_not_configured");
        const containerRoot = join(root, "containers"); mkdirSync(containerRoot, { recursive: true, mode: 0o700 });
        const channel = communication ? prepareNativeAgentConfiguration(join(root, "task-channels", digest(job.task_id)),
          communication.node_executable as string, job.task_id, [...job.peer_tasks ?? []], job.parent_task ?? null) : undefined;
        const profile: OpenCodeContainerProfile = { container: { ...provider.container as OpenCodeContainerProfile["container"], state_root: containerRoot },
          executable: provider.executable as string, data_home: environment.XDG_DATA_HOME, cache_home: environment.XDG_CACHE_HOME,
          ...(channel ? { communication: channel } : {}) };
        const writes = selection.writable ? selected.write_roots : [];
        const roots = writes.length ? writeRoots(workspace, { roots: writes.map(item => resolve(workspace, item)) }) : [];
        const runner = roots.length ? new OpenCodeStagedContainerRunner(profile, { directory: workspace, write_roots: roots }) : new OpenCodeReadContainerRunner(profile);
        const specmesh = selected.specmesh ? new SpecMeshPort(selected.specmesh, workspace, current) : undefined;
        return new OpenCodeDeviceAdapter(actor, cache, journal, nativeStore,
          { executable: profile.executable, native_configuration: native, environment, state_home: root, ...(channel ? { communication: channel } : {}) },
          { read_files: selected.read_files, required_reads: selected.required_reads, write_roots: writes, timeout_ms: timeout, assertCurrent: current,
            ...(history ? { adoptions: history } : {}),
            ...(specmesh ? { specmesh } : {}), binding: () => ({ provider: "opencode", model: provider.model as string, cli_version: "1.18.29", device_id: actor.device_id!,
              config_digest: digest(native), credential_revision: privateFile(join(profile.data_home, "opencode/auth.json")).revision,
              permission_profile: writes.length ? "opencode-native-workspace-v1" : "opencode-native-read-v1", runtime_digest: runner.runtimeDigest() }) }, runner);
      };
      const worker = new DeviceWorker(client, { workspaces, adapters, journal, signal: abort.signal });
      const workerControl = new DeviceWorkerControl(local, actor, client, worker, current, () => abort.abort(), parallel, history);
      if (config.scheduler !== undefined) fields(config.scheduler, ["parallelism", "max_pending", "poll_ms", "lease_ms", "max_backoff_ms"], "invalid_device_scheduler_profile");
      const schedulerOptions = { parallelism: parallel, ...(config.scheduler as DeviceSchedulerOptions | undefined) };
      requireThat(Number(schedulerOptions.parallelism) <= parallel, "invalid_device_scheduler_limits");
      workerControl.attachScheduler(new DeviceScheduler(local, actor, client, { capacity: () => workerControl.capacity(), run: (id, job, admission) => workerControl.runScheduled(id, job, admission) }, current, schedulerOptions));
      control = workerControl;
    }
    let closing: Promise<void> | undefined;
    const stop = () => { stopping = true; return control.stop(); };
    return { control, startDaemon: () => { current(); control.startDaemon(); }, stop, close: () => closing ??= stop().finally(() => { closed = true; db!.close(); }) };
  } catch (error) { db?.close(); throw error; }
}
