import { opendirSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { Principal, RuntimeKernel, TaskSnapshot } from "../kernel";
import { digest, object, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import { GeminiSessionStore } from "./gemini-session";
import { GeminiTaskAdapter, type GeminiTaskConfiguration } from "./gemini-task-adapter";
import { GeminiTaskPreflight } from "./gemini-task-preflight";
import { geminiProbeCredentialRevision } from "./gemini-preflight";
import type { GeminiSettingsProbeInput } from "./gemini-settings-runner";
import type { PreflightCache } from "./preflight-cache";

/** Explicit native profile. Construction and session lookup never invoke the CLI. */
export class GeminiRegistration {
  private readonly config: { executable: string; model: string; sessions_directory: string; settings: GeminiSettingsProbeInput; credential_sources: string[]; timeout_ms: number };
  private readonly identity: string;
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache, private readonly actor: Principal,
    value: unknown, private readonly state: string, private readonly workspace: string, private readonly authorize: () => void) {
    requireThat(object(value) && value.cli_version === "0.59.0" && typeof value.executable === "string" && typeof value.model === "string"
      && /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/.test(value.model) && typeof value.sessions_directory === "string" && object(value.settings)
      && Array.isArray(value.credential_sources) && value.credential_sources.length <= 32 && value.credential_sources.every(path => typeof path === "string" && isAbsolute(path))
      && Object.keys(value).every(key => ["cli_version", "executable", "model", "sessions_directory", "settings", "credential_sources", "timeout_ms"].includes(key)), "invalid_local_gemini_profile");
    const settings = value.settings;
    requireThat(settings.workspace === workspace && typeof settings.node_executable === "string" && typeof settings.settings_module === "string"
      && object(settings.environment) && typeof settings.environment.HOME === "string" && isAbsolute(settings.environment.HOME)
      && settings.environment.NODE_OPTIONS === undefined && settings.environment.NODE_PATH === undefined
      && Object.entries(settings.environment).every(([key, val]) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) && typeof val === "string" && !val.includes("\0"))
      && [settings.runtime_files, settings.settings_sources].every(paths => Array.isArray(paths) && paths.length > 0 && paths.length <= 1024 && paths.every(path => typeof path === "string" && isAbsolute(path)))
      && object(settings.effective_policy) && typeof settings.effective_policy.module === "string" && typeof settings.effective_policy.admin_directory === "string"
      && isAbsolute(settings.effective_policy.admin_directory) && typeof settings.effective_policy.policy_filename === "string" && /^[A-Za-z0-9_.-]+\.toml$/.test(settings.effective_policy.policy_filename)
      && Array.isArray(settings.effective_policy.allowed_tools) && settings.effective_policy.allowed_tools.length === 0
      && Array.isArray(settings.effective_policy.sources) && settings.effective_policy.sources.length > 0 && settings.effective_policy.sources.length <= 32
      && settings.effective_policy.sources.every(path => typeof path === "string" && isAbsolute(path)), "invalid_local_gemini_settings");
    const timeout = value.timeout_ms ?? 60000;
    requireThat(Number.isSafeInteger(timeout) && Number(timeout) >= 1000 && Number(timeout) <= 300000, "invalid_native_timeout");
    this.config = structuredClone({ executable: value.executable, model: value.model, sessions_directory: value.sessions_directory,
      settings: settings as unknown as GeminiSettingsProbeInput, credential_sources: value.credential_sources as string[], timeout_ms: Number(timeout) });
    requireThat(this.config.settings.runtime_files.includes(this.config.executable) && this.config.settings.runtime_files.includes(this.config.settings.settings_module)
      && this.config.settings.runtime_files.includes(this.config.settings.effective_policy!.module), "gemini_runtime_files_unproven");
    for (const path of [this.config.executable, this.config.sessions_directory, workspace]) requireThat(isAbsolute(path) && realpathSync(path) === path, "native_store_path_must_be_canonical");
    requireThat(statSync(this.config.executable).isFile() && (statSync(this.config.executable).mode & 0o111) !== 0, "invalid_provider_executable");
    this.identity = digest([directoryIdentity(this.config.sessions_directory), directoryIdentity(workspace), this.config]);
  }
  private current = () => {
    const value: unknown = this.authorize();
    if (value !== undefined) { void Promise.resolve(value).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(digest([directoryIdentity(this.config.sessions_directory), directoryIdentity(this.workspace), this.config]) === this.identity, "gemini_registration_changed");
  };
  private locate(id: string) {
    requireThat(/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id), "invalid_native_session_id");
    this.current(); const reader = opendirSync(this.config.sessions_directory); let count = 0, found: string | undefined;
    try {
      for (let entry = reader.readSync(); entry; entry = reader.readSync()) {
        requireThat(++count <= 20000, "native_catalog_limit_or_changed");
        if (entry.isFile() && entry.name.startsWith("session-") && entry.name.endsWith(`-${id.slice(0, 8)}.jsonl`)) {
          const path = join(this.config.sessions_directory, entry.name);
          // Refuse ambiguous prefix matches rather than guessing another session's identity.
          new GeminiSessionStore(path, this.actor.device_id!, this.workspace).snapshot(id);
          requireThat(!found, "native_session_ambiguous"); found = path;
        }
      }
    } finally { reader.closeSync(); }
    this.current(); requireThat(found, "native_session_missing"); return found;
  }
  adapter(task: TaskSnapshot, recovery = false) {
    this.current(); requireThat(task.task.provider === "gemini" && task.task.model === this.config.model && task.task.repo_root === this.workspace
      && object(task.task.native_session) && typeof task.task.native_session.session_id === "string", "gemini_native_adoption_required");
    const config: GeminiTaskConfiguration = { executable: this.config.executable, cli_version: "0.59.0", state_home: this.state, model: this.config.model,
      session_path: this.locate(task.task.native_session.session_id), settings: this.config.settings, timeout_ms: this.config.timeout_ms };
    if (recovery) return new GeminiTaskAdapter(this.kernel, this.actor, config, {
      ensure: async () => { throw new Error("recovery_must_not_probe"); }, assertReady: () => { throw new Error("recovery_must_not_execute"); },
    }, this.current);
    const input = { executable: this.config.executable, model: this.config.model, native_configuration: {}, settings: this.config.settings,
      environment: this.config.settings.environment, credential_sources: this.config.credential_sources };
    const credentials = geminiProbeCredentialRevision(input);
    const current = () => { this.current(); requireThat(geminiProbeCredentialRevision(input) === credentials, "gemini_authentication_changed"); };
    return new GeminiTaskAdapter(this.kernel, this.actor, config, new GeminiTaskPreflight(this.cache, this.actor, input, current), current);
  }
}
