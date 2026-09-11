import { decodeExecutionContext, decodeSourceScope, type ExecutionContext, type SourceScope } from "./execution-context";
import { requireThat } from "./value";

const sandboxScopes: readonly SourceScope[] = ["group_message", "bot_handoff", "api", "cron", "webhook", "heartbeat"];
export function sourceRequiresSandbox(scope: SourceScope): boolean { return sandboxScopes.includes(decodeSourceScope(scope)); }

export interface ExecutionPolicyDecision extends ExecutionContext {
  schema_version: "controlmesh.execution_policy.v1";
  sandbox_required: boolean;
  sandbox_available: boolean;
  outcome: "accepted" | "denied";
  reason_code: "sandbox_required_unavailable" | "sandbox_required_ready" | "sandbox_optional_ready" | "trusted_host_compatibility";
  tool_policy: "request_bound";
  network_policy: "container_default" | "host_inherited";
  writable_roots_policy: "configured_container_mounts" | "configured_workspace";
  confirmation_policy: "controller_required" | "provider_runtime";
}
export class ExecutionPolicyDenied extends Error {
  constructor(public readonly decision: ExecutionPolicyDecision) {
    super(`execution_policy_denied:${decision.reason_code}`); this.name = "ExecutionPolicyDenied";
  }
}

/** Pure policy, parity with the Python owner. The caller must obtain sandbox readiness from the actual launcher. */
export function evaluateExecutionPolicy(raw: ExecutionContext, sandboxAvailable: boolean): ExecutionPolicyDecision {
  const context = decodeExecutionContext(raw);
  requireThat(typeof sandboxAvailable === "boolean", "invalid_sandbox_readiness");
  const required = sourceRequiresSandbox(context.source_scope), accepted = !required || sandboxAvailable;
  return Object.freeze({ ...context, schema_version: "controlmesh.execution_policy.v1", sandbox_required: required, sandbox_available: sandboxAvailable,
    outcome: accepted ? "accepted" : "denied",
    reason_code: !accepted ? "sandbox_required_unavailable" : required ? "sandbox_required_ready" : sandboxAvailable ? "sandbox_optional_ready" : "trusted_host_compatibility",
    tool_policy: "request_bound", network_policy: sandboxAvailable ? "container_default" : "host_inherited",
    writable_roots_policy: sandboxAvailable ? "configured_container_mounts" : "configured_workspace",
    confirmation_policy: required ? "controller_required" : "provider_runtime" });
}
export function enforceExecutionPolicy(context: ExecutionContext, sandboxAvailable: boolean): ExecutionPolicyDecision {
  const decision = evaluateExecutionPolicy(context, sandboxAvailable);
  if (decision.outcome === "denied") throw new ExecutionPolicyDenied(decision);
  return decision;
}

/** Current concrete native launcher has a local foreground host profile only, regardless of worker identity. */
export function enforceLocalReadSource(raw: unknown): ExecutionContext {
  const context = decodeExecutionContext(raw);
  enforceExecutionPolicy(context, false);
  requireThat(context.origin === "user" && context.source_scope === "local_foreground", "source_execution_floor_unavailable");
  return context;
}

/** Concrete runners own the source floor. A task body cannot declare sandbox availability. */
export function enforceNativeReadSource(raw: unknown, runner: { assertSource?: (context: ExecutionContext) => void }): ExecutionContext {
  const context = decodeExecutionContext(raw);
  if (!runner.assertSource) return enforceLocalReadSource(raw);
  const checked: unknown = runner.assertSource(context);
  if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  return context;
}
