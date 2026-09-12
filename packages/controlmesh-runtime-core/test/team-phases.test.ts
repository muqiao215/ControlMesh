import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { initialTeamPhaseState, transitionTeamPhase, teamPhases, TeamOrchestrator, type TeamPhaseState } from "../src/team-phases";

test("all team phase edges and repair bounds match the live Python owner", () => {
  const python = `
import json
from datetime import datetime
from controlmesh.team.models import TeamPhaseState
from controlmesh.team.phases import transition_phase, initial_phase_state
phases = ${JSON.stringify([...teamPhases])}
at = datetime.fromisoformat('2026-09-12T03:04:05.123+00:00')
rows = []
for phase in phases:
 for target in phases:
  for limit, attempt in [(0,0),(3,0),(3,3),(3,4),(-1,0)]:
   state = TeamPhaseState(current_phase=phase, created_at='original', max_repair_attempts=limit, current_repair_attempt=attempt, terminal_reason='preserved')
   try: result = {'state': transition_phase(state, target, reason='test reason', at=at).model_dump()}
   except ValueError as error: result = {'error': str(error)}
   rows.append({'input':state.model_dump(), 'target':target, 'result':result})
print(json.dumps({'initial':initial_phase_state(at=at).model_dump(), 'rows':rows}))
`;
  const result = Bun.spawnSync(["uv", "run", "python", "-c", python], { cwd: resolve(import.meta.dir, "../../.."), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ exit: result.exitCode, stderr: result.stderr.toString() }).toEqual({ exit: 0, stderr: "" });
  const golden = JSON.parse(result.stdout.toString()), at = new Date("2026-09-12T03:04:05.123Z");
  expect(initialTeamPhaseState(at)).toEqual(golden.initial);
  for (const row of golden.rows) {
    let actual: unknown;
    try { actual = { state: transitionTeamPhase(row.input, row.target, "test reason", at) }; }
    catch (error) { actual = { error: (error as Error).message }; }
    expect(actual).toEqual(row.result);
  }
  expect(golden.rows).toHaveLength(320);
});

test("orchestrator persists once per transition, preserves failed writes and never mutates prior history", () => {
  let saved: TeamPhaseState = { ...initialTeamPhaseState(), created_at: null, max_repair_attempts: 0 }, writes = 0, fail = false;
  const clock = () => new Date("2026-09-12T00:00:00Z");
  const orchestrator = new TeamOrchestrator({ readPhase: () => structuredClone(saved), writePhase: state => {
    if (fail) throw new Error("persistence failed"); saved = structuredClone(state); writes++;
  } }, clock);
  const initial = orchestrator.readState(); expect(writes).toBe(1); orchestrator.readState(); expect(writes).toBe(1);
  fail = true; expect(() => orchestrator.transition("approve")).toThrow("persistence failed");
  expect(saved.current_phase).toBe("plan"); fail = false;
  for (const phase of ["approve", "execute", "verify", "repair"] as const) orchestrator.transition(phase);
  expect(saved.current_phase).toBe("failed"); expect(saved.current_repair_attempt).toBe(0);
  expect(saved.terminal_reason).toBe("repair loop limit reached (0)");
  expect(initial.transitions).toEqual([]); expect(() => orchestrator.transition("execute")).toThrow("terminal team phase");
  expect(writes).toBe(5);
});

test("persistent phase owner fences stale writers and retries across reopen without duplicate transitions", async () => {
  const { RuntimeDatabase } = await import("../src/database");
  const { RuntimeTeamPhases } = await import("../src/runtime-team-phases");
  const fs = await import("node:fs"), os = await import("node:os"), path = await import("node:path");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cm-team-phases-"));
  let db = new RuntimeDatabase(path.join(root, "state.sqlite"));
  const actor = { id: "owner", origin: "human_request" as const, scopes: ["team:read", "team:write"] };
  let revoked = false, owner = new RuntimeTeamPhases(db, () => { if (revoked) throw new Error("revoked"); });
  try {
    const initial = owner.create(actor, "create", "team", 0);
    const approved = owner.transition(actor, "approve", "team", initial.revision, "approve");
    expect(() => owner.transition(actor, "stale", "team", initial.revision, "cancelled")).toThrow("revision_conflict");
    db.close(); db = new RuntimeDatabase(path.join(root, "state.sqlite")); owner = new RuntimeTeamPhases(db, () => { if (revoked) throw new Error("revoked"); });
    expect(owner.transition(actor, "approve", "team", initial.revision, "approve")).toEqual(approved);
    expect(() => owner.transition(actor, "approve", "team", initial.revision, "failed")).toThrow("idempotency_conflict");
    expect(() => owner.inspect({ ...actor, id: "other" }, "team")).toThrow("team_access_denied");
    db.sql.exec("CREATE TEMP TRIGGER fail_phase BEFORE UPDATE ON team_phases BEGIN SELECT RAISE(ABORT,'injected failure'); END");
    expect(() => owner.transition(actor, "execute", "team", approved.revision, "execute")).toThrow("injected failure");
    expect(owner.inspect(actor, "team")).toEqual(approved);
    db.sql.exec("DROP TRIGGER fail_phase");
    const executed = owner.transition(actor, "execute", "team", approved.revision, "execute");
    const verified = owner.transition(actor, "verify", "team", executed.revision, "verify");
    const exhausted = owner.transition(actor, "repair", "team", verified.revision, "repair");
    expect(exhausted.state.current_phase).toBe("failed"); expect(exhausted.state.current_repair_attempt).toBe(0);
    expect(exhausted.state.transitions).toHaveLength(4);
    revoked = true; expect(() => owner.transition(actor, "repair", "team", verified.revision, "repair")).toThrow("revoked");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM tasks").get()).toEqual({ n: 0 });
  } finally { db.close(); fs.rmSync(root, { recursive: true, force: true }); }
});
