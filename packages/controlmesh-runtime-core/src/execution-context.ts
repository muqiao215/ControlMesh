import { AsyncLocalStorage } from "node:async_hooks";
import { createHash, randomBytes } from "node:crypto";
import { object, requireThat } from "./value";

export const executionOrigins = ["background", "cron", "webhook_wake", "webhook_cron", "heartbeat", "interagent", "task_result", "task_question", "user", "api"] as const;
export const sourceScopes = ["local_foreground", "direct_message", "group_message", "bot_handoff", "api", "cron", "webhook", "heartbeat", "background_task", "task_result", "legacy_compat"] as const;
export type ExecutionOrigin = typeof executionOrigins[number];
export type SourceScope = typeof sourceScopes[number];
export interface ExecutionContext {
  readonly trace_id: string;
  readonly origin: ExecutionOrigin;
  readonly source_scope: SourceScope;
  readonly transport: string;
  readonly source_ref: string;
}

export function decodeSourceScope(value: unknown): SourceScope {
  requireThat(typeof value === "string" && sourceScopes.includes(value as SourceScope), "invalid_execution_source_scope");
  return value as SourceScope;
}

/** Decode stored provenance, never issue authority from an inbound message body. Missing legacy fields require explicit reissue. */
export function decodeExecutionContext(value: unknown): ExecutionContext {
  requireThat(object(value), "issued_execution_context_required");
  requireThat(typeof value.trace_id === "string" && /^[0-9a-f]{32}$/.test(value.trace_id), "invalid_execution_trace_id");
  requireThat(typeof value.origin === "string" && executionOrigins.includes(value.origin as ExecutionOrigin), "invalid_execution_origin");
  const source_scope = decodeSourceScope(value.source_scope);
  requireThat(typeof value.transport === "string" && /^[a-z0-9_-]{1,32}$/.test(value.transport), "invalid_execution_transport");
  const source_ref = value.source_ref ?? "";
  requireThat(typeof source_ref === "string" && (source_ref === "" || /^[0-9a-f]{24}$/.test(source_ref)), "invalid_execution_source_ref");
  return Object.freeze({ trace_id: value.trace_id, origin: value.origin as ExecutionOrigin, source_scope, transport: value.transport, source_ref });
}

/** Trusted ingress only. Authentication determines origin/scope; raw text is not an input. */
export function issueExecutionContext(input: { origin: ExecutionOrigin; source_scope: SourceScope; transport: string; source_id?: string }): ExecutionContext {
  requireThat(typeof input.transport === "string" && (input.source_id === undefined || typeof input.source_id === "string"), "invalid_execution_identity");
  const normalized = input.transport.trim().toLowerCase();
  const transport = /^[a-z0-9_-]{1,32}$/.test(normalized) ? normalized : "unknown";
  return decodeExecutionContext({ trace_id: randomBytes(16).toString("hex"), origin: input.origin, source_scope: input.source_scope, transport,
    source_ref: input.source_id ? createHash("sha256").update(`${transport}\0${input.source_id}`).digest("hex").slice(0, 24) : "" });
}

const current = new AsyncLocalStorage<ExecutionContext>();
export function currentExecutionContext(): ExecutionContext | undefined { return current.getStore(); }
/** Lexical run restores the parent context on success, throw and async completion without leaking between tasks. */
export function withExecutionContext<T>(context: ExecutionContext, run: () => T): T {
  return current.run(decodeExecutionContext(context), run);
}
