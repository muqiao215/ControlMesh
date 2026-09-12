import { codexNativeFailure } from "./codex-failure";
import { object } from "../value";
import { failureFromNativeStderr, nativeFailure } from "./opencode-events";
import { oneShotProvider } from "./oneshot-command";

export interface OneShotObservation {
  text: string; terminal: boolean; error_code: string | null; session_id: string | null; quota_reset_at: string | null;
}

/** Native record semantics, independent of exit code. Prose and tool data do not grant success or classify quota. */
export function observeOneShot(provider: string, stdout: string, stderr = ""): OneShotObservation {
  oneShotProvider(provider);
  const raw = stdout.trim();
  let events: unknown[] = [], invalid = false;
  if (raw) {
    try { const data: unknown = JSON.parse(raw); events = Array.isArray(data) ? data : [data]; }
    catch {
      for (const line of raw.split("\n").filter(line => line.trim())) {
        try { events.push(JSON.parse(line)); } catch { invalid = true; }
      }
    }
  }
  const texts: string[] = [];
  let error: string | null = null, session: string | null = null, reset: string | null = null, terminal = false;
  for (const value of events) {
    if (!object(value)) { invalid = true; continue; }
    const kind = value.type;
    if (provider === "opencode" && kind === "text" && object(value.part) && typeof value.part.text === "string") texts.push(value.part.text);
    else if (provider === "codex") {
      const item = value.item;
      if (object(item)) {
        if (kind === "item.started" && ["command_execution", "file_change", "web_search", "mcp_tool_call"].includes(String(item.type))) texts.length = 0;
        if (kind === "item.completed" && item.type === "agent_message" && typeof item.text === "string") texts.push(item.text);
      }
      if (kind === "message" && value.role === "assistant" && Array.isArray(value.content)) {
        for (const block of value.content) if (object(block) && block.type === "text" && typeof block.text === "string") texts.push(block.text);
      }
    } else if (["claude", "gemini", "claw"].includes(provider)) {
      const keys = provider === "claude" ? ["result"] : provider === "gemini" ? ["result", "response", "output"] : ["result", "output", "text", "message", "response", "content"];
      if (kind === undefined || kind === null || kind === "result") {
        const key = keys.find(key => typeof value[key] === "string"); if (key) texts.push(value[key] as string);
      } else if (provider === "gemini" && kind === "message" && ["assistant", "model"].includes(String(value.role)) && typeof value.content === "string") texts.push(value.content);
    }
    const nativeError = value.error;
    // Python truthiness for empty native error objects/lists; nonempty structured error fields veto success.
    const hasError = object(nativeError) ? Object.keys(nativeError).length > 0 : Array.isArray(nativeError) ? nativeError.length > 0 : Boolean(nativeError);
    if (hasError || value.is_error || kind === "error" || kind === "turn.failed") {
      if (error !== "quota_exhausted") error = "provider_error";
      if (provider === "codex") {
        const failure = codexNativeFailure(value);
        if (failure && error !== "quota_exhausted") {
          error = failure.code;
          if (failure.code === "quota_exhausted") reset = failure.reset_at === null ? null : new Date(failure.reset_at).toISOString();
        }
      }
      if (provider === "opencode" && kind === "error" && object(nativeError)) {
        const message = nativeError.message || (object(nativeError.data) ? nativeError.data.message : "");
        if (typeof message === "string") {
          const failure = nativeFailure(message);
          if (failure.code === "quota_exhausted") { error = failure.code; reset = failure.reset_text; }
        }
      }
    }
    const candidate = provider === "opencode" ? value.sessionID : provider === "codex" ? value.thread_id : value.session_id;
    if (candidate !== undefined && candidate !== null) {
      if (typeof candidate !== "string" || !candidate || (session && session !== candidate)) invalid = true;
      else session = candidate;
    }
    if (provider === "opencode") {
      if (["step_start", "text", "step_finish"].includes(String(kind)) && typeof candidate !== "string") invalid = true;
      if (["step_start", "text", "tool_use"].includes(String(kind))) terminal = false;
      if (kind === "step_finish") terminal = object(value.part) && value.part.reason === "stop";
    } else if (provider === "codex") {
      if (["turn.started", "item.started", "item.updated", "item.completed"].includes(String(kind))) terminal = false;
      if (kind === "turn.completed") terminal = true;
    } else terminal = true;
  }
  if (provider === "opencode") {
    for (const line of stderr.split("\n")) {
      const failure = failureFromNativeStderr(line);
      if (failure?.code === "quota_exhausted") { error = failure.code; reset = failure.reset_text; }
    }
  }
  const text = texts.join(provider === "opencode" ? "" : provider === "gemini" ? "\n\n" : "\n");
  error = error || (invalid ? "invalid_native_output" : null) || (!terminal ? "native_completion_unproven" : null) || (!text.trim() ? "empty_native_output" : null);
  return { text, terminal: error === null, error_code: error, session_id: session, quota_reset_at: reset };
}
