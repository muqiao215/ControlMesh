import { realpathSync } from "node:fs";
import { ProcessSupervisor, type ProcessAdmission, type ProcessSpec, type ProcessOutcome } from "../process-supervisor";
import { object, requireThat } from "../value";
import { NativeSessionStore, type NativeSessionRef } from "./native-session";

interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome> }
export interface HistoryConfig {
  python: string;
  viewer_directory: string;
  environment: Record<string, string>;
}

/** Local, bounded CLI integration; does not require the Viewer Web server or a transcript export. */
export class HistoryClient {
  constructor(private readonly config: HistoryConfig, private readonly store: NativeSessionStore,
    private readonly runner: Runner = new ProcessSupervisor()) {}

  private async invoke(args: string[], assertCurrent: () => void): Promise<unknown> {
    const result = await this.runner.run({ command: [this.config.python, "-m", "history_core", "--source", "opencode", "--source-path", this.store.path, ...args],
      cwd: realpathSync(this.config.viewer_directory), env: this.config.environment, timeout_ms: 10_000, max_output_bytes: 256 * 1024 }, { assertCurrent });
    requireThat(result.reason === "exited" && result.exit_code === 0, "history_service_unavailable");
    try { return JSON.parse(result.stdout); } catch { throw new Error("invalid_history_response"); }
  }

  async inspect(sessionId: string, assertCurrent: () => void): Promise<NativeSessionRef> {
    requireThat(/^ses_[A-Za-z0-9]{1,192}$/.test(sessionId), "invalid_native_session_id");
    const candidate = await this.invoke(["native-reference", sessionId, "--device-id", this.store.deviceId], assertCurrent);
    requireThat(object(candidate) && candidate.schema_version === "history.native_candidate.v2" && candidate.authorization === "context_only" && object(candidate.reference), "unsupported_history_candidate");
    requireThat(candidate.reference.session_id === sessionId, "history_session_mismatch");
    assertCurrent();
    return this.store.validate(candidate.reference as unknown as NativeSessionRef);
  }

  async search(query: string, project: string | null, assertCurrent: () => void): Promise<{ session_id: string; directory: string; title: string }[]> {
    requireThat(query.length <= 256 && !query.includes("\0"), "invalid_history_query");
    const payload = await this.invoke(["search", "--query", query, "--limit", "20", ...(project ? ["--project", realpathSync(project)] : [])], assertCurrent);
    requireThat(object(payload) && Array.isArray(payload.items) && payload.items.length <= 20, "invalid_history_candidates");
    // Search results are suggestions. Only inspect() produces a revalidated native reference.
    return payload.items.filter(item => object(item) && typeof item.id === "string" && /^ses_[A-Za-z0-9]{1,192}$/.test(item.id) && typeof item.cwd === "string")
      .map(item => ({ session_id: item.id, directory: item.cwd, title: typeof item.title === "string" ? item.title.slice(0, 512) : "" }));
  }
}
