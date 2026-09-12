import { mkdtempSync, mkdirSync, rmSync, writeFileSync, realpathSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome, type ProcessSpec } from "../process-supervisor";
import { digest, object, requireThat } from "../value";
import { codexNativeFailure, codexFailureLine } from "./codex-failure";
import type { PreflightObservation, ProviderFailure } from "./opencode-events";
import type { OpenCodeProbeInput } from "./opencode-preflight";
import type { ProviderProbeReport } from "./probe-report";

export interface CodexProbeInput extends OpenCodeProbeInput {
  /** Trusted owner supplies a private snapshot; no implicit access to the user's auth store. */
  auth_json?: string;
}
interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome>; runtimeDigest?(): string }
export const codexProbeVersion = "0.154.0";
export const codexProbeProfile = "codex-isolated-readonly-v1";
export const codexProbeCredentialKeys = Object.freeze(["OPENAI_API_KEY", "OPENAI_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE"]);
export function codexProbeCredentialRevision(input: Pick<CodexProbeInput, "environment" | "auth_json">): string {
  return digest({ environment: input.environment, auth_json: input.auth_json ?? null });
}
const disabled = ["shell_tool", "unified_exec", "shell_snapshot", "shell_snapshot_v2", "apps", "hooks", "multi_agent", "multi_agent_v2",
  "browser_use", "browser_use_external", "computer_use", "in_app_browser", "image_generation", "memories", "skill_search", "code_mode", "code_mode_host", "sleep_tool"];
export function codexProbeCommand(executable: string, model: string, baseUrl?: string): string[] {
  requireThat(typeof model === "string" && /^[^\s\x00]{1,256}$/.test(model), "invalid_provider_model");
  const provider: string[] = [];
  if (baseUrl !== undefined) {
    let url: URL; try { url = new URL(baseUrl); } catch { requireThat(false, "invalid_codex_probe_endpoint"); }
    requireThat(["http:", "https:"].includes(url!.protocol) && !url!.username && !url!.password && !url!.search && !url!.hash, "invalid_codex_probe_endpoint");
    for (const [key, value] of Object.entries({ model_provider: "controlmesh_preflight", "model_providers.controlmesh_preflight.name": "ControlMesh preflight",
      "model_providers.controlmesh_preflight.base_url": baseUrl, "model_providers.controlmesh_preflight.env_key": "OPENAI_API_KEY",
      "model_providers.controlmesh_preflight.wire_api": "responses", "model_providers.controlmesh_preflight.requires_openai_auth": false })) provider.push("-c", `${key}=${JSON.stringify(value)}`);
  }
  return [executable, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
    "-c", 'approval_policy="never"', "-c", 'web_search="disabled"', "-c", "mcp_servers={}",
    ...disabled.flatMap(feature => ["--disable", feature]), ...provider, "--model", model, "--skip-git-repo-check", "--", "-"];
}

/** A successful probe proves this bounded response, not general native sandbox enforcement. */
export function judgeCodexPreflight(outcome: ProcessOutcome): PreflightObservation {
  const unavailable = (reason: string): PreflightObservation => ({ status: "unavailable", reason, session_id: null, failure: null });
  let rows: Record<string, unknown>[];
  try {
    const parsed: unknown[] = outcome.stdout.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
    if (!parsed.every(object)) return unavailable("invalid_native_output"); rows = parsed;
  } catch { return unavailable("invalid_native_output"); }
  let failure: ProviderFailure | null = null;
  const priority = ["quota_exhausted", "authentication_failed", "model_unavailable", "rate_limited", "provider_error"];
  for (const row of rows) {
    const next = codexNativeFailure(row);
    if (next && (!failure || priority.indexOf(next.code) < priority.indexOf(failure.code))) failure = next;
  }
  if (failure) return { status: failure.code === "rate_limited" ? "degraded" : "unavailable", reason: failure.code, session_id: null, failure };
  if (outcome.reason !== "exited" || outcome.exit_code !== 0) return unavailable("native_completion_unproven");
  const first = rows[0], last = rows.at(-1);
  if (first?.type !== "thread.started" || typeof first.thread_id !== "string" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(first.thread_id)
    || rows[1]?.type !== "turn.started" || last?.type !== "turn.completed") return unavailable("native_completion_unproven");
  const ids = new Set<string>(); let text = "";
  for (const row of rows.slice(2, -1)) {
    if (row.thread_id !== undefined && row.thread_id !== first.thread_id) return unavailable("native_probe_identity_mismatch");
    if (row.type !== "item.completed" || !object(row.item) || !["agent_message", "reasoning"].includes(String(row.item.type))) return unavailable("native_probe_unexpected_event");
    const item = row.item;
    if (typeof item.id !== "string" || !item.id || ids.has(item.id) || typeof item.text !== "string") return unavailable("invalid_native_output");
    ids.add(item.id);
    if (item.type === "agent_message") { if (text) return unavailable("native_completion_unproven"); text = item.text; }
  }
  if (rows.some(row => row.thread_id !== undefined && row.thread_id !== first.thread_id)
    || !/^PONG\.?$/.test(text.trim())) return unavailable("missing_native_completion_or_sentinel");
  return { status: "ready", reason: "native_sentinel_verified", session_id: first.thread_id, failure: null };
}

