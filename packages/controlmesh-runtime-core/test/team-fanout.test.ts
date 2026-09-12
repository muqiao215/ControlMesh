import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { startTopology } from "../src/team-topology";
import { dispatchFanoutWorkers, collectFanoutWorkers, applyFanoutResult, resumeFanout } from "../src/team-fanout";
import { decodeTeamResult } from "../src/team-result-validation";

test("fanout batch, reduction, repair and parent resume match the real Python runtime", () => {
  const statuses = ["completed", "failed", "blocked", "needs_parent_input", "needs_repair"];
  const cases: { workers: string[]; steps: string[] }[] = [];
  for (const a of statuses) for (const b of statuses) for (const r of statuses) cases.push({ workers: [a, b], steps: [r] });
  cases.push({ workers: ["completed", "failed"], steps: ["needs_repair", "completed", "completed"] }, { workers: ["completed", "completed"], steps: ["needs_parent_input", "resume", "completed"] });
  const script = `import json,sys\nfrom datetime import datetime\nfrom types import SimpleNamespace\nfrom controlmesh.team.execution import TeamFanoutMergeRuntime,TeamTopologyExecutionSpine\nfrom controlmesh.team.models import TeamStructuredResult\nclass Hub:\n def __init__(self):self.state=None;self._config=SimpleNamespace(max_parallel=2)\n def read_topology_state(self,task):return self.state\n def write_topology_state(self,task,payload):self.state=payload\ndef result(status,stage,role):\n return TeamStructuredResult(topology='fanout_merge',substage=stage,worker_role=role,status=status,summary='🙂 '*60+'output',evidence=[{'ref':'event:'+role}],artifacts=[{'ref':'file:'+role}],needs_parent_input=status=='needs_parent_input',repair_hint='fix' if status=='needs_repair' else None)\nat=datetime.fromisoformat('2026-09-12T01:02:03+00:00');rows=[]\nfor case in json.load(sys.stdin):\n p=TeamFanoutMergeRuntime(TeamTopologyExecutionSpine(Hub()));p.start('parent',planning_summary='plan',at=at);state=p.dispatch_workers('parent',worker_roles=['a','b'],at=at);states=[state.model_dump(mode='json')];ok=True\n try:\n  state=p.record_worker_results('parent',[result(s,'collecting',r) for s,r in zip(case['workers'],['a','b'])],at=at);states.append(state.model_dump(mode='json'))\n  for step in case['steps']:\n   if step=='resume':state=p.resume_from_parent('parent',parent_input='answer',at=at)\n   elif state.current_checkpoint.substage=='reducing':state=p.record_reducer_result('parent',result(step,'reducing','reducer'),parent_question='question',waiting_on='user',at=at)\n   elif state.current_checkpoint.substage=='repairing':state=p.record_repair_result('parent',result(step,'repairing','coordinator'),at=at)\n   else:raise ValueError('terminal')\n   states.append(state.model_dump(mode='json'))\n except ValueError:ok=False\n rows.append({'ok':ok,'states':states})\nprint(json.dumps(rows))`;
  const child = Bun.spawnSync(["uv", "run", "python", "-c", script], { cwd: resolve(import.meta.dir, "../../.."), stdin: Buffer.from(JSON.stringify(cases)), stdout: "pipe", stderr: "pipe", timeout: 30_000 });
  expect({ code: child.exitCode, stderr: child.stderr.toString() }).toEqual({ code: 0, stderr: "" });
  const oracle = JSON.parse(child.stdout.toString()), at = new Date("2026-09-12T01:02:03Z");
  const result = (status: string, substage: string, worker_role: string) => decodeTeamResult({ topology: "fanout_merge", substage, worker_role, status,
    summary: "🙂 ".repeat(60) + "output", evidence: [{ ref: `event:${worker_role}` }], artifacts: [{ ref: `file:${worker_role}` }],
    needs_parent_input: status === "needs_parent_input", repair_hint: status === "needs_repair" ? "fix" : null });
  for (const [i, input] of cases.entries()) {
    let state = dispatchFanoutWorkers(startTopology("parent", "fanout_merge", { active_roles: ["coordinator"], latest_summary: "plan" }, at), ["a", "b"], 2, undefined, at);
    const states = [state]; let ok = true;
    try {
      state = collectFanoutWorkers(state, input.workers.map((status, index) => result(status, "collecting", index === 0 ? "a" : "b")), "reducer", at); states.push(state);
      for (const step of input.steps) {
        const stage = state.checkpoints.at(-1)!.substage;
        state = step === "resume" ? resumeFanout(state, "answer", undefined, at) : applyFanoutResult(state, result(step, stage, stage === "repairing" ? "coordinator" : "reducer"), { parent_question: "question", waiting_on: "user" }, at);
        states.push(state);
      }
    } catch { ok = false; }
    expect({ input, actual: { ok, states } }).toEqual({ input, actual: oracle[i] });
  }
});
