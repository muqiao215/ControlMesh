import { object } from "../value";
import type { ProcessOutcome } from "../process-supervisor";

export interface ProviderFailure {
  code: "quota_exhausted" | "rate_limited" | "authentication_failed" | "model_unavailable" | "provider_error";
  reset_at: number | null;
  reset_text: string | null;
  retry_after_ms: number | null;
}

/** Call only for a native error event/log field, never assistant text or tool output. */
export function nativeFailure(message: string): ProviderFailure {
  let code: ProviderFailure["code"] = "provider_error";
  if (/usage limit reached|insufficient_quota|quota_exceeded|credit balance is too low|insufficient balance/i.test(message)) code = "quota_exhausted";
  else if (/\b429\b|too many requests|rate.?limit/i.test(message)) code = "rate_limited";
  else if (/\b401\b|invalid.api.key|authentication.failed|unauthorized|invalid.access.token|token.expired/i.test(message)) code = "authentication_failed";
  else if (/model.not.found|unknown.model|model.*not (?:available|supported)|provider.not.found/i.test(message)) code = "model_unavailable";
  const reset = /(?:will reset at|resets? at)\s+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)/i.exec(message)?.[1] ?? null;
  const zoned = reset && /(?:Z|[+-]\d{2}:\d{2})$/.test(reset) ? Date.parse(reset.replace(" ", "T")) : NaN;
  const retry = /retry (?:after|in)\s+(\d+(?:\.\d+)?)\s*(?:s\b|seconds?)/i.exec(message)?.[1];
  const retryMs = retry ? Math.ceil(Number(retry) * 1000) : null;
  return { code, reset_at: Number.isFinite(zoned) ? zoned : null, reset_text: reset,
    retry_after_ms: retryMs !== null && retryMs > 0 && retryMs <= 86_400_000 ? retryMs : null };
}

export function failureFromNativeStderr(line: string): ProviderFailure | null {
  if (!line.startsWith("timestamp=") || !line.includes(" level=ERROR ") || !line.includes(' message="stream error" ')) return null;
  const encoded = /error\.error=("(?:[^"\\]|\\.)*")/.exec(line)?.[1];
  if (!encoded) return null;
  try {
    const message: unknown = JSON.parse(encoded);
    return typeof message === "string" ? nativeFailure(message) : null;
  } catch { return null; }
}

export interface OpenCodeObservation {
  session_id: string | null;
  text: string;
  terminal: boolean;
  failure: ProviderFailure | null;
  invalid_reason: string | null;
}

function preferFailure(previous: ProviderFailure | null, next: ProviderFailure): ProviderFailure {
  const order = ["quota_exhausted", "authentication_failed", "model_unavailable", "rate_limited", "provider_error"];
  return previous && order.indexOf(previous.code) <= order.indexOf(next.code) ? previous : next;
}

export function observeOpenCode(outcome: ProcessOutcome, expectedSession: string | null = null): OpenCodeObservation {
  let session: string | null = null;
  const texts: string[] = [];
  let terminal = false;
  let failure: ProviderFailure | null = null;
  let invalid: string | null = null;
  for (const line of outcome.stdout.split("\n").filter(line => line.trim())) {
    let event: unknown;
    try { event = JSON.parse(line); } catch { invalid = "non_json_native_output"; continue; }
    if (!object(event) || typeof event.type !== "string") { invalid = "invalid_native_event"; continue; }
    if (["step_start", "text", "step_finish"].includes(event.type) && typeof event.sessionID !== "string") invalid = "native_event_missing_session";
    if (event.type === "step_start" || event.type === "text" || event.type === "tool_use") terminal = false;
    if (typeof event.sessionID === "string") {
      if (!/^ses_[A-Za-z0-9]+$/.test(event.sessionID)) invalid = "invalid_native_session";
      if ((session && session !== event.sessionID) || (expectedSession && expectedSession !== event.sessionID)) invalid = "native_session_mismatch";
      session = event.sessionID;
    }
    if (event.type === "error") {
      const error = object(event.error) ? event.error : {};
      const data = object(error.data) ? error.data : {};
      const message = error.message ?? data.message;
      failure = preferFailure(failure, typeof message === "string" ? nativeFailure(message) : nativeFailure(""));
    }
    if (event.type === "text" && object(event.part) && typeof event.part.text === "string") texts.push(event.part.text);
    if (event.type === "step_finish" && object(event.part)) terminal = event.part.reason === "stop";
  }
  for (const line of outcome.stderr.split("\n")) {
    const reported = failureFromNativeStderr(line);
    if (reported) failure = preferFailure(failure, reported);
  }
  if (outcome.reason !== "exited" || outcome.exit_code !== 0 || failure || invalid || !session) terminal = false;
  return { session_id: session, text: texts.join(""), terminal, failure, invalid_reason: invalid };
}

export interface PreflightObservation {
  status: "ready" | "degraded" | "unavailable";
  reason: string;
  session_id: string | null;
  failure: ProviderFailure | null;
}

export function judgeOpenCodePreflight(outcome: ProcessOutcome): PreflightObservation {
  const observation = observeOpenCode(outcome);
  if (observation.failure) return { status: observation.failure.code === "rate_limited" ? "degraded" : "unavailable", reason: observation.failure.code, session_id: observation.session_id, failure: observation.failure };
  if (observation.invalid_reason) return { status: "unavailable", reason: observation.invalid_reason, session_id: observation.session_id, failure: null };
  if (observation.terminal && /^(?:PONG|PONG\.)$/.test(observation.text.trim())) return { status: "ready", reason: "native_sentinel_verified", session_id: observation.session_id, failure: null };
  return { status: "unavailable", reason: outcome.reason === "exited" ? "missing_native_completion_or_sentinel" : outcome.reason, session_id: observation.session_id, failure: null };
}
