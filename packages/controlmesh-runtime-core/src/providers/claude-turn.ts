import { object, requireThat } from "../value";

export interface ClaudeToolEvidence {
  id: string;
  name: string;
  input: Record<string, unknown>;
  output: string;
  is_error: boolean;
}
export interface ClaudeTurnEvidence {
  user_message_id: string;
  assistant_message_ids: string[];
  tools: ClaudeToolEvidence[];
  output: string;
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const metadata = new Set(["atis-latch", "custom-title", "ai-title", "mode", "permission-mode", "cost-state", "last-prompt"]);
const id = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 256;
function contentText(value: unknown): string {
  if (typeof value === "string") return value;
  requireThat(Array.isArray(value) && value.every(part => object(part) && part.type === "text" && typeof part.text === "string"), "unsupported_native_content");
  return value.map(part => part.text).join("");
}
interface InspectedTurn { prompt: string; evidence: ClaudeTurnEvidence; models: string[]; interrupted: boolean }

/** Inspect the pinned main-session append format. This proves lineage, never tool authority.
 * Compaction, branching and unknown executable records need separate qualification.
 */
export function inspectClaudeChain(records: Record<string, unknown>[], sessionId: string, directory: string, offset = 0): {
  tip_uuid: string; turns: InspectedTurn[];
} {
  const seen = new Set<string>(), toolIds = new Set<string>(), messageIds = new Set<string>();
  const pending = new Map<string, { evidence: Pick<ClaudeToolEvidence, "id" | "name" | "input">; owner: string }>();
  let tip: string | null = null, last: Record<string, unknown> | undefined, queued = false;
  const turns: InspectedTurn[] = [];
  let current: typeof turns[number] | undefined, finalMessageId: string | undefined;
  let resumePadding: "assistant" | "input" | null = null;
  const finalText: string[] = [];
  for (const [index, row] of records.entries()) {
    requireThat(!("sessionId" in row) || row.sessionId === sessionId, "native_session_mismatch");
    requireThat(!("session_id" in row) || row.session_id === sessionId, "native_session_mismatch");
    if (row.type === "queue-operation") {
      requireThat(!("uuid" in row) && !("parentUuid" in row), "unsupported_native_lineage");
      if (row.operation === "enqueue") {
        requireThat(!queued && typeof row.content === "string", "native_pending_or_concurrent_input"); queued = true;
      } else { requireThat(row.operation === "dequeue" && queued, "native_pending_or_concurrent_input"); queued = false; }
      continue;
    }
    if (metadata.has(String(row.type))) {
      requireThat(!("uuid" in row) && !("parentUuid" in row), "unsupported_native_lineage");
      if (row.type === "last-prompt") requireThat(row.leafUuid === tip, "native_metadata_leaf_mismatch");
      continue;
    }
    requireThat(["user", "assistant", "attachment"].includes(String(row.type)), "unsupported_native_lineage");
    requireThat(row.sessionId === sessionId && row.cwd === directory && row.isSidechain === false, "unsupported_native_lineage");
    requireThat(typeof row.uuid === "string" && uuid.test(row.uuid) && !seen.has(row.uuid), "native_duplicate_or_invalid_message");
    // Parallel native results point back to their own tool block, not the last flushed row.
    // Accept only that proved pending edge; ordinary messages still extend the physical tip.
    const resultParts = row.type === "user" && object(row.message) ? row.message.content : undefined;
    const pendingParent = Array.isArray(resultParts) && resultParts.length > 0 && resultParts.every(part =>
      object(part) && part.type === "tool_result" && id(part.tool_use_id)
      && pending.get(part.tool_use_id)?.owner === row.parentUuid && row.sourceToolAssistantUUID === row.parentUuid);
    requireThat(row.parentUuid === tip || pendingParent, "native_parent_mismatch");
    seen.add(row.uuid); tip = row.uuid;
    if (row.type === "attachment") {
      requireThat(current && !current.interrupted && last?.role === "user" && object(row.attachment), "unsupported_native_attachment");
      if (row.attachment.type === "max_turns_reached") {
        requireThat(!queued && pending.size === 0 && current.models.length > 0 && current.evidence.tools.length > 0
          && Number.isSafeInteger(row.attachment.maxTurns) && (row.attachment.maxTurns as number) > 0
          && Number.isSafeInteger(row.attachment.turnCount) && row.attachment.turnCount === (row.attachment.maxTurns as number) + 1,
        "invalid_native_interruption");
        current.interrupted = true;
      } else requireThat(row.attachment.type === "total_tokens_reminder", "unsupported_native_attachment");
      continue;
    }
    requireThat(object(row.message) && row.message.role === row.type && !row.isApiErrorMessage, "unsupported_native_content");
    const message = row.message, parts = message.content;
    // Pinned native resume inserts this exact non-model pair after a max-turns boundary.
    // Neither record is a submitted task input, model output or proof of completion.
    if (row.isMeta || resumePadding === "assistant") {
      requireThat(current?.interrupted && !queued && pending.size === 0 && row.version === "2.1.263" && row.entrypoint === "sdk-cli",
        "unsupported_native_resume_padding");
      if (resumePadding === "assistant") {
        requireThat(row.type === "assistant" && !row.isMeta && message.model === "<synthetic>" && id(message.id) && !messageIds.has(message.id)
          && message.stop_reason === "stop_sequence" && message.stop_sequence === "" && object(message.usage)
          && message.usage.input_tokens === 0 && message.usage.output_tokens === 0 && Array.isArray(parts) && parts.length === 1
          && object(parts[0]) && parts[0].type === "text" && parts[0].text === "No response requested.", "unsupported_native_resume_padding");
        messageIds.add(message.id); resumePadding = "input";
      } else {
        requireThat(resumePadding === null && row.type === "user" && row.isMeta === true && typeof row.promptId === "string" && uuid.test(row.promptId)
          && Array.isArray(parts) && parts.length === 1 && object(parts[0]) && parts[0].type === "text"
          && parts[0].text === "Continue from where you left off.", "unsupported_native_resume_padding");
        resumePadding = "assistant";
      }
      continue;
    }
    if (resumePadding === "input") {
      requireThat(row.type === "user" && !(Array.isArray(parts) && parts.some(part => object(part) && part.type === "tool_result")), "native_resume_input_missing");
      resumePadding = null;
    }
    if (row.type === "user") {
      if (Array.isArray(parts) && parts.some(part => object(part) && part.type === "tool_result")) {
        requireThat(parts.length > 0 && current, "native_unowned_tool_result");
        for (const part of parts) {
          requireThat(object(part) && part.type === "tool_result" && id(part.tool_use_id) && pending.has(part.tool_use_id), "native_unowned_tool_result");
          requireThat(part.is_error === undefined || typeof part.is_error === "boolean", "unsupported_native_tool_result");
          const call = pending.get(part.tool_use_id)!;
          requireThat(row.sourceToolAssistantUUID === undefined || row.sourceToolAssistantUUID === call.owner, "native_tool_parent_mismatch");
          current.evidence.tools.push({ ...call.evidence, output: contentText(part.content), is_error: part.is_error === true });
          pending.delete(part.tool_use_id);
        }
      } else {
        requireThat(pending.size === 0 && (!last || last.stop_reason === "end_turn" || current?.interrupted), "native_session_not_idle");
        current = { prompt: contentText(parts), evidence: { user_message_id: row.uuid, assistant_message_ids: [], tools: [], output: "" }, models: [], interrupted: false };
        if (index >= offset) turns.push(current);
        finalMessageId = undefined; finalText.length = 0;
      }
    } else {
      requireThat(current && !current.interrupted && id(message.id) && typeof message.model === "string" && !message.model.startsWith("<") && Array.isArray(parts) && parts.length > 0, "unsupported_native_content");
      current.evidence.assistant_message_ids.push(row.uuid); current.models.push(message.model);
      if (message.id !== finalMessageId) {
        requireThat(pending.size === 0, "native_model_advanced_with_pending_tools");
        requireThat(!messageIds.has(message.id), "native_reused_model_message"); messageIds.add(message.id);
        finalMessageId = message.id; finalText.length = 0;
      }
      for (const part of parts) {
        requireThat(object(part), "unsupported_native_content");
        if (part.type === "text") { requireThat(typeof part.text === "string", "unsupported_native_content"); finalText.push(part.text); }
        else if (part.type === "thinking") requireThat(typeof part.thinking === "string", "unsupported_native_content");
        else {
          requireThat(part.type === "tool_use" && id(part.id) && id(part.name) && object(part.input), "unsupported_native_tool_use");
          requireThat(!toolIds.has(part.id), "native_duplicate_tool_use"); toolIds.add(part.id);
          pending.set(part.id, { evidence: { id: part.id, name: part.name, input: part.input }, owner: row.uuid });
        }
      }
      current.evidence.output = finalText.join("");
    }
    last = message;
  }
  requireThat(!queued && pending.size === 0 && resumePadding === null && (current?.interrupted || (last?.role === "assistant" && last.stop_reason === "end_turn")) && tip !== null, "native_session_not_idle");
  return { tip_uuid: tip, turns };
}
