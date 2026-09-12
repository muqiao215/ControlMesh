/** Port of controlmesh/team/phases.py. No task execution or approval authority is issued here. */
export const teamPhases = ["plan", "approve", "execute", "verify", "repair", "complete", "failed", "cancelled"] as const;
export type TeamPhase = typeof teamPhases[number];
export interface TeamPhaseTransition { from_phase: TeamPhase; to_phase: TeamPhase; at: string; reason: string | null }
export interface TeamPhaseState {
  current_phase: TeamPhase; active: boolean; created_at: string | null; updated_at: string | null;
  transitions: TeamPhaseTransition[]; max_repair_attempts: number; current_repair_attempt: number; terminal_reason: string | null;
}
const edges: Partial<Record<TeamPhase, readonly TeamPhase[]>> = {
  plan: ["approve", "cancelled"], approve: ["execute", "failed", "cancelled"], execute: ["verify", "failed", "cancelled"],
  verify: ["repair", "complete", "failed", "cancelled"], repair: ["execute", "verify", "complete", "failed", "cancelled"],
};
export function isTerminalTeamPhase(phase: string): boolean { return ["complete", "failed", "cancelled"].includes(phase); }
function utc(at: Date): string { return at.toISOString().replace(/\.000Z$/, "+00:00").replace(/\.(\d{3})Z$/, ".$1000+00:00"); }
export function initialTeamPhaseState(at = new Date(), maxRepairAttempts = 3): TeamPhaseState {
  const now = utc(at);
  return { current_phase: "plan", active: true, created_at: now, updated_at: now, transitions: [],
    max_repair_attempts: maxRepairAttempts, current_repair_attempt: 0, terminal_reason: null };
}
export function transitionTeamPhase(state: TeamPhaseState, to: TeamPhase, reason: string | null = null, at = new Date()): TeamPhaseState {
  const from = state.current_phase;
  if (isTerminalTeamPhase(from)) throw new Error(`cannot transition from terminal team phase: ${from}`);
  if (!edges[from]?.includes(to)) throw new Error(`invalid team phase transition: ${from} -> ${to}`);
  const now = utc(at), attempt = state.current_repair_attempt + (to === "repair" ? 1 : 0);
  const exceeded = to === "repair" && attempt > state.max_repair_attempts;
  const target = exceeded ? "failed" : to;
  const why = exceeded ? `repair loop limit reached (${state.max_repair_attempts})` : reason;
  return { current_phase: target, active: !isTerminalTeamPhase(target), created_at: state.created_at, updated_at: now,
    transitions: [...structuredClone(state.transitions), { from_phase: from, to_phase: target, at: now, reason: why }],
    max_repair_attempts: state.max_repair_attempts, current_repair_attempt: exceeded ? state.current_repair_attempt : attempt,
    terminal_reason: isTerminalTeamPhase(target) ? why : state.terminal_reason };
}

export interface TeamPhaseStore { readPhase(): TeamPhaseState; writePhase(state: TeamPhaseState): void }
/** Same lazy-initialization boundary as Python TeamOrchestrator; persistence is supplied by its owner. */
export class TeamOrchestrator {
  constructor(private readonly store: TeamPhaseStore, private readonly clock: () => Date = () => new Date()) {}
  readState(): TeamPhaseState {
    let state = this.store.readPhase();
    if (state.created_at === null) { state = initialTeamPhaseState(this.clock(), state.max_repair_attempts); this.store.writePhase(state); }
    return state;
  }
  transition(to: TeamPhase, reason: string | null = null): TeamPhaseState {
    const next = transitionTeamPhase(this.readState(), to, reason, this.clock()); this.store.writePhase(next); return next;
  }
}
