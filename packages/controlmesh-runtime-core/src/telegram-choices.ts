import type { TerminalDelivery } from "@controlmesh/protocol";
import { digest } from "./value";

/** Agent choices are ordinary continuation text, never control-plane commands. */
export function telegramChoices(envelope: TerminalDelivery): { text: string; choices?: NonNullable<TerminalDelivery["choices"]> } {
  if (envelope.target.transport !== "telegram" || (envelope.execution_context.source_scope !== "direct_message" && envelope.execution_context.source_scope !== "group_message")) return { text: envelope.text };
  const choices: NonNullable<TerminalDelivery["choices"]> = []; let fence = "", inlineWidth = 0;
  const text = envelope.text.split("\n").map(line => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = "";
      return line;
    }
    if (!inlineWidth && marker && !(marker[1][0] === "`" && marker[2].includes("`"))) { fence = marker[1]; return line; }
    return line.replace(/`+|\[button:([^\]\n]+)\]/g, (whole, spec: string | undefined) => {
      if (spec === undefined) { if (!inlineWidth) inlineWidth = whole.length; else if (inlineWidth === whole.length) inlineWidth = 0; return whole; }
      if (inlineWidth) return whole;
      const split = spec.indexOf("|"), label = (split < 0 ? spec : spec.slice(0, split)).trim();
      const prompt = (split < 0 ? label : spec.slice(split + 1).trim()) || label;
      if (!label || [...label].length > 64 || [...prompt].length > 4096) return whole;
      choices.push({ id: `cmc:${digest([envelope.delivery_id, choices.length, label, prompt]).slice(0, 48)}`, label, text: prompt });
      return "";
    });
  }).join("\n").trim();
  if (!choices.length || choices.length > 16) return { text: envelope.text };
  return { text: text || "Choose an option.", choices };
}
