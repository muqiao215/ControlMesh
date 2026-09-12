import { existsSync, opendirSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import type { Principal, RuntimeKernel, TaskSnapshot } from "../kernel";
import { privateFile } from "../private-runtime-file";
import { digest, object, requireThat } from "../value";
import { directoryIdentity } from "./native-manifest";
import { CodexSessionStore } from "./codex-session";
import { CodexTaskAdapter, type CodexTaskConfiguration } from "./codex-task-adapter";
import { CodexTaskPreflight } from "./codex-task-preflight";
import { codexProbeCredentialKeys } from "./codex-preflight";
import { codexProviderArguments } from "./codex-provider-profile";
import type { PreflightCache } from "./preflight-cache";

export function findCodexSession(sessions: string, device: string, id: string): CodexSessionStore {
  requireThat(/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(id), "invalid_native_session_id");
  requireThat(isAbsolute(sessions) && realpathSync(sessions) === sessions, "native_store_path_must_be_canonical");
  const identity = digest(directoryIdentity(sessions)), pending = [sessions];
  let entries = 0, directories = 0, found: string | undefined;
  while (pending.length) {
    const directory = pending.pop()!;
    requireThat(++directories <= 512 && realpathSync(directory) === directory, "native_catalog_limit_or_changed");
    const reader = opendirSync(directory);
    try {
      for (let entry = reader.readSync(); entry; entry = reader.readSync()) {
        requireThat(++entries <= 20000, "native_catalog_limit_or_changed");
        const path = join(directory, entry.name);
        if (entry.isDirectory()) pending.push(path);
        if (entry.isFile() && entry.name.startsWith("rollout-") && entry.name.endsWith(`-${id}.jsonl`)) {
          requireThat(!found, "native_session_ambiguous"); found = path;
        }
      }
    } finally { reader.closeSync(); }
  }
  requireThat(digest(directoryIdentity(sessions)) === identity, "native_history_catalog_changed");
  requireThat(found, "native_session_missing");
  return new CodexSessionStore(found, device);
}

/** Registered native state/config only; construction and History access never probe a model. */
export class CodexRegistration {
  private readonly config: { executable: string; codex_home: string; model: string; environment: Record<string, string>; timeout_ms: number };
  private readonly identity: string;
  readonly sessions: string;
  constructor(private readonly kernel: RuntimeKernel, private readonly cache: PreflightCache, private readonly actor: Principal,
    value: unknown, private readonly state: string, private readonly workspace: string, private readonly authorize: () => void) {
    requireThat(object(value) && value.cli_version === "0.154.0" && typeof value.executable === "string" && typeof value.codex_home === "string"
      && typeof value.model === "string" && /^[^\s\x00]{1,256}$/.test(value.model) && object(value.environment)
      && Object.keys(value.environment).every(key => codexProbeCredentialKeys.includes(key))
      && Object.values(value.environment).every(v => typeof v === "string" && !v.includes("\0"))
      && Object.keys(value).every(key => ["cli_version", "executable", "codex_home", "model", "environment", "timeout_ms"].includes(key)), "invalid_local_codex_profile");
    const timeout = value.timeout_ms ?? 60000;
    requireThat(Number.isSafeInteger(timeout) && Number(timeout) >= 1000 && Number(timeout) <= 300000, "invalid_native_timeout");
    this.config = { executable: value.executable, codex_home: value.codex_home, model: value.model, environment: value.environment as Record<string, string>, timeout_ms: Number(timeout) };
    for (const path of [this.config.executable, this.config.codex_home, workspace]) requireThat(isAbsolute(path) && realpathSync(path) === path, "native_store_path_must_be_canonical");
    requireThat(statSync(this.config.executable).isFile() && (statSync(this.config.executable).mode & 0o111) !== 0, "invalid_provider_executable");
    codexProviderArguments(this.config.environment.OPENAI_BASE_URL);
    this.sessions = join(this.config.codex_home, "sessions");
    this.identity = digest([directoryIdentity(this.config.codex_home), directoryIdentity(this.sessions), directoryIdentity(workspace), this.config]);
  }
  private current = () => {
    const result: unknown = this.authorize();
    if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    requireThat(digest([directoryIdentity(this.config.codex_home), directoryIdentity(this.sessions), directoryIdentity(this.workspace), this.config]) === this.identity, "codex_registration_changed");
  };
  private authentication() {
    const path = join(this.config.codex_home, "auth.json");
    return existsSync(path) ? privateFile(path, 65536) : undefined;
  }
  history = () => {
    this.current(); return { sessions_directory: this.sessions, workspace: this.workspace, model: this.config.model,
      profile_digest: digest({ identity: this.identity, credential_revision: this.authentication()?.revision ?? null }) };
  };
  locate = (id: string) => { this.current(); return findCodexSession(this.sessions, this.actor.device_id!, id); };
  adapter(task: TaskSnapshot, recovery = false): CodexTaskAdapter {
    this.current(); requireThat(task.task.provider === "codex" && task.task.model === this.config.model && task.task.repo_root === this.workspace
      && object(task.task.native_session) && typeof task.task.native_session.session_id === "string", "codex_native_adoption_required");
    const store = this.locate(task.task.native_session.session_id);
    const config: CodexTaskConfiguration = { executable: this.config.executable, cli_version: "0.154.0", state_home: this.state,
      codex_home: this.config.codex_home, rollout_path: store.path, sandbox: "read-only", model: this.config.model, timeout_ms: this.config.timeout_ms,
      environment: { ...this.config.environment, HOME: dirname(this.config.codex_home), CODEX_HOME: this.config.codex_home, PATH: "/usr/bin:/bin" } };
    // Recovery consumes retained evidence; it must not require fresh credentials or readiness.
    if (recovery) return new CodexTaskAdapter(this.kernel, this.actor, config, {
      ensure: async () => { throw new Error("recovery_must_not_probe"); }, assertReady: () => { throw new Error("recovery_must_not_execute"); },
    }, this.current);
    const auth = this.authentication(), current = () => {
      this.current(); requireThat(this.authentication()?.revision === auth?.revision, "codex_authentication_changed");
    };
    const ready = new CodexTaskPreflight(this.cache, this.actor, { executable: this.config.executable, model: this.config.model,
      native_configuration: {}, environment: this.config.environment, ...(auth ? { auth_json: auth.bytes.toString("utf8") } : {}) }, current);
    return new CodexTaskAdapter(this.kernel, this.actor, config, ready, current);
  }
}
