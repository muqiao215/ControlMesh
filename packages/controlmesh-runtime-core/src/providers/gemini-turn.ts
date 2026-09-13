import type { ProcessOutcome } from "../process-supervisor";
import { object, requireThat } from "../value";
import { GeminiSessionStore, type GeminiNativeBaseline } from "./gemini-session";
import { parseGeminiStream } from "./gemini-stream";

function text(value: unknown): string {
  if (typeof value === "string") return value;
  requireThat(Array.isArray(value) && value.every(part => object(part) && typeof part.text === "string" && part.thought !== true), "gemini_text_content_unproven");
  return value.map(part => part.text).join("");
}
/** Text-turn qualification only. Tool-bearing turns require a separate scoped receipt owner. */
export function verifyGeminiTextTurn(store: GeminiSessionStore, baseline: GeminiNativeBaseline, outcome: ProcessOutcome, prompt: string, model: string) {
  requireThat(outcome.reason === "exited" && outcome.exit_code === 0, "gemini_native_outcome_unproven");
  const stream = parseGeminiStream(outcome.stdout);
  requireThat(stream.session_id === baseline.session_id && stream.model === model && stream.prompt === prompt, "gemini_turn_binding_changed");
  requireThat(stream.tools.length === 0, "gemini_tool_profile_unavailable");
  const saved = store.assertAppend(baseline), messages = saved.appended_messages;
  requireThat(messages.length >= 2 && messages[0]!.type === "user" && text(messages[0]!.content) === prompt, "gemini_turn_input_unproven");
  const answers = messages.slice(1);
  requireThat(answers.every(message => message.type === "gemini" && message.model === model
    && (message.toolCalls === undefined || (Array.isArray(message.toolCalls) && message.toolCalls.length === 0))), "gemini_turn_output_unproven");
  requireThat(answers.map(message => text(message.content)).join("") === stream.text, "gemini_turn_output_unproven");
  return { session_id: stream.session_id, store_id: saved.store_id, revision: saved.revision, model,
    user_message_id: messages[0]!.id as string, assistant_message_ids: answers.map(message => message.id as string), text: stream.text };
}
