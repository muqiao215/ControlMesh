import { RuntimeDatabase } from "./database";
import { command, requireScope } from "./commands";
import type { Principal } from "./kernel";
import { canonical, identifier, requireThat } from "./value";
import { initialTeamPhaseState, transitionTeamPhase, type TeamPhaseState, type TeamPhase } from "./team-phases";

export interface TeamPhaseSnapshot { team_id: string; revision: number; state: TeamPhaseState }
/** Private TS phase owner. Phase changes do not authorize or dispatch provider work. */
export class RuntimeTeamPhases {
  constructor(private readonly db: RuntimeDatabase, private readonly assertCurrent: () => void) {}
  private authorize(actor: Principal, scope: string): void {
    requireScope(actor, scope);
    const checked: unknown = this.assertCurrent();
    if (checked !== undefined) { void Promise.resolve(checked).catch(() => {}); requireThat(false, "admission_must_be_synchronous"); }
  }
  private row(actor: Principal, teamId: string): TeamPhaseSnapshot {
    identifier(teamId);
    const row = this.db.sql.query("SELECT principal,revision,state FROM team_phases WHERE team_id=?").get(teamId) as { principal: string; revision: number; state: string } | null;
    requireThat(row, "team_not_found"); requireThat(row.principal === actor.id, "team_access_denied");
    return { team_id: teamId, revision: row.revision, state: JSON.parse(row.state) as TeamPhaseState };
  }
  inspect(actor: Principal, teamId: string): TeamPhaseSnapshot { this.authorize(actor, "team:read"); return this.row(actor, teamId); }
  create(actor: Principal, requestId: string, teamId: string, maxRepairAttempts = 3): TeamPhaseSnapshot {
    this.authorize(actor, "team:write"); identifier(teamId);
    requireThat(Number.isSafeInteger(maxRepairAttempts), "invalid_team_repair_limit");
    return command(this.db, actor, requestId, "team.create", { teamId, maxRepairAttempts }, () => {
      this.authorize(actor, "team:write");
      requireThat(!this.db.sql.query("SELECT 1 FROM team_phases WHERE team_id=?").get(teamId), "team_exists");
      const state = initialTeamPhaseState(new Date(this.db.now()), maxRepairAttempts);
      this.db.sql.query("INSERT INTO team_phases VALUES (?,?,1,?)").run(teamId, actor.id, canonical(state));
      return { team_id: teamId, revision: 1, state };
    }, value => { this.authorize(actor, "team:write"); return value; });
  }
  transition(actor: Principal, requestId: string, teamId: string, expectedRevision: number, to: TeamPhase, reason: string | null = null): TeamPhaseSnapshot {
    this.authorize(actor, "team:write"); identifier(teamId);
    requireThat(Number.isSafeInteger(expectedRevision) && expectedRevision >= 1 && (reason === null || typeof reason === "string"), "invalid_team_transition");
    return command(this.db, actor, requestId, "team.transition", { teamId, expectedRevision, to, reason }, () => {
      this.authorize(actor, "team:write"); const current = this.row(actor, teamId);
      requireThat(current.revision === expectedRevision, "revision_conflict");
      const state = transitionTeamPhase(current.state, to, reason, new Date(this.db.now()));
      const revision = current.revision + 1;
      this.db.sql.query("UPDATE team_phases SET revision=?,state=? WHERE team_id=?").run(revision, canonical(state), teamId);
      return { team_id: teamId, revision, state };
    }, value => { this.authorize(actor, "team:write"); this.row(actor, teamId); return value; });
  }
}
