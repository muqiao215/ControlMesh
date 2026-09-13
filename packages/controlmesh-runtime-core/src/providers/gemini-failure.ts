import { object } from "../value";
import { nativeFailure, type ProviderFailure } from "./opencode-events";

/** Native Gemini error envelopes only; assistant/tool output and warning prose are not failures. */
export function geminiNativeFailure(event: unknown): ProviderFailure | null {
  if (!object(event)) return null;
  let error: Record<string, unknown>;
  if (event.type === "result" && event.status === "error") error = object(event.error) ? event.error : {};
  else if (event.type === "error" && event.severity === "error") error = event;
  else return null;
  const type = typeof error.type === "string" ? error.type : "";
  const message = typeof error.message === "string" ? error.message : "";
  const failure = nativeFailure(message);
  if (type === "TerminalQuotaError") failure.code = "quota_exhausted";
  else if (type === "RetryableQuotaError") failure.code = "rate_limited";
  else if (type === "FatalAuthenticationError" || type === "ValidationRequiredError") failure.code = "authentication_failed";
  else if (type === "ModelNotFoundError") failure.code = "model_unavailable";
  else if (/\b(?:QUOTA_EXHAUSTED|INSUFFICIENT_G1_CREDITS_BALANCE|MODEL_CAPACITY_EXHAUSTED|MODEL_CAPACITY_EXCEEDED)\b|exhausted your capacity/i.test(message)) failure.code = "quota_exhausted";
  // Gemini emits seconds and milliseconds. Do not invent a reset time from a relative delay.
  const delay = /(?:retry (?:after|in)|Suggested retry after)\s+(\d+(?:\.\d+)?)\s*(ms|s\b|seconds?)/i.exec(message);
  if (delay) {
    const milliseconds = Math.ceil(Number(delay[1]) * (delay[2]!.toLowerCase() === "ms" ? 1 : 1000));
    failure.retry_after_ms = milliseconds > 0 && milliseconds <= 86400000 ? milliseconds : null;
  }
  return failure;
}
export function geminiFailureLine(line: string): ProviderFailure | null {
  try { return geminiNativeFailure(JSON.parse(line)); } catch { return null; }
}
