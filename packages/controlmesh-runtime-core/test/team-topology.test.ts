import { expect, test } from "bun:test";
import { resolve, join } from "node:path";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { RuntimeDatabase, RuntimeKernel, RuntimeTopology, type Principal } from "../src";
import { startTopology, appendTopologyCheckpoint, interruptTopology, resumeTopology, decodeTopologyState } from "../src/team-topology";

test("topology start/checkpoint/interrupt/resume matches real Python spine for every topology", () => {
  const at = new Date("2026-09-12T01:02:03.123Z");
  const inputs = ["pipeline", "fanout_merge", "director_worker", "debate_judge"].map(topology => ({ topology }));
  const script = `import json,sys\nfrom datetime import datetime\nfrom controlmesh.team.execution import TeamTopologyExecutionSpine\nclass Hub:\n def __init__(self): self.state=None\n def read_topology_state(self,task): return self.state\n def write_topology_state(self,task,payload): self.state=payload\nrows=[]\nfor entry in json.load(sys.stdin):\n s=TeamTopologyExecutionSpine(Hub());at=datetime.fromisoformat('2026-09-12T01:02:03.123+00:00')\n states=[]\n states.append(s.start('parent',topology=entry['topology'],active_roles=[' worker '],round_index=1,round_limit=3,at=at))\n states.append(s.record_checkpoint('parent',substage='planning',phase_status='in_progress',completed_roles=[' prior '],artifact_count=2,round_index=2,round_limit=3,at=at))\n states.append(s.interrupt_for_parent('parent',requested_by_role=' worker ',question=' question ',waiting_on=' user ',completed_roles=[],at=at))\n states.append(s.resume_from_parent('parent',parent_input=' answer ',active_roles=[],completed_roles=[],at=at))\n rows.append([v.model_dump(mode='json') for v in states])\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(inputs)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const expected = JSON.parse(child.stdout.toString());
  for (const [i, { topology }] of inputs.entries()) {
    const start = startTopology("parent", topology, { active_roles: [" worker "], round_index: 1, round_limit: 3 }, at);
    const checkpoint = appendTopologyCheckpoint(start, { substage: "planning", phase_status: "in_progress", completed_roles: [" prior "], artifact_count: 2, round_index: 2, round_limit: 3 }, at);
    const blocked = interruptTopology(checkpoint, { requested_by_role: " worker ", question: " question ", waiting_on: " user ", completed_roles: [] }, at);
    const resumed = resumeTopology(blocked, { parent_input: " answer ", active_roles: [], completed_roles: [] }, at);
    expect([start, checkpoint, blocked, resumed]).toEqual(expected[i]);
    expect(() => resumeTopology(resumed, { parent_input: "again" }, at)).toThrow("topology_not_waiting_parent");
    const contradictory = structuredClone(blocked); contradictory.interruption.status = "idle";
    expect(() => decodeTopologyState(contradictory)).toThrow("topology_interruption_mismatch");
    for (const stamp of ["tomorrow", "2026-02-30T01:00:00+00:00", "2026-09-12T24:00:00+00:00"]) {
      const invalid = structuredClone(resumed); invalid.updated_at = stamp;
      expect(() => decodeTopologyState(invalid)).toThrow("invalid_topology_timestamp");
    }
    const wrongRound = structuredClone(resumed); wrongRound.checkpoints[0]!.round_limit = 0;
    expect(() => decodeTopologyState(wrongRound)).toThrow();
    const wrongTopology = structuredClone(resumed); wrongTopology.checkpoints[0]!.topology = topology === "pipeline" ? "fanout_merge" : "pipeline";
    expect(() => decodeTopologyState(wrongTopology)).toThrow("topology_checkpoint_mismatch");
  }
});

test("topology persistence survives restart, rejects stale owners and rolls back failed writes", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-topology-")); const path = join(root, "runtime.sqlite");
  let db = new RuntimeDatabase(path, () => 1000);
  const actor: Principal = { id: "owner", origin: "internal", scopes: ["task:create", "task:read", "task:cancel", "team:write"] };
  try {
    let kernel = new RuntimeKernel(db), topology = new RuntimeTopology(kernel);
    kernel.submit(actor, "create-task", { task_id: "parent", chat_id: "test", status: "waiting", provider: "opencode" });
    const first = topology.create(actor, "create-topology", "parent", 1, "pipeline");
    expect(topology.create(actor, "create-topology", "parent", 1, "pipeline")).toEqual(first);
    const input = { requested_by_role: "worker", question: "choose", waiting_on: "user" };
    const blocked = topology.interrupt(actor, "interrupt", "parent", 1, 1, input);
    expect(topology.interrupt(actor, "interrupt", "parent", 1, 1, input)).toEqual(blocked);
    db.close(); db = new RuntimeDatabase(path, () => 2000); kernel = new RuntimeKernel(db); topology = new RuntimeTopology(kernel);
    expect(topology.inspect(actor, "parent")).toEqual(blocked);
    expect(() => topology.inspect({ ...actor, id: "stranger" }, "parent")).toThrow("task_access_denied");
    expect(() => topology.resume(actor, "stale", "parent", 1, 1, { parent_input: "yes" })).toThrow("revision_conflict");
    db.sql.exec("CREATE TRIGGER refuse_topology BEFORE UPDATE ON team_topologies BEGIN SELECT RAISE(ABORT,'injected_failure'); END");
    expect(() => topology.resume(actor, "resume", "parent", 1, 2, { parent_input: "yes" })).toThrow("injected_failure");
    expect(topology.inspect(actor, "parent")).toEqual(blocked);
    db.sql.exec("DROP TRIGGER refuse_topology");
    const resumed = topology.resume(actor, "resume", "parent", 1, 2, { parent_input: "yes" });
    expect(resumed.state.interruption.resume_count).toBe(1);
    expect(resumed.revision).toBe(3);
    const cancelled = kernel.cancel(actor, "cancel", "parent", 1);
    expect(() => topology.checkpoint(actor, "late", "parent", cancelled.revision, 3, { substage: "completed", phase_status: "completed" })).toThrow("topology_task_not_active");
    expect(db.sql.query("SELECT COUNT(*) AS n FROM episodes").get()).toEqual({ n: 0 });
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});

test("version sixteen upgrades topology storage without losing existing task and team phase data", () => {
  const root = mkdtempSync(join(tmpdir(), "cm-topology-upgrade-")); const path = join(root, "runtime.sqlite");
  let db = new RuntimeDatabase(path);
  try {
    const actor: Principal = { id: "owner", origin: "internal", scopes: ["task:create", "task:read"] };
    new RuntimeKernel(db).submit(actor, "create", { task_id: "parent", chat_id: "test", status: "waiting", provider: "opencode" });
    db.sql.query("INSERT INTO team_phases VALUES ('team','owner',1,'{}')").run();
    db.sql.exec("DROP TABLE topology_runs; ALTER TABLE topology_tasks DROP COLUMN execution_id; DROP TABLE topology_completions; DROP TABLE topology_controls; DROP TABLE topology_task_history; DROP TABLE topology_tasks; DROP TABLE team_topologies; PRAGMA user_version=16");
    db.close(); db = new RuntimeDatabase(path);
    expect(db.sql.query("PRAGMA user_version").get()).toEqual({ user_version: 22 });
    expect(new RuntimeKernel(db).inspect(actor, "parent").task.status).toBe("waiting");
    expect(db.sql.query("SELECT state FROM team_phases WHERE team_id='team'").get()).toEqual({ state: "{}" });
    expect(new RuntimeTopology(new RuntimeKernel(db)).inspect(actor, "parent")).toBeNull();
  } finally { db.close(); rmSync(root, { recursive: true, force: true }); }
});
