import { randomUUID } from "node:crypto";
/** Synthetic Responses stream for qualifying an installed native CLI without a model service. */
export function codexTextResponse(model: unknown, text: string): Response {
  return codexMessagesResponse(model, [{ text }]);
}
export function codexMessagesResponse(model: unknown, messages: { text: string; phase?: string }[]): Response {
  const items = messages.map(({ text, phase }) => ({ id: `msg_${randomUUID()}`, type: "message", role: "assistant", status: "completed", ...(phase ? { phase } : {}), content: [{ type: "output_text", text, annotations: [] }] }));
  const response = { id: `resp_${randomUUID()}`, object: "response", created_at: 1, status: "completed", model, output: items, usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } };
  const events: Record<string, unknown>[] = [
    { type: "response.created", response: { ...response, status: "in_progress", output: [] } },
  ];
  for (const [output_index, item] of items.entries()) {
    const text = item.content[0].text;
    events.push(
      { type: "response.output_item.added", output_index, item: { ...item, status: "in_progress", content: [] } },
      { type: "response.content_part.added", item_id: item.id, output_index, content_index: 0, part: { type: "output_text", text: "", annotations: [] } },
      { type: "response.output_text.delta", item_id: item.id, output_index, content_index: 0, delta: text },
      { type: "response.output_text.done", item_id: item.id, output_index, content_index: 0, text },
      { type: "response.output_item.done", output_index, item });
  }
  events.push({ type: "response.completed", response });
  return new Response(events.map((event, sequence_number) => `event: ${event.type}\ndata: ${JSON.stringify({ ...event, sequence_number })}\n\n`).join(""), { headers: { "content-type": "text/event-stream" } });
}

/** Real native apply_patch is invoked only inside an isolated test workspace. */
export function codexPatchResponse(model: unknown, patch: string): Response {
  const item = { id: `ctc_${randomUUID()}`, type: "custom_tool_call", call_id: `call_${randomUUID()}`, name: "apply_patch", input: patch };
  const response = { id: `resp_${randomUUID()}`, object: "response", created_at: 1, status: "completed", model, output: [item], usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } };
  const events = [
    { type: "response.created", response: { ...response, status: "in_progress", output: [] } },
    { type: "response.output_item.added", output_index: 0, item: { ...item, input: "" } },
    { type: "response.custom_tool_call_input.delta", item_id: item.id, output_index: 0, delta: patch },
    { type: "response.custom_tool_call_input.done", item_id: item.id, output_index: 0, input: patch },
    { type: "response.output_item.done", output_index: 0, item }, { type: "response.completed", response },
  ];
  return new Response(events.map((event, sequence_number) => `event: ${event.type}\ndata: ${JSON.stringify({ ...event, sequence_number })}\n\n`).join(""), { headers: { "content-type": "text/event-stream" } });
}
