import { createHash } from "node:crypto";
import { canonical, identifier, object, requireThat } from "./value";

export const hostJobStates = ["pending", "running", "awaiting_approval", "completed", "failed", "cancelled"] as const;
export const hostStepStates = ["pending", "awaiting_approval", "running", "completed", "failed", "cancelled", "skipped"] as const;
export type HostJobState = typeof hostJobStates[number];
export type HostStepState = typeof hostStepStates[number];
const terminalJobs = new Set<string>(["completed", "failed", "cancelled"]);
const terminalSteps = new Set<string>([...terminalJobs, "skipped"]);
const stepStrings = ["id", "title", "command", "cwd", "stdout_path", "stderr_path", "started_at", "finished_at", "completed_at", "approved_at", "approved_by", "command_digest", "detail"] as const;
const jobStrings = ["job_id", "job_kind", "source_task_id", "plan_id", "repo", "version", "tag", "summary", "current_step_id", "created_at", "updated_at", "completed_at", "last_error"] as const;
export type HostJobStep = Record<typeof stepStrings[number], string> & {
  kind: "host_job" | "short_shell"; state: HostStepState; approval_required: boolean; side_effect: boolean;
  exit_code: number | null; pid: number | null; pgid: number | null;
};
export type HostJob = Record<typeof jobStrings[number], string> & { state: HostJobState; steps: HostJobStep[] };
const commandDigest = (command: string) => createHash("sha256").update(command).digest("hex");
function stringFields<T extends string>(raw: Record<string, unknown>, fields: readonly T[]): Record<T, string> {
  const out = {} as Record<T, string>;
  for (const field of fields) { requireThat(raw[field] === undefined || raw[field] === null || typeof raw[field] === "string", "invalid_host_job_string"); out[field] = (raw[field] as string | null | undefined) ?? ""; }
  return out;
}
export function decodeHostJobStep(raw: unknown): HostJobStep {
  requireThat(object(raw), "invalid_host_job_step");
  const text = stringFields(raw, stepStrings); identifier(text.id);
  const kind = raw.kind || "host_job", state = raw.state || "pending";
  requireThat(["host_job", "short_shell"].includes(String(kind)) && hostStepStates.includes(state as HostStepState), "invalid_host_job_step_state");
  for (const flag of ["approval_required", "side_effect"]) requireThat(raw[flag] === undefined || typeof raw[flag] === "boolean", "invalid_host_job_flag");
  for (const field of ["exit_code", "pid", "pgid"]) requireThat(raw[field] == null || Number.isSafeInteger(raw[field]), "invalid_host_job_process_value");
  const expected = commandDigest(text.command);
  requireThat(!text.command_digest || text.command_digest === expected, "host_job_command_digest_mismatch");
  return { ...text, finished_at: text.finished_at || text.completed_at, command_digest: expected,
    kind: kind as HostJobStep["kind"], state: state as HostStepState,
    approval_required: raw.approval_required === true, side_effect: raw.side_effect === true,
    exit_code: (raw.exit_code ?? null) as number | null, pid: (raw.pid ?? null) as number | null, pgid: (raw.pgid ?? null) as number | null };
}
/** Internal candidate model; timestamps are supplied by the owner, never invented during import. */
export function decodeHostJob(raw: unknown): HostJob {
  requireThat(object(raw), "invalid_host_job");
  requireThat(Buffer.byteLength(canonical(raw)) <= 1024 * 1024, "host_job_too_large");
  const text = stringFields(raw, jobStrings); identifier(text.job_id);
  requireThat(text.created_at && text.updated_at, "host_job_timestamps_required");
  const state = raw.state || "pending";
  requireThat(hostJobStates.includes(state as HostJobState), "invalid_host_job_state");
  requireThat(raw.steps === undefined || (Array.isArray(raw.steps) && raw.steps.length <= 256), "invalid_host_job_steps");
  const steps = ((raw.steps ?? []) as unknown[]).map(decodeHostJobStep);
  requireThat(new Set(steps.map(step => step.id)).size === steps.length, "duplicate_host_job_step");
  return { ...text, job_kind: text.job_kind || "generic", state: state as HostJobState, steps };
}
export function mergeHostJob(existingRaw: unknown, incomingRaw: unknown): HostJob {
  const existing = decodeHostJob(existingRaw), incoming = decodeHostJob(incomingRaw);
  requireThat(existing.job_id === incoming.job_id, "host_job_identity_changed");
  const prior = new Map(existing.steps.map(step => [step.id, step]));
  requireThat(existing.steps.every(step => !terminalSteps.has(step.state) || incoming.steps.some(next => next.id === step.id)), "host_job_terminal_step_removed");
  const steps = incoming.steps.map(step => {
    const old = prior.get(step.id);
    requireThat(!old || (old.command_digest === step.command_digest && old.cwd === step.cwd && old.kind === step.kind
      && old.approval_required === step.approval_required && old.side_effect === step.side_effect), "host_job_step_definition_changed");
    return old && terminalSteps.has(old.state) ? old : step;
  });
  const rank: Record<HostJobState, number> = { pending: 0, running: 1, awaiting_approval: 2, completed: 3, failed: 3, cancelled: 3 };
  const result = { ...incoming, steps, state: terminalJobs.has(existing.state) || rank[incoming.state] < rank[existing.state] ? existing.state : incoming.state };
  for (const key of jobStrings) result[key] = incoming[key] || existing[key];
  result.created_at = existing.created_at;
  result.completed_at = existing.completed_at || incoming.completed_at;
  result.last_error = existing.last_error || incoming.last_error;
  return result;
}
