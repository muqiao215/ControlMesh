import { object } from "../value";
import { nativeFailure, type ProviderFailure } from "./opencode-events";

/** Only native error events qualify; model prose and nested tool results do not. */
export function codexNativeFailure(event: unknown): ProviderFailure | null {
  if (!object(event) || !["error", "turn.failed"].includes(String(event.type))) return null;
  const error = event.type === "turn.failed" ? event.error : event;
  if (!object(error)) return nativeFailure("");
  const code = typeof error.code === "string" ? error.code : "";
  const message = typeof error.message === "string" ? error.message : "";
  const normalized = /you(?:'|’)ve hit your (?:usage )?limit|exceeded your current quota/i.test(message)
    ? `usage limit reached; ${message}` : message;
  return nativeFailure(`${code}\n${normalized}`);
}
