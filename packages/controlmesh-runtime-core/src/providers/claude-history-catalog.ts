import { lstatSync, mkdirSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome, type ProcessSpec } from "../process-supervisor";
import { directoryIdentity } from "./native-manifest";
import { contains } from "../containers/plan";
import { digest, object, requireThat } from "../value";
import { ClaudeHistoryClient, type HistoryConfig } from "./history-client";
import type { ClaudeSessionStore, ClaudeSessionRef } from "./claude-session";

interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> }
export interface ClaudeHistoryCatalogConfig extends HistoryConfig { source_directory: string; cache_directory: string }

function canonicalDirectory(path: string): void {
  requireThat(isAbsolute(path) && resolve(path) === path, "native_history_path_must_be_canonical");
  let ancestor = path;
  for (;;) {
    try {
      const stat = lstatSync(ancestor);
      requireThat(stat.isDirectory() && realpathSync(ancestor) === ancestor, "native_history_path_must_be_canonical"); return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      const parent = dirname(ancestor); requireThat(parent !== ancestor, "native_history_path_must_be_canonical"); ancestor = parent;
    }
  }
}

/** Explicit History-owned derived index; lookup paths always come from the registered native catalog. */
export class ClaudeHistoryCatalog {
  private refreshing = false;
  private readonly cacheIdentity: string;
  constructor(private readonly config: ClaudeHistoryCatalogConfig, private readonly locate: (sessionId: string) => ClaudeSessionStore,
    private readonly runner: Runner = new ProcessSupervisor()) {
    requireThat(isAbsolute(config.source_directory) && isAbsolute(config.cache_directory)
      && !contains(config.source_directory, config.cache_directory) && !contains(config.cache_directory, config.source_directory), "native_history_cache_overlaps_source");
    canonicalDirectory(config.source_directory); canonicalDirectory(config.cache_directory);
    mkdirSync(config.cache_directory, { recursive: true, mode: 0o700 });
    const cache = statSync(config.cache_directory);
    requireThat(realpathSync(config.cache_directory) === config.cache_directory && cache.isDirectory()
      && cache.uid === process.getuid?.() && (cache.mode & 0o077) === 0, "native_history_private_cache_required");
    this.cacheIdentity = digest(directoryIdentity(config.cache_directory));
  }
  private async invoke(args: string[], current: () => void): Promise<Record<string, unknown>> {
    current(); const identity = directoryIdentity(this.config.source_directory);
    requireThat(identity.path === this.config.source_directory, "native_history_path_must_be_canonical");
    const source = digest(identity);
    const assertCurrent = () => {
      current(); requireThat(digest(directoryIdentity(this.config.source_directory)) === source
        && digest(directoryIdentity(this.config.cache_directory)) === this.cacheIdentity, "native_history_catalog_changed");
    };
    const result = await this.runner.run({ command: [this.config.python, "-m", "history_core", "--source", "claude", "--source-path", this.config.source_directory,
      "--data-dir", this.config.cache_directory, ...args], cwd: realpathSync(this.config.viewer_directory), env: this.config.environment,
      timeout_ms: 10000, max_output_bytes: 256 * 1024 }, { assertCurrent });
    requireThat(result.reason === "exited" && result.exit_code === 0, "history_service_unavailable"); assertCurrent();
    const payload: unknown = JSON.parse(result.stdout); requireThat(object(payload), "invalid_history_response"); return payload;
  }
  async refresh(_project: string, current: () => void): Promise<Record<string, unknown>> {
    requireThat(!this.refreshing, "native_history_refresh_in_progress"); this.refreshing = true;
    try {
      const result = await this.invoke(["refresh"], current);
      requireThat(result.source === "claude" && result.status === "refreshed" && result.native_source_read_only === true, "invalid_history_refresh");
      return { source: "claude", status: "refreshed", refresh_policy: "explicit", native_source_read_only: true };
    } finally { this.refreshing = false; }
  }
  async search(query: string, project: string | null, current: () => void): Promise<{ session_id: string; directory: string; title: string }[]> {
    requireThat(typeof query === "string" && Buffer.byteLength(query) <= 256 && !query.includes("\0"), "invalid_history_query");
    const result = await this.invoke(["search", "--query", query, "--limit", "20", ...(project ? ["--project", realpathSync(project)] : [])], current);
    requireThat(Array.isArray(result.items) && result.items.length <= 20, "invalid_history_candidates");
    return result.items.filter(item => object(item) && typeof item.id === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(item.id)
      && typeof item.cwd === "string").map(item => ({ session_id: item.id, directory: item.cwd, title: typeof item.title === "string" ? item.title.slice(0, 512) : "" }));
  }
  inspect(sessionId: string, current: () => void): Promise<ClaudeSessionRef> {
    current(); return new ClaudeHistoryClient(this.config, this.locate(sessionId), this.runner).inspect(sessionId, current);
  }
}
