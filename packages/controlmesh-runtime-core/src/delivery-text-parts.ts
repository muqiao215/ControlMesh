import type { TerminalDelivery } from "@controlmesh/protocol";
import { requireThat } from "./value";

export function telegramDeliveryText(envelope: TerminalDelivery): string {
  const scope = envelope.execution_context.source_scope;
  const label = scope === "cron" ? "Scheduled task" : scope === "heartbeat" ? "Heartbeat task"
    : scope === "bot_handoff" ? "Agent task" : scope === "webhook" ? "Webhook task" : "Task";
  return `${label} ${envelope.task_id}: ${envelope.status === "done" ? "completed" : envelope.status}\n\n${envelope.text}`;
}
/** Projection is pure: every part is persisted before the first transport attempt. */
export function deliveryTextParts(envelope: TerminalDelivery): string[] {
  if (envelope.target.transport !== "telegram" || telegramDeliveryText(envelope).length <= 4096) return [envelope.text];
  const heading = telegramDeliveryText({ ...envelope, text: "" }).length;
  const budget = 4096 - heading - 32; // Room for the bounded [part i/n] marker.
  requireThat(budget > 0, "delivery_heading_too_large");
  const segments: string[] = []; let segment = "";
  for (const point of envelope.text) {
    if (segment.length + point.length > budget) { segments.push(segment); segment = ""; }
    segment += point;
  }
  if (segment) segments.push(segment);
  requireThat(segments.length <= 32, "delivery_parts_limit");
  return segments.map((text, index) => `[part ${index + 1}/${segments.length}]\n\n${text}`);
}
