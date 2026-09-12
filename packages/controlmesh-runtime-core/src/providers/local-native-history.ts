import { realpathSync } from "node:fs";
import { join } from "node:path";
import type { RuntimeDatabase } from "../database";
import type { Principal } from "../kernel";
import { digest, object, requireThat, type LegacyTask } from "../value";
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
