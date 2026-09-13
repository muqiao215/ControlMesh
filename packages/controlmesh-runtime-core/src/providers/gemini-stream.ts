import { geminiNativeFailure } from "./gemini-failure";
import { object, requireThat } from "../value";

export interface GeminiStreamTool { id: string; name: string; parameters: Record<string, unknown>; status: "success" | "error"; output: unknown }
/** Gemini 0.59 --output-format stream-json. Chunks are concatenated verbatim. */
export function parseGeminiStream(stdout: string) {
  requireThat(Buffer.byteLength(stdout) <= 16 * 1024 * 1024 && stdout.endsWith("\n"), "invalid_gemini_stream");
  const lines = stdout.split("\n").slice(0, -1);
  requireThat(lines.length > 0 && lines.length <= 100000, "invalid_gemini_stream");
  const events = lines.map(line => { const event: unknown = JSON.parse(line); requireThat(object(event), "invalid_gemini_stream"); return event; });
  const init = events[0]!;
  requireThat(init.type === "init" && typeof init.session_id === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(init.session_id)
    && typeof init.model === "string" && init.model.length > 0, "gemini_stream_identity_missing");
  let prompt: string | undefined, text = "", terminal = false;
  const pending = new Map<string, { name: string; parameters: Record<string, unknown> }>(), seen = new Set<string>(), tools: GeminiStreamTool[] = [];
  for (const event of events.slice(1)) {
    requireThat(!terminal && (event.session_id === undefined || event.session_id === init.session_id), "gemini_stream_sequence_invalid");
    const failure = geminiNativeFailure(event);
    requireThat(!failure, failure?.code ?? "provider_error");
    if (event.type === "message") {
      requireThat(typeof event.content === "string", "invalid_gemini_stream");
      if (event.role === "user") { requireThat(prompt === undefined && event.delta !== true, "gemini_stream_sequence_invalid"); prompt = event.content; }
      else { requireThat(event.role === "assistant" && prompt !== undefined && event.delta === true, "gemini_stream_sequence_invalid"); text += event.content; }
    } else if (event.type === "tool_use") {
      requireThat(prompt !== undefined && typeof event.tool_id === "string" && event.tool_id.length > 0 && !seen.has(event.tool_id)
        && typeof event.tool_name === "string" && event.tool_name.length > 0 && object(event.parameters), "gemini_tool_sequence_invalid");
      seen.add(event.tool_id); pending.set(event.tool_id, { name: event.tool_name, parameters: event.parameters });
      requireThat(seen.size <= 256, "gemini_tool_limit");
    } else if (event.type === "tool_result") {
      requireThat(typeof event.tool_id === "string" && pending.has(event.tool_id)
        && (event.status === "success" || event.status === "error"), "gemini_tool_sequence_invalid");
      const call = pending.get(event.tool_id)!; pending.delete(event.tool_id);
      tools.push({ id: event.tool_id, ...call, status: event.status, output: event.output });
    } else if (event.type === "error") {
      requireThat(event.severity === "warning", "provider_error");
    } else if (event.type === "result") {
      requireThat(event.status === "success" && !event.error, "provider_error");
      requireThat(prompt !== undefined && pending.size === 0, "gemini_stream_sequence_invalid"); terminal = true;
    } else requireThat(false, "invalid_gemini_stream");
  }
  requireThat(terminal, "native_completion_unproven");
  requireThat(text.trim().length > 0, "empty_native_output");
  return { session_id: init.session_id, model: init.model, prompt: prompt!, text, tools };
}
