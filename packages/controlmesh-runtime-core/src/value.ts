import { createHash } from "node:crypto";

export class RuntimeConflict extends Error {
  constructor(public readonly code: string) {
    super(code);
    this.name = "RuntimeConflict";
  }
}

export function requireThat(condition: unknown, code: string): asserts condition {
  if (!condition) throw new RuntimeConflict(code);
}

export function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

// Reject values JSON would silently discard/coerce. Order must not change retry identity.
export function canonical(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) {
    requireThat(!Number.isInteger(value) || Number.isSafeInteger(value), "unsafe_json_integer");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (object(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  throw new RuntimeConflict("invalid_json_value");
}

export function digest(value: unknown): string {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

export function identifier(value: unknown): asserts value is string {
  requireThat(typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,191}$/.test(value), "invalid_identifier");
}

export const statuses = ["running", "done", "failed", "cancelled", "waiting", "detached", "recovering", "stale"] as const;
export type TaskStatus = typeof statuses[number];
export const terminal = new Set<TaskStatus>(["done", "failed", "cancelled"]);

export interface LegacyTask extends Record<string, unknown> {
  task_id: string;
  chat_id: string | number;
  status: TaskStatus;
}

export function legacyTask(value: unknown): asserts value is LegacyTask {
  requireThat(object(value), "invalid_task");
  identifier(value.task_id);
  requireThat(typeof value.chat_id === "string" || (typeof value.chat_id === "number" && Number.isSafeInteger(value.chat_id)), "invalid_chat_id");
  requireThat(statuses.includes(value.status as TaskStatus), "invalid_task_status");
  canonical(value);
}
