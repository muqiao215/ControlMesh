import { realpathSync } from "node:fs";
import { join } from "node:path";
import type { RuntimeDatabase } from "../database";
import type { Principal } from "../kernel";
import { digest, object, requireThat, type LegacyTask } from "../value";
import { HistoryClient } from "./history-client";
import { NativeSessionStore } from "./native-session";
import { DeviceNativeAdoptions } from "./device-native-adoption";
import { ClaudeHistoryCatalog } from "./claude-history-catalog";
import { findClaudeSession, type ClaudeTaskConfiguration } from "./claude-task-profile";

export interface LocalNativeHistoryPort {
  search(provider: string, query: string): Promise<Record<string, unknown>>;
  refresh(provider: string): Promise<Record<string, unknown>>;
  prepare(requestId: string, taskId: string, provider: string, sessionId: string): Promise<Record<string, unknown>>;
  resolve(task: LegacyTask): LegacyTask;
  stop(): Promise<void>;
}

/** The local computer is also a device: reuse its existing adoption registry, never create a task writer. */
export class LocalNativeHistory implements LocalNativeHistoryPort {
  private readonly adoptions: DeviceNativeAdoptions<"claude">;
  constructor(db: RuntimeDatabase, actor: Principal, history: { directory: string; python: string }, stateRoot: string,
    private readonly configured: (taskId: string) => ClaudeTaskConfiguration, current: () => void) {
    const config = configured("history-registration"), locate = (sessionId: string) => {
      current(); const store = findClaudeSession(config, actor.device_id!, sessionId);
      requireThat(store, "native_session_missing"); return store;
    };
    const client = new ClaudeHistoryCatalog({ python: history.python, viewer_directory: history.directory,
      environment: { PATH: "/usr/bin:/bin", PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
      source_directory: join(config.environment.config_directory, "projects"), cache_directory: join(stateRoot, "history-claude") }, locate);
    this.adoptions = new DeviceNativeAdoptions(db, actor, { deviceId: actor.device_id!, baseline: ref => locate(ref.session_id).baseline(ref) }, client,
      workspaceId => { requireThat(workspaceId === "local", "native_history_workspace_unregistered"); return config.workspace; },
      (workspaceId, capability, taskId) => {
        requireThat(workspaceId === "local" && capability === "claude.native", "native_history_capability_unregistered");
        const selected = configured(taskId); return { directory: selected.workspace, model: selected.model, digest: digest(selected) };
      }, current);
  }
  private provider(value: string): void { requireThat(value === "claude", "local_history_provider_unqualified"); }
  search(provider: string, query: string): Promise<Record<string, unknown>> { this.provider(provider); return this.adoptions.search("local", query); }
  refresh(provider: string): Promise<Record<string, unknown>> { this.provider(provider); return this.adoptions.refresh("local"); }
  prepare(requestId: string, taskId: string, provider: string, sessionId: string): Promise<Record<string, unknown>> {
    this.provider(provider); return this.adoptions.prepare(requestId, { task_id: taskId, workspace_id: "local", capability: "claude.native", session_id: sessionId });
  }
  resolve(task: LegacyTask): LegacyTask {
    if (!object(task.native_session) || task.native_session.schema_version !== "controlmesh.device_native_adoption.v1") return task;
    this.provider(String(task.provider));
    const reference = this.adoptions.resolve(task.native_session, { task_id: task.task_id, workspace_id: "local", capability: "claude.native" });
    requireThat(task.provider === reference.provider && task.model === reference.model && typeof task.repo_root === "string"
      && realpathSync(task.repo_root) === reference.directory, "native_adoption_task_mismatch");
    return { ...task, native_session: reference };
  }
  stop(): Promise<void> { return this.adoptions.stop(); }
}

/** OpenCode uses its registered SQLite source directly; History remains a read-only catalog. */
export class LocalOpenCodeHistory implements LocalNativeHistoryPort {
  private readonly adoptions: DeviceNativeAdoptions<"opencode">;
  constructor(db: RuntimeDatabase, actor: Principal, history: { directory: string; python: string },
    configured: () => { data_home: string; workspace: string; model: string; profile_digest: string }, current: () => void) {
    const config = configured(), store = new NativeSessionStore(join(config.data_home, "opencode/opencode.db"), actor.device_id!);
    const client = new HistoryClient({ python: history.python, viewer_directory: history.directory,
      environment: { PATH: "/usr/bin:/bin", PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" } }, store);
    this.adoptions = new DeviceNativeAdoptions(db, actor, store, client,
      workspaceId => { current(); requireThat(workspaceId === "local", "native_history_workspace_unregistered"); return configured().workspace; },
      (workspaceId, capability) => {
        current(); requireThat(workspaceId === "local" && capability === "opencode.native", "native_history_capability_unregistered");
        const selected = configured(); return { directory: selected.workspace, model: selected.model, digest: selected.profile_digest };
      }, current);
  }
  private provider(value: string): void { requireThat(value === "opencode", "local_history_provider_unqualified"); }
  search(provider: string, query: string): Promise<Record<string, unknown>> { this.provider(provider); return this.adoptions.search("local", query); }
  refresh(provider: string): Promise<Record<string, unknown>> { this.provider(provider); return this.adoptions.refresh("local"); }
  prepare(requestId: string, taskId: string, provider: string, sessionId: string): Promise<Record<string, unknown>> {
    this.provider(provider); return this.adoptions.prepare(requestId, { task_id: taskId, workspace_id: "local", capability: "opencode.native", session_id: sessionId });
  }
  resolve(task: LegacyTask): LegacyTask {
    if (!object(task.native_session) || task.native_session.schema_version !== "controlmesh.device_native_adoption.v1") return task;
    this.provider(String(task.provider));
    const reference = this.adoptions.resolve(task.native_session, { task_id: task.task_id, workspace_id: "local", capability: "opencode.native" });
    requireThat(task.provider === reference.provider && task.model === reference.model && typeof task.repo_root === "string"
      && realpathSync(task.repo_root) === reference.directory, "native_adoption_task_mismatch");
    return { ...task, native_session: reference };
  }
  stop(): Promise<void> { return this.adoptions.stop(); }
}

/** Route only explicitly registered providers; no inference from installed binaries or history. */
export class RegisteredLocalHistory implements LocalNativeHistoryPort {
  constructor(private readonly providers: ReadonlyMap<string, LocalNativeHistoryPort>) {}
  private port(provider: string): LocalNativeHistoryPort {
    const port = this.providers.get(provider); requireThat(port, "local_history_provider_unqualified"); return port;
  }
  search(provider: string, query: string) { return this.port(provider).search(provider, query); }
  refresh(provider: string) { return this.port(provider).refresh(provider); }
  prepare(id: string, task: string, provider: string, session: string) { return this.port(provider).prepare(id, task, provider, session); }
  resolve(task: LegacyTask): LegacyTask {
    if (!object(task.native_session) || task.native_session.schema_version !== "controlmesh.device_native_adoption.v1") return task;
    return this.port(String(task.provider)).resolve(task);
  }
  async stop(): Promise<void> { await Promise.all([...this.providers.values()].map(port => port.stop())); }
}
