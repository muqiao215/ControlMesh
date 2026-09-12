import type { StructuredTeamResult } from "./team-result-validation";
import type { TeamReducedResult } from "./team-results";

export function compactTeamText(value: string, limit = 140): string {
  const normalized = value.split(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u).filter(Boolean).join(" ");
  const chars = Array.from(normalized);
  return chars.length <= limit ? normalized : `${chars.slice(0, limit - 3).join("").replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/u, "")}...`;
}
export function teamResultSummary(result: StructuredTeamResult): string {
  const parts = [`${result.worker_role}: ${compactTeamText(result.summary, 96)}`];
  if (result.evidence.length) parts.push(`${result.evidence.length} evidence`);
  if (result.artifacts.length) parts.push(`${result.artifacts.length} artifacts`);
  if (result.status === "needs_repair" && result.repair_hint !== null) parts.push(`repair: ${compactTeamText(result.repair_hint, 40)}`);
  else if (result.next_action !== null) parts.push(compactTeamText(result.next_action, 40));
  return parts.join(" | ");
}
export function teamReducedSummary(result: TeamReducedResult): string {
  const parts = [compactTeamText(result.reduced_summary, 104)];
  if (result.selected_evidence.length) parts.push(`${result.selected_evidence.length} evidence`);
  if (result.selected_artifacts.length) parts.push(`${result.selected_artifacts.length} artifacts`);
  if (result.next_action !== null) parts.push(compactTeamText(result.next_action, 40));
  return parts.join(" | ");
}