function executableIdentity(input: CodexProbeInput): string {
  const path = realpathSync(input.executable), stat = statSync(path, { bigint: true });
  requireThat(stat.isFile() && (stat.mode & 0o111n) !== 0n, "invalid_provider_executable");
  return digest([path, stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String));
}

/** Explicit isolated native probe; all retry decisions belong to PreflightCache. */
export class CodexPreflight {
  constructor(private readonly runner: Runner = new ProcessSupervisor()) {}
  runtimeDigest(input?: CodexProbeInput): string | undefined {
    return input ? digest({ profile: codexProbeProfile, executable: executableIdentity(input), runner: this.runner.runtimeDigest?.() ?? null }) : this.runner.runtimeDigest?.();
  }
  async probe(input: CodexProbeInput): Promise<ProviderProbeReport> {
    const command = codexProbeCommand(input.executable, input.model, input.environment.OPENAI_BASE_URL);
    requireThat(isAbsolute(input.executable), "absolute_process_paths_required");
    requireThat(Object.keys(input.native_configuration).length === 0, "unqualified_codex_probe_configuration");
    requireThat(Object.keys(input.environment).every(key => codexProbeCredentialKeys.includes(key))
      && Object.values(input.environment).every(value => typeof value === "string" && !value.includes("\0")), "unqualified_codex_probe_environment");
    if (input.auth_json !== undefined) {
      requireThat(typeof input.auth_json === "string" && Buffer.byteLength(input.auth_json) <= 65536, "invalid_codex_auth_snapshot");
      let auth: unknown; try { auth = JSON.parse(input.auth_json); } catch { requireThat(false, "invalid_codex_auth_snapshot"); }
      requireThat(object(auth), "invalid_codex_auth_snapshot");
    }
    const executable = executableIdentity(input), configuration = digest(input.native_configuration), credentials = codexProbeCredentialRevision(input), runtime = this.runtimeDigest(input);
    const timeout = input.timeout_ms ?? 45000;
    requireThat(Number.isSafeInteger(timeout) && timeout >= 1000 && timeout <= 60000, "invalid_probe_timeout");
    const started = performance.now(), root = mkdtempSync(join(tmpdir(), "cm-codex-preflight-"));
    let version = "", invoked = false;
    const current = () => {
      requireThat(digest(input.native_configuration) === configuration && codexProbeCredentialRevision(input) === credentials, "native_configuration_changed");
      requireThat(executableIdentity(input) === executable && this.runtimeDigest(input) === runtime, "native_runtime_changed");
      const result: unknown = input.assertCurrent();
      if (result !== undefined) { void Promise.resolve(result).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
    };
    try {
      const home = join(root, "home"), workspace = join(root, "workspace");
      mkdirSync(home, { mode: 0o700 }); mkdirSync(workspace, { mode: 0o700 });
      if (input.auth_json !== undefined) writeFileSync(join(home, "auth.json"), input.auth_json, { mode: 0o600, flag: "wx" });
      const env = { ...input.environment, HOME: home, CODEX_HOME: home, XDG_CONFIG_HOME: home, XDG_DATA_HOME: home, XDG_CACHE_HOME: home,
        PATH: "/usr/bin:/bin", LANG: "C.UTF-8" };
      const run = (argv: string[], model: boolean) => {
        current();
        const remaining = Math.floor(timeout - (performance.now() - started)); requireThat(remaining > 0, "probe_deadline_expired");
        return this.runner.run({ command: argv, cwd: workspace, env, timeout_ms: Math.min(remaining, model ? 30000 : 10000), max_output_bytes: 512 * 1024,
          ...(model ? { stdin_text: "Reply with exactly PONG." } : {}) }, { assertCurrent: current, signal: input.signal, remainingMs: input.remainingMs,
            ...(model ? { abortOnStdoutLine: (line: string) => codexFailureLine(line) !== null } : {}) });
      };
      const report = (observation: PreflightObservation): ProviderProbeReport => ({ model: input.model, config_digest: configuration, cli_version: version,
        observation, permission_digest: observation.status === "ready" ? digest({ profile: codexProbeProfile, version, command: command.slice(1) }) : null,
        tool_count: null, model_invoked: invoked, duration_ms: Math.round(performance.now() - started), ...(runtime ? { runtime_digest: runtime } : {}) });
      const result = await run([input.executable, "--version"], false);
      version = result.stdout.trim().replace(/^codex-cli /, "");
      if (result.reason !== "exited" || result.exit_code !== 0 || version !== codexProbeVersion) return report({ status: "unavailable", reason: "unsupported_codex_version", session_id: null, failure: null });
      current(); invoked = true;
      const outcome = await run(command, true); current();
      return report(judgeCodexPreflight(outcome));
    } finally { rmSync(root, { recursive: true, force: true }); }
  }
}
