import { decodeSourceScope, type SourceScope } from "./execution-context";
import { sourceRequiresSandbox, type ExecutionPolicyDecision } from "./execution-policy";
import { object, requireThat } from "./value";

export interface ToolGrantSnapshot {
  readonly schema_version: "controlmesh.tool_grant.v1";
  readonly tool_allow: readonly string[];
  readonly tool_deny: readonly string[];
  readonly network_policy: "sandbox_default" | "no_network";
  readonly writable_roots: readonly string[];
  readonly confirmation_policy: "provider_runtime" | "controller_required";
  readonly provider_surface: string;
  readonly reply_transport: string;
  readonly reply_chat: string;
  readonly reply_topic: string;
  readonly reply_thread: string;
}
type GrantInput = Partial<Omit<ToolGrantSnapshot, "schema_version">>;
const surfaces = ["", "claude_tool_flags", "codex_sandbox", "gemini_policy", "opencode_config"];
function token(value: unknown): string {
  const text = value ?? "";
  requireThat(typeof text === "string" && /^[^\r\n\x00]{0,128}$/u.test(text), "invalid_tool_grant_identity");
  return text;
}
function tokens(value: unknown, roots = false): readonly string[] {
  if (value === undefined || value === null) return Object.freeze([]);
  requireThat(Array.isArray(value) && value.length <= 256, "invalid_tool_grant_list");
  const pattern = roots ? /^[A-Za-z0-9_.\-/]{1,256}$/ : /^[A-Za-z0-9_][A-Za-z0-9_:.\-]{0,63}$/;
  requireThat(value.every(item => typeof item === "string" && pattern.test(item) && (!roots || !item.split("/").includes(".."))), "invalid_tool_grant_token");
  return Object.freeze([...new Set(value as string[])]);
}
function configuredDenials(value: readonly string[] | undefined): readonly string[] {
  const list = value ?? [];
  // Native static config supports expressions such as Bash(rm *), unlike the portable grant token format.
  requireThat(Array.isArray(list) && list.length <= 256 && list.every(item => typeof item === "string"
    && item.length > 0 && item.length <= 1024 && !/^[\-]|[\r\n\x00]/.test(item)), "invalid_configured_tool_denial");
  return list;
}

/** Shape compatibility for persisted v1, with strict types and bounded lists at the new TS boundary. */
export function decodeToolGrant(raw: unknown): ToolGrantSnapshot {
  requireThat(object(raw) && raw.schema_version === "controlmesh.tool_grant.v1", "issued_tool_grant_required");
  requireThat(raw.network_policy === "sandbox_default" || raw.network_policy === "no_network", "invalid_tool_grant_network");
  requireThat(raw.confirmation_policy === "provider_runtime" || raw.confirmation_policy === "controller_required", "invalid_tool_grant_confirmation");
  return Object.freeze({ schema_version: "controlmesh.tool_grant.v1", tool_allow: tokens(raw.tool_allow), tool_deny: tokens(raw.tool_deny), writable_roots: tokens(raw.writable_roots, true),
    network_policy: raw.network_policy, confirmation_policy: raw.confirmation_policy, provider_surface: token(raw.provider_surface),
    reply_transport: token(raw.reply_transport), reply_chat: token(raw.reply_chat), reply_topic: token(raw.reply_topic), reply_thread: token(raw.reply_thread) });
}

/** Trusted local issuance only. A provider_surface label never proves enforcement. */
export function issueToolGrant(input: GrantInput = {}): ToolGrantSnapshot {
  const grant = decodeToolGrant({ network_policy: "sandbox_default", confirmation_policy: "provider_runtime", ...input, schema_version: "controlmesh.tool_grant.v1" });
  requireThat(surfaces.includes(grant.provider_surface), "unknown_tool_grant_surface");
  return grant;
}

export function restrictiveGrant(grant: ToolGrantSnapshot): boolean {
  return !!(grant.tool_allow.length || grant.tool_deny.length || grant.writable_roots.length || grant.network_policy === "no_network");
}

export interface ToolGrantMapping { provider: string; surface: string; flags: readonly string[] }
export interface ProviderGrantConfig {
  config_allowed?: readonly string[];
  config_disallowed?: readonly string[];
  config_permission_mode?: string;
  config_sandbox_mode?: string;
  config_cli_parameters?: readonly string[];
}
export class ToolGrantDenied extends Error {
  constructor(public readonly provider: string, public readonly reason_code: string) {
    super(`tool_grant_denied:${provider}:${reason_code}`); this.name = "ToolGrantDenied";
  }
}

