import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ProcessSupervisor, type ProcessAdmission, type ProcessOutcome, type ProcessSpec } from "../process-supervisor";
import { digest, object, requireThat } from "../value";
import { nativeFailure, type PreflightObservation } from "./opencode-events";
import type { OpenCodeProbeInput } from "./opencode-preflight";
import type { ProviderProbeReport } from "./probe-report";

export type ClaudeProbeInput = OpenCodeProbeInput;
interface Runner { run(spec: ProcessSpec, admission: ProcessAdmission): Promise<ProcessOutcome>; runtimeDigest?(): string }
const VERSION = "2.1.263";
const AUTH_KEYS = new Set(["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE"]);

/** Classify native error fields only. Assistant prose never supplies quota/reset evidence. */
export function judgeClaudePreflight(outcome: ProcessOutcome, model: string): { observation: PreflightObservation; permissions: string | null } {
  const unavailable = (reason: string) => ({ observation: { status: "unavailable", reason, session_id: null, failure: null } as PreflightObservation, permissions: null });
  let rows: Record<string, unknown>[];
  try {
    const values: unknown[] = outcome.stdout.trim().split("\n").filter(Boolean).map(line => JSON.parse(line));
    if (!values.every(object)) return unavailable("invalid_native_output"); rows = values;
  } catch { return unavailable("invalid_native_output"); }
  const terminal = rows.filter(row => row.type === "result");
  if (terminal.length !== 1) return unavailable("native_completion_unproven");
  const result = terminal[0];
  if (result.is_error === true) {
    const fields = [result.error, ...(Array.isArray(result.errors) ? result.errors : []), result.result]
      .flatMap(value => typeof value === "string" ? [value] : object(value) && typeof value.message === "string" ? [value.message] : []);
    const message = fields.join("\n");
    const failure = nativeFailure(/you['’]?ve hit your limit|exceeded your current quota/i.test(message) ? `usage limit reached; ${message}` : message);
    return { observation: { status: failure.code === "rate_limited" ? "degraded" : "unavailable", reason: failure.code, session_id: null, failure } as PreflightObservation, permissions: null };
  }
  if (outcome.reason !== "exited" || outcome.exit_code !== 0 || result.subtype !== "success" || result.is_error !== false) return unavailable("native_completion_unproven");
  const init = rows.filter(row => row.type === "system" && row.subtype === "init");
  if (init.length !== 1 || init[0].model !== model || typeof init[0].session_id !== "string" || result.session_id !== init[0].session_id) return unavailable("native_probe_identity_mismatch");
  if (!Array.isArray(init[0].tools) || init[0].tools.length !== 0 || !Array.isArray(init[0].mcp_servers) || init[0].mcp_servers.length !== 0
    || !Array.isArray(init[0].plugins) || init[0].plugins.length !== 0) return unavailable("native_tool_denial_unverified");
  const assistants = rows.filter(row => row.type === "assistant");
  const text: string[] = [];
  for (const row of assistants) {
    if (row.session_id !== result.session_id || !object(row.message) || row.message.model !== model || !Array.isArray(row.message.content)) return unavailable("native_probe_identity_mismatch");
    for (const part of row.message.content) {
      if (!object(part) || !["text", "thinking"].includes(String(part.type))) return unavailable("native_tool_denial_unverified");
      if (part.type === "text" && typeof part.text === "string") text.push(part.text);
    }
  }
  if (rows.some(row => row.type === "user" || row.type === "tool_result" || row.type === "error") || result.num_turns !== 1
    || typeof result.result !== "string" || text.join("") !== result.result || !/^PONG\.?$/.test(result.result.trim())) return unavailable("missing_native_completion_or_sentinel");
  return { observation: { status: "ready", reason: "native_sentinel_verified", session_id: result.session_id, failure: null },
    permissions: digest({ profile: "claude-native-none-v1", cli_version: VERSION, tools: [], mcp_servers: [], safe_mode: true }) };
}

/** Isolated print-mode probe, with native tools/configuration disabled and no saved session. */
export class ClaudePreflight {
  constructor(private readonly runner: Runner = new ProcessSupervisor()) {}
  runtimeDigest(): string | undefined { return this.runner.runtimeDigest?.(); }
  async probe(input: ClaudeProbeInput): Promise<ProviderProbeReport> {
    requireThat(/^[^\s\x00]{1,256}$/.test(input.model), "invalid_provider_model");
    requireThat(Object.keys(input.environment).every(key => AUTH_KEYS.has(key)) && Object.values(input.environment).every(value => typeof value === "string" && !value.includes("\0")), "unqualified_claude_probe_environment");
    requireThat(!existsSync("/etc/claude-code"), "claude_managed_configuration_unqualified");
    const configDigest = digest(input.native_configuration), envDigest = digest(input.environment), runtimeDigest = this.runtimeDigest();
    const timeout = input.timeout_ms ?? 45_000;
    requireThat(Number.isSafeInteger(timeout) && timeout >= 1000 && timeout <= 60_000, "invalid_probe_timeout");
    const started = performance.now(), root = mkdtempSync(join(tmpdir(), "cm-claude-preflight-"));
    let version = "", invoked = false;
    const report = (observation: PreflightObservation, permissions: string | null = null): ProviderProbeReport => ({ model: input.model,
      config_digest: configDigest, cli_version: version, observation, permission_digest: permissions, tool_count: 0,
      model_invoked: invoked, duration_ms: Math.round(performance.now() - started), ...(runtimeDigest ? { runtime_digest: runtimeDigest } : {}) });
    try {
      const env = { ...input.environment, HOME: root, CLAUDE_CONFIG_DIR: join(root, "config"), PATH: "/usr/bin:/bin", LANG: "C.UTF-8",
        CLAUDE_CODE_SAFE_MODE: "1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1", CLAUDE_CODE_MAX_OUTPUT_TOKENS: "128", MAX_THINKING_TOKENS: "0" };
      const run = (args: string[], model = false) => {
        const remaining = Math.floor(timeout - (performance.now() - started)); requireThat(remaining > 0, "probe_deadline_expired");
        return this.runner.run({ command: [input.executable, ...args], cwd: root, env, timeout_ms: Math.min(remaining, model ? 30_000 : 10_000), max_output_bytes: 512 * 1024 },
          { signal: input.signal, remainingMs: input.remainingMs, assertCurrent: () => {
            requireThat(digest(input.native_configuration) === configDigest && digest(input.environment) === envDigest, "native_configuration_changed");
            requireThat(this.runtimeDigest() === runtimeDigest && !existsSync("/etc/claude-code"), "native_runtime_changed");
            return input.assertCurrent();
          } });
      };
      const versionResult = await run(["--version"]); version = versionResult.stdout.trim().replace(/ \(Claude Code\)$/, "");
      if (versionResult.reason !== "exited" || versionResult.exit_code !== 0 || version !== VERSION) return report({ status: "unavailable", reason: "unsupported_claude_version", session_id: null, failure: null });
      invoked = true;
      const outcome = await run(["--print", "--output-format", "stream-json", "--verbose", "--safe-mode", "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-chrome", "--disable-slash-commands", "--tools", "", "--permission-mode", "dontAsk",
        "--no-session-persistence", "--model", input.model, "--effort", "low", "--max-turns", "1", "--", "Reply with exactly PONG."], true);
      const checked = judgeClaudePreflight(outcome, input.model); return report(checked.observation, checked.permissions);
    } finally { rmSync(root, { recursive: true, force: true }); }
  }
}
