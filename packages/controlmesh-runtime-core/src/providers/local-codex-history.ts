import { realpathSync } from "node:fs";
import { join } from "node:path";
import type { RuntimeDatabase } from "../database";
import type { Principal } from "../kernel";
import { contains } from "../containers/plan";
import { object, requireThat, type LegacyTask } from "../value";
import { CodexHistoryCatalog } from "./claude-history-catalog";
import { CodexSessionStore } from "./codex-session";
import { DeviceNativeAdoptions } from "./device-native-adoption";
import type { LocalNativeHistoryPort } from "./local-native-history";

export interface CodexHistoryRegistration {
  sessions_directory: string; workspace: string; model: string; profile_digest: string;
}
/** Same local adoption authority as other providers; source lookup is registered, never candidate supplied. */
export class LocalCodexHistory implements LocalNativeHistoryPort {
  private readonly adoptions: DeviceNativeAdoptions<"codex">;
  constructor(db: RuntimeDatabase, actor: Principal, history: { directory: string; python: string }, stateRoot: string,
    configured: () => CodexHistoryRegistration, locate: (sessionId: string) => CodexSessionStore, current: () => void) {
    const config = configured();
    const selectedStore = (sessionId: string) => {
      current(); const selected = configured();
      requireThat(selected.sessions_directory === config.sessions_directory, "native_history_catalog_changed");
      const store = locate(sessionId);
      requireThat(store.deviceId === actor.device_id && realpathSync(store.path) === store.path
        && contains(selected.sessions_directory, store.path) && store.path !== selected.sessions_directory, "native_history_source_unregistered");
      return store;
    };
    const client = new CodexHistoryCatalog({ python: history.python, viewer_directory: history.directory,
      environment: { PATH: "/usr/bin:/bin", PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
      source_directory: config.sessions_directory, cache_directory: join(stateRoot, "history-codex") }, selectedStore);
    this.adoptions = new DeviceNativeAdoptions(db, actor, { deviceId: actor.device_id!, baseline: ref => selectedStore(ref.session_id).baseline(ref) }, client,
      workspaceId => { current(); requireThat(workspaceId === "local", "native_history_workspace_unregistered"); return configured().workspace; },
      (workspaceId, capability) => {
        current(); requireThat(workspaceId === "local" && capability === "codex.native", "native_history_capability_unregistered");
        const selected = configured(); return { directory: selected.workspace, model: selected.model, digest: selected.profile_digest };
      }, current);
  }
  private provider(value: string): void { requireThat(value === "codex", "local_history_provider_unqualified"); }
  search(provider: string, query: string) { this.provider(provider); return this.adoptions.search("local", query); }
  refresh(provider: string) { this.provider(provider); return this.adoptions.refresh("local"); }
  prepare(requestId: string, taskId: string, provider: string, sessionId: string) {
    this.provider(provider); return this.adoptions.prepare(requestId, { task_id: taskId, workspace_id: "local", capability: "codex.native", session_id: sessionId });
  }
  resolve(task: LegacyTask): LegacyTask {
    if (!object(task.native_session) || task.native_session.schema_version !== "controlmesh.device_native_adoption.v1") return task;
    this.provider(String(task.provider));
    const reference = this.adoptions.resolve(task.native_session, { task_id: task.task_id, workspace_id: "local", capability: "codex.native" });
    requireThat(task.model === reference.model && typeof task.repo_root === "string" && realpathSync(task.repo_root) === reference.directory, "native_adoption_task_mismatch");
    return { ...task, native_session: reference };
  }
  stop() { return this.adoptions.stop(); }
}