/** Native flag mapping, matching the existing Python golden. This is NOT a process admission decision. */
export function mapToolGrant(provider: string, raw: ToolGrantSnapshot | null, config: ProviderGrantConfig = {}): ToolGrantMapping {
  requireThat(typeof provider === "string" && /^[a-z0-9_\-]{1,64}$/.test(provider), "invalid_grant_provider");
  const grant = raw === null ? null : decodeToolGrant(raw);
  const mapping = (surface: string, flags: readonly string[] = []): ToolGrantMapping => Object.freeze({ provider, surface, flags: Object.freeze([...flags]) });
  // Historical semantics retained for differential checks; admission below separately checks confirmation.
  if (grant === null || !restrictiveGrant(grant)) return mapping(`${provider}_floor`);
  const deny = (reason: string): never => { throw new ToolGrantDenied(provider, reason); };
  if (grant.confirmation_policy === "controller_required") deny("controller_approval_unavailable");
  if (!["claude", "codex", "gemini", "opencode"].includes(provider)) deny("surface_unproven");
  const parameters = config.config_cli_parameters ?? [];
  requireThat(Array.isArray(parameters) && parameters.length <= 256 && parameters.every(p => typeof p === "string" && p.length <= 4096 && !/[\x00\r\n]/.test(p)), "invalid_provider_parameters");
  const lowered = parameters.map(p => p.toLowerCase());
  if (provider === "codex" && /sandbox|network_access/.test(lowered.join(" "))) deny("override_conflicts_grant");
  if (provider === "claude" && lowered.some(p => p.startsWith("--dangerously") || p.startsWith("--permission-mode"))) deny("override_conflicts_grant");
  if (provider === "claude") {
    if (config.config_permission_mode === "bypassPermissions") deny("bypass_conflicts_grant");
    if (grant.network_policy === "no_network") deny("no_network_unenforceable");
    if (grant.tool_allow.length) deny("allowlist_not_enforceable_flags");
    if (grant.writable_roots.length) deny("writable_roots_needs_container_mounts");
    const denies = [...new Set([...configuredDenials(config.config_disallowed), ...grant.tool_deny])];
    return mapping("claude_tool_flags", denies.length ? ["--disallowedTools", ...denies] : []);
  }
  if (provider === "codex") {
    if (grant.tool_allow.length || grant.tool_deny.length) deny("tool_granularity_unsupported");
    if (grant.writable_roots.length) deny("writable_roots_unverified");
    if (config.config_permission_mode === "bypassPermissions") deny("bypass_conflicts_grant");
    if (grant.network_policy === "no_network") {
      if (config.config_sandbox_mode === "full-access") deny("no_network_conflicts_full_access");
      if (config.config_sandbox_mode === "workspace-write") return mapping("codex_sandbox", ["-c", 'sandbox_workspace_write={"network_access": false}']);
      if (config.config_sandbox_mode !== "read-only") deny("no_network_unproven_sandbox");
    }
    return mapping("codex_sandbox");
  }
  if (provider === "gemini") deny("policy_engine_config_unverified");
  return deny("config_overlay_unverified");
}

/** Admission is stricter than flag mapping: even an otherwise empty grant cannot waive a source/approval floor. */
export function enforceProviderConfirmation(provider: string, grant: ToolGrantSnapshot, policy?: ExecutionPolicyDecision): void {
  const current = decodeToolGrant(grant);
  requireThat(policy === undefined || policy.outcome === "accepted", "execution_policy_not_accepted");
  if (current.confirmation_policy === "controller_required" || policy?.confirmation_policy === "controller_required") {
    throw new ToolGrantDenied(provider, "controller_approval_unavailable");
  }
}

export interface SubmitGrantInput {
  source_scope: SourceScope;
  requested_tool_deny?: readonly string[];
  requested_no_network?: boolean;
  transport: string;
  chat_id?: string;
  topic_id?: string;
  thread_id?: string;
}
/** Source-derived floor plus narrowing requests only. Unknown ingress never falls back to host compatibility. */
export function issueTaskGrantForSubmit(input: SubmitGrantInput): ToolGrantSnapshot {
  const scope = decodeSourceScope(input.source_scope);
  requireThat(input.requested_no_network === undefined || typeof input.requested_no_network === "boolean", "invalid_requested_network_policy");
  return issueToolGrant({ tool_deny: input.requested_tool_deny ?? [], network_policy: input.requested_no_network ? "no_network" : "sandbox_default",
    confirmation_policy: sourceRequiresSandbox(scope) ? "controller_required" : "provider_runtime", reply_transport: input.transport,
    reply_chat: input.chat_id ?? "", reply_topic: input.topic_id ?? "", reply_thread: input.thread_id ?? "" });
}

export class ReplyTargetMismatch extends Error {
  constructor(public readonly field: string) { super(`reply_target_mismatch:${field}`); this.name = "ReplyTargetMismatch"; }
}
export function validateReplyTarget(raw: ToolGrantSnapshot | null, target: { transport: string; chat_id: string; topic_id?: string; thread_id?: string }): void {
  if (raw === null) return;
  const grant = decodeToolGrant(raw);
  const checks = { reply_transport: target.transport, reply_chat: target.chat_id, reply_topic: target.topic_id ?? "", reply_thread: target.thread_id ?? "" };
  for (const [field, value] of Object.entries(checks)) {
    requireThat(typeof value === "string", "invalid_reply_target");
    const expected = grant[field as keyof typeof checks];
    if (expected && value !== expected) throw new ReplyTargetMismatch(field);
  }
}
